# 🖼️ Pimmich – Smart Connected Photo Frame

Pimmich is a Python application designed to turn a Raspberry Pi into a smart and customizable digital photo frame. It can display photos from multiple sources, be controlled by voice, and much more.

<img src="static/pimmich_logo.png" alt="Pimmich Logo" width="300">

<p align="center">
  <a href="https://ko-fi.com/pimmich">
    <img src="https://img.shields.io/badge/Support%20on%20Ko--fi-F16061?logo=kofi&logoColor=white" alt="Support Pimmich on Ko-fi">
  </a>
</p>

---

## 📖 Table of Contents

- ✨ Main Features
- 🧰 Technologies Used
- 🚀 Installation
- 🔧 Configuration
- 🗣️ Voice Control
- ❓ Troubleshooting (FAQ)
- 🛣️ Roadmap
  - June 2025
  - July 2025
  - August 2025
- 💖 Credits

---

## ✨ Main Features

Pimmich is packed with features to provide a complete and customizable experience:

#### 🖼️ **Display & Slideshow**
- **Multi-source:** Display photos from Immich, a network share (Samba/Windows), a USB drive, a smartphone, or via Telegram.
- **Advanced Customization:** Set display duration, active hours, transitions (fade, slide, or Random to choose an effect for each photo change), and enable a "Pan & Zoom" motion effect.
- **Creative Filters:** Apply filters to your photos (Black & White, Sepia, Vintage) and unique effects like **Polaroid** or **Postcard**.
- **Format Handling:** Smart support for portrait photos (blurred background) and videos (with sound and optional hardware acceleration).

#### ⚙️ **Interface & Control**
- **Comprehensive Web Interface:** A local configuration page, password-protected and organized into thematic groups and tabs for an intuitive navigation.
- **Voice Control:** Control your frame with voice commands like *"Magic Frame, next photo"* or *"Magic Frame, play Vacation playlist"*.
- **Content Management:**
    - **Playlists:** Create virtual albums, reorder photos with drag-and-drop, and launch themed slideshows with a dynamic title screen (photo jumble on a corkboard background).
    - **Favorites:** Mark your favorite photos to make them appear more often.
    - **Captions:** Add custom text to your photos and postcards.

#### 🌐 **Connectivity & Interactions**
- **Telegram:** Allow friends and family to send photos to the frame via a Telegram bot, with a secure and temporary invitation system.
- **Wi-Fi & Network:** Configure Wi-Fi, scan for networks, and manage network interfaces directly from the interface.
- **Smartphone Upload:** Import photos directly from your phone's browser.

#### 🛠️ **Maintenance & Monitoring**
- **Easy Updates:** Update Pimmich with a single click from the interface.
- **Backup & Restore:** Back up and restore your entire configuration.
- **System Monitoring:** Track real-time temperature, CPU, RAM, and disk usage with history graphs.
- **Detailed Logs:** Access logs for each service (web server, slideshow, voice control) for easy troubleshooting.

---

## 🧰 Technologies Used

- **Backend:** Python, Flask
- **Frontend:** HTML, TailwindCSS, JavaScript
- **Slideshow:** Pygame
- **Image Processing:** Pillow
- **Voice Control:** Picovoice Porcupine (wake word) & Vosk (recognition)
- **Web Server:** NGINX (as a reverse proxy)

---

## 🚀 Installation

There are two methods to install Pimmich.

### Method 1: Pre-configured Image (Recommended and easier)

This method is ideal for a quick first-time installation.

1.  **Download the current month's image**
    Download the New Year version (v1.6.0) directly here: pimmich271225.img.xz or go to the Pimmich Releases page.

2.  **Flash the image to an SD card**
    Use software like Raspberry Pi Imager or BalenaEtcher to write the image file you just downloaded to your microSD card.

3.  **Start your Raspberry Pi**
    Insert the SD card into the Raspberry Pi, connect the screen and power supply. Pimmich will start automatically.

### Method 2: Manual Installation from Git Repository

This method is for advanced users or those who want to follow development closely.

#### ✅ Prerequisites

- A Raspberry Pi (model 3B+, 4, or 5 recommended) with Raspberry Pi OS Desktop (64-bit).
- An SD card, a power supply, a screen.
- An Internet connection.

#### 📝 Installation Steps

1.  **Clone the repository**
    Open a terminal on your Raspberry Pi and run:
    ```bash
    git clone https://github.com/gotenash/pimmich.git
    cd pimmich
    ```

2.  **Run the installation script**
    This script installs all dependencies, configures the environment, and prepares for automatic startup.
```bash
chmod +x setup.sh
sudo ./setup.sh
```

This script installs system and Python dependencies, sets up the environment, and configures auto-start of the slideshow.

---

### 🔑 Get Your Immich API Token

1. Log into your Immich web interface  
2. Go to **Account Settings**

Click your profile icon (top-right), then choose **Account Settings**.

3. Generate a new API key  
In the **API Key** section, click **Generate new API Key** and give it a name (e.g., `PimmichFrame`).

⚠️ Once the token is shown, **copy it immediately** — you won’t be able to see it again. If lost, you’ll need to generate a new one.

🔒 We recommend creating a dedicated Immich account for the photo frame, with access to a single shared album.

---

### Connect to Pimmich

From a web browser on another device, access:

```
http://<your-raspberry-ip>:7090
```

For local development, run `python -u app.py` from the project directory and open
`http://127.0.0.1:7090`. Look for `HTTP server READY` in the console.

Startup stages, worker failures, and HTTP request timings are recorded in
`logs/pimmich.log`. If startup takes more than 30 seconds, thread stack traces
are written to `logs/startup_threads.log`. A request with `HTTP started` but no
matching `HTTP finished` identifies an unfinished handler.

Existing Raspberry Pi installations using NGINX must change their
`proxy_pass` upstream from port 5000 to 7090 and reload NGINX; updating the
repository alone does not update the installed NGINX configuration.

### Set or reset the admin password

From the project directory on Raspberry Pi, run:

```bash
sudo python3 reset_admin_password.py
```

On Windows, run `python reset_admin_password.py` instead.
Enter your chosen password twice at the hidden prompts, then log in as `admin`.
No output-file argument or app restart is needed. The script uses the platform's
credentials location, stores a password hash, and preserves other credential
settings. It can also create the credentials file if it is missing.

---

### Add photos from a folder without the web interface

Stop the app before importing. From the project directory on Raspberry Pi:

```bash
# Prepare and enable photos already copied into static/photos/smartphone:
./venv/bin/python add_photos.py

# Or copy photos from another folder, prepare them, and enable their source:
./venv/bin/python add_photos.py "/home/pi/Pictures"
```

Use `python3` instead of `./venv/bin/python` for a global Python installation,
or `python` on Windows. Relative input paths are relative to your terminal's
current directory. JPG, JPEG, PNG, HEIC, and HEIF files directly inside the
folder are imported; subfolders and videos are not. HEIC/HEIF requires
`pillow-heif`. Originals are kept, existing files are not overwritten, and
conflicting filenames receive a numeric suffix. Photos with identical file contents
are skipped, even under a different filename, so repeating an import does not add
duplicate copies. Already prepared photos are also skipped by the preparation pipeline.
Restart the app/slideshow after successful preparation. Do not use `sudo` unless
your photo/configuration directories actually require it.

## ⚙️ Configuration Interface

### Slideshow Settings

Here, you can set the display time per photo (minimum ~10s, due to background blur processing for portrait images) and define active hours for the slideshow.

Photos are fitted and centered using the same framing during transitions and
static display, including when prepared photos are larger than the Windows slideshow window.
With Pan & Zoom enabled, transitions end at the animation's starting crop, so
motion begins without a sudden change in framing.
Photo metadata uses Immich's cached details for Immich photos and the original
file's EXIF capture date / IPTC city and country for locally imported photos.
Keep originals under `static/photos/{source}`. Missing dates or location names
cannot be displayed; GPS coordinates alone are not converted into city names.
Both live previews show the metadata text selected for display, or **No Metadata**
if none is available under the saved settings. Hover over the single-line caption
to read its full text when it is truncated.
The Preview and Favorites photo tiles also show this caption below each image,
next to its filter and caption controls. Both date-format fields include an
expandable reference with codes and examples (such as `%d/%m/%Y` for 15/06/2020).

### Photo Import Settings

Choose between importing from an Immich album or a USB stick, and manage downloaded files.

In the Actions tab under photo importing, **Import photos** selects multiple
files and **Import folder** selects a folder on the device running your browser
(including its subfolders). Photos are added to the Smartphone source, prepared,
and enabled automatically. Identical file contents are skipped, including renamed
duplicates; different photos with matching names are preserved with numeric suffixes.
Each selection is limited to 32 MB including upload overhead; use smaller selections
or the command-line importer for large folders. Folder selection requires a browser
that supports directory uploads.
