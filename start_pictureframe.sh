#!/bin/bash

# This is PictureFrame's main entry-point script, managed by Sway.
# It ensures only one application instance is running and handles restarts.

# Special exit code used to request a restart.
RESTART_CODE=42

cd "$(dirname "$0")" || exit 1
mkdir -p logs || exit 1

# --- Helper: log to both console and log file --------------------------
log() {
    local msg="📟$(date +'%d-%m %H:%M:%S') 📟 $1"
    echo "$msg"
    echo "$msg" >> logs/pictureframe.log
}

# Prevent multiple instances of this supervisor script.
LOCK_FILE="/tmp/pictureframe_app.lock"
if [ -f "$LOCK_FILE" ]; then
    PID=$(cat "$LOCK_FILE")
    if ps -p "$PID" > /dev/null; then
        log "❌ Instance already running (PID: $PID). Exiting."
        exit 1
    fi
fi
echo $$ > "$LOCK_FILE"

# Change to the script directory so relative paths work.
cd "$(dirname "$0")" || exit 1

# Ensure the log directory exists.
mkdir -p logs

# --- Python environment setup -------------------------------------------
# Use a virtual environment if one exists; otherwise fall back to the
# global Python installation.  In both cases, ensure dependencies are
# installed before launching the app.

if [ -f "venv/bin/activate" ]; then
    log "🐍 Activating virtual environment"
    . venv/bin/activate
    PIP_CMD="python3 -m pip install"
    PYTHON_CMD="python3"
else
    log "🐍 Using global Python (no venv found)"
    # On Debian 12+ / Pi OS with PEP 668, --break-system-packages is needed.
    if python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" 2>/dev/null; then
        PIP_CMD="python3 -m pip install --break-system-packages"
    else
        PIP_CMD="python3 -m pip install"
    fi
    PYTHON_CMD="python3"
fi

# Check and install core requirements if missing.
log "📦 Checking dependencies..."
if ! $PYTHON_CMD -c "import flask, PIL, pygame, psutil, requests, flask_babel, piexif" 2>/dev/null; then
    log "📦 Installing core dependencies from requirements.txt..."
    log "📦 Using: $PIP_CMD -r requirements.txt"
    $PIP_CMD -r requirements.txt 2>&1 | tee -a logs/pictureframe.log
    # Verify the install succeeded.
    if ! $PYTHON_CMD -c "import flask_babel" 2>/dev/null; then
        log "❌ Failed to install dependencies. Trying with pip3 directly..."
        pip3 install flask-babel 2>&1 | tee -a logs/pictureframe.log
    fi
    if ! $PYTHON_CMD -c "import flask_babel" 2>/dev/null; then
        log "❌ Cannot import flask_babel after install. Please run manually:"
        log "❌   $PIP_CMD -r requirements.txt"
        log "❌ Or: pip3 install --break-system-packages flask-babel"
        exit 1
    fi
    log "📦 Dependencies installed successfully."
else
    log "📦 All core dependencies are installed."
fi

# Check and install Pi-specific requirements if on a Raspberry Pi.
if [ -f /proc/device-tree/model ]; then
    if ! $PYTHON_CMD -c "import RPi.GPIO" 2>/dev/null; then
        log "📦 Installing Pi-specific dependencies from requirements-pi.txt..."
        $PIP_CMD -r requirements-pi.txt 2>&1 | tee -a logs/pictureframe.log
    else
        log "📦 Pi-specific dependencies are installed."
    fi
fi

# --- One-time cleanup of stale processes (before first launch) ----------
# Only run once at startup, NOT on every restart loop iteration.
# This prevents killing the app we just started (exit code 143 bug).
cleanup_stale() {
    log "🧹 Cleaning up stale processes from previous run..."

    # Terminate the slideshow process via its PID file.
    if [ -f /tmp/pictureframe_slideshow.pid ]; then
        PID=$(cat /tmp/pictureframe_slideshow.pid 2>/dev/null)
        if [ -n "$PID" ] && ps -p "$PID" > /dev/null 2>&1; then
            log "🧹 Terminating slideshow (PID: $PID)"
            kill "$PID" 2>/dev/null
            sleep 1
            ps -p "$PID" > /dev/null 2>&1 && kill -9 "$PID" 2>/dev/null
        fi
        rm -f /tmp/pictureframe_slideshow.pid
    fi

    # Terminate the background updater process via its PID file.
    if [ -f /tmp/pictureframe_background.pid ]; then
        PID=$(cat /tmp/pictureframe_background.pid 2>/dev/null)
        if [ -n "$PID" ] && ps -p "$PID" > /dev/null 2>&1; then
            log "🧹 Terminating background updater (PID: $PID)"
            kill "$PID" 2>/dev/null
            sleep 1
            ps -p "$PID" > /dev/null 2>&1 && kill -9 "$PID" 2>/dev/null
        fi
        rm -f /tmp/pictureframe_background.pid
    fi

    # Terminate any leftover app.py processes (but not this script).
    CURRENT_PID=$$
    for PID in $(pgrep -f "python3.*app\.py" 2>/dev/null); do
        if [ "$PID" != "$CURRENT_PID" ]; then
            log "🧹 Terminating leftover app.py (PID: $PID)"
            kill "$PID" 2>/dev/null
        fi
    done

    # Terminate any ffmpeg child processes.
    for PID in $(pgrep -f "ffmpeg" 2>/dev/null); do
        log "🧹 Terminating ffmpeg (PID: $PID)"
        kill "$PID" 2>/dev/null
    done

    sleep 1
}

# Run cleanup once before the first launch.
cleanup_stale

while true; do
    log "========================================================"
    log "🚀 Starting the PictureFrame application..."
    log "========================================================"

    # Start the application — output to both console and log file.
    log "▶️ Executing: $PYTHON_CMD -u app.py"
    $PYTHON_CMD -u app.py 2>&1 | tee -a logs/pictureframe.log

    exit_code=${PIPESTATUS[0]}
    log "🛑 Application exited with code $exit_code"

    if [ $exit_code -eq 0 ]; then
        log "✅ Normal shutdown (code 0)"
        break
    fi

    if [ $exit_code -eq 143 ] || [ $exit_code -eq 137 ]; then
        log "⚠️ Application was killed by signal (code $exit_code = SIGTERM/SIGKILL)"
        log "⚠️ This may happen during shutdown. Restarting in 5s..."
        sleep 5
        continue
    fi

    if [ $exit_code -ne $RESTART_CODE ]; then
        log "🔄 Application crashed (code $exit_code). Restarting in 5s..."
        sleep 5 # Prevent a rapid loop if the application crashes.
        continue
    fi

    log "🔄 Restart requested (exit code 42). Relaunching in 2 seconds..."
    sleep 2
done
