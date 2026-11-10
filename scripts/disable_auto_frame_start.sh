#!/bin/bash
set -euo pipefail

if ! command -v raspi-config >/dev/null 2>&1; then
    echo "Error: raspi-config is required. Run this on Raspberry Pi OS." >&2
    exit 1
fi

sudo raspi-config nonint do_boot_behaviour B4
echo "PictureFrame auto-start disabled for the next boot (desktop auto-login)."
echo "Requires Raspberry Pi OS Desktop; PictureFrame remains installed."
echo "Rebooting now..."
sudo reboot
