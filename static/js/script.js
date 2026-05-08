/**
 * CCTV System - Frontend Interactions
 */

document.addEventListener('DOMContentLoaded', () => {

    // 1. Sidebar Active State Toggle
    // Automatically highlights the link that matches the current URL
    const currentPath = window.location.pathname;
    const sidebarLinks = document.querySelectorAll('.sidebar a');

    sidebarLinks.forEach(link => {
        if (link.getAttribute('href') === currentPath) {
            link.classList.add('active');
        }
    });

    // 2. Real-Time Digital Clock
    // Useful for security monitoring to keep track of precise time
    const updateClock = () => {
        const now = new Date();
        const timeString = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });

        // We look for a clock element (see HTML update below)
        const clockElement = document.getElementById('live-clock');
        if (clockElement) {
            clockElement.textContent = timeString;
        }
    };
    setInterval(updateClock, 1000);

    // 3. Table Row Highlighting
    // Makes it easier to read logs when hovering with the mouse
    const logRows = document.querySelectorAll('table tbody tr');
    logRows.forEach(row => {
        row.addEventListener('mouseenter', () => {
            row.style.transition = 'background 0.2s';
        });
    });

    // 4. Camera Status Indicator (Simulated)
    // Randomly "flickers" a status dot to make the dashboard feel alive
    const statusDot = document.querySelector('.status-badge.active');
    if (statusDot) {
        setInterval(() => {
            statusDot.style.opacity = statusDot.style.opacity === '0.5' ? '1' : '0.5';
        }, 800);
    }
});

/**
 * 5. Snapshot Feature (Optional)
 * If you add a "Snapshot" button, this captures the current frame
 */
function takeSnapshot() {
    alert("Snapshot saved to server! (Functionality can be added to App.py)");
    // In a real app, this would trigger an AJAX call to save the frame
}

document.addEventListener('DOMContentLoaded', () => {

    // --- 1. AJAX BLUR TOGGLE (No Flicker) ---
    const blurBtn = document.getElementById('blur-btn');
    const blurStatusText = document.getElementById('blur-status-text');

    if (blurBtn) {
        blurBtn.addEventListener('click', (e) => {
            e.preventDefault(); // Stop the page from reloading

            fetch('/toggle_blur')
                .then(response => response.json())
                .then(data => {
                    // Update the button text
                    blurBtn.textContent = data.blur_active ? 'Disable Blur' : 'Blur Background';

                    // Update the "Privacy Status" card text if it exists
                    if (blurStatusText) {
                        blurStatusText.textContent = data.blur_active ? 'Yes' : 'No';
                    }
                })
                .catch(err => console.error('Error toggling blur:', err));
        });
    }

    // --- 2. SIDEBAR ACTIVE LINK HIGHLIGHT ---
    const currentPath = window.location.pathname;
    const navLinks = document.querySelectorAll('.sidebar nav a');

    navLinks.forEach(link => {
        if (link.getAttribute('href') === currentPath) {
            link.classList.add('active');
        }
    });
});
document.addEventListener('DOMContentLoaded', () => {
    const updateClock = () => {
        const now = new Date();
        const timeString = now.toLocaleTimeString('en-US', {
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hour12: true
        });

        const clockElement = document.getElementById('monitor-clock');
        if (clockElement) {
            clockElement.textContent = timeString;
        }
    };

    setInterval(updateClock, 1000);
    updateClock(); // Initial call
});