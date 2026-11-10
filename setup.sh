#!/bin/bash

echo "=== [1/12] Updating package lists (apt update) ==="
sudo apt update


echo "=== [2/12] Installing dependencies ==="
sudo apt install -y sway xterm python3 python3-venv python3-pip libjpeg-dev libopenjp2-7-dev libtiff-dev ffmpeg git network-manager jq mpv gettext libheif-dev

echo "=== [2.5/12] Configuring the French system locale (fr_FR) ==="
if [ -f "/etc/locale.gen" ]; then
    if ! grep -q "^fr_FR.UTF-8 UTF-8" /etc/locale.gen; then
        echo "Enabling the fr_FR.UTF-8 locale..."
        sudo sed -i 's/# fr_FR.UTF-8 UTF-8/fr_FR.UTF-8 UTF-8/' /etc/locale.gen
        sudo locale-gen
    else
        echo "✅ The fr_FR.UTF-8 locale is already enabled."
    fi
fi


echo "=== [3/12] Disabling Wi-Fi power saving ==="
# Install RPi.GPIO conditionally for fan control.
if [ -f "/etc/os-release" ]; then
    source /etc/os-release
    if [[ "$ID" == "raspbian" || "$ID" == "debian" ]]; then
        echo "Raspberry Pi OS (or Debian) detected. Installing RPi.GPIO..."
        sudo apt-get install -y python3-rpi.gpio
    fi
fi

CONF_FILE="/etc/NetworkManager/conf.d/99-disable-wifi-powersave.conf"
if [ ! -f "$CONF_FILE" ]; then
    echo "Creating the configuration file to disable Wi-Fi power saving..."
    sudo tee "$CONF_FILE" > /dev/null <<'EOL'
[connection]
wifi.powersave = 2
EOL
    echo "✅ Wi-Fi power saving disabled. Restarting NetworkManager..."
    sudo systemctl restart NetworkManager
    sleep 2 # Briefly wait for the service to restart.
else
    echo "✅ Wi-Fi power saving is already disabled."
fi

echo "=== [4/12] Automatic time zone configuration ==="
DETECTED_TIMEZONE="UTC" # Default value.
TIMEZONE_SOURCE="fallback" # Default source.

echo "Attempting to detect the time zone from the public IP address..."
# Use the ip-api.com API and jq to extract the time zone.
TIMEZONE_FROM_API=$(curl -s http://ip-api.com/json | jq -r '.timezone')

# Check whether detection succeeded.
if [ -n "$TIMEZONE_FROM_API" ] && [ "$TIMEZONE_FROM_API" != "null" ]; then
    echo "Detected time zone: $TIMEZONE_FROM_API"
    sudo timedatectl set-timezone "$TIMEZONE_FROM_API"
    DETECTED_TIMEZONE="$TIMEZONE_FROM_API"
    TIMEZONE_SOURCE="auto"
    echo "✅ Time zone configured automatically. Current time: $(date)"
else
    echo "⚠️ Automatic detection failed. The time zone will default to UTC."
    sudo timedatectl set-timezone UTC
    echo "You can change it later with: sudo timedatectl set-timezone Your/City"
fi

echo "=== [5/12] Installing and configuring NGINX to avoid requiring :7090 ==="
# Install NGINX if it is not already installed.
if ! command -v nginx &> /dev/null; then
    echo "Installing NGINX..."
    sudo apt install -y nginx
else
    echo "✅ NGINX is already installed"
fi

# Remove the default configuration if it exists.
if [ -f /etc/nginx/sites-enabled/default ]; then
    sudo rm /etc/nginx/sites-enabled/default
    echo "⛔ Default configuration file removed"
fi

# Migrate names from older installations before configuring NGINX.
REAL_USER=${SUDO_USER:-$(logname)}
USER_HOME=$(getent passwd "$REAL_USER" | cut -d: -f6)
sudo python3 "$(dirname "$0")/utils/migrate_frame_names.py" --user-home "$USER_HOME" || exit 1

# Create a new configuration for PictureFrame.
sudo tee /etc/nginx/sites-available/pictureframe > /dev/null <<'EOL'
server {
    listen 80;
    server_name _;

    client_max_body_size 200M;

    location / {
        proxy_pass http://127.0.0.1:7090;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;

        # Increase timeouts for long-running operations such as video imports.
        proxy_connect_timeout 600s;
        proxy_send_timeout 600s;
        proxy_read_timeout 600s;
    }
}
EOL

# Enable the new configuration.
if [ ! -f /etc/nginx/sites-enabled/pictureframe ]; then
    sudo ln -s /etc/nginx/sites-available/pictureframe /etc/nginx/sites-enabled/
    echo "✅ PictureFrame configuration enabled in NGINX"
fi

# Restart NGINX.
sudo systemctl restart nginx
echo "✅ NGINX restarted and ready"

echo "=== [6/12] Creating the Python environment ==="
cd "$(dirname "$0")"
python3 -m venv venv
source venv/bin/activate

echo "Updating pip..."
pip install --default-timeout=1000 --retries=10 --upgrade pip

echo "Installing dependencies from requirements.txt..."
if ! pip install --default-timeout=1000 --retries=10 -r requirements.txt; then
    echo "❌ Failed to install the base Python dependencies!"
    exit 1
fi

echo "Installing the QR code library..."
if ! pip install --default-timeout=1000 --retries=10 "qrcode[pil]"; then
    echo "❌ Failed to install qrcode[pil]!"
    exit 1
fi

# Detect the Raspberry Pi model.
PI_MODEL=""
if [ -f /proc/device-tree/model ]; then
    MODEL_STR=$(cat /proc/device-tree/model)
    if [[ "$MODEL_STR" =~ "Raspberry Pi 4" ]]; then
        PI_MODEL="4"
    elif [[ "$MODEL_STR" =~ "Raspberry Pi 5" ]]; then
        PI_MODEL="5"
    elif [[ "$MODEL_STR" =~ "Raspberry Pi 3" ]]; then
        PI_MODEL="3"
    elif [[ "$MODEL_STR" =~ "Raspberry Pi 2" ]]; then
        PI_MODEL="2"
    elif [[ "$MODEL_STR" =~ "Zero" ]]; then
        PI_MODEL="1"
    else
        PI_MODEL="1"
    fi
fi

ARCH=$(uname -m)
if [[ "$ARCH" == "armv6l" || "$PI_MODEL" == "1" || "$PI_MODEL" == "2" ]]; then
    echo "⚠️ Raspberry Pi 1/2/Zero or armv6l architecture detected."
    echo "⚠️ Optional HEIC/HEIF support will not be installed."
else
    echo "Installing pillow-heif for HEIC photo support (iPhone)..."
    if ! pip install pillow-heif; then
        echo "⚠️ Warning: pillow-heif installation failed. HEIC/HEIF support will be disabled."
    else
        echo "✅ pillow-heif installed successfully."
    fi

fi

echo "=== [7/12] Creating the required directory structure ==="
mkdir -p logs
mkdir -p cache
mkdir -p static/photos
mkdir -p static/prepared
mkdir -p static/pending_uploads
mkdir -p config
echo "✅ Directory structure created."

# Fix permissions even when the script is run with sudo.
REAL_USER=$(logname)
sudo chown -R "$REAL_USER:$REAL_USER" static logs cache config
chmod -R u+rwX static logs cache config

echo "=== [8/12] Creating the secure credentials file ==="
CREDENTIALS_FILE="/boot/firmware/credentials.json"
VENV_PYTHON="venv/bin/python3"

if [ ! -f "$CREDENTIALS_FILE" ]; then
    echo "Generating a random password and creating the credentials file..."
    # Use sudo with the full path to the virtual environment's Python.
    # sudo's -E option preserves the environment, which may help.
    # The Python script displays the generated password.
    sudo -E "$VENV_PYTHON" utils/create_initial_user.py --output "$CREDENTIALS_FILE"
    
    echo "🔑 Configuring sudo permissions (security, reboot, shutdown)..."
    SUDOERS_CONF="/etc/sudoers.d/pictureframe-auth"
    # NOPASSWD permissions for critical operations (network, disks, system).
    COMMANDS="/usr/bin/tee $CREDENTIALS_FILE, /usr/sbin/reboot, /usr/sbin/shutdown, /usr/bin/nmcli, /usr/bin/raspi-config, /usr/bin/mount, /usr/bin/umount, /usr/bin/timedatectl"
    echo "$REAL_USER ALL=(ALL) NOPASSWD: $COMMANDS" | sudo tee "$SUDOERS_CONF" > /dev/null
    sudo chmod 440 "$SUDOERS_CONF"
else
    echo "✅ Credentials file $CREDENTIALS_FILE already exists. No changes made."
fi

echo "=== [9/12] Configuring console-mode startup (CLI) ==="
sudo raspi-config nonint do_boot_behaviour B2
echo "✅ System configured to start in console mode with auto-login."


echo "=== [10/12] Configuring Sway auto-start ==="
# Get the real user's home directory.
USER_HOME=$(getent passwd "$REAL_USER" | cut -d: -f6)
BASH_PROFILE="$USER_HOME/.bash_profile"
if ! grep -q 'exec sway' "$BASH_PROFILE"; then
    echo 'if [[ -z $DISPLAY ]] && [[ $(tty) = /dev/tty1 ]]; then' >> "$BASH_PROFILE"
    echo '  exec sway' >> "$BASH_PROFILE"
    echo 'fi' >> "$BASH_PROFILE"
    echo "Added Sway auto-start to $BASH_PROFILE"
else
    echo "✅ Sway is already configured to start automatically"
fi

echo "=== [11/12] Configuring PictureFrame auto-start in Sway ==="
SWAY_CONFIG_DIR="$USER_HOME/.config/sway"
SWAY_CONFIG_FILE="$SWAY_CONFIG_DIR/config"
mkdir -p "$SWAY_CONFIG_DIR"

# Absolute path to the startup script.
INSTALL_DIR=$(pwd)
START_SCRIPT="$INSTALL_DIR/start_pictureframe.sh"

# Make the script executable.
chmod +x "$START_SCRIPT"

# Add exec_always if it is missing.
sudo -u "$REAL_USER" python3 "$INSTALL_DIR/scripts/configure_auto_frame.py" --home "$USER_HOME" || exit 1

# Configure window rules so mpv videos appear in the foreground.
if ! grep -q 'app_id="mpv"' "$SWAY_CONFIG_FILE" 2>/dev/null; then
    echo 'for_window [app_id="mpv"] floating enable, border none, fullscreen enable' >> "$SWAY_CONFIG_FILE"
    echo 'for_window [class="python3"] floating enable, border none, fullscreen enable' >> "$SWAY_CONFIG_FILE"
fi

echo "=== [12/12] Installation complete ==="
echo "✅ Installation complete. Reboot to start Sway and PictureFrame automatically."
