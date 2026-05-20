from flask import Flask, render_template, request, redirect, session, Response, jsonify, send_from_directory
import psycopg2
import cv2
import numpy as np
import time
import os
from datetime import datetime
import re
import cloudinary
import cloudinary.uploader
import cloudinary.api
import threading
import base64

app = Flask(__name__)
app.secret_key = "secretkey123"

# ========================================================
# CLOUDINARY CONFIGURATION
# ========================================================
cloudinary.config(
    cloud_name=os.environ.get("CLOUDINARY_CLOUD_NAME", "djgvzkcxa"),
    api_key=os.environ.get("CLOUDINARY_API_KEY", "423185958454492"),
    api_secret=os.environ.get("CLOUDINARY_API_SECRET", "9pNxrN_qJkKOJ3R6wnX6R6EKneM"),
    secure=True
)

# ========================================================
# GLOBAL SYSTEMS STATE & COMPUTER VISION VARIABLES
# ========================================================
is_recording = False
recording_frames = []  # In-memory storage for recording frames to bypass Render's read-only disk block

first_frame = None
motion_cooldown = 0

FRAME_WIDTH, FRAME_HEIGHT = 640, 480
CAM_RES = f"{FRAME_WIDTH}x{FRAME_HEIGHT}"
CAM_FPS_DEFAULT = 30

face_cascade = cv2.CascadeClassifier(
    cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
)

# ========================================================
# POSTGRESQL DATABASE INTEGRATION & AUTO-MIGRATION
# ========================================================
db_url = os.environ.get("DATABASE_URL")
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

try:
    if db_url:
        conn = psycopg2.connect(db_url)
        print("--- CONNECTED TO PRODUCTION DATABASE ---")
    else:
        conn = psycopg2.connect(
            host="localhost", database="surveillance_db", user="postgres", password="admin123", port="5432"
        )
        print("--- CONNECTED TO LOCAL DATABASE ---")
except Exception as e:
    print(f"--- DATABASE ERROR: {e} ---")
    conn = None

if conn:
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(50) UNIQUE NOT NULL,
                password VARCHAR(255) NOT NULL
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS security_videos (
                id SERIAL PRIMARY KEY,
                filename VARCHAR(255) NOT NULL,
                cloudinary_url TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS camera_logs (
                id SERIAL PRIMARY KEY,
                camera_name VARCHAR(100) NOT NULL,
                status VARCHAR(50) NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS login_logs (
                id SERIAL PRIMARY KEY,
                username VARCHAR(50) NOT NULL,
                ip_address VARCHAR(45),
                login_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cursor.execute("""
            INSERT INTO users (username, password) 
            VALUES ('yvan', 'admin123') 
            ON CONFLICT (username) DO NOTHING;
        """)
        conn.commit()
        print("--- DATABASE SCHEMA SEEDING COMPLETE ---")
    except Exception as migration_err:
        print(f"--- DATABASE MIGRATION WARNING: {migration_err} ---")
        conn.rollback()


# ========================================================
# ASYNC THREAD WORKER PIPELINE
# ========================================================
def process_and_upload_video(frames_to_upload, filename):
    """Compiles frames in memory and handles the heavy Cloudinary upload in an isolated background thread."""
    global conn
    if not frames_to_upload:
        return

    try:
        print(f"--- [BACKGROUND THREAD] Compiling {len(frames_to_upload)} frames into temporary container... ---")

        # Use Render's verified scratch directory (/tmp) to safely handle the file write bypass
        temp_path = os.path.join("/tmp", filename)

        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(temp_path, fourcc, 15.0, (FRAME_WIDTH, FRAME_HEIGHT))

        for frame in frames_to_upload:
            out.write(frame)
        out.release()

        print(f"--- [BACKGROUND THREAD] Starting Cloudinary upload for {filename}... ---")
        upload_result = cloudinary.uploader.upload_large(
            temp_path,
            resource_type="video",
            folder="cctv_recordings",
            public_id=filename.split('.')[0],
            video_codec="h264"
        )

        cloudinary_url = upload_result.get("secure_url")
        print(f"--- [BACKGROUND THREAD] Cloudinary Sync Complete! Link: {cloudinary_url} ---")

        if conn and cloudinary_url:
            db_cursor = conn.cursor()
            db_cursor.execute(
                "INSERT INTO security_videos (filename, cloudinary_url) VALUES (%s, %s)",
                (filename, cloudinary_url)
            )
            conn.commit()
            db_cursor.close()
            print("--- [BACKGROUND THREAD] Database Record Successfully Written! ---")

        if os.path.exists(temp_path):
            os.remove(temp_path)

    except Exception as e:
        print(f"--- [BACKGROUND THREAD] CRITICAL FAILURE: {e} ---")
        if conn:
            conn.rollback()


# ========================================================
# ROUTING & SURVEILLANCE ENDPOINTS
# ========================================================
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username, password = request.form['username'], request.form['password']
        if conn:
            try:
                local_cursor = conn.cursor()
                local_cursor.execute("SELECT * FROM users WHERE username=%s AND password=%s", (username, password))
                user_match = local_cursor.fetchone()
                local_cursor.close()

                if user_match:
                    session['user'] = username
                    try:
                        forwarded_for = request.headers.get('X-Forwarded-For')
                        user_ip = forwarded_for.split(',')[0].strip() if forwarded_for else request.remote_addr
                        log_cursor = conn.cursor()
                        log_cursor.execute("INSERT INTO login_logs (username, ip_address) VALUES (%s, %s)",
                                           (username, user_ip))
                        conn.commit()
                        log_cursor.close()
                    except Exception as log_err:
                        conn.rollback()
                    return redirect('/')
            except Exception as e:
                if conn: conn.rollback()
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect('/login')


@app.route('/')
def dashboard():
    if 'user' not in session: return redirect('/login')
    logs = []
    if conn:
        try:
            local_cursor = conn.cursor()
            local_cursor.execute("SELECT * FROM camera_logs ORDER BY id DESC LIMIT 50")
            logs = local_cursor.fetchall()
            local_cursor.close()
        except:
            conn.rollback()
    return render_template('dashboard.html', logs=logs, user=session['user'])


@app.route('/camera_monitoring')
def camera_monitoring():
    if 'user' not in session: return redirect('/login')
    return render_template('camera_monitoring.html', user=session['user'], resolution=CAM_RES,
                           stream_type="WebRTC Inbound", fps=CAM_FPS_DEFAULT)


@app.route('/start_recording')
def start_recording():
    global is_recording, recording_frames
    if not is_recording:
        recording_frames = []  # Clear previous memory cache
        is_recording = True
        print("--- RECORDING ENGINE: Activated (Caching in Memory) ---")
    return jsonify({"status": "success"})


@app.route('/stop_recording')
def stop_recording():
    global is_recording, recording_frames
    if not is_recording:
        return jsonify({"status": "error", "message": "Not currently recording"}), 400

    is_recording = False
    filename = f"capture_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"

    # Deep copy the cached frame array and immediately pass it to our background thread
    frames_snapshot = list(recording_frames)
    recording_frames = []

    # Offload the video processing and Cloudinary upload entirely to a background thread
    upload_thread = threading.Thread(target=process_and_upload_video, args=(frames_snapshot, filename))
    upload_thread.start()

    print("--- RECORDING ENGINE: Stopped. Processing upload in background thread. ---")
    return jsonify({"status": "success", "message": "Background upload thread deployed cleanly."})


@app.route('/recordings_gallery')
def recordings_gallery():
    if 'user' not in session: return redirect('/login')
    videos = []
    if conn:
        try:
            db_cursor = conn.cursor()
            db_cursor.execute("SELECT id, filename, cloudinary_url FROM security_videos ORDER BY id DESC")
            videos = db_cursor.fetchall()
            db_cursor.close()
        except Exception as e:
            print(f"Gallery SQL Exception: {e}")
            conn.rollback()
    return render_template('recordings_gallery.html', videos=videos, user=session['user'])


@app.route('/delete_video/<int:video_id>', methods=['POST'])
def delete_video(video_id):
    if 'user' not in session: return jsonify({"status": "error", "message": "Unauthorized"}), 401
    if conn:
        try:
            db_cursor = conn.cursor()
            db_cursor.execute("SELECT cloudinary_url FROM security_videos WHERE id = %s", (video_id,))
            row = db_cursor.fetchone()
            if not row:
                db_cursor.close()
                return jsonify({"status": "error", "message": "Video not found"}), 404

            cloudinary_url = row[0]
            try:
                public_id = ("cctv_recordings/" + cloudinary_url.split('/')[-1]).split('.')[0]
                cloudinary.uploader.destroy(public_id, resource_type="video")
            except Exception as e:
                print(f"Cloudinary delete warning: {e}")

            db_cursor.execute("DELETE FROM security_videos WHERE id = %s", (video_id,))
            conn.commit()
            db_cursor.close()
            return jsonify({"status": "success"})
        except Exception as e:
            conn.rollback()
            return jsonify({"status": "error", "message": str(e)}), 500
    return jsonify({"status": "error", "message": "Database disconnected"}), 500


@app.route('/login_logs')
def login_logs():
    if 'user' not in session: return redirect('/login')
    logs = []
    if conn:
        try:
            db_cursor = conn.cursor()
            db_cursor.execute("SELECT id, username, ip_address, login_time FROM login_logs ORDER BY login_time DESC")
            logs = db_cursor.fetchall()
            db_cursor.close()
        except:
            conn.rollback()
    return render_template('login_logs.html', logs=logs, user=session['user'])


@app.route('/device_management')
def device_management():
    if 'user' not in session: return redirect('/login')
    devices = [{"name": "Router", "ip": "192.168.1.1", "status": "ONLINE"},
               {"name": "IP Camera", "ip": "192.168.1.10", "status": "ONLINE"}]
    return render_template('device_management.html', devices=devices, user=session['user'])


# ========================================================
# BROWSER CLIENT-FRAME CV ANALYTICS RECEIVER
# ========================================================
@app.route('/process_client_frame', methods=['POST'])
def process_client_frame():
    global first_frame, motion_cooldown, is_recording, recording_frames
    if 'user' not in session: return jsonify({"status": "unauthorized"}), 401

    try:
        data = request.get_json()
        if not data or 'image' not in data: return jsonify({"status": "invalid data"}), 400

        image_data = data['image'].split(',')[1]
        image_bytes = base64.b64decode(image_data)
        np_array = np.frombuffer(image_bytes, dtype=np.uint8)
        frame = cv2.imdecode(np_array, cv2.IMREAD_COLOR)

        if frame is not None:
            output_frame = frame.copy()
            current_time = time.time()

            # ----------------------------------------
            # COMPUTER VISION: MOTION DETECTION
            # ----------------------------------------
            gray_motion = cv2.cvtColor(output_frame, cv2.COLOR_BGR2GRAY)
            gray_motion = cv2.GaussianBlur(gray_motion, (21, 21), 0)

            if first_frame is None:
                first_frame = np.float32(gray_motion)
                return jsonify({"status": "calibrating"}), 200

            cv2.accumulateWeighted(gray_motion, first_frame, 0.5)
            background_uint8 = cv2.convertScaleAbs(first_frame)
            frame_delta = cv2.absdiff(background_uint8, gray_motion)
            thresh = cv2.threshold(frame_delta, 25, 255, cv2.THRESH_BINARY)[1]
            thresh = cv2.dilate(thresh, None, iterations=2)

            contours, _ = cv2.findContours(thresh.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            motion_detected = any(cv2.contourArea(c) >= 5000 for c in contours)

            if motion_detected and conn and (current_time - motion_cooldown > 5):
                try:
                    log_cursor = conn.cursor()
                    log_cursor.execute("INSERT INTO camera_logs (camera_name, status) VALUES (%s, %s)",
                                       ("Cam 01", "MOTION DETECTED"))
                    conn.commit()
                    log_cursor.close()
                    motion_cooldown = current_time
                except Exception as log_err:
                    conn.rollback()

            # ----------------------------------------
            # COMPUTER VISION: FACE DETECTION
            # ----------------------------------------
            gray_face = cv2.cvtColor(output_frame, cv2.COLOR_BGR2GRAY)
            gray_face = cv2.equalizeHist(gray_face)
            faces = face_cascade.detectMultiScale(gray_face, 1.1, 8, minSize=(50, 50))

            # Burn drawing matrices to the frame
            for (x, y, w, h) in faces:
                cv2.rectangle(output_frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
            if motion_detected:
                cv2.putText(output_frame, "MOTION DETECTED", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 3)

            # If the recording engine is active, cache the frame securely in memory
            if is_recording:
                recording_frames.append(output_frame)

            return jsonify({"status": "frame_analyzed", "faces_found": len(faces)}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)