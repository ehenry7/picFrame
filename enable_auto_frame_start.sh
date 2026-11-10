#!/bin/bash
set -euo pipefail

if ! command -v raspi-config >/dev/null 2>&1; then
    echo "Error: raspi-config is required. Run this on Raspberry Pi OS." >&2
    exit 1
fi

sudo raspi-config nonint do_boot_behaviour B2
echo "PictureFrame auto-start enabled for the next boot (console auto-login)."
echo "Requires the Sway auto-start configuration created by setup.sh."
echo "Rebooting now..."
sudo reboot
