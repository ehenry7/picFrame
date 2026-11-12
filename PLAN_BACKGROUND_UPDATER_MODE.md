# Plan: Desktop Background Updater Mode for PictureFrame

**Status:** Implemented 2026-11-11 — all phases complete, test suite green (no new failures)
**Author:** Planning session 2026-11-11
**Scope:** Add a top-level "run mode" switch so the application runs either as its current
digital photo frame (Pygame fullscreen slideshow on a Pi) **or** as a desktop background
updater for regular Windows/Linux desktops: pick a photo, render it with all existing
overlays into a single image file, and set that file as the wallpaper on **all screens /
monitors**.

---

## 1. Executive summary

PictureFrame already has everything needed to *compose* a wallpaper: a photo-fit pipeline
(`fit_photo_to_screen`), a rich overlay renderer (`draw_overlay`: clock, date, weather,
tides, photo metadata), an async overlay-data cache (`OverlayDataCache`), and playlist
logic (`build_playlist`). Today all of that renders onto a Pygame *screen* via
`local_slideshow.py`.

The plan is to add a second top-level runtime mode:

| Mode | Process | Output |
|---|---|---|
| `picture_frame` (default, current behavior) | `local_slideshow.py` | Pygame fullscreen kiosk on the Pi |
| `background_updater` (new) | `background_updater.py` (new) | One image file → set as the wallpaper on every monitor |

The mode is a **single top-level switch** (config key `app_mode`, with an environment
override), resolved at process-launch time by a mode-aware process manager. Switching
modes stops the active child process and starts the other. The web UI gets a mode
selector. All existing photo import, playlist, overlay, and config machinery is reused
unchanged.

**Multi-screen guarantee:** the updater renders one image file and applies it to *all*
monitors using OS/desktop-wide wallpaper APIs (Windows `SystemParametersInfoW`,
GNOME/MATE/Cinnamon `gsettings`, KDE `plasma-apply-wallpaper`, XFCE `xfconf-query`), with
a "fill/zoom" fit policy so differently-sized monitors stay distortion-free.

---

## 2. Current architecture (relevant facts)

```
app.py (Flask, :7090)
 ├─ schedule_worker (daemon thread) ── start/stop per active hours
 └─ utils/slideshow_manager.py ── subprocess lifecycle, PID files
       └─ python -u local_slideshow.py      ← hardcoded script name
            ├─ pygame fullscreen render loop
            ├─ draw_overlay()  → clock/date/weather/tides/metadata onto a Surface
            ├─ OverlayDataCache → background weather/tide fetch
            └─ status files + SIGUSR1/2 + command-file queue for Flask ↔ process IPC
```

- Config: `utils/config_manager.py::create_default_config()` is the single source of
  defaults; `load_config()` merges with defaults and caches 2 s.
- Platform abstraction: `platform_utils.py` (path helpers, command queue
  `enqueue_slideshow_command()` / `consume_slideshow_commands()`, `get_pygame_display_*`).
- IPC: status files `pictureframe_slideshow_status.json`,
  `pictureframe_current_photo.txt`, `pictureframe_custom_playlist.json`; PID file
  `pictureframe_slideshow.pid`; command dir `pictureframe_slideshow_commands/` (used on
  Windows instead of POSIX signals).
- `draw_overlay(screen, screen_width, screen_height, config, main_font, photo_metadata)`
  is already surface-agnostic: it just blits onto whatever `pygame.Surface` it receives.
- `fit_photo_to_screen(pil_image, w, h)` returns a PIL `RGB` image sized exactly
  `w×h` — perfect wallpaper material.
- `slideshow_manager.py` hardcodes `"local_slideshow.py"` in three places: zombie cleanup,
  stale-PID validation, and `subprocess.Popen`.

---

## 3. Proposed design

### 3.1 Top-level switch

**Config keys** (added to `create_default_config()` in `utils/config_manager.py`):

```python
# --- Run mode (top-level switch) ---
"app_mode": "picture_frame",          # "picture_frame" | "background_updater"

# --- Background updater settings (only used when app_mode == "background_updater") ---
"background_update_interval": 3600,   # seconds between wallpaper changes
"background_output_format": "png",    # "png" | "jpg"
"background_resolution_mode": "auto", # "auto" (largest monitor) | "manual" (display_width/height)
```

**Resolution order** (a new helper `utils/app_mode.py`):

1. `PICTUREFRAME_APP_MODE` environment variable (for headless/kiosk boot overrides) —
   wins if set to a valid value.
2. `config["app_mode"]` from `config.json`.
3. Default `"picture_frame"`.

```python
# utils/app_mode.py (new)
VALID_APP_MODES = ("picture_frame", "background_updater")

def get_app_mode(config=None) -> str:
    """Return the effective run mode ('picture_frame' or 'background_updater')."""
    env = os.environ.get("PICTUREFRAME_APP_MODE", "").strip().lower()
    if env in VALID_APP_MODES:
        return env
    mode = (config or {}).get("app_mode", "picture_frame")
    return mode if mode in VALID_APP_MODES else "picture_frame"
```

Invalid values **never crash the app** — they log a warning and fall back to
`picture_frame` (matches the project's "graceful degradation" convention).

The mode is resolved **when a child process is about to be launched** (never mid-flight):
`schedule_worker` and the restart routes ask the process manager, "which process does the
current mode want?", then start/stop accordingly.

### 3.2 New child process: `background_updater.py`

A new top-level script, sibling to `local_slideshow.py`, mirroring its structure
(logging, PID file, status file, command handling) but with a headless render loop:

```
loop:
  1. (re)load config
  2. resolve render size  (wallpaper_manager.get_monitors() → largest monitor,
                           or display_width/display_height when mode == "manual")
  3. pick next photo from playlist (build_playlist + get_path_to_display, reusing
     local_slideshow logic; videos → use prepared video_thumbnail.jpg)
  4. compose image:
       pil  = fit_photo_to_screen(Image.open(photo), w, h)
       surf = pygame.image.fromstring(pil.tobytes(), pil.size, pil_image.mode)
       draw_overlay(surf, w, h, config, main_font, photo_metadata)   # reused as-is
  5. save ATOMICALLY:  write cache/desktop_background.tmp.<ext>
                       → os.replace(...) → cache/desktop_background.<ext>
  6. wallpaper_manager.set_wallpaper(cache/desktop_background.<ext>)   # all monitors
  7. update pictureframe_background_status.json
  8. sleep background_update_interval (interruptible: next/previous/pause commands
     wake it early; "pause" freezes on the last image)
```

**Headless Pygame rules** (important, keep these in the plan review):

- Never call `pygame.display.set_mode()` — the updater only uses off-screen
  `pygame.Surface` objects, `pygame.font`, and `pygame.image.save()`. This works with no
  display server on any OS.
- Call `pygame.font.init()` only (skip mixer/display).
- On Linux, defensively `os.environ.setdefault("SDL_VIDEODRIVER", "dummy")` before
  importing pygame in this script — cheap insurance if any reused helper touches the
  display.

**Code reuse strategy — facade, not refactor:** `background_updater.py` does **not**
duplicate rendering code. It imports the proven pieces from `local_slideshow`
(`fit_photo_to_screen`, `draw_overlay`, `parse_color`, `build_playlist`,
`get_path_to_display`, `OverlayDataCache`, weather/tides getters). To keep that coupling
isolated, all such imports go through one thin module:

```python
# utils/render_pipeline.py (new)
"""Headless composition pipeline shared by the slideshow and the background updater."""
from local_slideshow import (
    fit_photo_to_screen, draw_overlay, parse_color,
    build_playlist, get_path_to_display,
    get_weather_and_forecast, get_tides, OverlayDataCache,
)

def compose_background(photo_path, width, height, config, main_font):
    """Return a composed pygame.Surface: photo + overlays, sized width×height."""
    ...
```

If a later phase extracts these functions out of `local_slideshow.py` into
`utils/render_core.py`, only `render_pipeline.py` changes. (Full extraction is explicitly
*out of scope* for this change — the 2,330-line file is stable and heavily tested.)

**Not applicable in background mode** (skipped, not ported): transitions, pan/zoom,
background music, playlist title slides, pause icon, GPIO fan, video playback (video
entries use their prepared thumbnail). Videos: the prepared pipeline already writes
`video_thumbnail.jpg`, so playlist code keeps working with a one-line mapping.

### 3.3 Wallpaper backend: `utils/wallpaper_manager.py` (new)

Follows the `platform_utils.py` contract: safe to call anywhere, never raises, logs and
returns `False` when unavailable.

```python
def set_wallpaper(image_path: str) -> bool          # apply file to ALL monitors
def get_monitors() -> list[tuple[int, int]]         # [(width, height), ...]
def desktop_environment() -> str                    # 'gnome' | 'kde' | 'xfce' | ...
```

**Windows (`IS_WINDOWS`) — `set_wallpaper`:**

- Primary mechanism: ctypes `user32.SystemParametersInfoW(SPI_SETDESKWALLPAPER=20, 0,
  path, SPIF_UPDATEINIFILE | SPIF_SENDCHANGE)`. This sets the wallpaper on **all**
 monitors (Windows replicates the current wallpaper across monitors), which is exactly
  the required behavior.
- Also write the fit style once via registry
  (`HKCU\Control Panel\Desktop\WallpaperStyle=6` "Fit", `TileWallpaper=0`) so differently
  sized monitors don't distort the photo, then re-apply.
- Acceptance note: SystemParametersInfoW requires an **absolute path** and fails for
  images on transient media — we always render into the project `cache/` dir, so this is
  satisfied by construction.

**Windows — `get_monitors`:** ctypes `EnumDisplayMonitors` + `GetMonitorInfo` (per-monitor
desktop rects). Fallback: `GetSystemMetrics(SM_CXSCREEN/SM_CYSCREEN)` (primary only).

**Linux — `set_wallpaper` by detected desktop environment** (`XDG_CURRENT_DESKTOP`,
`DESKTOP_SESSION`):

| DE | Command (same file applied to all monitors) |
|---|---|
| GNOME/Ubuntu | `gsettings set org.gnome.desktop.background picture-uri file://…` **and** `picture-uri-dark` (same image); set `picture-options` to `'zoom'` |
| MATE | `gsettings set org.mate.background picture-filename …` |
| Cinnamon | `gsettings set org.cinnamon.desktop.background picture-uri file://…` |
| KDE Plasma | `plasma-apply-wallpaper <path>` (Plasma ≥ 5.25; applies to all screens) |
| XFCE | Enumerate `xfconf-query -c xfce4-desktop -l`, set every `…last-image` property to the path |
| Any, X11 fallback | `feh --bg-fill <path>` if installed |

GNOME/MATE/Cinnamon/KDE apply one background to all monitors by default; XFCE is
per-property and we simply set them all — the "same file everywhere" requirement is met
on every supported DE.

**Linux — `get_monitors`:** parse `xrandr --query` when available; fallback to
(`display_width`, `display_height`) from config; final fallback `(1920, 1080)`.
On Wayland-composited setups without xrandr, config values win.

### 3.4 Process lifecycle: mode-aware process manager

Refactor `utils/slideshow_manager.py` internals around a small process descriptor, while
keeping the existing public API 100 % intact (13 call sites in `app.py` depend on it):

```python
# utils/slideshow_manager.py (refactored)
@dataclass(frozen=True)
class ProcessSpec:
    script: str                    # "local_slideshow.py" | "background_updater.py"
    pid_name: str                  # PID file stem: "pictureframe_slideshow" | "pictureframe_background"
    # zombie cleanup + is_running + start/stop driven by `script` and `pid_name`

SLIDESHOW = ProcessSpec("local_slideshow.py", "pictureframe_slideshow")
BACKGROUND = ProcessSpec("background_updater.py", "pictureframe_background")

# Existing names keep working (delegate to SLIDESHOW):
def start_slideshow(): ...          # unchanged signature
def stop_slideshow(): ...
def is_slideshow_running(): ...

# New mode-aware entry points used by app.py:
def start_display_process() -> None     # resolves get_app_mode() → starts the right one
def stop_display_process() -> None
def is_display_process_running() -> bool
def switch_app_mode(new_mode: str) -> None   # validate → stop active → save config → start new
```

Add one tiny extension to `platform_utils.py`: parameterize the command queue so the
background updater gets its own directory (`pictureframe_background_commands/`), keeping
the slideshow queue untouched:

```python
def get_slideshow_command_dir(process: str = "slideshow") -> Path   # backward-compatible default
def enqueue_slideshow_command(command, process: str = "slideshow")
def consume_slideshow_commands(process: str = "slideshow")
```

### 3.5 app.py integration

1. **`schedule_worker`** — replace direct `start_slideshow()` / `is_slideshow_running()`
   calls with `start_display_process()` / `is_display_process_running()`. The active-hours
   semantics stay identical for both modes (background updates pause outside active hours
   unless the user overrides, exactly like the slideshow today).
2. **Slideshow API routes** (`/api/slideshow/next`, `/previous`, `/toggle_pause`,
   `/status`, `/restart_standard`, `/set_duration`) — keep the URLs (no client breakage);
   internally route by mode: enqueue commands to the right queue and read the right
   status file. In background mode "pause" = freeze on last image; next/previous take
   effect on the next update cycle (or trigger an immediate refresh).
3. **New route `/api/app_mode`** (`GET` current mode, `POST` new mode):
   - validates the value,
   - calls `switch_app_mode()`: stop active child → `save_config` → start new child,
   - returns `{ "ok": true, "app_mode": "..." }`.
   The generic config-save endpoint keeps working for the auxiliary background settings
   (`background_update_interval`, etc.) — only the mode flip needs the dedicated route
   because it has side effects.
4. **Startup** — nothing else changes: `app.py` boots identically in both modes; only the
   child it spawns differs.

### 3.6 Web UI (templates/configure.html.jinja)

- New "Mode d'exécution / Run mode" card in the **Affichage (Display)** tab:
  - radio: `picture_frame` (Cadre photo) | `background_updater` (Mise à jour du fond d'écran)
  - auxiliary fields shown only when background mode is selected: update interval
    (minutes), output format, resolution mode.
- On save with a changed mode, JS calls `POST /api/app_mode` instead of (after) the
  normal config save; on success it reloads so the status bar reflects the new process.
- Status/monitoring widgets that read the slideshow status file continue to work: the
  background updater writes the same status schema to
  `pictureframe_background_status.json` (`current_photo`, `paused`, plus
  `last_wallpaper_update`, `monitors`).
- New strings go through the existing i18n flow (`pybabel extract/update/compile`).

### 3.7 Multi-screen design summary

The requirement is "one composed file, applied to all screens":

1. **Render once** — at the largest detected monitor resolution (or manual
   `display_width`/`display_height`).
2. **Apply everywhere** — each supported platform applies a single file to all monitors
   (see 3.3); XFCE loops over every monitor property.
3. **Fit policy** — wallpaper style set to *Fit/Fill/zoom* (per platform) so
   differently-sized monitors crop rather than distort.
4. **Re-detect every cycle** — monitor topology is re-queried on each update, so
   hot-plug/resolution changes self-heal without restarts.

Per-monitor *renders* (different image per screen, e.g. via Windows `IDesktopWallpaper`
COM API) are deliberately out of scope; the data model and manager are structured so it
can be added later without redesign.

---

## 4. File-by-file change list

| File | Change | Type |
|---|---|---|
| `utils/config_manager.py` | Add `app_mode`, `background_update_interval`, `background_output_format`, `background_resolution_mode` defaults | edit |
| `utils/app_mode.py` | **New.** `get_app_mode()`, `VALID_APP_MODES`, mode resolution | new |
| `utils/wallpaper_manager.py` | **New.** `set_wallpaper`, `get_monitors`, `desktop_environment` (Win ctypes + Linux DE matrix) | new |
| `utils/render_pipeline.py` | **New.** `compose_background()` facade over `local_slideshow` render helpers | new |
| `background_updater.py` | **New.** Headless updater process (PID/status/command handling, render loop, atomic save, wallpaper apply) | new |
| `platform_utils.py` | Parameterize command queue by process name (3 functions, backward-compatible defaults) | edit |
| `utils/slideshow_manager.py` | `ProcessSpec` refactor; keep old API; add `start_display_process`, `stop_display_process`, `is_display_process_running`, `switch_app_mode` | edit |
| `app.py` | `schedule_worker` uses mode-aware calls; `/api/app_mode` route; slideshow routes dispatch by mode | edit |
| `templates/configure.html.jinja` | Run-mode card + conditional background settings + JS mode-switch call | edit |
| `tests/test_background_mode.py` | **New.** Unit tests (see §6) | new |
| `AGENTS.md`, `README.md` | Document the two modes, new architecture box, new config keys | edit |

**Unchanged on purpose:** photo import/prepare pipeline, playlists, filters, favorites,
auth, i18n infrastructure, NGINX setup, `start_pictureframe.sh` (it supervises `app.py`
only), and `local_slideshow.py` rendering internals.

---

## 5. Implementation phases

Each phase is independently committable and leaves the app green
(`python -m unittest discover -s tests -p 'test_*.py' -q`).

**Phase 1 — Config & mode resolution (small, safe)**
Add config keys; create `utils/app_mode.py`; unit tests for precedence and invalid-value
fallback.

**Phase 2 — Wallpaper backend**
`utils/wallpaper_manager.py` with Windows ctypes implementation and the Linux DE matrix;
`get_monitors()`. Unit-testable on any OS (unsupported paths return `False`); live
wallpaper application verified manually on the dev box.

**Phase 3 — Headless render pipeline**
`utils/render_pipeline.py::compose_background()`; verify byte-identical overlay output
vs. the slideshow path using a synthetic photo + fixed config (smoke test writes a file
and checks dimensions + non-black pixels).

**Phase 4 — Background updater process**
`background_updater.py` with full loop, atomic file save, status file, command handling.
Manual run: `python -u background_updater.py` updates the wallpaper without Flask.

**Phase 5 — Process manager & app integration**
`slideshow_manager.py` refactor; `schedule_worker` and API route updates;
`/api/app_mode`. Regression: all existing `test_slideshow_*` tests must pass unchanged.

**Phase 6 — Web UI**
Mode card in configure page, JS mode-switch call, i18n extraction for new strings.

**Phase 7 — Docs & polish**
AGENTS.md architecture diagram update, README mode section, FAQ entry, final regression
pass on Windows dev machine + Linux target.

---

## 6. Testing plan

**Unit tests (`tests/test_background_mode.py`):**

- `get_app_mode()` precedence: env var → config → default; invalid values fall back.
- Config defaults: all four new keys present; round-trip save/load.
- `compose_background()`: produces file of expected size for portrait and landscape
  test images (overlay on/off).
- `wallpaper_manager`: returns `False` (not raises) on unsupported DEs; `get_monitors()`
  returns sane fallback.
- Command queue: slideshow and background queues are isolated (enqueue to one does not
  affect the other).
- `slideshow_manager`: PID/status/command naming per mode; `switch_app_mode` rejects
  invalid modes without touching config.
- Regression: full existing suite passes (`test_slideshow_controls`,
  `test_slideshow_navigation`, `test_weekend_schedule`, …).

**Manual test matrix:**

| Environment | Checks |
|---|---|
| Windows 10/11, 1 monitor | wallpaper updates, fit style correct, app restart keeps mode |
| Windows 10/11, 2+ monitors (mixed sizes) | same file on all monitors, no distortion |
| Linux GNOME (X11 + Wayland) | `gsettings` applies to all monitors; dark-URI variant also set |
| Linux KDE Plasma | `plasma-apply-wallpaper` path |
| Linux XFCE | all `last-image` properties updated |
| Unsupported DE | log message, process keeps running, status file reports `last_error` |
| Mode switch under load | switch mid-update: no orphan processes, PID files consistent |
| Pi (picture_frame mode) | zero behavior change (regression) |

---

## 7. Risks & mitigations

| # | Risk | Mitigation |
|---|---|---|
| R1 | Importing `local_slideshow` pulls module side effects into the updater | Reused code is import-time-safe today (verified: only constants, logger, `OverlayDataCache` instantiation); isolated behind `render_pipeline.py`; smoke test in Phase 3 |
| R2 | Linux DE fragmentation (many wallpaper APIs) | Explicit DE matrix with detection, per-DE commands, `feh` fallback, and honest `False` + log when nothing matches (project convention: never fake success) |
| R3 | Mixed monitor sizes distort the image | Fit/Fill/zoom policy per platform + render at largest monitor resolution |
| R4 | Pygame needs a display server | Updater never calls `set_mode`; only Surface/font/image APIs + `SDL_VIDEODRIVER=dummy` insurance |
| R5 | Process-manager refactor breaks slideshow control | Public API kept byte-compatible; existing slideshow tests run unmodified in Phase 5 gate |
| R6 | OS reads a half-written image | Atomic write (`tmp` + `os.replace`) |
| R7 | Windows API path quirks (relative paths, non-ASCII) | Always pass absolute path from `Path.resolve()`; `cache/` is project-local |
| R8 | Mode switched while child mid-render | `switch_app_mode` stops first, waits for PID exit, then starts new mode; stale PID cleanup reuses existing zombie logic |

---

## 8. Confirmed decisions

*(Review completed 2026-11-11 — all items confirmed.)*

1. **Active hours in background mode** — the background updater shares the same
   active-hours schedule gating as the slideshow (updates pause outside active hours,
   with the same manual-override semantics). No separate behavior.
2. **Update interval** — dedicated `background_update_interval` config key
   (default 3600 s = 1 h), separate from the slideshow's `display_duration`.
3. **Output format default** — PNG (configurable to JPEG via `background_output_format`).
4. **Video handling** — videos in playlists use the prepared `video_thumbnail.jpg`.
   Videos are not skipped; playlists stay identical across both modes.

All other behavior (playlists, favorites, filters, overlays, config, active hours,
manual next/previous/pause controls) is common to both modes.

---

## 9. Out of scope (future work)

- Per-monitor rendered images (Windows `IDesktopWallpaper` COM, GNOME extensions).
- Lock/login-screen backgrounds.
- Transitions, Ken Burns effects, or animated wallpapers (e.g., wallpaper-engine).
- Executing `background_updater.py` standalone via a systemd user unit (it already works
  standalone for testing, but deployment scripts are not updated).
