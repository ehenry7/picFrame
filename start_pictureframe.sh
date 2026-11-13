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

# Prevent multiple instances.
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
    PIP_CMD="pip install"
    PYTHON_CMD="python3"
else
    log "🐍 Using global Python (no venv found)"
    # On Debian 12+ / Pi OS with PEP 668, --break-system-packages is needed.
    if python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" 2>/dev/null; then
        PIP_CMD="pip3 install --break-system-packages"
    else
        PIP_CMD="pip3 install"
    fi
    PYTHON_CMD="python3"
fi

# Check and install core requirements if missing.
log "📦 Checking dependencies..."
if ! $PYTHON_CMD -c "import flask, PIL, pygame, psutil, requests, flask_babel, piexif" 2>/dev/null; then
    log "📦 Installing core dependencies from requirements.txt..."
    $PIP_CMD -r requirements.txt 2>&1 | tee -a logs/pictureframe.log
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

# --- Helper: log and kill a process by PID file ------------------------
kill_pid_file() {
    local pid_file="$1"
    local label="$2"
    if [ -f "$pid_file" ]; then
        local pid
        pid=$(cat "$pid_file" 2>/dev/null)
        if [ -n "$pid" ] && ps -p "$pid" > /dev/null 2>&1; then
            local cmd
            cmd=$(ps -p "$pid" -o comm= 2>/dev/null || echo "unknown")
            log "🧹 Terminating $label (PID: $pid, command: $cmd)"
            kill "$pid" 2>/dev/null
            # Wait briefly for graceful exit, then force-kill if still alive.
            for i in 1 2 3; do
                if ! ps -p "$pid" > /dev/null 2>&1; then
                    break
                fi
                sleep 0.5
            done
            if ps -p "$pid" > /dev/null 2>&1; then
                log "🧹 Force-killing $label (PID: $pid)"
                kill -9 "$pid" 2>/dev/null
            fi
        else
            log "🧹 $label PID file found but process $pid is not running (stale)"
        fi
        rm -f "$pid_file"
    fi
}

# --- Helper: log and kill processes matching a pattern -----------------
kill_pattern() {
    local pattern="$1"
    local label="$2"
    local pids
    pids=$(pgrep -f "$pattern" 2>/dev/null)
    if [ -n "$pids" ]; then
        for pid in $pids; do
            local cmd
            cmd=$(ps -p "$pid" -o args= 2>/dev/null | head -c 120 || echo "unknown")
            log "🧹 Terminating $label (PID: $pid, command: $cmd)"
            kill "$pid" 2>/dev/null
        done
        sleep 0.5
        # Force-kill any survivors.
        pids=$(pgrep -f "$pattern" 2>/dev/null)
        if [ -n "$pids" ]; then
            for pid in $pids; do
                log "🧹 Force-killing $label (PID: $pid)"
                kill -9 "$pid" 2>/dev/null
            done
        fi
    fi
}

cleanup() {
    log "🧹 Cleaning up existing PictureFrame processes..."

    # Terminate the slideshow process via its PID file.
    kill_pid_file "/tmp/pictureframe_slideshow.pid" "slideshow"

    # Terminate the background updater process via its PID file.
    kill_pid_file "/tmp/pictureframe_background.pid" "background updater"

    # Terminate any previous Flask application instance (app.py).
    kill_pattern "python3 -u app.py" "Flask app (app.py -u)"
    kill_pattern "python3 app.py" "Flask app (app.py)"

    # Terminate any ffmpeg child processes.
    kill_pattern "ffmpeg" "ffmpeg"

    sleep 1 # Allow processes time to exit.
}

while true; do
    # Clean up before each launch.
    cleanup

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

    if [ $exit_code -ne $RESTART_CODE ]; then
        log "🔄 Restart requested in 5s..."
        sleep 5 # Prevent a rapid loop if the application crashes.
        continue
    fi

    log "🔄 Restart requested (exit code 42). Relaunching in 2 seconds..."
    sleep 2
done
