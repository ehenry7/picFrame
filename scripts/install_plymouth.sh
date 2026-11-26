#!/bin/bash
# Install the PictureFrame Plymouth boot splash on a Raspberry Pi.
# Idempotent: copies the theme, selects it, enables 'splash' on the kernel
# command line, hides the firmware rainbow and rebuilds the initramfs.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
THEME="/usr/share/plymouth/themes/pictureframe"

echo "==> Installing theme into $THEME"
sudo mkdir -p "$THEME"
sudo cp "$ROOT/scripts/plymouth/pictureframe.plymouth" "$THEME/"
sudo cp "$ROOT/scripts/plymouth/pictureframe.script" "$THEME/"
sudo cp "$ROOT/static/splash_boot.png" "$THEME/splash.png"
sudo chmod -R a+rX "$THEME"

echo "==> Selecting theme"
sudo plymouth-set-default-theme pictureframe

echo "==> Patching kernel command line"
sudo python3 - "$ROOT" <<'PY'
import sys
from pathlib import Path

cmdline = Path("/boot/firmware/cmdline.txt")
tokens = cmdline.read_text().strip().split()
for token in ("splash", "quiet", "plymouth.ignore-serial-consoles"):
    if token not in tokens:
        tokens.append(token)
cmdline.write_text(" ".join(tokens) + "\n")

config = Path("/boot/firmware/config.txt")
lines = config.read_text().splitlines()
if not any(line.strip().startswith("disable_splash=") for line in lines):
    lines.insert(0, "disable_splash=1")
    config.write_text("\n".join(lines) + "\n")
print("cmdline:", cmdline.read_text().strip())
PY

echo "==> Rebuilding initramfs"
sudo plymouth-set-default-theme -R pictureframe

echo "==> Done. Reboot to see the splash."
