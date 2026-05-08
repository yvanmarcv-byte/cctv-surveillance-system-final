from flask import Flask, render_template, request, redirect, session, Response
import psycopg2
import cv2
import numpy as np
from flask import jsonify
import time

app = Flask(__name__)
app.secret_key = "secretkey123"
blur_background = False

# =========================
# POSTGRESQL CONNECTION
# =========================
conn = psycopg2.connect(
    host="localhost",
    database="surveillance_db",
    user="postgres",
    password="admin123",
    port="5432"
)

cursor = conn.cursor()

# =========================
# CAMERA SETUP
# =========================
# 0 = local webcam
# Replace with RTSP link later if needed
camera = cv2.VideoCapture(0)

if not camera.isOpened():
    print("Warning: Camera not available")


# =========================
# VIDEO STREAM FUNCTION
# =========================
def generate_frames():
    global blur_background
    prev_time = 0

    while True:
        success, frame = camera.read()
        if not success:
            break

        output_frame = frame.copy()

        # --- CALCULATE REAL FPS ---
        current_time = time.time()
        # Calculate the difference in time
        fps_real = 1 / (current_time - prev_time)
        prev_time = current_time

        # --- FACE DETECTION & BLUR LOGIC ONLY ---
        gray = cv2.cvtColor(output_frame, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, 1.1, 5, minSize=(30, 30))

        if blur_background:
            blurred_frame = cv2.GaussianBlur(output_frame, (55, 55), 0)
            temp_frame = blurred_frame.copy()
            for (x, y, w, h) in faces:
                temp_frame[y:y + h, x:x + w] = output_frame[y:y + h, x:x + w]
                cv2.rectangle(temp_frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
            output_frame = temp_frame
        else:
            for (x, y, w, h) in faces:
                cv2.rectangle(output_frame, (x, y), (x + w, y + h), (0, 255, 0), 2)

        # --- ENCODE AND YIELD (No Timestamp) ---
        ret, buffer = cv2.imencode('.jpg', output_frame)
        if not ret:
            continue

        frame_bytes = buffer.tobytes()
        yield (b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
# =========================
# LOGIN ROUTE
# =========================
@app.route('/login', methods=['GET', 'POST'])
def login():

    if request.method == 'POST':

        username = request.form['username']
        password = request.form['password']

        cursor.execute(
            "SELECT * FROM users WHERE username=%s AND password=%s",
            (username, password)
        )

        user = cursor.fetchone()

        if user:

            session['user'] = username

            # SAVE LOGIN LOG
            cursor.execute(
                "INSERT INTO login_logs (username) VALUES (%s)",
                (username,)
            )

            conn.commit()

            return redirect('/')

        else:

            return render_template(
                'login.html',
                error="Invalid username or password"
            )

    return render_template('login.html')


# =========================
# REGISTER ROUTE
# =========================
@app.route('/register', methods=['GET', 'POST'])
def register():

    if request.method == 'POST':

        username = request.form['username']
        password = request.form['password']

        # Check if username already exists
        cursor.execute(
            "SELECT * FROM users WHERE username=%s",
            (username,)
        )

        existing_user = cursor.fetchone()

        if existing_user:
            return render_template(
                'register.html',
                error="Username already exists"
            )

        # Insert new user
        cursor.execute(
            "INSERT INTO users (username, password) VALUES (%s, %s)",
            (username, password)
        )

        conn.commit()

        return redirect('/login')

    return render_template('register.html')


# =========================
# DASHBOARD
# =========================
from datetime import datetime

@app.route('/')
def dashboard():
    # Protect dashboard
    if 'user' not in session:
        return redirect('/login')

    try:
        cursor.execute("SELECT * FROM camera_logs ORDER BY id DESC")
        raw_logs = cursor.fetchall()

        # Ensure timestamps are datetime objects for Jinja2
        logs = []
        for row in raw_logs:
            temp_list = list(row)
            # If the timestamp (index 3) is a string, convert it
            if len(temp_list) > 3 and isinstance(temp_list[3], str):
                try:
                    # Adjust format if your DB uses a different string format
                    temp_list[3] = datetime.strptime(temp_list[3], '%Y-%m-%d %H:%M:%S.%f')
                except ValueError:
                    temp_list[3] = datetime.strptime(temp_list[3], '%Y-%m-%d %H:%M:%S')
            logs.append(temp_list)

    except Exception as e:
        print("Database error:", e)
        logs = []

    return render_template(
        'dashboard.html',
        logs=logs,
        user=session['user']
    )

# =========================
# VIDEO STREAM ROUTE
# =========================
@app.route('/video')
def video():

    if 'user' not in session:
        return redirect('/login')

    return Response(
        generate_frames(),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )


# =========================
# LOGOUT ROUTE
# =========================
@app.route('/logout')
def logout():

    session.pop('user', None)

    return redirect('/login')

camera = cv2.VideoCapture(0)
# Cache these values so we don't ask the hardware every second
CAM_RES = f"{int(camera.get(cv2.CAP_PROP_FRAME_WIDTH))}x{int(camera.get(cv2.CAP_PROP_FRAME_HEIGHT))}"
CAM_FPS = int(camera.get(cv2.CAP_PROP_FPS))
if CAM_FPS <= 0: CAM_FPS = 30 # Standard fallback

# =========================
# CAMERA MONITORING ROUTE
# =========================
@app.route('/camera_monitoring')
def camera_monitoring():
    if 'user' not in session:
        return redirect('/login')

    # Get actual resolution from the camera object
    width = int(camera.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(camera.get(cv2.CAP_PROP_FRAME_HEIGHT))
    res_string = f"{width}x{height}"


    # Get the codec/format (usually MJPEG for webcams)
    # This is a bit advanced, so we can also check if the camera is opened
    stream_type = "MJPEG (Live)" if camera.isOpened() else "Disconnected"

    return render_template(
        'camera_monitoring.html',
        user=session['user'],
        blur_background=blur_background,
        resolution=CAM_RES,
        stream_type="MJPEG (Live)",
        fps=CAM_FPS  # <-- This name MUST match the HTML
    )

# =========================
# DEVICE MANAGEMENT ROUTE
# =========================
@app.route('/device_management')
def device_management():

    # Protect page
    if 'user' not in session:
        return redirect('/login')

    devices = [

        {
            "name": "Router",
            "ip": "192.168.1.1",
            "status": "ONLINE"
        },

        {
            "name": "IP Camera",
            "ip": "192.168.1.10",
            "status": "ONLINE"
        },

        {
            "name": "Web Server",
            "ip": "192.168.1.20",
            "status": "ONLINE"
        }

    ]

    return render_template(
        'device_management.html',
        devices=devices,
        user=session['user']
    )


# =========================
# FACE DETECTION
# =========================
face_cascade = cv2.CascadeClassifier(
    cv2.data.haarcascades +
    'haarcascade_frontalface_default.xml'
)

# =========================
# LOGIN LOGS PAGE
# =========================
@app.route('/login_logs')
def login_logs():

    if 'user' not in session:
        return redirect('/login')

    cursor.execute(
        "SELECT * FROM login_logs ORDER BY login_time DESC"
    )

    logs = cursor.fetchall()

    return render_template(
        'login_logs.html',
        logs=logs,
        user=session['user']
    )

# =========================
# TOGGLE BLUR BACKGROUND
# =========================


@app.route('/toggle_blur')
def toggle_blur():
    global blur_background
    blur_background = not blur_background
    # Return a JSON response instead of a redirect
    return jsonify({"status": "success", "blur_active": blur_background})

# =========================
# RUN APP
# =========================
if __name__ == '__main__':

    app.run(
        host='0.0.0.0',
        port=5000,
        debug=True
    )