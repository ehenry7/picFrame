#!/bin/bash
set -euo pipefail

if ! command -v raspi-config >/dev/null 2>&1; then
    echo "Error: raspi-config is required. Run this on Raspberry Pi OS." >&2
    exit 1
fi

for required in sway python3; do
    if ! command -v "$required" >/dev/null 2>&1; then
        echo "Error: $required is required. Run setup first." >&2
        exit 1
    fi
done

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
FRAME_USER="${SUDO_USER:-$(id -un)}"
FRAME_HOME="$(getent passwd "$FRAME_USER" | cut -d: -f6)"
if [ -z "$FRAME_HOME" ] || [ "$FRAME_USER" = root ]; then
    echo "Error: run this from the Pi desktop user's account (sudo is allowed)." >&2
    exit 1
fi
sudo -u "$FRAME_USER" python3 "$SCRIPT_DIR/configure_auto_frame.py" --home "$FRAME_HOME"
sudo raspi-config nonint do_boot_behaviour B2
echo "PictureFrame auto-start enabled for the next boot (console auto-login)."
echo "The console and Sway startup configuration has been repaired."
echo "Rebooting now..."
sudo reboot
