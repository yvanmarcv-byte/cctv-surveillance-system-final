/**
 * CCTV System - Frontend Interactions
 * Consolidated & Optimized Version
 */

document.addEventListener('DOMContentLoaded', () => {

    // --- 1. SIDEBAR ACTIVE LINK HIGHLIGHT ---
    // Automatically highlights the link that matches the current URL
    const currentPath = window.location.pathname;
    const navLinks = document.querySelectorAll('.sidebar a, .sidebar nav a');

    navLinks.forEach(link => {
        if (link.getAttribute('href') === currentPath) {
            link.classList.add('active');
        }
    });


    // --- 2. REAL-TIME DIGITAL CLOCKS ---
    // Updates both the monitor-specific clock and any global sidebar clocks
    const updateClock = () => {
        const now = new Date();
        const timeString = now.toLocaleTimeString('en-US', {
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hour12: true
        });

        // Target for Camera Monitoring page
        const monitorClock = document.getElementById('monitor-clock');
        if (monitorClock) {
            monitorClock.textContent = timeString;
        }

        // Target for Sidebar or Dashboard if added later
        const liveClock = document.getElementById('live-clock');
        if (liveClock) {
            liveClock.textContent = timeString;
        }
    };

    // Add this inside your DOMContentLoaded block
setInterval(() => {
    fetch('/heartbeat');
}, 3000); // Sends a pulse every 3 seconds


    // Initial call and set interval
    updateClock();
    setInterval(updateClock, 1000);


    // --- 3. SYSTEM STATUS PULSE EFFECT ---
    // Animates the "Live" or "Active" badges to show the system is processing
    const activeBadges = document.querySelectorAll('.status-badge.active');

    if (activeBadges.length > 0) {
        setInterval(() => {
            activeBadges.forEach(badge => {
                badge.style.transition = 'opacity 0.6s ease-in-out';
                badge.style.opacity = (badge.style.opacity === '0.4') ? '1' : '0.4';


            });
        }, 1000);
    }


    // --- 4. TABLE ROW HOVER STYLING ---
    // Ensures smooth transitions for log table rows
    const logRows = document.querySelectorAll('table tbody tr');
    logRows.forEach(row => {
        row.addEventListener('mouseenter', () => {
            row.style.transition = 'background 0.2s ease';
        });
    });

});

/**
 * UTILITY FUNCTIONS
 * Placeholder for future expansion
 */
function takeSnapshot() {
    console.log("Snapshot command triggered.");
    alert("Snapshot feature: This requires a backend route in app.py to save the frame.");
}

document.addEventListener('DOMContentLoaded', () => {
    const startBtn = document.getElementById('start-btn');
    const stopBtn = document.getElementById('stop-btn');
    const recordStatus = document.getElementById('record-status');

    if (startBtn && stopBtn) {
        startBtn.addEventListener('click', () => {
            fetch('/start_recording')
                .then(res => res.json())
                .then(data => {
                    if (data.status === "success") {
                        startBtn.style.display = 'none';
                        stopBtn.style.display = 'inline-block';
                        recordStatus.textContent = 'RECORDING';
                        recordStatus.style.background = '#451a1a';
                        recordStatus.style.color = '#f87171';
                        recordStatus.classList.add('active'); // Re-enables the pulse effect
                    }
                });
        });

        stopBtn.addEventListener('click', () => {
            fetch('/stop_recording')
                .then(res => res.json())
                .then(data => {
                    if (data.status === "success") {
                        stopBtn.style.display = 'none';
                        startBtn.style.display = 'inline-block';
                        recordStatus.textContent = 'IDLE';
                        recordStatus.style.background = '#374151';
                        recordStatus.style.color = '#94a3b8';
                        recordStatus.classList.remove('active');
                    }
                });
        });
    }
});
document.addEventListener('DOMContentLoaded', () => {
    const startBtn = document.getElementById('start-btn');
    const stopBtn = document.getElementById('stop-btn');
    const recordStatus = document.getElementById('record-status');

    if (startBtn && stopBtn) {
        startBtn.addEventListener('click', () => {
            fetch('/start_recording')
                .then(res => res.json())
                .then(data => {
                    if (data.status === "success") {
                        startBtn.style.display = 'none';
                        stopBtn.style.display = 'inline-block';
                        stopBtn.textContent = 'Stop Recording'; // Reset button text context
                        stopBtn.disabled = false;

                        recordStatus.textContent = 'RECORDING';
                        recordStatus.style.background = '#451a1a';
                        recordStatus.style.color = '#f87171';
                        recordStatus.classList.add('active');
                    }
                });
        });

        stopBtn.addEventListener('click', () => {
            // Visual Validation: Instantly disable button and show processing state
            stopBtn.disabled = true;
            stopBtn.style.backgroundColor = '#4b5563'; // Switch to a neutral gray color
            stopBtn.textContent = 'Processing...';
            recordStatus.textContent = 'SAVING';

            fetch('/stop_recording')
                .then(res => res.json())
                .then(data => {
                    if (data.status === "success") {
                        // Reset control interface states instantly
                        stopBtn.style.display = 'none';
                        stopBtn.style.backgroundColor = '#dc2626'; // Revert back to red color

                        startBtn.style.display = 'inline-block';

                        recordStatus.textContent = 'IDLE';
                        recordStatus.style.background = '#374151';
                        recordStatus.style.color = '#94a3b8';
                        recordStatus.classList.remove('active');
                    }
                })
                .catch(err => {
                    console.error("Stop tracking failure: ", err);
                    stopBtn.disabled = false;
                    stopBtn.textContent = 'Stop Recording';
                });
        });
    }
});