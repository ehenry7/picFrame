# 🖼️ PictureFrame – Smart Connected Photo Frame

PictureFrame is a Python application designed to turn a Raspberry Pi into a smart and customizable digital photo frame. It can display photos from multiple sources and be controlled through its web interface.

PictureFrame is a fork of [Pimmich](https://github.com/gotenash/pimmich).
Legacy internal names (the startup script, status files, logs, NGINX site and
EXIF metadata prefix) are retained for existing-installation compatibility.

<img src="static/pictureframe_logo.svg" alt="PictureFrame Logo" width="300">

<p align="center">
  <a href="https://ko-fi.com/pimmich">
    <img src="https://img.shields.io/badge/Support%20on%20Ko--fi-F16061?logo=kofi&logoColor=white" alt="Support the original Pimmich project on Ko-fi">
  </a>
</p>

---

## 📖 Table of Contents

- ✨ Main Features
- 🧰 Technologies Used
- 🚀 Installation
- 🔧 Configuration
- ❓ Troubleshooting (FAQ)
- 🛣️ Roadmap
  - June 2025
  - July 2025
  - August 2025
- 💖 Credits

---

## ✨ Main Features

PictureFrame is packed with features to provide a complete and customizable experience:

#### 🖼️ **Display & Slideshow**
- **Multi-source:** Display photos from Immich, a USB drive, or a smartphone.
- **Manual Immich imports:** Use the Import from Immich button to refresh photos. No automatic background synchronization runs.
- **Advanced Customization:** Set display duration, active hours, transitions (fade, slide, or Random to choose an effect for each photo change), and enable a "Pan & Zoom" motion effect.
- **Active-hour schedules:** Weekend hours apply on Friday and Saturday; weekday hours apply Sunday through Thursday.
- **Creative Filters:** Apply filters to your photos (Black & White, Sepia, Vintage) and unique effects like **Polaroid** or **Postcard**.
- **Format Handling:** Smart support for portrait photos (blurred background) and videos (with sound and optional hardware acceleration).

#### ⚙️ **Interface & Control**
- **Comprehensive Web Interface:** A local configuration page, password-protected and organized into thematic groups and tabs for an intuitive navigation.
- **Content Management:**
    - **Playlists:** Create virtual albums, reorder photos with drag-and-drop, and launch themed slideshows with a dynamic title screen (photo jumble on a corkboard background).
    - **Favorites:** Mark your favorite photos to make them appear more often.
    - **Captions:** Add custom text to your photos and postcards.

#### 🌐 **Connectivity & Interactions**
- **Wi-Fi & Network:** Configure Wi-Fi, scan for networks, and manage network interfaces directly from the interface.
- **Smartphone Upload:** Import photos directly from your phone's browser.

#### 🛠️ **Maintenance & Monitoring**
- **Manual Updates:** Application code is updated manually outside the web interface; no remote self-update service is included.
- **Backup & Restore:** Back up and restore your entire configuration.
- **System Monitoring:** Track real-time temperature, CPU, RAM, and disk usage with history graphs.
- **Detailed Logs:** Access logs for each service (web server, slideshow) for easy troubleshooting.

---

## 🧰 Technologies Used

- **Backend:** Python, Flask
- **Frontend:** HTML, TailwindCSS, JavaScript
- **Slideshow:** Pygame
- **Image Processing:** Pillow
- **Web Server:** NGINX (as a reverse proxy)

---

## 🚀 Installation

There are two methods to install PictureFrame.

### Method 1: Pre-configured Image (Recommended and easier)

This method is ideal for a quick first-time installation.

1.  **Download the current month's image**
    Download the New Year version (v1.6.0) directly here: pimmich271225.img.xz or go to the PictureFrame Releases page.

2.  **Flash the image to an SD card**
    Use software like Raspberry Pi Imager or BalenaEtcher to write the image file you just downloaded to your microSD card.

3.  **Start your Raspberry Pi**
    Insert the SD card into the Raspberry Pi, connect the screen and power supply. PictureFrame will start automatically.

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

If a configured slideshow font is unavailable, PictureFrame logs one warning
and uses a cached system font at the requested size for the rest of the session.
Changing the configured font path tries the new font; restart to retry a repaired path.

### Switch between frame mode and the desktop

After running setup, use either command from the project directory:

```bash
bash enable_auto_frame_start.sh   # Frame mode: console auto-login + Sway
bash disable_auto_frame_start.sh  # Desktop mode: desktop auto-login
```

The scripts request sudo privileges and **reboot automatically** after successfully
changing the boot mode. Save your work before running either script.
Enabling requires the Sway auto-start configuration created by setup;
disabling requires Raspberry Pi OS Desktop, not Lite. Neither script removes
PictureFrame or changes its settings.

---

### 🔑 Get Your Immich API Token

1. Log into your Immich web interface  
2. Go to **Account Settings**

Click your profile icon (top-right), then choose **Account Settings**.

3. Generate a new API key  
In the **API Key** section, click **Generate new API Key** and give it a name (e.g., `PictureFrame`).

⚠️ Once the token is shown, **copy it immediately** — you won’t be able to see it again. If lost, you’ll need to generate a new one.

🔒 We recommend creating a dedicated Immich account for the photo frame, with access to a single shared album.

---

### Connect to PictureFrame

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
Pan and zoom now animate together throughout each photo's display time, from
the configured **Start zoom** to **End zoom**, rather than zooming before panning.
Start zoom can be as low as 0.01; below 1.00, the image is smaller and centered on
a black background. End zoom is at least 1.00 (the full fitted image);
1.15 means 15% enlargement.
The default is 1.00 → 1.15. Use a larger start than end value to zoom out, or equal
values to pan at a constant zoom. Transitions match the selected starting zoom.
Pan/zoom targets 60 FPS independently of the transition FPS setting. Its overlay
is refreshed once per second and reused between frames to reduce animation work.
Actual smoothness still depends on display resolution and available CPU.
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

Use **Crop photo** on a Preview or Favorites tile to select which part is displayed.
Drag the selection and adjust **Selection size**; its aspect ratio always matches
the configured slideshow width and height. Increase the size beyond the photo's
edges to include more of a portrait (up to the entire photo); extra space is filled
with a blurred background, while the original stays centered on the padded axis.
**Save crop** regenerates that photo's
prepared image, Polaroid and postcard versions, keeps saved filters/captions, and
reloads a running slideshow. **Reset crop** restores the uncropped preparation.
Originals are never modified and must remain in `static/photos/{source}`.
Selections are saved in `config/crop_states.json` and reused during future preparation.

The Preview and Favorites filter menus also offer **Auto Enhance**, **Vivid**,
**Warm**, **Cool**, **Dramatic B&W**, **Soft Glow**, **Sharpen**, **Duotone**
(navy shadows and warm highlights), and **Posterize**. Filters are applied on demand,
not per animation frame, and always start from the clean prepared backup.
Choose **Original** to remove a color effect; this keeps the saved crop.
Additional presets include **Matte** (lifted blacks), **Film Grain** (repeatable
fine texture), **Pencil Sketch** (monochrome outlines), **Selective Color**
(red, green or blue retained against grayscale), and **Tilt Shift** (a sharp
horizontal center band with progressively blurred top and bottom).
**Cinematic** adds teal shadows and warm highlights; **Cross Process** uses
retro channel curves; **Watercolor** smooths detail into painted color patches
with subtle outlines. **Vignette - Dark Edges** gently darkens the edges while
retaining center brightness and color. The separate **B&W Background** effect
(previously labeled Vignette) keeps the prepared foreground in color and makes
its surroundings grayscale. If the photo fills the frame or an older photo
lacks foreground bounds, it keeps a soft central oval in color instead.
These effects do not detect subjects.
These are stylized presets, not adjustable filter controls.
Click a Preview or Favorites photo to enlarge it. The enlarged view includes its
current filter, a filter selector, caption field, favorite star, crop and delete
actions on a single row (scroll horizontally on narrow screens). Crop opens
the existing editor after closing the enlarged view.
Small live previews and Preview/Favorites tiles also show a separate location
line with available city/country names and a country flag emoji. Missing data
is labeled **No location metadata**. This line is independent of the slideshow
overlay settings; flag appearance depends on the browser/system emoji font.

Touch or click the local slideshow to reveal Previous, Pause/Play and Next
buttons for five seconds. Tap a visible button to operate it and extend the
display time. The first tap reveals controls without changing the photo.
Keyboard shortcuts also work: Left = Previous, Right = Next, Space = Pause/Play.
They reveal or extend the controls. Navigation can interrupt a fade or photo
loading; it does not wait for the display duration or transition to finish.

The enlarged photo toolbar also provides:
- **Filter strength** (0–100%), saved per photo for color/effect filters.
  Original, Polaroid and Postcard do not use strength. Saved strength is reused
  when changing effects and when regenerating a crop.
- **Before/After** (half-circle icon): hold the button, Space or Enter to see
  the clean prepared photo with its saved crop; release to return to the edit.
- **Edit location** (map-pin icon): enter a city and choose a country. These
  app-only overrides are saved in `config/photo_edits.json`; originals are
  never modified. **Use original location** removes the manual override.

Photo grids and enlarged views use shared editing operations, with filter
requests queued per photo. Slideshow country flags are cached and fetched
outside rendering so unavailable network access does not block drawing.

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
