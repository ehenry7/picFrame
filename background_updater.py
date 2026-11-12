import os

if __name__ == "__main__" and os.name == "nt":
    import truststore
    truststore.inject_into_ssl()

# Background rendering must work on machines without any display server:
# headless SDL insurance before pygame gets imported by the render pipeline.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import json
import logging
import signal
import sys
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pygame

from platform_utils import (
    get_pid_file,
    get_status_file,
    consume_slideshow_commands,
)
from utils.config_manager import load_config
from utils.metadata_utils import get_photo_metadata

# ── Paths �───────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent
PID_FILE = get_pid_file("pictureframe_background")
STATUS_FILE = get_status_file("pictureframe_background_status.json")
CUSTOM_PLAYLIST_FILE = get_status_file("pictureframe_custom_playlist.json")
WALLPAPER_BASENAME = "desktop_background"

# ── Logging (mirrors local_slideshow.py) ────────────────────────

LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)


import logging  # noqa: E402  (already imported at the top)

class EmojiFormatter(logging.Formatter):
    """Format log records with an emoji based on their severity."""

    EMOJI_MAP = {
        "DEBUG": "🔍",
        "INFO": "ℹ️",
        "WARNING": "😒",
        "ERROR": "❌",
        "CRITICAL": "🔥",
    }

    def format(self, record):
        emoji = self.EMOJI_MAP.get(record.levelname, "")
        record.emoji = emoji
        return super().format(record)


_logger_config = load_config()
LOGS_DIR.mkdir(exist_ok=True)
file_handler = RotatingFileHandler(
    LOGS_DIR / "pictureframe.log",
    maxBytes=10 * 1024 * 1024,
    backupCount=3,
    encoding="utf-8",
)
level_name = _logger_config.get("level_log", "INFO")
level = getattr(logging, level_name.upper(), logging.INFO)
file_handler.setLevel(level)
file_handler.setFormatter(EmojiFormatter(
    "%(emoji)s🖼️%(asctime)s %(message)s", datefmt="%d-%m %H:%M:%S"))
logging.basicConfig(level=level, handlers=[file_handler, logging.StreamHandler()],
                     force=True)
logger = logging.getLogger(__name__)

# ── Control state (signal handlers) ─────────────────────────────

paused = False
next_photo_requested = False
previous_photo_requested = False


def update_status_file(new_fields):
    """Update the JSON status file while preserving other fields."""
    global _current_status
    _current_status.update(new_fields)
    try:
        with open(STATUS_FILE, "w") as f:
            json.dump(_current_status, f)
    except IOError as e:
        logger.info(f"Error writing status file: {e}")


_current_status = {"paused": False}


def signal_handler_next(signum, frame):
    global next_photo_requested, previous_photo_requested
    next_photo_requested = True
    previous_photo_requested = False


def signal_handler_previous(signum, frame):
    global next_photo_requested, previous_photo_requested
    previous_photo_requested = True
    next_photo_requested = False


def signal_handler_pause_toggle(signum, frame):
    global paused
    paused = not paused
    update_status_file({"paused": paused})


def handle_commands():
    """Apply queued control commands (all platforms: files + POSIX signals)."""
    global paused, next_photo_requested, previous_photo_requested
    for command in consume_slideshow_commands("background"):
        if command == "next":
            signal_handler_next(None, None)
        elif command == "previous":
            signal_handler_previous(None, None)
        elif command == "toggle_pause":
            signal_handler_pause_toggle(None, None)


# ── Helpers ─────────────────────────────────────────────────────


def load_custom_playlist():
    """Return a list of prepared-photo paths from the custom playlist, or None."""
    if not os.path.exists(CUSTOM_PLAYLIST_FILE):
        return None
    try:
        with open(CUSTOM_PLAYLIST_FILE, "r") as f:
            playlist_data = json.load(f)
        if isinstance(playlist_data, dict):
            playlist_data = playlist_data.get("photos", [])
        paths = [str(BASE_DIR / "static" / "prepared" / p) for p in playlist_data]
        if not paths:
            return None
        try:
            os.remove(CUSTOM_PLAYLIST_FILE)
            logger.info(f"🖼️ Custom playlist loaded with {len(paths)} photos.")
        except (IOError, OSError) as e:
            logger.warning(f"Could not remove custom playlist file: {e}")
        return paths
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"Invalid custom playlist file: {e}")
        return None


def resolve_render_size(config):
    """Return the (width, height) the wallpaper should be rendered at."""
    from utils.wallpaper_manager import largest_monitor_size
    mode = config.get("background_resolution_mode", "auto")
    if mode == "manual":
        width = int(config.get("display_width", 0) or 0)
        height = int(config.get("display_height", 0) or 0)
        if width > 0 and height > 0:
            return width, height
    return largest_monitor_size(config)


def wallpaper_output_path(config, cycle=0, monitor_index=0):
    """Return the wallpaper image path in the project cache directory.

    ``cycle`` alternates between two file names on purpose: Windows caches
    the wallpaper by file path and silently ignores requests to re-apply
    the very same file, which would freeze the clock overlay and the photo
    rotation. Handing the OS a different path on every update forces a
    real refresh on every platform.

    ``monitor_index`` is used when rendering per-monitor wallpapers so each
    monitor gets its own stable pair of alternating filenames (e.g.
    ``desktop_background_mon0.png`` / ``desktop_background_mon0_alt.png``).
    """
    fmt = config.get("background_output_format", "png")
    if fmt not in ("png", "jpg"):
        fmt = "png"
    suffix = f"_mon{monitor_index}" if monitor_index > 0 else ""
    base = f"{WALLPAPER_BASENAME}{suffix}" if cycle % 2 == 0 else f"{WALLPAPER_BASENAME}{suffix}_alt"
    return BASE_DIR / "cache" / f"{base}.{fmt}"


# ── Main loop ───────────────────────────────────────────────────


def start_background_updater():
    """Compose photos with overlays and apply them as the desktop wallpaper."""
    global paused, next_photo_requested, previous_photo_requested

    from utils.render_pipeline import (
        build_media_playlist,
        compose_background,
        ensure_font_init,
        load_main_font,
        save_surface_atomic,
        warm_up_overlays,
    )
    from utils.wallpaper_manager import get_monitors, set_wallpaper

    logger.info("🖼️ Background updater starting.")

    # Off-screen rendering only: fonts and Surfaces, never set_mode().
    ensure_font_init()

    # --- Register control signals (Linux/Pi) ---
    if all(hasattr(signal, name) for name in ("SIGUSR1", "SIGUSR2", "SIGTSTP")):
        signal.signal(signal.SIGUSR1, signal_handler_next)
        signal.signal(signal.SIGUSR2, signal_handler_previous)
        signal.signal(signal.SIGTSTP, signal_handler_pause_toggle)

    update_status_file({"paused": False})

    # The overlay data cache fetches weather/tides asynchronously; wait a
    # few seconds so the very first wallpaper already shows them.
    try:
        warm_up_overlays(load_config())
    except Exception as exc:
        logger.debug(f"Overlay warm-up skipped: {exc}")

    playlist = []
    playlist_index = -1
    first_cycle = True
    # Alternates the wallpaper file name on every render: Windows caches
    # the wallpaper by path and would ignore re-applying the same file.
    wallpaper_cycle = 0
    # Deadline at which the photo should rotate to the next one.
    photo_deadline = 0.0

    while True:
        config = load_config()
        interval = max(30, int(config.get("background_update_interval", 3600)))

        # A custom playlist file is consumed as soon as it appears; the
        # media playlist is (re)built only when empty so the rotation
        # order stays stable between cycles (no reshuffle every cycle).
        custom_playlist = load_custom_playlist()
        if custom_playlist is not None:
            playlist = custom_playlist
            playlist_index = -1
        elif not playlist:
            playlist = build_media_playlist(config)

        if not playlist:
            logger.info("🖼️ No photos found in enabled sources. "
                        "Retrying in 60 seconds.")
            _interruptible_sleep(60)
            continue

        now = time.monotonic()
        rotate_photo = now >= photo_deadline
        if first_cycle:
            playlist_index = 0
            first_cycle = False
            rotate_photo = True
        elif previous_photo_requested:
            playlist_index = (playlist_index - 1) % len(playlist)
        elif next_photo_requested or rotate_photo:
            playlist_index = (playlist_index + 1) % len(playlist)
            if playlist_index == 0:
                # Full pass completed: rebuild so new/removed photos are
                # picked up without reshuffling on every single cycle.
                playlist = build_media_playlist(config)
                playlist_index = 0
                if not playlist:
                    logger.info("No photos found in enabled sources. "
                                "Retrying in 60 seconds.")
                    _interruptible_sleep(60)
                    continue
        # else: overlay-only repaint, keep the current photo.

        if rotate_photo:
            photo_deadline = now + interval

        photo_path = playlist[playlist_index]
        main_font = load_main_font(config)
        photo_metadata = get_photo_metadata(photo_path)

        # Compute the current overlay snapshot so we can detect changes
        # during the wait loop and only re-render when something visible
        # has actually changed (clock minute, weather, etc.).
        current_overlay_text = _overlay_snapshot(config, photo_metadata)

        # Get per-monitor details so we can render a separate wallpaper
        # image for each monitor at its native resolution and DPI,
        # with the correct taskbar inset for that monitor.
        from utils.wallpaper_manager import get_monitor_details, set_wallpaper_per_monitor
        monitor_details = get_monitor_details(config)

        rendered_files = []
        all_ok = True
        for mon_idx, mon in enumerate(monitor_details):
            mon_w = mon["width"]
            mon_h = mon["height"]
            mon_inset = mon["taskbar_inset"]
            mon_id = mon["id"]

            surface = compose_background(photo_path, mon_w, mon_h, config,
                                         main_font, photo_metadata,
                                         bottom_inset=mon_inset)
            if surface is None:
                all_ok = False
                continue

            output_path = wallpaper_output_path(config, wallpaper_cycle,
                                                monitor_index=mon_idx)
            wallpaper_cycle += 1
            if save_surface_atomic(surface, output_path):
                rendered_files.append((mon_id, str(output_path)))
            else:
                all_ok = False

        if rendered_files:
            applied = set_wallpaper_per_monitor(rendered_files)
            logger.info(
                "🖼️ Wallpaper updated (%d monitor(s), photo %d/%d): %s",
                len(rendered_files), playlist_index + 1, len(playlist),
                Path(photo_path).name)
            update_status_file({
                "current_photo": str(photo_path),
                "photo_index": playlist_index + 1,
                "playlist_size": len(playlist),
                "paused": paused,
                "last_wallpaper_update": datetime.now().isoformat(),
                "monitors": get_monitors(),
                "last_error": None if applied else "set_wallpaper failed",
            })
        elif not all_ok:
            update_status_file({"last_error": "save failed"})

        # --- Wait for the next cycle, responsive to commands ---
        # Instead of a fixed timer, poll every second for overlay text
        # changes (clock minute, weather).  Only re-render when the
        # overlay text has actually changed or the photo must rotate.
        next_photo_requested = False
        previous_photo_requested = False
        while True:
            handle_commands()
            if next_photo_requested or previous_photo_requested:
                break
            now = time.monotonic()
            if not paused:
                # Check if it's time to rotate the photo.
                if now >= photo_deadline:
                    break
                # Check if the overlay text has changed (e.g. clock minute).
                config = load_config()
                new_overlay_text = _overlay_snapshot(config, photo_metadata)
                if new_overlay_text != current_overlay_text:
                    break
            else:
                # While paused, freeze the rotation deadline so
                # the current photo keeps its remaining time once resumed.
                photo_deadline = now + interval
            _interruptible_sleep(1)


def _interruptible_sleep(seconds):
    time.sleep(seconds)


def _overlay_snapshot(config, photo_metadata=None):
    """Return a lightweight string representing the current overlay state.

    This is compared between poll iterations to decide whether the wallpaper
    needs to be re-rendered.  Only elements that are visible on the wallpaper
    and can change without a config save are included (clock, date, weather,
    tides).  Photo metadata and config-driven settings are stable between
    polls, so they are omitted for efficiency.
    """
    from datetime import datetime
    parts = []
    if config.get("show_clock"):
        parts.append(datetime.now().strftime(config.get("clock_format", "%H:%M")))
        if config.get("show_date"):
            parts.append(datetime.now().strftime(config.get("date_format", "%A %d %B %Y")))
    if config.get("show_weather"):
        try:
            from local_slideshow import overlay_data
            weather, tides = overlay_data.get(config)
            if weather:
                current = (weather.get("current") or {})
                temp = current.get("main", {}).get("temp")
                icon = (current.get("weather") or [{}])[0].get("icon", "")
                parts.append(f"w:{temp}:{icon}")
        except Exception:
            pass
    if config.get("show_clock") and config.get("show_tides"):
        try:
            from local_slideshow import overlay_data
            _weather, tides = overlay_data.get(config)
            if tides:
                parts.append(f"t:{len(tides)}")
        except Exception:
            pass
    return "|".join(parts)


def _is_background_updater_pid(pid):
    """Return True when ``pid`` is a live background_updater.py process."""
    import psutil

    try:
        proc = psutil.Process(pid)
        return proc.is_running() and any(
            "background_updater.py" in part for part in proc.cmdline())
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


def main():
    import psutil

    # Single-instance guard. CAUTION: the process manager
    # (utils/slideshow_manager.py) writes our PID file right after spawning
    # us, so a live PID equal to our own means "that is us", not a second
    # instance — exiting on it would kill the updater and leave the web UI
    # reporting the process as stopped.
    try:
        with open(PID_FILE, "r") as f:
            existing_pid = int(f.read().strip())
        if existing_pid != os.getpid() and _is_background_updater_pid(existing_pid):
            logger.info(f"\U0001f5bc\ufe0f Background updater already running "
                        f"(PID {existing_pid}); not starting another")
            return
    except (FileNotFoundError, ValueError):
        pass
    except Exception as e:
        logger.debug(f"PID file check error: {e}")

    try:
        with open(PID_FILE, "w") as f:
            f.write(str(os.getpid()))
        logger.info(f"\U0001f5bc\ufe0f Background updater started (PID {os.getpid()}).")
        start_background_updater()
    except KeyboardInterrupt:
        logger.info("\U0001f5bc\ufe0f Background updater interrupted.")
    finally:
        # Only remove the PID file if we own it: when the guard above
        # returned early, the file belongs to the other live instance.
        try:
            with open(PID_FILE, "r") as f:
                pid_in_file = int(f.read().strip())
        except (FileNotFoundError, ValueError, OSError):
            pid_in_file = None
        if pid_in_file == os.getpid():
            try:
                os.remove(PID_FILE)
                logger.info("\U0001f5bc\ufe0f Background updater stopped; PID file removed.")
            except OSError:
                logger.exception("Failed to remove PID file")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.exception("Background updater failed")
        raise
