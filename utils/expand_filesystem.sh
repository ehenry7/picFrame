#!/bin/bash

# This script is designed to be run by the PictureFrame web application.
# It uses raspi-config to expand the root partition so the system
# can use all available space on the SD card.

set -e # Exit if any command fails.

echo "STEP:START:--- Starting filesystem expansion ---"
echo "STEP:INFO:Using raspi-config to expand the root partition..."
sudo raspi-config --expand-rootfs
echo "STEP:DONE:The change has been scheduled. Expansion will complete at the next system restart. Restart the Raspberry Pi from the interface to apply the changes."