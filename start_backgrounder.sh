#!/bin/bash
# start_backgrounder.sh — Start PictureFrame in background updater mode on Linux.
#
# This script launches the Flask app with PICTUREFRAME_APP_MODE=background_updater
# so the app runs as a desktop wallpaper updater instead of a fullscreen slideshow.
#
# Usage: ./start_backgrounder.sh
# Stop with: python stop.py  (or Ctrl+C)

cd "$(dirname "$0")" || exit 1
mkdir -p logs

# Force background updater mode via environment variable.
export PICTUREFRAME_APP_MODE=background_updater

# Use venv if available, otherwise global Python.
if [ -f "venv/bin/activate" ]; then
    echo "🐍 Activating virtual environment"
    . venv/bin/activate
    PIP_CMD="pip install"
    PYTHON_CMD="python3"
else
    echo "🐍 Using global Python"
    if python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" 2>/dev/null; then
        PIP_CMD="pip3 install --break-system-packages"
    else
        PIP_CMD="pip3 install"
    fi
    PYTHON_CMD="python3"
fi

# Check and install core requirements if missing.
if ! $PYTHON_CMD -c "import flask, PIL, pygame, psutil, requests, flask_babel, piexif" 2>/dev/null; then
    echo "📦 Installing dependencies from requirements.txt..."
    $PIP_CMD -r requirements.txt >> logs/pictureframe.log 2>&1
fi

echo "🖼️ Starting PictureFrame in background updater mode..."
echo "📋 Logs: logs/pictureframe.log"
echo "🛑 Stop with: python stop.py  (or Ctrl+C)"

exec $PYTHON_CMD -u app.py >> logs/pictureframe.log 2>&1
