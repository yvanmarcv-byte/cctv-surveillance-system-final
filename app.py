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
import threading  # Added for asynchronous background cloud uploading tasks

app = Flask(__name__)
app.secret_key = "secretkey123"

# ========================================================
# CLOUDINARY CONFIGURATION
# ========================================================
cloudinary.config(
  cloud_name = os.environ.get("CLOUDINARY_CLOUD_NAME", "djgvzkcxa"),
  api_key = os.environ.get("CLOUDINARY_API_KEY", "423185958454492"),
  api_secret = os.environ.get("CLOUDINARY_API_SECRET", "9pNxrN_qJkKOJ3R6wnX6R6EKneM"),
  secure = True
)

# ========================================================
# GLOBAL SYSTEMS STATE
# ========================================================
is_recording = False
video_writer = None
current_recording_path = None  # Tracking path for temporary local files

# ========================================================
# FACE DETECTION ENGINE SETUP
# ========================================================
face_cascade = cv2.CascadeClassifier(
    cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
)

# ========================================================
# POSTGRESQL DATABASE INTEGRATION
# ========================================================
db_url = os.environ.get("DATABASE_URL")

# Render compatibility hotfix: ensures string uses "postgresql://" prefix
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

try:
    if db_url:
        conn = psycopg2.connect(db_url)
        print("--- CONNECTED TO PRODUCTION DATABASE ---")
    else:
        conn = psycopg2.connect(
            host="localhost",
            database="surveillance_db",
            user="postgres",
            password="admin123",
            port="5432"
        )
        print("--- CONNECTED TO LOCAL DATABASE ---")
except Exception as e:
    print(f"--- DATABASE ERROR: {e} ---")
    conn = None

if conn:
    cursor = conn.cursor()

# ========================================================
# HARDWARE / CAMERA CONFIGURATION
# ========================================================
camera = cv2.VideoCapture(0)

if not camera.isOpened():
    print("Warning: Camera not available (Expected in Cloud Mode)")
    FRAME_WIDTH, FRAME_HEIGHT = 640, 480
else:
    FRAME_WIDTH = int(camera.get(cv2.CAP_PROP_FRAME_WIDTH))
    FRAME_HEIGHT = int(camera.get(cv2.CAP_PROP_FRAME_HEIGHT))

CAM_RES = f"{FRAME_WIDTH}x{FRAME_HEIGHT}"
CAM_FPS_DEFAULT = 30


# ========================================================
# ANALYTICS ENGINE: LIVE FRAME GENERATOR
# ========================================================
def generate_frames():
    global is_recording, video_writer
    prev_time = 0
    first_frame = None  # Floating-point (float32) background baseline
    motion_cooldown = 0  # Prevents spamming the logs database

    while True:
        success, frame = camera.read()
        if not success:
            break

        current_time = time.time()
        fps_real = 1 / (current_time - prev_time) if (current_time - prev_time) > 0 else 30
        prev_time = current_time

        output_frame = frame.copy()

        # ----------------------------------------
        # SYSTEM A: MOTION DETECTION
        # ----------------------------------------
        motion_detected = False
        gray_motion = cv2.cvtColor(output_frame, cv2.COLOR_BGR2GRAY)
        gray_motion = cv2.GaussianBlur(gray_motion, (21, 21), 0)

        if first_frame is None:
            first_frame = np.float32(gray_motion)
            continue

        cv2.accumulateWeighted(gray_motion, first_frame, 0.5)
        background_uint8 = cv2.convertScaleAbs(first_frame)

        frame_delta = cv2.absdiff(background_uint8, gray_motion)
        thresh = cv2.threshold(frame_delta, 25, 255, cv2.THRESH_BINARY)[1]
        thresh = cv2.dilate(thresh, None, iterations=2)

        contours, _ = cv2.findContours(thresh.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        for contour in contours:
            if cv2.contourArea(contour) < 5000:
                continue

            motion_detected = True
            (x, y, w, h) = cv2.boundingRect(contour)
            cv2.rectangle(output_frame, (x, y), (x + w, y + h), (0, 0, 255), 2)  # Red Alert Box

        # ----------------------------------------
        # TELEMETRY ALERTS & DATABASE LOGS
        # ----------------------------------------
        if motion_detected:
            cv2.putText(output_frame, "MOTION DETECTED", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 3)

            if conn and (current_time - motion_cooldown > 5):
                try:
                    log_cursor = conn.cursor()
                    log_cursor.execute(
                        "INSERT INTO camera_logs (camera_name, status) VALUES (%s, %s)",
                        ("Cam 01", "MOTION DETECTED")
                    )
                    conn.commit()
                    log_cursor.close()
                    motion_cooldown = current_time
                    print("--- DB UPDATE: Motion Detected Saved! ---")
                except Exception as e:
                    print(f"Failed to log motion event: {e}")

        # ----------------------------------------
        # SYSTEM B: FACE DETECTION
        # ----------------------------------------
        gray_face = cv2.cvtColor(output_frame, cv2.COLOR_BGR2GRAY)
        gray_face = cv2.equalizeHist(gray_face)
        faces = face_cascade.detectMultiScale(gray_face, 1.1, 8, minSize=(50, 50))

        for (x, y, w, h) in faces:
            cv2.rectangle(output_frame, (x, y), (x + w, y + h), (0, 255, 0), 2)  # Green Face Box

        # ----------------------------------------
        # ENCODER AND LOCAL DISK WRITER
        # ----------------------------------------
        if is_recording and video_writer is not None:
            if video_writer.isOpened():
                video_writer.write(output_frame)

        ret, buffer = cv2.imencode('.jpg', output_frame)
        if not ret:
            continue
        yield (b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')


# ========================================================
# NETWORK INFRASTRUCTURE BACKEND HOOKS
# ========================================================
@app.route('/heartbeat')
def heartbeat():
    return jsonify({"status": "healthy", "timestamp": time.time()}), 200


# ========================================================
# ASYNC THREAD WORKER PIPELINE
# ========================================================
def background_cloudinary_upload(local_path, filename):
    """Processes large video uploads and DB tracking on an isolated background thread."""
    global conn
    try:
        print(f"--- [BACKGROUND THREAD] Starting cloud sync for {filename}... ---")

        # Upload and explicitly convert resource into standard browser H.264 MP4 structures
        upload_result = cloudinary.uploader.upload_large(
            local_path,
            resource_type="video",
            folder="cctv_recordings",
            public_id=filename.split('.')[0],
            video_codec="h264"
        )

        cloudinary_url = upload_result.get("secure_url")
        print(f"--- [BACKGROUND THREAD] Cloudinary Sync Complete! Link: {cloudinary_url} ---")

        # Write secure resource link index into Postgres
        if conn:
            db_cursor = conn.cursor()
            db_cursor.execute(
                "INSERT INTO security_videos (filename, cloudinary_url) VALUES (%s, %s)",
                (filename, cloudinary_url)
            )
            conn.commit()
            db_cursor.close()
            print(f"--- [BACKGROUND THREAD] Asset catalog index complete for {filename}. ---")

        # Discard temporary local cache file safely off the local filesystem
        if os.path.exists(local_path):
            os.remove(local_path)
            print(f"--- [BACKGROUND THREAD] Local disk cache cleaned up. ---")

    except Exception as e:
        print(f"--- [BACKGROUND THREAD] CRITICAL MEDIA PIPELINE FAILURE: {e} ---")


# ========================================================
# USER AUTHENTICATION ROUTING SYSTEM
# ========================================================

@app.route('/register', methods=['GET', 'POST'])
def register():
    if 'user' in session:
        return redirect('/')

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        if not username or not password:
            return render_template('register.html', error="All fields are required.")

        if len(password) < 8 or len(password) > 20:
            return render_template('register.html', error="Password must be between 8 and 20 characters long.")

        if not re.search(r"[A-Za-z]", password) or not re.search(r"[0-9]", password):
            return render_template('register.html', error="Password must contain at least one letter and one number.")

        try:
            cursor.execute("SELECT * FROM users WHERE username=%s", (username,))
            if cursor.fetchone():
                return render_template('register.html', error="Username is already registered.")

            cursor.execute("INSERT INTO users (username, password) VALUES (%s, %s)", (username, password))
            conn.commit()

            # --- UPDATED: Grab IP and track registration log ---
            user_ip = request.remote_addr
            session['user'] = username
            cursor.execute(
                "INSERT INTO login_logs (username, ip_address) VALUES (%s, %s)",
                (username, user_ip)
            )
            conn.commit()

            return redirect('/')

        except Exception as e:
            print(f"--- REGISTRATION DATABASE ERROR: {e} ---")
            return render_template('register.html', error="A system error occurred. Please try again.")

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username, password = request.form['username'], request.form['password']
        cursor.execute("SELECT * FROM users WHERE username=%s AND password=%s", (username, password))
        if cursor.fetchone():
            session['user'] = username

            # --- SAFE IP TRACKING LAYER ---
            try:
                # Safely grab headers without crashing if they are missing
                forwarded_for = request.headers.get('X-Forwarded-For')
                if forwarded_for:
                    user_ip = forwarded_for.split(',')[0].strip()
                else:
                    user_ip = request.remote_addr

                # Attempt inserting into database
                cursor.execute(
                    "INSERT INTO login_logs (username, ip_address) VALUES (%s, %s)",
                    (username, user_ip)
                )
                conn.commit()
            except Exception as log_err:
                # If column missing or string parsing fails, print error to logs but DO NOT crash the login!
                print(f"--- WARNING: Could not save login log safely: {log_err} ---")
                if conn:
                    conn.rollback()  # Reset failed transaction state safely

            return redirect('/')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect('/login')

# ========================================================
# SURVEILLANCE DASHBOARD AND RECORDING HOOKS
# ========================================================

@app.route('/')
def dashboard():
    if 'user' not in session:
        return redirect('/login')
    try:
        cursor.execute("SELECT * FROM camera_logs ORDER BY id DESC")
        logs = cursor.fetchall()
    except:
        logs = []
    return render_template('dashboard.html', logs=logs, user=session['user'])


@app.route('/video')
def video():
    if 'user' not in session:
        return redirect('/login')
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/camera_monitoring')
def camera_monitoring():
    if 'user' not in session:
        return redirect('/login')
    return render_template('camera_monitoring.html', user=session['user'], resolution=CAM_RES,
                           stream_type="MJPEG (Live)", fps=CAM_FPS_DEFAULT, is_recording=is_recording)


@app.route('/start_recording')
def start_recording():
    global is_recording, video_writer, current_recording_path
    if not is_recording:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        recordings_dir = os.path.join(base_dir, 'recordings')
        if not os.path.exists(recordings_dir):
            os.makedirs(recordings_dir)

        filename = f"capture_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
        current_recording_path = os.path.join(recordings_dir, filename)

        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        video_writer = cv2.VideoWriter(current_recording_path, fourcc, 20.0, (FRAME_WIDTH, FRAME_HEIGHT))

        if not video_writer.isOpened():
            return jsonify({"status": "error", "message": "Could not open video writer"}), 500
        is_recording = True
    return jsonify({"status": "success"})


@app.route('/stop_recording')
def stop_recording():
    global is_recording, video_writer, current_recording_path
    if not is_recording:
        return jsonify({"status": "error", "message": "Not currently recording"}), 400

    # Unlatch state context rules instantly
    is_recording = False
    if video_writer:
        video_writer.release()
        video_writer = None

    if current_recording_path and os.path.exists(current_recording_path):
        filename = os.path.basename(current_recording_path)

        # Offload heavy cloud I/O transfers onto a background sub-thread worker
        upload_thread = threading.Thread(
            target=background_cloudinary_upload,
            args=(current_recording_path, filename)
        )
        upload_thread.start()

        # Wipe tracking token references instantly to avoid collision loops
        current_recording_path = None

        return jsonify({
            "status": "success",
            "message": "Recording halted successfully. Processing upload in background framework layer."
        })

    return jsonify({"status": "success"})


@app.route('/video_file/<filename>')
def video_file(filename):
    if 'user' not in session:
        return redirect('/login')
    return send_from_directory('recordings', filename)


@app.route('/device_management')
def device_management():
    if 'user' not in session:
        return redirect('/login')
    devices = [{"name": "Router", "ip": "192.168.1.1", "status": "ONLINE"},
               {"name": "IP Camera", "ip": "192.168.1.10", "status": "ONLINE"}]
    return render_template('device_management.html', devices=devices, user=session['user'])


@app.route('/login_logs')
def login_logs():
    if 'user' not in session:
        return redirect('/login')

    logs = []
    if conn:
        try:
            # Open an isolated local request worker cursor
            db_cursor = conn.cursor()
            db_cursor.execute("""
                SELECT id, username, ip_address, login_time 
                FROM login_logs 
                ORDER BY login_time DESC
            """)
            logs = db_cursor.fetchall()
            db_cursor.close()
        except Exception as e:
            print(f"--- DATABASE ERROR ON LOGIN LOGS: {e} ---")
            # CRITICAL: Rollback clears the broken transaction state flag instantly!
            conn.rollback()
            logs = []

    return render_template('login_logs.html', logs=logs, user=session['user'])


@app.route('/recordings_gallery')
def recordings_gallery():
    if 'user' not in session:
        return redirect('/login')

    videos = []
    if conn:
        try:
            db_cursor = conn.cursor()
            db_cursor.execute("SELECT id, filename, cloudinary_url FROM security_videos ORDER BY id DESC")
            videos = db_cursor.fetchall()
            db_cursor.close()
        except Exception as e:
            print(f"--- DATABASE ERROR ON GALLERY: {e} ---")
            # Clear transaction blocks if the schema isn't fully ready
            conn.rollback()
            videos = []

    return render_template('recordings_gallery.html', videos=videos, user=session['user'])


@app.route('/delete_video/<int:video_id>', methods=['POST'])
def delete_video(video_id):
    if 'user' not in session:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

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
                public_id_with_ext = "cctv_recordings/" + cloudinary_url.split('/')[-1]
                public_id = public_id_with_ext.split('.')[0]

                print(f"--- Deleting from Cloudinary: {public_id} ---")
                cloudinary.uploader.destroy(public_id, resource_type="video")
            except Exception as cloud_err:
                print(f"Warning: Cloudinary file deletion failed/skipped: {cloud_err}")

            db_cursor.execute("DELETE FROM security_videos WHERE id = %s", (video_id,))
            conn.commit()
            db_cursor.close()

            print(f"--- DB UPDATE: Video ID {video_id} deleted successfully ---")
            return jsonify({"status": "success"})

        except Exception as e:
            print(f"Error during video deletion: {e}")
            return jsonify({"status": "error", "message": str(e)}), 500

    return jsonify({"status": "error", "message": "Database disconnected"}), 500


# ========================================================
# RUNNER ENVIRONMENT RUN TIME CONTROL
# ========================================================
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)