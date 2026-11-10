# AGENTS.md — Pimmich

## Project Goal

**Pimmich** is a Python application that turns a Raspberry Pi into a smart, connected digital photo frame. It displays photos from multiple sources (Immich, Samba shares, USB drives, smartphones), supports voice control, and provides a comprehensive web-based configuration interface.

**Development / Deployment target for this fork:**
- **Development environment:** Windows (local coding, testing, and debugging).
- **Production runtime:** Linux on a Raspberry Pi (models 4, with Raspberry Pi OS Desktop 64-bit).
- **Python environment:** Use the **global Python installation** — do **not** use a virtual environment (`venv`). Install all dependencies directly into the system/global Python. This applies to both Windows development and Raspberry Pi deployment.
- Code must remain cross-platform-aware: hardware-specific subsystems (GPIO, DPMS via wlr-randr/swaymsg, nmcli, raspi-config, /proc/device-tree, /boot/firmware) should be guarded and report unavailable when unsupported. Do not claim that a skipped operation succeeded.

---

## Architecture Overview

Pimmich is a multi-process application with three main runtime components, plus several background worker threads:

```
┌─────────────────────────────────────────────────────────┐
│  Sway (Wayland compositor) — auto-starts on boot        │
│  └─ start_pimmich.sh (supervisor loop, exit 42 restart) │
│     ├─ app.py            (Flask web server, port 7090)   │
│     │   ├─ Immich update worker (daemon thread)          │
│     │   ├─ Samba update worker (daemon thread)           │
│     │   └─ Slideshow scheduler worker (daemon thread)    │
│     ├─ local_slideshow.py  (Pygame fullscreen slideshow) │
│     └─ voice_control.py    (Porcupine + Vosk voice cmd)  │
│                                                           │
│  NGINX reverse proxy (:80 → :7090)                       │
└─────────────────────────────────────────────────────────┘
```

### Process Communication
- **Flask ↔ Slideshow:** via OS signals (`SIGUSR1` = next, `SIGUSR2` = previous, `SIGRTMIN` = pause toggle) and status files in `/tmp/` (`pimmich_slideshow_status.json`, `pimmich_current_photo.txt`, `pimmich_custom_playlist.json`).
- **Flask ↔ Voice Control:** via HTTP API calls to `http://127.0.0.1:7090/api/*` from `voice_control.py`.
- **PID files:** `/tmp/pimmich_slideshow.pid`, `/tmp/pimmich_voice_control.pid`, `/tmp/pimmich_app.lock`.

---

## Repository Structure

```
pimmich/
├── app.py                    # Flask web application (3,780 lines) — main entry point
├── local_slideshow.py        # Pygame-based fullscreen slideshow engine (2,330 lines)
├── voice_control.py          # Voice control via Porcupine (wake word) + Vosk (recognition) (578 lines)
├── platform_utils.py         # OS-aware paths, platform detection, and hardware helpers — THIS FORK
├── text_drawer.py            # Empty stub (text drawing moved to utils/text_drawer.py)
├── requirements.txt          # Cross-platform Python dependencies (Windows + Linux)
├── requirements-pi.txt       # Linux/Pi-only dependencies (THIS FORK)
├── babel.cfg                 # Babel i18n configuration
│
├── utils/                    # Utility modules (23 Python files)
│   ├── auth.py               # Flask login_required decorator
│   ├── auth_manager.py       # Password change (writes to /boot/firmware/credentials.json)
│   ├── archive_manager.py    # ZIP download/extract/clean helpers
│   ├── config.py             # Legacy config loader (superseded by config_manager.py)
│   ├── config_manager.py     # Primary config loader/saver with default schema + caching
│   ├── create_initial_user.py# Generates random password + credentials.json on first boot
│   ├── display_manager.py    # Display power control (DPMS via wlr-randr/swaymsg, smart plug)
│   ├── display_message.py    # Standalone script: shows a centered message on screen
│   ├── download_album.py     # Downloads photos from Immich API (album or random mode)
│   ├── exif.py               # EXIF rotation angle + photo date extraction
│   ├── image_filters.py      # Image filters (grayscale, sepia, vintage, polaroid, postcard)
│   ├── import_samba.py       # Samba/SMB photo synchronization
│   ├── import_usb_photos.py  # USB drive photo import (auto-mount/unmount)
│   ├── metadata_utils.py     # Photo metadata cache (date, location from Immich EXIF)
│   ├── network_manager.py    # Network interface status/control via nmcli
│   ├── playlist_manager.py   # Playlist JSON load/save
│   ├── prepare_all_photos.py # Image/video preparation pipeline (resize, blur bg, polaroid, postcard)
│   ├── slideshow_manager.py  # Slideshow process lifecycle (start/stop/restart via PID files)
│   ├── text_drawer.py        # Pygame text rendering with outline
│   ├── translate_po.py       # Auto-translate .po files via Google Translate
│   ├── voice_control_manager.py # Voice control process lifecycle (start/stop via PID files)
│   └── wifi_manager.py       # Wi-Fi configuration via nmcli + raspi-config
│
├── templates/                # Jinja2 HTML templates
│   ├── configure.html.jinja  # Main configuration page (5,476 lines — the big one)
│   ├── login.html.jinja      # Login page
│   ├── rebooting.html.jinja  # Reboot waiting screen
│   ├── slideshow.html.jinja  # Slideshow web view
│   ├── update.html.jinja     # Update progress page
│   └── upload.html.jinja     # Smartphone photo upload page
│
├── static/                   # Static assets
│   ├── styles.css            # Web interface styles
│   ├── backgrounds/          # Cork board background for playlist title screens
│   ├── flags/                # Country flag images + country_codes.json
│   ├── fonts/                # Caveat-Regular.ttf (handwriting font for polaroid/postcard)
│   ├── icons/                # UI icons (pause, envelope, thumbtack, postal)
│   ├── music/                # Background music MP3 files
│   ├── sounds/               # Voice command feedback sounds (WAV)
│   ├── stamps/               # Postcard stamp images
│   ├── weather_icons/        # OpenWeatherMap-style weather icons
│   └── *.png                 # Logos and background images
│
├── translations/             # Babel i18n translations
│   ├── messages.pot          # Translation template
│   └── {en,fr,he}/LC_MESSAGES/        # Compiled .mo + source .po per language
│
├── voice_models/             # Picovoice Porcupine wake word model (.ppn for Raspberry Pi)
│
├── config/                   # Runtime configuration (gitignored)
│   ├── config.json           # Main configuration file
│   ├── favorites.json        # Favorite photos list
│   ├── filter_states.json    # Per-photo filter state
│   ├── playlists.json        # User-created playlists
│   └── import_status.json    # Import progress tracking
│
├── setup.sh                  # Installation script (apt packages, venv, NGINX, Sway, sudoers)
├── start_pimmich.sh          # Supervisor script (launched by Sway, restarts app on crash)
├── update_script.sh          # Self-updating script (git pull + pip install, runs from /tmp)
├── README.md / README_en.md  # Project documentation (French + English)
├── FAQ.md / FAQ_en.md        # FAQ (French + English)
├── procedure_trad.md / .pdf  # Translation procedure guide
├── wakeword_pimmich.ipynb    # Jupyter notebook for training custom Porcupine wake word
├── LICENSE                   # License file
├── .gitignore                # Ignores config/, static/prepared/, static/photos/, cache/, venv/, logs/ (venv entry is legacy — this fork uses global Python)
└── .gitattributes            # Forces LF line endings on .sh files
```

---

## Key Components in Detail

### 1. `app.py` — Flask Web Application (Main Entry Point)

The central web server providing all configuration, photo management, and system control via a RESTful API and Jinja2 templates.

**Key subsystems:**
- **Logging:** Custom `EmojiFormatter` with emoji-per-level, rotating file handler (10MB, 3 backups) writing to `logs/pimmich.log`, plus console output.
- **Authentication:** Session-based login using `credentials.json` stored at `/boot/firmware/credentials.json` (on Pi). Passwords hashed with Werkzeug. `login_required` decorator protects all config routes.
- **i18n:** Flask-Babel with locale auto-detection. Supports en, fr, and he; Hebrew pages use right-to-left document direction.
- **Config management:** `load_config()` / `save_config()` via `utils/config_manager.py` with a 2-second cache and default-merge strategy.
- **Background workers (daemon threads):**
  - `immich_update_worker` — periodic Immich album sync (configurable interval).
  - `samba_update_worker` — periodic Samba share sync.
  - `schedule_worker` — manages active hours (starts/stops slideshow based on configured time window).

**Major route groups (70+ routes):**
| Group | Routes | Purpose |
|-------|--------|---------|
| Pages | `/`, `/login`, `/logout`, `/configure`, `/slideshow`, `/upload`, `/update`, `/rebooting` | Web UI pages |
| Import | `/import-usb`, `/import-immich`, `/import-samba`, `/import-smartphone`, `/prepare-photos` | Photo import pipelines (streaming responses) |
| Slideshow API | `/api/slideshow/next`, `/previous`, `/toggle_pause`, `/status`, `/restart_standard`, `/set_duration` | Slideshow control via signals |
| Display | `/api/display/power`, `/api/get_available_resolutions`, `/api/set_resolution` | Screen power + resolution |
| Sources | `/api/sources/play/<name>`, `/api/sources/toggle` | Display source management |
| Playlists | `/api/playlists` (CRUD), `/api/playlists/<id>/photos`, `/reorder`, `/rename`, `/update_music` | Playlist management |
| Photo ops | `/delete_photo/<path>`, `/api/apply_filter`, `/api/set_photo_filter`, `/api/toggle_favorite`, `/api/set_polaroid_text`, `/api/set_image_text` | Per-photo operations |
| System | `/shutdown`, `/reboot`, `/api/system/shutdown`, `/restart_app`, `/api/ping`, `/api/system_info`, `/api/cpu_temperature` | System control + monitoring |
| Network | `/save_wifi_settings`, `/api/wifi_status`, `/scan_wifi`, `/api/interface_status/<name>`, `/api/set_interface_state` | Network/Wi-Fi management |
| Voice | `/api/voice_control/status`, `/api/toggle_voice_control`, `/api/audio_devices`, `/api/audio_diagnostics` | Voice control management |
| Maintenance | `/api/backup_settings`, `/api/restore_settings`, `/api/list_logs`, `/api/clear_logs`, `/api/update_app`, `/api/expand_filesystem` | Backup, logs, updates |
| Tides/Weather | `/test-weather-api`, `/test-stormglass-api`, `/api/force_tide_update`, `/api/tide_info` | Weather + tide data |

### 2. `local_slideshow.py` — Pygame Slideshow Engine

A fullscreen Pygame application that displays photos with transitions, overlays, and special effects.

**Key features:**
- **Photo display:** Resizes photos to screen resolution, adds blurred background for portrait images.
- **Transitions:** Fade and slide transitions between photos (configurable duration/FPS).
- **Pan & Zoom:** Ken Burns-style motion effect on photos.
- **Overlays:** Clock, date, weather (OpenWeatherMap), tides (Stormglass), photo metadata (date, location, country flag).
- **Video playback:** Uses `mpv` as an external player for video files (with optional hardware acceleration).
- **Special effects:** Polaroid frames, postcard effects (with stamps and postmarks), creative filters.
- **Playlists:** Supports custom playlists with title slides (corkboard background with photo jumble), background music.
- **GPIO:** Fan control based on CPU temperature (pin 14, threshold 55°C) — Raspberry Pi only.
- **Signal handling:** `SIGUSR1` (next), `SIGUSR2` (previous), `SIGRTMIN` (pause toggle) from Flask.
- **Status reporting:** Writes current photo path and pause state to `/tmp/` files for Flask to read.
- **Active hours:** Checks config for active time window; sleeps (display off) outside active hours.

**Key functions:**
- `start_slideshow()` — main loop, builds playlist, displays photos, handles navigation.
- `display_photo_with_pan_zoom()` — renders a photo with optional pan/zoom motion.
- `draw_overlay()` — draws clock, date, weather, metadata, notification icons on screen.
- `perform_transition()` — handles fade/slide transitions between photos.
- `display_video()` — launches mpv for video playback.
- `display_title_slide()` — renders a playlist title screen with photo jumble on corkboard.
- `get_weather_and_forecast()` — fetches weather from OpenWeatherMap API.
- `get_tides()` — fetches tide data from Stormglass API.

### 3. `voice_control.py` — Voice Control

Offline voice control using Picovoice Porcupine (wake word detection) and Vosk (speech recognition).

- **Wake word:** "Cadre Magique" (French) / custom English wake word, using a `.ppn` model file.
- **Commands (fr + en):** next/previous photo, pause/play, shutdown, sleep/wake, show postcards, return to main slideshow, play playlist <name>, set duration <N> seconds, enable/disable source <name>.
- **Feedback sounds:** Plays WAV files from `static/sounds/` for each command.
- **API communication:** Sends HTTP POST/GET to `http://127.0.0.1:7090/api/*`.
- **Fuzzy matching:** Uses `thefuzz` + `python-Levenshtein` for playlist name matching.
- **Number parsing:** Uses `num2words` for spoken number → integer conversion.

### 4. `utils/` — Utility Modules

#### `config_manager.py`
- Single source of truth for default configuration (`create_default_config()`).
- `load_config()` — loads from `config/config.json`, merges with defaults, 2-second cache.
- `save_config()` — writes JSON with indent=4, UTF-8, updates cache.
- **~80 configuration keys** covering: display, Immich, Samba, clock, date, weather, tides, smart plug, Wi-Fi, timezone, voice control, photo metadata, video, audio, playlists, favorites, anniversary boost.

#### `prepare_all_photos.py`
- Photo/video preparation pipeline.
- `prepare_photo()` — resizes, handles EXIF rotation, creates blurred background for portraits, generates Polaroid + Postcard variants, stores content bbox in EXIF UserComment.
- `prepare_video()` — re-encodes with ffmpeg (hardware encoder detection: h264_v4l2m2m, h264_omx, or libx264), generates thumbnail.
- `prepare_all_photos_with_progress()` — generator function yielding progress dicts for streaming responses. Smart sync: only processes new/changed files, deletes obsolete ones.
- Pi model detection for performance optimization (BILINEAR on Pi 1/2/3, LANCZOS on Pi 4/5).

#### `download_album.py`
- Downloads photos from Immich server via REST API.
- Two modes: **album mode** (specific album by name) or **random mode** (random photos from library).
- Uses `/api/download/archive` endpoint for ZIP download.
- Caches EXIF metadata to `cache/immich_description_map.json`.
- Smart cleanup: removes local files no longer in the Immich album.
- Generator function yielding progress for streaming responses.

#### `image_filters.py`
- `apply_filter_to_image()` — applies filters: original, grayscale, sepia, vignette, vintage, polaroid_vintage.
- `create_polaroid_effect()` — adds Polaroid-style frame.
- `create_postcard_effect()` — creates tilted postcard with white border, shadow, stamp, postmark, and optional caption.
- `add_text_to_image()` / `add_text_to_polaroid()` — adds/updates user captions.
- Backup system: originals saved to `static/.backups/` before filter application.

#### `slideshow_manager.py`
- Process lifecycle management for `local_slideshow.py`.
- `start_slideshow()` — cleans zombies, checks PID file, launches subprocess.
- `stop_slideshow()` — terminates process, kills zombies, turns off display.
- `restart_slideshow_process()` — restarts for config changes (shows message on screen).
- `restart_slideshow_for_update()` — restarts after content update (no display power cycle).

#### `display_manager.py`
- `get_display_output_name()` — detects active HDMI output via `wlr-randr` or `swaymsg`.
- `set_display_power()` — turns screen on/off via smart plug (HTTP) or DPMS (wlr-randr/swaymsg).
- `set_software_display_power()` — DPMS control via Wayland compositor.
- Smart plug support: HTTP commands to configurable URLs, with reboot for HDMI stability on power-on.

#### Other utilities
- `import_samba.py` — SMB sync with mtime comparison, smart cleanup.
- `import_usb_photos.py` — USB detection via `lsblk`, auto-mount/unmount, recursive image scan.
- `network_manager.py` — interface status/control via `ip` and `nmcli`.
- `wifi_manager.py` — Wi-Fi config via `raspi-config` (country) + `nmcli` (connect).
- `auth_manager.py` — password change via `sudo tee` to `/boot/firmware/credentials.json`.
- `metadata_utils.py` — cached photo metadata lookup (date, city, country, GPS from Immich EXIF).
- `exif.py` — EXIF orientation + date extraction.
- `text_drawer.py` — Pygame text rendering with outline for readability.
- `translate_po.py` — auto-translate `.po` files using Google Translate (with placeholder protection).

---

## Configuration Schema

Configuration is stored in `config/config.json` (gitignored). The full default schema is defined in `utils/config_manager.py:create_default_config()`.

**Key configuration groups:**

| Group | Keys | Description |
|-------|------|-------------|
| Display | `display_duration`, `display_width`, `display_height`, `screen_height_percent`, `active_start`, `active_end` | Slideshow timing + screen |
| Transitions | `transition_enabled`, `transition_type`, `transition_duration`, `transition_fps` | Photo transition effects |
| Pan & Zoom | `pan_zoom_enabled`, `pan_zoom_factor` | Ken Burns effect |
| Immich | `immich_url`, `immich_token`, `album_name`, `immich_auto_update`, `immich_update_interval_hours` | Immich server connection |
| Samba | `smb_host`, `smb_share`, `smb_user`, `smb_password`, `smb_path`, `smb_auto_update` | SMB share connection |
| Video | `video_audio_enabled`, `video_audio_output`, `video_audio_volume`, `video_hwdec_enabled` | Video playback settings |
| Clock/Date | `show_clock`, `clock_format`, `clock_color`, `clock_position`, `show_date`, `date_format` | On-screen clock + date |
| Weather | `show_weather`, `weather_api_key`, `weather_city`, `weather_units` | OpenWeatherMap integration |
| Tides | `show_tides`, `tide_latitude`, `tide_longitude`, `stormglass_api_key` | Stormglass tide data |
| Photo metadata | `show_photo_date`, `show_photo_location`, `show_country_flag`, `photo_metadata_*` | On-screen photo info |
| Smart plug | `smart_plug_enabled`, `smart_plug_on_url`, `smart_plug_off_url`, `smart_plug_on_delay` | HTTP-controlled power plug |
| Voice control | `voice_control_enabled`, `voice_control_language`, `porcupine_access_key`, `notification_sound_volume` | Voice control settings |
| Sources | `display_sources` (list), `max_photos_to_download` (dict) | Active photo sources + limits |
| System | `timezone`, `level_log`, `favorite_boost_factor`, `anniversary_boost_enabled` | Misc system settings |

---

## Dependencies

Dependencies are split into two files for cross-platform development (see "Development Workflow" section for details).

### `requirements.txt` — Cross-platform core (Windows + Linux)
| Package | Purpose |
|---------|---------|
| Flask 2.3.2 | Web framework |
| requests 2.31.0 | HTTP client (Immich API, weather, etc.) |
| Pillow 10.4.0 | Image processing |
| pygame | Slideshow rendering + audio |
| psutil | Process management + system monitoring |
| werkzeug | WSGI utilities + password hashing |
| Flask-Babel | Internationalization |
| piexif | EXIF metadata read/write |
| qrcode[pil] | QR code generation |
| thefuzz | Fuzzy string matching (playlist names) |
| deep-translator | Auto-translation of .po files |
| polib | .po file parsing |

### `requirements-pi.txt` — Linux / Raspberry Pi only
| Package | Purpose |
|---------|---------|
| smbprotocol | Samba/SMB share access |
| python-Levenshtein | Levenshtein distance for thefuzz (C extension) |
| pillow-heif | HEIC/HEIF photo support (iPhone photos) |
| vosk | Offline speech recognition |
| sounddevice | Audio capture for voice control |
| pvporcupine | Wake word detection (Picovoice) |
| num2words | Number-to-word conversion (voice commands) |
| RPi.GPIO | GPIO hardware control (fan, button) |
| numpy | Numerical operations (voice control) |

### System packages (installed by `setup.sh`)
`sway`, `xterm`, `python3`, `python3-venv`, `python3-pip`, `libjpeg-dev`, `libopenjp2-7-dev`, `libtiff-dev`, `libopenblas-dev`, `ffmpeg`, `git`, `cifs-utils`, `smbclient`, `network-manager`, `jq`, `mpv`, `gettext`, `portaudio19-dev`, `unzip`, `libheif-dev`, `nginx`, `python3-rpi.gpio`

---

## Build, Test, and Lint

- **Windows:** Install cross-platform deps with `pip install -r requirements.txt` (global Python, no venv). Start Flask with `python app.py`.
- **Raspberry Pi:** Install both files: `pip install -r requirements.txt && pip install -r requirements-pi.txt` (add `--break-system-packages` on Debian 12+).
- No automated test suite or test/lint configuration is currently present.
- To update translations:
  - `pybabel extract -F babel.cfg -o translations/messages.pot .`
  - `pybabel update -i translations/messages.pot -d translations`
  - `pybabel compile -d translations`
- Deployment scripts (`setup.sh`, `start_pimmich.sh`, `update_script.sh`) still reference `venv` — these need updating to use global Python (remove venv creation/activation lines, install deps globally).

---

## Setup & Deployment

### First-time Installation (on Raspberry Pi)
```bash
git clone https://github.com/gotenash/pimmich.git
cd pimmich
chmod +x setup.sh
sudo ./setup.sh
```

> **Note (this fork):** The original `setup.sh` creates a Python virtual environment (`venv`). For this fork, **skip venv** and use the global Python instead. Modify `setup.sh` to remove the `python3 -m venv venv` and `source venv/bin/activate` steps, and install dependencies directly with `pip3 install -r requirements.txt` (or `pip install --break-system-packages -r requirements.txt` on newer Debian/Raspberry Pi OS that enforces PEP 668). Similarly, update `start_pimmich.sh` to remove the `source venv/bin/activate` line and run `python3 -u app.py` directly.

`setup.sh` performs 12 steps:
1. `apt update`
2. Install system dependencies (with fallback for portaudio package name)
3. Configure French locale
4. Disable Wi-Fi power saving + install RPi.GPIO
5. Auto-detect timezone via IP geolocation
6. Install + configure NGINX (reverse proxy :80 → :7090)
7. Create Python venv + install pip dependencies + voice models (Vosk FR/EN) — **this fork: install into global Python instead**
8. Create directory structure (logs, cache, static/photos, config, etc.)
9. Generate credentials.json with random password + configure sudoers NOPASSWD
10. Set boot to console mode with auto-login
11. Configure Sway auto-start in `.bash_profile`
12. Configure Pimmich auto-start in Sway config + mpv window rules

### Startup Flow
1. Pi boots → console auto-login → `.bash_profile` → `exec sway`
2. Sway starts → `exec_always start_pimmich.sh`
3. `start_pimmich.sh` → runs `python3 -u app.py` directly (no venv activation — **this fork uses global Python**)
4. `app.py` → starts Flask on :7090, launches background workers, optionally starts voice control in a background thread
5. Flask starts the slideshow process via `slideshow_manager.start_slideshow()`
6. NGINX proxies :80 → :7090 for clean URL access. Existing installations must update the installed NGINX upstream and reload NGINX.

### Updating
- Via web interface: "Update" button calls `update_script.sh`
- Script copies itself to `/tmp` (survives git reset), backs up config, does `git fetch --all && git reset --hard origin/main`, restores config, runs `pip install` (**global, not venv — this fork**), reloads Sway config.
- App exits with code 42 → `start_pimmich.sh` supervisor loop restarts it.

---

## Development Workflow (Windows, Linux, and Raspberry Pi)

Develop and debug the Flask application on Windows or Linux, then validate Raspberry Pi hardware integrations on the target device.

### 1. OS-Aware Hardware Abstraction (`platform_utils.py`)

`platform_utils.py` at the project root provides shared platform flags, temporary/status paths, font defaults, Pi detection, and Pygame display settings. Hardware helpers exist there, but not every legacy hardware call site has been migrated; unsupported device operations should report unavailable rather than pretend to succeed.

**Design:**
- `IS_LINUX`, `IS_WINDOWS`, `IS_RASPBERRY_PI` flags set at import time via `platform.system()`.
- Path helpers (`get_temp_dir()`, `get_pid_file()`, `get_status_file()`, `get_credentials_path()`, `get_default_font_path()`, `get_cancel_flag_path()`) provide OS-appropriate paths where wired in.
- Credentials use `/boot/firmware/credentials.json` on Raspberry Pi and a project-root `credentials.json` on Windows and other Linux systems.
- Pygame helpers (`get_pygame_display_flags()`, `get_pygame_display_size()`) return fullscreen flags on Pi, windowed 1280×720 on Windows.

**Available functions:**
| Function | Purpose | Windows behavior |
|----------|---------|-------------------|
| `set_display_power(on, config)` | HDMI power on/off | Unavailable |
| `get_display_output_name()` | Detect active display | Returns None |
| `set_display_resolution(w, h)` | Set screen resolution | Unavailable |
| `get_available_resolutions()` | List screen modes | No hardware modes |
| `system_reboot()` / `system_shutdown()` | Power control | Not run |
| `get_cpu_temperature()` | CPU temp (°C) | Returns None |
| `get_pi_model()` | Detect Pi model | Returns None |
| `get_interface_status(name)` | Network interface | Unavailable status |
| `set_interface_state(name, state)` | Enable/disable interface | Unavailable |
| `get_wifi_status()` / `set_wifi_config(...)` | Wi-Fi management | Unavailable |
| `scan_wifi_networks()` | Wi-Fi scan | Empty list |
| `set_timezone(tz)` | System timezone | Not run |
| `find_and_mount_usb()` / `unmount_usb(path)` | USB mount/unmount | Not available |
| `get_sway_socket()` / `reload_sway_config()` | Sway IPC | Returns None |
| `get_ffmpeg_encoders()` / `has_ffmpeg()` | ffmpeg detection | Empty/false |
| `get_system_info()` | System dashboard data | Works (via psutil) |
| `get_pygame_display_flags()` | Pygame flags | Windowed (0) |
| `get_pygame_display_size()` | Pygame size | (1280, 720) |
| `get_temp_dir()` | Temp directory | OS temp dir |
| `get_pid_file(name)` / `get_status_file(name)` | PID/status paths | OS temp dir |
| `get_credentials_path()` | Credentials file | Project root |
| `get_default_font_path()` | Default font | `arialbd.ttf` |
| `get_cancel_flag_path()` | Cancel flag | OS temp dir |

**Refactoring guideline:** When touching any file that calls `subprocess.run(["sudo", ...])`, `wlr-randr`, `swaymsg`, `nmcli`, `raspi-config`, `vcgencmd`, reads `/proc/`, `/sys/`, `/boot/`, or hardcodes `/tmp/` paths, replace it with the corresponding `platform_utils` function. Files that need refactoring:

- `app.py` — ~20 subprocess calls (reboot, shutdown, swaymsg, vcgencmd, nmcli, timedatectl, cancel flag paths, PID/status file paths)
- `local_slideshow.py` — `/proc/device-tree/model`, `/tmp/` paths, `/usr/share/fonts/` defaults, GPIO, mpv log path
- `utils/display_manager.py` — wlr-randr, swaymsg, sudo reboot
- `utils/network_manager.py` — `ip addr`, `nmcli`
- `utils/wifi_manager.py` — `nmcli`, `raspi-config`
- `utils/import_usb_photos.py` — `lsblk`, `mount`, `umount`
- `utils/auth_manager.py` — `/boot/firmware/credentials.json`
- `utils/slideshow_manager.py` — PID file path, `os.getuid()`, sway socket
- `utils/prepare_all_photos.py` — `/proc/device-tree/model`, cancel flag path
- `utils/config_manager.py` — font path defaults
- `utils/display_message.py` — sway socket, `os.getuid()`
- `voice_control.py` — `/tmp/` debug wav path

### 2. Path Management with `pathlib`

- **Never hardcode** `/tmp/`, `/home/pi/`, `/boot/firmware/`, or `/usr/share/fonts/` in new code.
- Use `platform_utils.get_temp_dir()`, `get_pid_file()`, `get_status_file()`, `get_credentials_path()`, `get_default_font_path()`, or `Path(__file__).resolve().parent` for project-relative paths.
- Existing hardcoded paths in `config_manager.py` defaults (font paths) should use `platform_utils.get_default_font_path()` at runtime.
- Consider a `.env` file (gitignored) for environment-specific overrides (Immich URL/token, Samba creds, port). Use `python-dotenv` if environment variable loading is needed.

### 3. Dependency Management (Dual Requirements Files)

Dependencies are split into two files:

**`requirements.txt`** — Cross-platform core (installs on Windows + Linux):
- Flask, requests, Pillow, pygame, psutil, werkzeug, Flask-Babel, piexif, qrcode, thefuzz, deep-translator, polib, smbprotocol

**`requirements-pi.txt`** — Linux/Pi only (do NOT install on Windows):
- numpy, python-Levenshtein, pillow-heif, vosk, sounddevice, pvporcupine, num2words, RPi.GPIO

**Install on Windows (global Python, no venv):**
```bash
pip install -r requirements.txt
```

**Install on Raspberry Pi (global Python, no venv):**
```bash
pip install -r requirements.txt
pip install -r requirements-pi.txt
# On Debian 12+ / Pi OS with PEP 668, add --break-system-packages
```

### 4. Dual-Mode Dev Loop

**Windows (local development):**
- Develop and debug Flask routes, Pillow image processing, EXIF handling, Immich API calls, template rendering, playlist logic.
- Run Flask: `python -u app.py` (starts on port 7090). Open `http://127.0.0.1:7090` and look for the `HTTP server READY` log.
- Pygame runs in **windowed mode** (1280×720) via `platform_utils.get_pygame_display_flags()` — not fullscreen.
- Pi-specific hardware operations are unavailable; they must not be reported as successful. Voice/GPIO features require their platform dependencies and hardware.
- The web UI is fully functional for configuration, playlist management, photo metadata, and system monitoring (except real hardware actions).

**Raspberry Pi 4 (hardware testing via SSH):**
- Commit and push from Windows → pull on Pi (or use VS Code Remote-SSH directly).
- On Pi: `git pull && python3 -u app.py` (or restart via `start_pimmich.sh`).
- Test real hardware: HDMI standby, touchscreen/GPIO button, voice control, USB import, Wi-Fi management, CPU temperature, fan control, video playback with hardware acceleration.
- Pygame runs in `FULLSCREEN | NOFRAME` kiosk mode.

### 5. What Works on Windows vs. Pi

| Feature | Windows | Raspberry Pi |
|---------|---------|--------------|
| Flask web server | ✅ Full | ✅ Full |
| Web UI configuration | ✅ Full | ✅ Full |
| Immich API download | ✅ Full | ✅ Full |
| Image processing (Pillow) | ✅ Full | ✅ Full |
| Playlists management | ✅ Full | ✅ Full |
| Pygame slideshow | ⚠️ Windowed 1280×720 | ✅ Fullscreen kiosk |
| Display power (DPMS) | ❌ Unavailable | ✅ wlr-randr/swaymsg |
| System reboot/shutdown | ❌ Unavailable | ✅ sudo |
| CPU temperature | ❌ None | ✅ /sys/class/thermal |
| GPIO (fan, button) | ❌ None | ✅ RPi.GPIO |
| Voice control | ❌ None | ✅ Porcupine + Vosk |
| USB import | ❌ Unavailable | ✅ lsblk + mount |
| Wi-Fi management | ❌ Unavailable | ✅ nmcli + raspi-config |
| Samba import | ✅ Available with SMB access | ✅ smbprotocol |
| HEIC/HEIF photos | ❌ No pillow-heif | ✅ pillow-heif |
| Video playback | ⚠️ ffmpeg if installed | ✅ mpv + hwdec |
| NGINX reverse proxy | ❌ Not needed | ✅ :80 → :7090 |

### 6. Cross-Platform Considerations
- Shell scripts (`.sh`) use LF line endings (enforced by `.gitattributes`).
- The codebase uses French comments throughout — this is the original author's language.
- `smbprotocol` is in the cross-platform requirements because Samba modules are imported by the Flask application at startup. Voice dependencies, including `numpy`, remain Pi-specific.

---

## Internationalization (i18n)

- **Framework:** Flask-Babel with Jinja2 `ext.i18n` extension.
- **Configuration:** `babel.cfg` maps `**.py` and `**/templates/**.html.jinja`.
- **Supported languages:** English (en), French (fr), and Hebrew (he). Hebrew templates set right-to-left document direction.
- **Translation files:** `translations/{lang}/LC_MESSAGES/messages.po` (source) + `.mo` (compiled).
- **Auto-translation:** `utils/translate_po.py` can auto-translate untranslated entries using Google Translate.
- **Extraction:** `pybabel extract -F babel.cfg -o translations/messages.pot .`
- **Compilation:** `pybabel compile -d translations`

---

## Logging

- Startup stages, named workers, HTTP request start/end timings, and uncaught exceptions are recorded in `logs/pimmich.log` and the console.
- A localhost HTTP probe logs `HTTP server READY` once port 7090 responds. If startup stalls for 30 seconds, `logs/startup_threads.log` captures all Python thread stacks.
- **Log file:** `logs/pimmich.log` (rotating, 10MB max, 3 backups, UTF-8).
- **Format:** Emoji-prefixed lines with module color codes:
  - 🟨 = app.py
  - 🟦 = local_slideshow.py
  - 🟪 = slideshow_manager.py
  - 🟩 = display_manager.py
  - 🔄 = prepare_all_photos.py
  - 📥 = download_album.py
- **Level:** Configurable via `level_log` in config.json (default: "INFO").
- **Werkzeug logs:** Cleaned and reformatted by `CleanWerkzeugFormatter`.
- **Voice control logs:** Separate files: `logs/voice_control_stdout.log`, `logs/voice_control_stderr.log`.

---

## Photo Pipeline

```
Source (Immich/Samba/USB/Smartphone)
  → static/photos/{source}/          (raw downloaded photos)
  → prepare_all_photos.py            (resize, EXIF rotate, blur bg, polaroid, postcard)
  → static/prepared/{source}/        (display-ready images)
      ├── photo.jpg                  (main prepared image)
      ├── photo_polaroid.jpg         (Polaroid variant)
      ├── photo_postcard.jpg         (Postcard variant)
      └── video_thumbnail.jpg        (Video thumbnail)
  → static/.backups/{source}/        (originals for filter reset)
  → local_slideshow.py               (displays from static/prepared/)
```

### Smart Sync Logic
- `prepare_all_photos_with_progress()` only processes new/changed files.
- Compares source basenames against prepared basenames.
- Deletes obsolete prepared files (and their polaroid/postcard/backups).
- Skips smartphone source for deletion (user uploads are preserved).
- Cancellation support via `/tmp/pimmich_cancel_import.flag`.

---

## Key Patterns & Conventions

1. **Generator-based streaming:** Import/prepare/download functions are Python generators that yield progress dicts. Flask routes use `stream_with_context` to stream these as Server-Sent Events for real-time progress bars.

2. **PID file management:** Each long-running process (slideshow, voice control, app) uses a PID file in `/tmp/` for lifecycle management. Zombie processes are cleaned up before starting new instances.

3. **Config merge strategy:** User config is merged with defaults on load, ensuring new keys are added without losing existing settings. 2-second cache prevents excessive file reads.

4. **EXIF as metadata channel:** Content bounding boxes are stored in EXIF UserComment (`pimmich_bbox:x,y,w,h`) for Polaroid text placement. Immich EXIF metadata is cached to `cache/immich_description_map.json`.

5. **Process isolation:** Flask, slideshow, and voice control run as separate OS processes, communicating via signals, HTTP, and status files — not shared memory.

6. **Graceful degradation:** Voice control is skipped on Pi 1/2/Zero. HEIC support is optional (pillow-heif). Hardware video encoders are auto-detected. Smart plug is optional. All features degrade gracefully when unavailable.

---

## Git Information

- **Repository:** https://github.com/gotenash/pimmich.git
- **Default branch:** `main`
- **License:** See `LICENSE` file
- **Language:** Code comments are primarily in French; documentation is bilingual (French + English).
