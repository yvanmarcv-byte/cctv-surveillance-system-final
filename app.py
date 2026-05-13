from flask import Flask, render_template, request, redirect, session, Response, jsonify, send_from_directory
import psycopg2
import cv2
import numpy as np
import time
import os
from datetime import datetime

app = Flask(__name__)
app.secret_key = "secretkey123"

# =========================
# GLOBAL RECORDING STATE
# =========================
is_recording = False
video_writer = None

# =========================
# FACE DETECTION SETUP
# =========================
face_cascade = cv2.CascadeClassifier(
    cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
)

# POSTGRESQL CONNECTION
# =========================
# This looks for the DATABASE_URL provided by Railway.
# If it doesn't find it (like on your laptop), it falls back to localhost.
db_url = os.environ.get("DATABASE_URL")

try:
    if db_url:
        # Use the cloud connection string
        conn = psycopg2.connect(db_url)
        print("--- CONNECTED TO RAILWAY DATABASE ---")
    else:
        # Fallback for your local laptop testing
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
# =========================
# CAMERA SETUP
# =========================
camera = cv2.VideoCapture(0)

if not camera.isOpened():
    print("Warning: Camera not available")

FRAME_WIDTH = int(camera.get(cv2.CAP_PROP_FRAME_WIDTH))
FRAME_HEIGHT = int(camera.get(cv2.CAP_PROP_FRAME_HEIGHT))
CAM_RES = f"{FRAME_WIDTH}x{FRAME_HEIGHT}"
CAM_FPS_DEFAULT = 30


# =========================
# VIDEO STREAM FUNCTION
# =========================
def generate_frames():
    global is_recording, video_writer
    prev_time = 0

    while True:
        success, frame = camera.read()
        if not success:
            break

        # --- CALCULATE REAL FPS ---
        current_time = time.time()
        fps_real = 1 / (current_time - prev_time) if (current_time - prev_time) > 0 else 30
        prev_time = current_time

        output_frame = frame.copy()

        # --- FACE DETECTION ---
        gray = cv2.cvtColor(output_frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.equalizeHist(gray)
        faces = face_cascade.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=8, minSize=(50, 50)
        )

        for (x, y, w, h) in faces:
            cv2.rectangle(output_frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
            cv2.putText(output_frame, "FACE DETECTED", (x, y - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

        # --- PERSISTENT RECORDING LOGIC (UPDATED) ---
        if is_recording and video_writer is not None:
            # Only attempt to write if the writer is properly opened
            if video_writer.isOpened():
                try:
                    video_writer.write(output_frame)
                except Exception as e:
                    print(f"OpenCV Write Error: {e}")
                    # If it crashes once, stop recording to save the stream
                    is_recording = False
            else:
                # If we get here, the codec failed to start
                print("VideoWriter is not opened. Check codec compatibility.")
                is_recording = False

        # --- ENCODE AND YIELD ---
        ret, buffer = cv2.imencode('.jpg', output_frame)
        if not ret:
            continue

        frame_bytes = buffer.tobytes()
        yield (b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

# =========================
# RECORDING & GALLERY ROUTES
# =========================

@app.route('/start_recording')
def start_recording():
    global is_recording, video_writer
    if not is_recording:
        # Get the absolute path to the project directory
        base_dir = os.path.dirname(os.path.abspath(__file__))
        recordings_dir = os.path.join(base_dir, 'recordings')

        if not os.path.exists(recordings_dir):
            os.makedirs(recordings_dir)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(recordings_dir, f"capture_{timestamp}.mp4")

        # Use 'avc1' or 'mp4v' for better compatibility on Linux/Web
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        video_writer = cv2.VideoWriter(filename, fourcc, 20.0, (FRAME_WIDTH, FRAME_HEIGHT))

        if not video_writer.isOpened():
            return jsonify({"status": "error", "message": "Could not start video writer"}), 500

        is_recording = True
    return jsonify({"status": "success"})


@app.route('/stop_recording')
def stop_recording():
    global is_recording, video_writer
    is_recording = False
    if video_writer:
        video_writer.release()
        video_writer = None
        print("Recording stopped.")
    return jsonify({"status": "success", "is_recording": False})


@app.route('/recordings_gallery')
def recordings_gallery():
    if 'user' not in session:
        return redirect('/login')

    files = []
    if os.path.exists('recordings'):
        # List both webm and mp4 (if you have old ones)
        files = [f for f in os.listdir('recordings') if f.endswith(('.webm', '.mp4'))]
        files.sort(reverse=True)

    return render_template('recordings_gallery.html', files=files, user=session['user'])


@app.route('/video_file/<filename>')
def video_file(filename):
    if 'user' not in session:
        return redirect('/login')
    return send_from_directory('recordings', filename)


# =========================
# STANDARD ROUTES
# =========================

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
    return render_template(
        'camera_monitoring.html',
        user=session['user'],
        resolution=CAM_RES,
        stream_type="MJPEG (Live)",
        fps=CAM_FPS_DEFAULT,
        is_recording=is_recording
    )


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username, password = request.form['username'], request.form['password']
        cursor.execute("SELECT * FROM users WHERE username=%s AND password=%s", (username, password))
        if cursor.fetchone():
            session['user'] = username
            cursor.execute("INSERT INTO login_logs (username) VALUES (%s)", (username,))
            conn.commit()
            return redirect('/')
    return render_template('login.html')

@app.route('/device_management')
def device_management():
    if 'user' not in session:
        return redirect('/login')

    # This matches the list shown in your original screenshot
    devices = [
        {"name": "Router", "ip": "192.168.1.1", "status": "ONLINE"},
        {"name": "IP Camera", "ip": "192.168.1.10", "status": "ONLINE"},
        {"name": "Web Server", "ip": "192.168.1.20", "status": "ONLINE"}
    ]

    return render_template(
        'device_management.html',
        devices=devices,
        user=session['user']
    )

@app.route('/login_logs')
def login_logs():
    if 'user' not in session:
        return redirect('/login')

    # Fetching logs ordered by the most recent first
    cursor.execute("SELECT * FROM login_logs ORDER BY login_time DESC")
    logs = cursor.fetchall()

    return render_template(
        'login_logs.html',
        logs=logs,
        user=session['user']
    )

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect('/login')


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)