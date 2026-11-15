"""System tray icon for PictureFrame background updater mode.

Provides a minimal system tray icon with menu items for:
- Opening the web settings UI in a browser
- Next / Previous / Pause-Resume photo controls
- Exiting the application

Works on Windows (Win32 tray) and Linux (AppIndicator/GTK).
Requires ``pystray`` and ``Pillow``.
"""

import logging
import os
import subprocess
import threading
import webbrowser
from pathlib import Path

logger = logging.getLogger("pictureframe.tray")

BASE_DIR = Path(__file__).resolve().parent.parent
APP_URL = "http://127.0.0.1:7090"
LOGO_PATH = BASE_DIR / "static" / "pictureframe_logo.svg"
FAVICON_PATH = BASE_DIR / "static" / "favicon.ico"

# API endpoints (no login required for slideshow controls).
API_NEXT = f"{APP_URL}/api/slideshow/next"
API_PREVIOUS = f"{APP_URL}/api/slideshow/previous"
API_PAUSE = f"{APP_URL}/api/slideshow/toggle_pause"


def _send_command(command):
    """Write a command directly to the background updater's command queue.

    Uses the shared enqueue_slideshow_command from platform_utils so
    the queue path and format match what background_updater.py consumes.
    """
    try:
        from platform_utils import enqueue_slideshow_command
        enqueue_slideshow_command(command, process="background")
        logger.debug("Command '%s' enqueued for background", command)
    except Exception as exc:
        logger.warning("Failed to send command '%s': %s", command, exc)
        # Fallback: try the Flask API.
        _post_api(f"{APP_URL}/api/slideshow/{command}")


def _post_api(url):
    """Send a POST to an API endpoint; ignore errors (server may be starting)."""
    try:
        import urllib.request
        req = urllib.request.Request(url, method="POST")
        urllib.request.urlopen(req, timeout=5)
        logger.debug("API POST %s OK", url)
    except Exception as exc:
        logger.debug("API POST %s failed: %s", url, exc)


def _open_settings(icon, item):
    """Open the web UI in the default browser."""
    webbrowser.open(APP_URL)


def _next_photo(icon, item):
    _send_command("next")


def _previous_photo(icon, item):
    _send_command("previous")


def _toggle_pause(icon, item):
    _send_command("toggle_pause")


def _exit_app(icon, item):
    """Stop the tray icon and signal the main process to exit."""
    logger.info("Tray: exit requested")
    icon.stop()
    # The background_updater main loop checks a flag set via the tray.
    if hasattr(icon, '_exit_callback') and icon._exit_callback:
        icon._exit_callback()


def _create_icon_image():
    """Create a small PIL image for the tray icon."""
    from PIL import Image, ImageDraw

    # Try to load the favicon.ico first (best quality on Windows).
    if FAVICON_PATH.exists():
        try:
            return Image.open(str(FAVICON_PATH))
        except Exception:
            pass

    # Fallback: draw a simple camera-like icon.
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Blue rounded rectangle background.
    draw.rounded_rectangle([4, 8, 60, 56], radius=8, fill=(37, 99, 235, 255))
    # Camera body (white).
    draw.rounded_rectangle([14, 20, 50, 48], radius=4, fill=(255, 255, 255, 255))
    # Lens circle.
    draw.ellipse([22, 26, 42, 46], fill=(37, 99, 235, 255))
    draw.ellipse([26, 30, 38, 42], fill=(255, 255, 255, 255))
    # Flash bump.
    draw.rectangle([26, 16, 34, 20], fill=(255, 255, 255, 255))
    return img


def start_tray_icon(exit_callback=None):
    """Create and run the system tray icon in a daemon thread.

    Args:
        exit_callback: function called when the user clicks "Exit" in the
            tray menu.  The background updater uses this to break its main
            loop and shut down cleanly.

    Returns:
        The ``pystray.Icon`` instance, or ``None`` if pystray is unavailable.
    """
    try:
        import pystray
    except ImportError:
        logger.warning("pystray not available — tray icon disabled")
        return None

    image = _create_icon_image()

    menu = pystray.Menu(
        pystray.MenuItem("Open Settings", _open_settings, default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Next Photo", _next_photo),
        pystray.MenuItem("Previous Photo", _previous_photo),
        pystray.MenuItem("Pause / Resume", _toggle_pause),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Exit", _exit_app),
    )

    icon = pystray.Icon("PictureFrame", image, "PictureFrame", menu)
    icon._exit_callback = exit_callback

    def _run():
        try:
            icon.run()
        except Exception as exc:
            logger.warning("Tray icon stopped: %s", exc)

    thread = threading.Thread(target=_run, name="tray-icon", daemon=True)
    thread.start()
    logger.info("System tray icon started")
    return icon
