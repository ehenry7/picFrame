# AGENTS.md — PictureFrame

## Project Goal

**PictureFrame** is a Python application that turns a Raspberry Pi into a smart, connected digital photo frame. It displays photos imported from USB drives and smartphone/computer browsers and provides a comprehensive web-based configuration interface.

**Development / Deployment target for this fork:**
- **Development environment:** Windows (local coding, testing, and debugging).
- **Production runtime:** Linux on a Raspberry Pi (models 4, with Raspberry Pi OS Desktop 64-bit).
- **Python environment:** Use the **global Python installation** — do **not** use a virtual environment (`venv`). Install all dependencies directly into the system/global Python. This applies to both Windows development and Raspberry Pi deployment.
- Code must remain cross-platform-aware: hardware-specific subsystems (GPIO, DPMS via wlr-randr/swaymsg, nmcli, raspi-config, /proc/device-tree, /boot/firmware) should be guarded and report unavailable when unsupported. Do not claim that a skipped operation succeeded.

---

## Architecture Overview

PictureFrame runs in one of two top-level modes (config key `app_mode`, see
[Run modes](#run-modes) below):

```
┌─────────────────────────────────────────────────────────┐
│  Sway (Wayland compositor) — auto-starts on boot        │
│  └─ start_pictureframe.sh (supervisor loop, exit 42 restart) │
│     ├─ app.py            (Flask web server, port 7090)   │
│     │   └─ Slideshow scheduler worker (daemon thread)    │
│     ├─ local_slideshow.py  (Pygame fullscreen slideshow) │
│     └─ background_updater.py (desktop wallpaper updater) │
│                                                           │
│  NGINX reverse proxy (:80 → :7090)                       │
└─────────────────────────────────────────────────────────┘
```

### Run Modes

| Mode | Process | Output |
|---|---|---|
| `picture_frame` (default) | `local_slideshow.py` | Fullscreen Pygame kiosk slideshow (Pi target) |
| `background_updater` | `background_updater.py` | Composes photo + overlays into per-monitor wallpaper images and sets them via OS wallpaper APIs (Windows/Linux desktops) |

- Mode resolution: `utils/app_mode.py::get_app_mode()` — `PICTUREFRAME_APP_MODE`
  env var overrides config; invalid values fall back to `picture_frame`.
- Process lifecycle: `utils/slideshow_manager.py` exposes mode-aware functions
  (`start_display_process`, `stop_display_process`, `is_display_process_running`,
  `restart_display_process`, `restart_display_process_for_update`,
  `switch_app_mode`) plus the legacy slideshow-specific API.
- The background updater reuses the slideshow's rendering through
  `utils/render_pipeline.py` (`compose_background`, `save_surface_atomic`,
  `build_media_playlist`, `fit_photo_to_style`, `warm_up_overlays`). It never calls
  `pygame.display.set_mode()` — only fonts and off-screen Surfaces, so it works headless.
  `SDL_VIDEODRIVER=dummy` is set defensively before pygame imports.
- **Weather icon in headless mode:** `load_icon()` in `local_slideshow.py` guards
  `.convert_alpha()` with `pygame.display.get_surface() is not None` — in background
  mode (no display surface), the raw surface is used directly, which still blits
  correctly onto the off-screen composition surface.
- **Wallpaper placement styles:** `fit_photo_to_style()` in `render_pipeline.py`
  supports six placement modes selected by the `background_display_style` config key:
  `fill` (cover + center-crop), `fit` (letterbox, default), `stretch` (distort),
  `span` (fill, sized for all screens), `center` (1:1, black canvas), `tile` (repeat).
- **Per-monitor rendering (Windows):** the updater renders a **separate wallpaper
  image per monitor** at each monitor's native resolution and DPI scaling. Each
  image gets its own `bottom_inset` (taskbar height for that monitor) so overlays
  sit exactly above the taskbar on every screen. Uses the `IDesktopWallpaper` COM
  API via `comtypes` to set per-monitor wallpapers with `SetPosition(2)` (Stretch,
  1:1 pixel mapping at native resolution). Falls back to legacy
  `SystemParametersInfoW` when COM is unavailable.
  - `get_monitor_details(config)` returns per-monitor `{id, width, height, taskbar_inset}`.
  - `_monitor_taskbar_inset()` matches COM monitor rects against `EnumDisplayMonitors`
    work areas for DPI-aware per-monitor taskbar height.
  - `set_wallpaper_per_monitor([(id, path), ...])` applies each image to its monitor.
- **Per-monitor alternating output paths:** `wallpaper_output_path()` uses
  per-monitor filenames (e.g. `desktop_background_mon0.png` / `desktop_background_mon0_alt.png`)
  so each monitor has a stable pair of alternating paths across repaints. Windows
  caches wallpaper by file path — alternating prevents stale images.
- **Content-change clock detection:** instead of a fixed timer, the updater polls
  every 1 second and only re-renders when the overlay text actually changes (clock
  minute, weather update, tide update) or the photo rotation deadline is reached.
  `_overlay_snapshot()` returns a lightweight string of current overlay state for
  comparison. This means the clock updates within ~1 second of the minute change.
- **Overlay warm-up:** `warm_up_overlays()` blocks briefly (≤8 s) on first boot so
  weather/tide data is ready before the first wallpaper is composed.
- **Schedule skip in background mode:** the `schedule_worker` in `app.py` skips
  active-hours gating when `app_mode == "background_updater"` — the desktop wallpaper
  should update regardless of time of day. Pi-specific wake code (DPMS, resolution
  forcing via `swaymsg`) is also guarded to `picture_frame` mode only. At boot, the
  display process starts immediately in background mode regardless of active hours.
- **Overlay positioning:** `draw_overlay()` in `local_slideshow.py` accepts a
  `bottom_inset` parameter applied to all bottom-anchored elements: weather
  (bottom-right), tides (bottom-center), photo metadata/shooting date (bottom_left,
  bottom_right, bottom_center, fallback), and country flag (bottom_left, bottom_right).
- Wallpaper backends live in `utils/wallpaper_manager.py`:
  Windows `IDesktopWallpaper` COM (per-monitor, via `comtypes`) with
  `SystemParametersInfoW` fallback, GNOME/MATE/Cinnamon `gsettings`, KDE
  `plasma-apply-wallpaper`, XFCE `xfconf-query` (all monitor properties), `feh`
  fallback. Unsupported environments log and return `False`.
- The web UI switches modes via `POST /api/app_mode` (stops the active process,
  persists the mode, starts the new one; display power is never touched).

### Process Communication
- **Flask ↔ Slideshow/Background:** via OS signals (`SIGUSR1` = next, `SIGUSR2` = previous, `SIGTSTP` = pause toggle) and status files in the OS temp dir (`pictureframe_slideshow_status.json`, `pictureframe_current_photo.txt`, `pictureframe_custom_playlist.json`). On Windows (no POSIX signals), commands are enqueued to a per-process command directory (`pictureframe_slideshow_commands/` or `pictureframe_background_commands/`) via `platform_utils.enqueue_slideshow_command(process=…)`.
- **Mode-aware dispatch in app.py:** `_display_pid_file()`, `_display_status_file()`, and `_send_slideshow_command()` resolve the correct PID/status file and command queue based on `get_app_mode()`, so the existing `/api/slideshow/*` routes work unchanged in both modes.
- **PID files:** `pictureframe_slideshow.pid`, `pictureframe_background.pid`, `pictureframe_app.lock` (all in the OS temp dir).

---

## Repository Structure

```
picFrame/
├── app.py                    # Flask web application (3,780 lines) — main entry point
├── local_slideshow.py        # Pygame-based fullscreen slideshow engine (2,330 lines)
├── background_updater.py     # Desktop wallpaper updater process (background_updater mode)
├── platform_utils.py         # OS-aware paths, platform detection, and hardware helpers — THIS FORK
├── stop.py                   # CLI process stopper: gracefully kills app + slideshow + background updater
├── scripts/                 # Maintenance CLI tools, boot-mode toggles and temporary check_* helpers
├── text_drawer.py            # Empty stub (text drawing moved to utils/text_drawer.py)
├── requirements.txt          # Cross-platform Python dependencies (Windows + Linux)
├── requirements-pi.txt       # Linux/Pi-only dependencies (THIS FORK)
├── babel.cfg                 # Babel i18n configuration
│
├── utils/                    # Utility modules (23 Python files)
│   ├── app_mode.py           # Run-mode resolution (picture_frame | background_updater)
│   ├── auth.py               # Flask login_required decorator
│   ├── auth_manager.py       # Password change (writes to /boot/firmware/credentials.json)
│   ├── config.py             # Legacy config loader (superseded by config_manager.py)
│   ├── config_manager.py     # Primary config loader/saver with default schema + caching
│   ├── create_initial_user.py# Generates random password + credentials.json on first boot
│   ├── display_manager.py    # Display power control (DPMS via wlr-randr/swaymsg, smart plug)
│   ├── display_message.py    # Standalone script: shows a centered message on screen
│   ├── exif.py               # EXIF rotation angle + photo date extraction
│   ├── image_filters.py      # Image filters (grayscale, sepia, vintage, polaroid, postcard)
│   ├── import_usb_photos.py  # USB drive photo import (auto-mount/unmount)
│   ├── metadata_utils.py     # Local EXIF/IPTC and cached photo metadata
│   ├── network_manager.py    # Network interface status/control via nmcli
│   ├── playlist_manager.py   # Playlist JSON load/save
│   ├── prepare_all_photos.py # Image/video preparation pipeline (resize, blur bg, polaroid, postcard)
│   ├── render_pipeline.py    # Headless photo + overlay composition (shared by both modes)
│   ├── slideshow_manager.py  # Display process lifecycle (start/stop/restart via PID files)
│   ├── text_drawer.py        # Pygame text rendering with outline
│   ├── translate_po.py       # Auto-translate .po files via Google Translate
│   ├── wallpaper_manager.py  # Desktop wallpaper backend (Windows ctypes + Linux DE matrix)
│   └── wifi_manager.py       # Wi-Fi configuration via nmcli + raspi-config
│
├── templates/                # Jinja2 HTML templates
│   ├── configure.html.jinja  # Main configuration page (5,476 lines — the big one)
│   ├── login.html.jinja      # Login page
│   ├── rebooting.html.jinja  # Reboot waiting screen
│   ├── slideshow.html.jinja  # Slideshow web view
│   └── upload.html.jinja     # Smartphone photo upload page
│
├── static/                   # Static assets
│   ├── styles.css            # Web interface styles
│   ├── backgrounds/          # Cork board background for playlist title screens
│   ├── flags/                # Country flag images + country_codes.json
│   ├── fonts/                # Caveat-Regular.ttf (handwriting font for polaroid/postcard)
│   ├── icons/                # UI icons (pause, envelope, thumbtack, postal)
│   ├── music/                # Background music MP3 files
│   ├── sounds/               # Notification sound asset (WAV)
│   ├── stamps/               # Postcard stamp images
│   ├── weather_icons/        # OpenWeatherMap-style weather icons
│   └── *.png                 # Logos and background images
│
├── translations/             # Babel i18n translations
│   ├── messages.pot          # Translation template
│   └── {en,fr,he}/LC_MESSAGES/        # Compiled .mo + source .po per language
│
│
├── config/                   # Runtime configuration (gitignored)
│   ├── config.json           # Main configuration file
│   ├── favorites.json        # Favorite photos list
│   ├── filter_states.json    # Per-photo filter state
│   ├── playlists.json        # User-created playlists
│   └── import_status.json    # Import progress tracking
│
├── setup.sh                  # Installation script (apt packages, venv, NGINX, Sway, sudoers)
├── start_pictureframe.sh          # Supervisor script (launched by Sway, restarts app on crash)
├── README.md                  # Project documentation (English)
├── FAQ.md                     # FAQ (English)
├── procedure_trad.md / .pdf  # Translation procedure guide
├── LICENSE                   # License file
├── .gitignore                # Ignores config/, static/prepared/, static/photos/, cache/, venv/, logs/ (venv entry is legacy — this fork uses global Python)
└── .gitattributes            # Forces LF line endings on .sh files
```

---

## Key Components in Detail

### 1. `app.py` — Flask Web Application (Main Entry Point)

The central web server providing all configuration, photo management, and system control via a RESTful API and Jinja2 templates.

**Key subsystems:**
- **Logging:** Custom `EmojiFormatter` with emoji-per-level, rotating file handler (10MB, 3 backups) writing to `logs/pictureframe.log`, plus console output.
- **Authentication:** Session-based login using `credentials.json` stored at `/boot/firmware/credentials.json` (on Pi). Passwords hashed with Werkzeug. `login_required` decorator protects all config routes.
- **i18n:** Flask-Babel with locale auto-detection. Supports en, fr, and he; Hebrew pages use right-to-left document direction.
- **Config management:** `load_config()` / `save_config()` via `utils/config_manager.py` with a 2-second cache and default-merge strategy.
- **Upload limit:** `MAX_CONTENT_LENGTH` is set to 500 MB for photo imports (was 32 MB).
- **Timezone dropdown:** `get_available_timezones()` uses `zoneinfo.available_timezones()` (requires `tzdata` on Windows). Falls back to a built-in `_FALLBACK_TIMEZONES` list (~80 common IANA zones including `Asia/Jerusalem`) when the system tz database is empty.
- **Background workers (daemon threads):**
  - `schedule_worker` — manages active hours (starts/stops slideshow based on configured time window). In `background_updater` mode, active-hours gating is skipped (desktop wallpaper updates regardless of time).

**Major route groups (70+ routes):**
| Group | Routes | Purpose |
|-------|--------|---------|
| Pages | `/`, `/login`, `/logout`, `/configure`, `/slideshow`, `/upload`, `/rebooting` | Web UI pages |
| Import | `/import-usb`, `/import-smartphone`, `/prepare-photos` | Photo import pipelines (streaming responses) |
| Slideshow API | `/api/slideshow/next`, `/previous`, `/toggle_pause`, `/status`, `/restart_standard`, `/set_duration` | Slideshow/background control via signals or command queue (mode-aware) |
| Run mode | `/api/app_mode` (GET current, POST switch) | Switch between picture_frame and background_updater modes |
| Display | `/api/display/power`, `/api/get_available_resolutions`, `/api/set_resolution` | Screen power + resolution |
| Sources | `/api/sources/play/<name>`, `/api/sources/toggle` | Display source management |
| Playlists | `/api/playlists` (CRUD), `/api/playlists/<id>/photos`, `/reorder`, `/rename`, `/update_music` | Playlist management |
| Photo ops | `/delete_photo/<path>`, `/api/apply_filter`, `/api/set_photo_filter`, `/api/toggle_favorite`, `/api/set_polaroid_text`, `/api/set_image_text` | Per-photo operations |
| System | `/shutdown`, `/reboot`, `/api/system/shutdown`, `/restart_app`, `/api/ping`, `/api/system_info`, `/api/cpu_temperature` | System control + monitoring |
| Network | `/save_wifi_settings`, `/api/wifi_status`, `/scan_wifi`, `/api/interface_status/<name>`, `/api/set_interface_state` | Network/Wi-Fi management |
| Maintenance | `/api/backup_settings`, `/api/restore_settings`, `/api/list_logs`, `/api/clear_logs`, `/api/expand_filesystem` | Backup, logs, filesystem |
| Tides/Weather | `/test-weather-api`, `/test-stormglass-api`, `/api/force_tide_update`, `/api/tide_info` | Weather + tide data |

### 2. `local_slideshow.py` — Pygame Slideshow Engine

A fullscreen Pygame application that displays photos with transitions, overlays, and special effects.

**Key features:**
- **Photo display:** Resizes photos to screen resolution, adds blurred background for portrait images.
- **Transitions:** Fade and slide transitions between photos (configurable duration/FPS).
- **Pan & Zoom:** Ken Burns-style motion effect on photos.
- **Overlays:** Clock, date, weather (OpenWeatherMap/Open-Meteo), tides (Stormglass), photo metadata (date, location, country flag).
- **Video playback:** Uses `mpv` as an external player for video files (with optional hardware acceleration).
- **Special effects:** Polaroid frames, postcard effects (with stamps and postmarks), creative filters.
- **Playlists:** Supports custom playlists with title slides (corkboard background with photo jumble), background music.
- **GPIO:** Fan control based on CPU temperature (pin 14, threshold 55°C) — Raspberry Pi only.
- **Signal handling:** `SIGUSR1` (next), `SIGUSR2` (previous), `SIGTSTP` (pause toggle) from Flask.
- **Status reporting:** Writes current photo path and pause state to status files for Flask to read.
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
- `OverlayDataCache` — async background fetcher for weather/tide data, shared by both modes via `render_pipeline.warm_up_overlays()`.

### 2b. `background_updater.py` — Headless Wallpaper Updater Process

A standalone script (sibling to `local_slideshow.py`) that composes photos with overlays
into a single image file and sets it as the desktop wallpaper on all monitors. Runs when
`app_mode == "background_updater"`.

**Key design:**
- **Headless pygame:** never calls `pygame.display.set_mode()` — only `pygame.font` and
  off-screen `pygame.Surface` blits. `SDL_VIDEODRIVER=dummy` is set before pygame imports.
- **Render loop:** (re)load config → resolve render size → pick next photo from playlist →
  `compose_background()` → `save_surface_atomic()` → `set_wallpaper()` → update status file →
  sleep `background_update_interval` (interruptible by next/previous/pause commands).
- **Playlist reuse:** `build_media_playlist()` mirrors the slideshow's playlist logic
  (scan prepared sources, apply filter variants, expand favorites/anniversary boosts, shuffle).
  Videos use their prepared `video_thumbnail.jpg`. Playlist rebuilds only on full pass or
  when a custom playlist file appears.
- **Not applicable in background mode** (skipped): transitions, pan/zoom, background music,
  playlist title slides, pause icon, GPIO fan, video playback.
- **Single-instance guard:** checks PID file on startup; exits if another live instance exists.
- **Signal handling:** `SIGUSR1` (next), `SIGUSR2` (previous), `SIGTSTP` (pause toggle).
  On Windows, commands arrive via the `pictureframe_background_commands/` queue.
- **Status file:** `pictureframe_background_status.json` with `current_photo`, `photo_index`,
  `playlist_size`, `paused`, `last_wallpaper_update`, `monitors`, `last_error`.

### 2c. `stop.py` — Process Stopper CLI

A standalone CLI utility to cleanly stop all PictureFrame processes. Useful for maintenance
and development when the web UI is unreachable.

**Usage:**
- `python stop.py` — graceful stop (SIGTERM, then SIGKILL after 5 s)
- `python stop.py --force` — immediate SIGKILL
- `python stop.py --dry-run` — list what would be killed without killing

Targets: `app.py`, `local_slideshow.py`, `background_updater.py`, `utils/display_message.py`,
`utils/render_pipeline.py`, `utils/wallpaper_manager.py`, any process listening on port 7090,
and any ffmpeg child processes. Cleans up PID and lock files in the OS temp dir afterward.

### 2d. `utils/render_pipeline.py` — Headless Composition Facade

The single import boundary between the background updater and `local_slideshow`'s rendering
code. Imports proven functions (`draw_overlay`, `build_playlist`, `get_path_to_display`,
`load_filter_states`, `load_favorites`) and exposes a small facade:

| Function | Purpose |
|---|---|
| `compose_background(photo_path, w, h, config, font, metadata)` | Photo + overlays → off-screen `pygame.Surface` (no display required) |
| `save_surface_atomic(surface, path)` | Atomic write: temp file → `os.replace`, so the OS never reads a half-written image |
| `build_media_playlist(config)` | Scan prepared sources, apply filters/favorites, shuffle; videos → thumbnails |
| `fit_photo_to_style(pil_image, w, h, style)` | Place photo on canvas using wallpaper style: fill/fit/stretch/span/center/tile |
| `load_main_font(config)` | Return the clock/metadata font |
| `ensure_font_init()` | Initialize `pygame.font` only (no display) |
| `warm_up_overlays(config, timeout=8)` | Block briefly until first weather/tide snapshot is ready |
| `collect_video_thumbnail(video_path)` | Return prepared thumbnail path for a video, or None |

### 2e. `utils/wallpaper_manager.py` — Desktop Wallpaper Backend

Applies a single image file as the wallpaper on **all monitors**. Follows the `platform_utils`
contract: safe to call on any OS, never raises, reports unavailability with `False` + log.

| Function | Purpose |
|---|---|
| `set_wallpaper(image_path)` | Apply file to all monitors (Windows ctypes / Linux DE matrix) |
| `get_monitors(config)` | Return `[(w, h), …]` via OS enumeration → config fallback → `(1920, 1080)` |
| `largest_monitor_size(config)` | Return the largest monitor by pixel count |
| `desktop_environment()` | Detect GNOME/MATE/Cinnamon/KDE/XFCE (returns `""` on Windows) |

**Platform matrix:**
| Platform | Mechanism |
|---|---|
| Windows | `SystemParametersInfoW(SPI_SETDESKWALLPAPER)` + registry "Fit" style |
| GNOME | `gsettings` (picture-uri + picture-uri-dark, picture-options=zoom) |
| MATE | `gsettings` (picture-filename) |
| Cinnamon | `gsettings` (picture-uri) |
| KDE Plasma | `plasma-apply-wallpaper` (≥5.25) |
| XFCE | `xfconf-query` (every `last-image` property) |
| Any X11 fallback | `feh --bg-fill` when available |

### 3. `utils/` — Utility Modules

#### `config_manager.py`
- Single source of truth for default configuration (`create_default_config()`).
- `load_config()` — loads from `config/config.json`, merges with defaults, 2-second cache.
- `save_config()` — writes JSON with indent=4, UTF-8, updates cache.
- **Configuration keys** covering: display, clock, date, weather, tides, smart plug, Wi-Fi, timezone, photo metadata, video, audio, playlists, favorites, anniversary boost.

#### `prepare_all_photos.py`
- Photo/video preparation pipeline.
- `prepare_photo()` — resizes, handles EXIF rotation, creates blurred background for portraits, generates Polaroid + Postcard variants, stores content bbox in EXIF UserComment.
- `prepare_video()` — re-encodes with ffmpeg (hardware encoder detection: h264_v4l2m2m, h264_omx, or libx264), generates thumbnail.
- `prepare_all_photos_with_progress()` — generator function yielding progress dicts for streaming responses. Smart sync: only processes new/changed files, deletes obsolete ones.
- Pi model detection for performance optimization (BILINEAR on Pi 1/2/3, LANCZOS on Pi 4/5).

#### `image_filters.py`
- `apply_filter_to_image()` — applies filters: original, grayscale, sepia, vignette, vintage, polaroid_vintage.
- `create_polaroid_effect()` — adds Polaroid-style frame.
- `create_postcard_effect()` — creates tilted postcard with white border, shadow, stamp, postmark, and optional caption.
- `add_text_to_image()` / `add_text_to_polaroid()` — adds/updates user captions.
- Backup system: originals saved to `static/.backups/` before filter application.

#### `slideshow_manager.py`
- Process lifecycle management for both display processes.
- `ProcessSpec` descriptor: `SLIDESHOW = ProcessSpec("local_slideshow.py", …)` and `BACKGROUND = ProcessSpec("background_updater.py", …)`.
- **Legacy slideshow API** (unchanged, delegates to `SLIDESHOW`):
  - `start_slideshow()`, `stop_slideshow()`, `is_slideshow_running()`,
    `restart_slideshow_process()`, `restart_slideshow_for_update()`.
- **Background updater API:** `start_background_updater()`, `stop_background_updater()`,
  `is_background_updater_running()`, `restart_background_updater_for_update()`.
  Stopping the background updater never touches display power (it's a desktop, not a frame).
- **Mode-aware API** (used by `app.py`'s `schedule_worker` and API routes):
  - `start_display_process()`, `stop_display_process()`, `is_display_process_running()`,
    `restart_display_process()`, `restart_display_process_for_update()`,
    `switch_app_mode(new_mode)` — validates, stops both processes (quietly, no display
    power change), persists config, starts the newly selected one.

#### `display_manager.py`
- `get_display_output_name()` — detects active HDMI output via `wlr-randr` or `swaymsg`.
- `set_display_power()` — turns screen on/off via smart plug (HTTP) or DPMS (wlr-randr/swaymsg).
- `set_software_display_power()` — DPMS control via Wayland compositor.
- Smart plug support: HTTP commands to configurable URLs, with reboot for HDMI stability on power-on.

#### Other utilities
- `import_usb_photos.py` — USB detection via `lsblk`, auto-mount/unmount, recursive image scan.
- `network_manager.py` — interface status/control via `ip` and `nmcli`.
- `wifi_manager.py` — Wi-Fi config via `raspi-config` (country) + `nmcli` (connect).
- `auth_manager.py` — password change via `sudo tee` to `/boot/firmware/credentials.json`.
- `metadata_utils.py` — local EXIF/IPTC and cached photo metadata lookup (date, city, country, GPS).
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
| Video | `video_audio_enabled`, `video_audio_output`, `video_audio_volume`, `video_hwdec_enabled` | Video playback settings |
| Clock/Date | `show_clock`, `clock_format`, `clock_color`, `clock_position`, `show_date`, `date_format` | On-screen clock + date |
| Weather | `show_weather`, `weather_api_key`, `weather_city`, `weather_units` | OpenWeatherMap integration |
| Tides | `show_tides`, `tide_latitude`, `tide_longitude`, `stormglass_api_key` | Stormglass tide data |
| Photo metadata | `show_photo_date`, `show_photo_location`, `show_country_flag`, `photo_metadata_*` | On-screen photo info |
| Smart plug | `smart_plug_enabled`, `smart_plug_on_url`, `smart_plug_off_url`, `smart_plug_on_delay` | HTTP-controlled power plug |
| Sources | `display_sources` (list) | Active photo sources |
| Run mode | `app_mode`, `background_update_interval`, `background_output_format`, `background_resolution_mode`, `background_display_style` | Top-level run mode + background updater settings |
| System | `timezone`, `level_log`, `favorite_boost_factor`, `anniversary_boost_enabled` | Misc system settings |

---

## Dependencies

Dependencies are split into two files for cross-platform development (see "Development Workflow" section for details).

### `requirements.txt` — Cross-platform core (Windows + Linux)
| Package | Purpose |
|---------|---------|
| Flask 2.3.2 | Web framework |
| requests 2.31.0 | HTTP client (weather, smart plugs, etc.) |
| Pillow 10.4.0 | Image processing |
| pygame | Slideshow rendering + audio |
| psutil | Process management + system monitoring |
| werkzeug | WSGI utilities + password hashing |
| Flask-Babel | Internationalization |
| piexif | EXIF metadata read/write |
| qrcode[pil] | QR code generation |
| deep-translator | Auto-translation of .po files |
| polib | .po file parsing |
| tzdata | IANA timezone database — needed by `zoneinfo` on Windows for the timezone dropdown |
| comtypes (Windows only) | COM interop for `IDesktopWallpaper` per-monitor wallpaper API |

### `requirements-pi.txt` — Linux / Raspberry Pi only
| Package | Purpose |
|---------|---------|
| pillow-heif | HEIC/HEIF photo support (iPhone photos) |
| RPi.GPIO | GPIO hardware control (fan, button) |

### System packages (installed by `setup.sh`)
`sway`, `xterm`, `python3`, `python3-venv`, `python3-pip`, `libjpeg-dev`, `libopenjp2-7-dev`, `libtiff-dev`, `ffmpeg`, `git`, `network-manager`, `jq`, `mpv`, `gettext`, `libheif-dev`, `nginx`, `python3-rpi.gpio`

---

## Build, Test, and Lint

- **Windows:** Install cross-platform deps with `pip install -r requirements.txt` (global Python, no venv). Start Flask with `python app.py`.
- **Raspberry Pi:** Install both files: `pip install -r requirements.txt && pip install -r requirements-pi.txt` (add `--break-system-packages` on Debian 12+).
- Run regression tests with `python -m unittest discover -s tests -p 'test_*.py' -q`.
- To update translations:
  - `pybabel extract -F babel.cfg -o translations/messages.pot .`
  - `pybabel update -i translations/messages.pot -d translations`
  - `pybabel compile -d translations`
- Deployment scripts (`setup.sh`, `start_pictureframe.sh`) still reference `venv` — these need updating to use global Python (remove venv creation/activation lines, install deps globally).

---

## Setup & Deployment

### First-time Installation (on Raspberry Pi)
```bash
git clone https://github.com/ehenry7/picFrame.git
cd picFrame
chmod +x setup.sh
sudo ./setup.sh
```

> **Note (this fork):** The original `setup.sh` creates a Python virtual environment (`venv`). For this fork, **skip venv** and use the global Python instead. Modify `setup.sh` to remove the `python3 -m venv venv` and `source venv/bin/activate` steps, and install dependencies directly with `pip3 install -r requirements.txt` (or `pip install --break-system-packages -r requirements.txt` on newer Debian/Raspberry Pi OS that enforces PEP 668). Similarly, update `start_pictureframe.sh` to remove the `source venv/bin/activate` line and run `python3 -u app.py` directly.

`setup.sh` performs 12 steps:
1. `apt update`
2. Install system dependencies
3. Configure French locale
4. Disable Wi-Fi power saving + install RPi.GPIO
5. Auto-detect timezone via IP geolocation
6. Install + configure NGINX (reverse proxy :80 → :7090)
7. Create Python venv + install pip dependencies — **this fork: install into global Python instead**
8. Create directory structure (logs, cache, static/photos, config, etc.)
9. Generate credentials.json with random password + configure sudoers NOPASSWD
10. Set boot to console mode with auto-login
11. Configure Sway auto-start in `.bash_profile`
12. Configure PictureFrame auto-start in Sway config + mpv window rules

### Startup Flow
1. Pi boots → console auto-login → `.bash_profile` → `exec sway`
2. Sway starts → `exec_always start_pictureframe.sh`
3. `start_pictureframe.sh` → runs `python3 -u app.py` directly (no venv activation — **this fork uses global Python**)
4. `app.py` → starts Flask on :7090, launches background workers
5. Flask starts the slideshow process via `slideshow_manager.start_slideshow()`
6. NGINX proxies :80 → :7090 for clean URL access. Existing installations must update the installed NGINX upstream and reload NGINX.

### Updating
- Remote self-update routes, UI and scripts are not included. Update code manually outside the app after stopping it and backing up configuration; preserve local changes.
- USB and browser photo imports remain available. Remote album downloads are not supported. Previously imported photos remain selectable as Imported photos; preserve their on-disk paths and cached metadata so playlists, favorites, filters and captions keep working. Retired connection settings are stripped on config load/save.
- Exit code 42 is retained for the separate app-restart action, not remote updates.

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

### 2. Path Management with `pathlib`

- **Never hardcode** `/tmp/`, `/home/pi/`, `/boot/firmware/`, or `/usr/share/fonts/` in new code.
- Use `platform_utils.get_temp_dir()`, `get_pid_file()`, `get_status_file()`, `get_credentials_path()`, `get_default_font_path()`, or `Path(__file__).resolve().parent` for project-relative paths.
- Existing hardcoded paths in `config_manager.py` defaults (font paths) should use `platform_utils.get_default_font_path()` at runtime.
- Consider a `.env` file (gitignored) for environment-specific overrides (port, weather keys). Use `python-dotenv` if environment variable loading is needed.

### 3. Dependency Management (Dual Requirements Files)

Dependencies are split into two files:

**`requirements.txt`** — Cross-platform core (installs on Windows + Linux):
- Flask, requests, Pillow, pygame, psutil, werkzeug, Flask-Babel, piexif, qrcode, deep-translator, polib

**`requirements-pi.txt`** — Linux/Pi only (do NOT install on Windows):
- pillow-heif, RPi.GPIO

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
- Develop and debug Flask routes, Pillow image processing, EXIF handling, browser imports, template rendering, playlist logic.
- Run Flask: `python -u app.py` (starts on port 7090). Open `http://127.0.0.1:7090` and look for the `HTTP server READY` log.
- Pygame runs in **windowed mode** (1280×720) via `platform_utils.get_pygame_display_flags()` — not fullscreen.
- Pi-specific hardware operations are unavailable; they must not be reported as successful. GPIO features require their platform dependencies and hardware.
- The web UI is fully functional for configuration, playlist management, photo metadata, and system monitoring (except real hardware actions).

**Raspberry Pi 4 (hardware testing via SSH):**
- Commit and push from Windows → pull on Pi (or use VS Code Remote-SSH directly).
- On Pi: `git pull && python3 -u app.py` (or restart via `start_pictureframe.sh`).
- Test real hardware: HDMI standby, touchscreen/GPIO button, USB import, Wi-Fi management, CPU temperature, fan control, video playback with hardware acceleration.
- Pygame runs in `FULLSCREEN | NOFRAME` kiosk mode.

### 5. What Works on Windows vs. Pi

| Feature | Windows | Raspberry Pi |
|---------|---------|--------------|
| Flask web server | ✅ Full | ✅ Full |
| Web UI configuration | ✅ Full | ✅ Full |
| Image processing (Pillow) | ✅ Full | ✅ Full |
| Playlists management | ✅ Full | ✅ Full |
| Pygame slideshow | ⚠️ Windowed 1280×720 | ✅ Fullscreen kiosk |
| Background updater mode | ✅ Full (Windows wallpaper API) | ⚠️ Works but not the primary use case |
| Desktop wallpaper (all monitors) | ✅ `SystemParametersInfoW` | ✅ `gsettings`/`plasma-apply-wallpaper`/`xfconf-query`/`feh` |
| Display power (DPMS) | ❌ Unavailable | ✅ wlr-randr/swaymsg |
| System reboot/shutdown | ❌ Unavailable | ✅ sudo |
| CPU temperature | ❌ None | ✅ /sys/class/thermal |
| GPIO (fan, button) | ❌ None | ✅ RPi.GPIO |
| USB import | ❌ Unavailable | ✅ lsblk + mount |
| Wi-Fi management | ❌ Unavailable | ✅ nmcli + raspi-config |
| HEIC/HEIF photos | ❌ No pillow-heif | ✅ pillow-heif |
| Video playback | ⚠️ ffmpeg if installed | ✅ mpv + hwdec |
| NGINX reverse proxy | ❌ Not needed | ✅ :80 → :7090 |

### 6. Cross-Platform Considerations
- Shell scripts (`.sh`) use LF line endings (enforced by `.gitattributes`).
- The codebase uses French comments throughout — this is the original author's language.

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

- Startup stages, named workers, HTTP request start/end timings, and uncaught exceptions are recorded in `logs/pictureframe.log` and the console.
- A localhost HTTP probe logs `HTTP server READY` once port 7090 responds. If startup stalls for 30 seconds, `logs/startup_threads.log` captures all Python thread stacks.
- **Log file:** `logs/pictureframe.log` (rotating, 10MB max, 3 backups, UTF-8).
- **Format:** Emoji-prefixed lines with module color codes:
  - 🟨 = app.py
  - 🟦 = local_slideshow.py
  - 🟪 = slideshow_manager.py
  - 🟩 = display_manager.py
  - 🔄 = prepare_all_photos.py
- **Level:** Configurable via `level_log` in config.json (default: "INFO").
- **Werkzeug logs:** Cleaned and reformatted by `CleanWerkzeugFormatter`.

---

## Photo Pipeline

```
Source (USB/Browser)
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
- Cancellation support via `/tmp/pictureframe_cancel_import.flag`.

---

## Key Patterns & Conventions

1. **Generator-based streaming:** Import/prepare/download functions are Python generators that yield progress dicts. Flask routes use `stream_with_context` to stream these as Server-Sent Events for real-time progress bars.

2. **PID file management:** Each long-running process (slideshow, app) uses a PID file in `/tmp/` for lifecycle management. Zombie processes are cleaned up before starting new instances.

3. **Config merge strategy:** User config is merged with defaults on load, ensuring new keys are added without losing existing settings. 2-second cache prevents excessive file reads.

4. **EXIF as metadata channel:** Content bounding boxes are stored in EXIF UserComment for Polaroid text placement. Keep the legacy prefix readable for existing prepared photos. Previously imported photo metadata remains cached locally; local uploads read EXIF/IPTC from originals.

5. **Process isolation:** Flask and slideshow run as separate OS processes, communicating via signals, HTTP, and status files — not shared memory.

6. **Graceful degradation:** HEIC support is optional (pillow-heif). Hardware video encoders are auto-detected. Smart plug is optional. All features degrade gracefully when unavailable.

---

## Git Information

- **Repository:** https://github.com/ehenry7/picFrame.git
- **Default branch:** `main`
- **License:** See `LICENSE` file
- **Language:** Code comments are primarily in French; documentation is bilingual (French + English).
