#!/bin/bash

# This is PictureFrame's main entry-point script, managed by Sway.
# It ensures only one application instance is running and handles restarts.

# Special exit code used to request a restart.
RESTART_CODE=42

cd "$(dirname "$0")" || exit 1
mkdir -p logs || exit 1

# Prevent multiple instances.
LOCK_FILE="/tmp/pictureframe_app.lock"
if [ -f "$LOCK_FILE" ]; then
    PID=$(cat "$LOCK_FILE")
    if ps -p "$PID" > /dev/null; then
        echo "📟📟$(date +'%d-%m %H:%M:%S') 📟 ❌ Instance already running (PID: $PID). Exiting." >> logs/pictureframe.log
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
    echo "📟📟$(date +'%d-%m %H:%M:%S') 📟 🐍 Activating virtual environment" >> logs/pictureframe.log
    . venv/bin/activate
    PIP_CMD="pip install"
    PYTHON_CMD="python3"
else
    echo "📟📟$(date +'%d-%m %H:%M:%S') 📟 🐍 Using global Python (no venv found)" >> logs/pictureframe.log
    # On Debian 12+ / Pi OS with PEP 668, --break-system-packages is needed.
    if python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" 2>/dev/null; then
        PIP_CMD="pip3 install --break-system-packages"
    else
        PIP_CMD="pip3 install"
    fi
    PYTHON_CMD="python3"
fi

# Check and install core requirements if missing.
echo "📟📟$(date +'%d-%m %H:%M:%S') 📟 📦 Checking dependencies..." >> logs/pictureframe.log
if ! $PYTHON_CMD -c "import flask, PIL, pygame, psutil, requests, flask_babel, piexif" 2>/dev/null; then
    echo "📟📟$(date +'%d-%m %H:%M:%S') 📟 📦 Installing core dependencies from requirements.txt..." >> logs/pictureframe.log
    $PIP_CMD -r requirements.txt >> logs/pictureframe.log 2>&1
fi

# Check and install Pi-specific requirements if on a Raspberry Pi.
if [ -f /proc/device-tree/model ]; then
    if ! $PYTHON_CMD -c "import RPi.GPIO" 2>/dev/null; then
        echo "📟📟$(date +'%d-%m %H:%M:%S') 📟 📦 Installing Pi-specific dependencies from requirements-pi.txt..." >> logs/pictureframe.log
        $PIP_CMD -r requirements-pi.txt >> logs/pictureframe.log 2>&1
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
            echo "📟📟$(date +'%d-%m %H:%M:%S') 📟 🧹 Terminating $label (PID: $pid, command: $cmd)" >> logs/pictureframe.log
            kill "$pid" 2>/dev/null
            # Wait briefly for graceful exit, then force-kill if still alive.
            for i in 1 2 3; do
                if ! ps -p "$pid" > /dev/null 2>&1; then
                    break
                fi
                sleep 0.5
            done
            if ps -p "$pid" > /dev/null 2>&1; then
                echo "📟📟$(date +'%d-%m %H:%M:%S') 📟 🧹 Force-killing $label (PID: $pid)" >> logs/pictureframe.log
                kill -9 "$pid" 2>/dev/null
            fi
        else
            echo "📟📟$(date +'%d-%m %H:%M:%S') 📟 🧹 $label PID file found but process $pid is not running (stale)" >> logs/pictureframe.log
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
            echo "📟📟$(date +'%d-%m %H:%M:%S') 📟 🧹 Terminating $label (PID: $pid, command: $cmd)" >> logs/pictureframe.log
            kill "$pid" 2>/dev/null
        done
        sleep 0.5
        # Force-kill any survivors.
        pids=$(pgrep -f "$pattern" 2>/dev/null)
        if [ -n "$pids" ]; then
            for pid in $pids; do
                echo "📟📟$(date +'%d-%m %H:%M:%S') 📟 🧹 Force-killing $label (PID: $pid)" >> logs/pictureframe.log
                kill -9 "$pid" 2>/dev/null
            done
        fi
    fi
}

cleanup() {
    echo "📟📟$(date +'%d-%m %H:%M:%S') 📟 🧹 Cleaning up existing PictureFrame processes..." >> logs/pictureframe.log

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

    echo "📟📟$(date +'%d-%m %H:%M:%S') 📟 ================================================================" >> logs/pictureframe.log
    echo "📟📟$(date +'%d-%m %H:%M:%S') 📟 🚀 Starting the PictureFrame application..." >> logs/pictureframe.log
    echo "📟📟$(date +'%d-%m %H:%M:%S') 📟 ================================================================" >> logs/pictureframe.log

    # Start the application.
    echo "📟📟$(date +'%d-%m %H:%M:%S') 📟 ▶️ Executing: $PYTHON_CMD -u app.py" >> logs/pictureframe.log
    $PYTHON_CMD -u app.py >> logs/pictureframe.log 2>&1

    exit_code=$?
    echo "📟📟$(date +'%d-%m %H:%M:%S') 📟 🛑 Application exited with code $exit_code" >> logs/pictureframe.log

    if [ $exit_code -eq 0 ]; then
        echo "📟📟$(date +'%d-%m %H:%M:%S') 📟 ✅ Normal shutdown (code 0)" >> logs/pictureframe.log
        break
    fi

    if [ $exit_code -ne $RESTART_CODE ]; then
        echo "📟📟$(date +'%d-%m %H:%M:%S') 📟 🔄 Restart requested in 5s..." >> logs/pictureframe.log
        sleep 5 # Prevent a rapid loop if the application crashes.
        continue
    fi

    echo "📟📟$(date +'%d-%m %H:%M:%S') 📟 🔄 Restart requested (exit code 42). Relaunching in 2 seconds..." >> logs/pictureframe.log
    sleep 2
done
