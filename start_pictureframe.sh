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

cleanup() {
    echo "📟📟$(date +'%d-%m %H:%M:%S') 📟 🧹 Cleaning up existing PictureFrame processes..." >> logs/pictureframe.log
    # Terminate the slideshow process if it is running.
    if [ -f /tmp/pictureframe_slideshow.pid ]; then
        pkill -F /tmp/pictureframe_slideshow.pid 2>/dev/null || true
        rm -f /tmp/pictureframe_slideshow.pid
    fi
    # Terminate any previous Flask application instance (app.py).
    # Use pkill -f for greater reliability.
    pkill -f "python3 -u app.py" 2>/dev/null || true
    pkill -f "python3 app.py" 2>/dev/null || true
    pkill -f ffmpeg 2>/dev/null || true
    sleep 1 # Allow processes time to exit.
}

while true; do
    # Clean up before each launch.
    cleanup

		echo "📟📟$(date +'%d-%m %H:%M:%S') 📟 ================================================================" >> logs/pictureframe.log
		echo "📟📟$(date +'%d-%m %H:%M:%S') 📟 🚀 Starting the PictureFrame application... 🚀🚀🚀🚀🚀🚀🚀🚀🚀" >> logs/pictureframe.log
		echo "📟📟$(date +'%d-%m %H:%M:%S') 📟 ================================================================" >> logs/pictureframe.log
    
    if [ -f "venv/bin/activate" ]; then
        source venv/bin/activate
    fi

    # Start the application.
    python3 -u app.py >> logs/pictureframe.log 2>&1

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

    echo "[start_pictureframe] Restart requested. Relaunching the application in 2 seconds..." >> logs/pictureframe.log
    sleep 2
done
