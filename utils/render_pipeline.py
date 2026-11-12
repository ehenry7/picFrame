"""Headless composition pipeline for PictureFrame's background updater.

This module is the single place where the background updater reuses the
slideshow's rendering code. It imports the proven pieces from
``local_slideshow`` (photo fitting, overlay drawing, playlist building) and
exposes a small facade:

- :func:`compose_background` — photo + overlays rendered onto an off-screen
  ``pygame.Surface`` (no display required);
- :func:`save_surface_atomic` — write a surface to disk without ever exposing
  a partially-written image;
- :func:`load_main_font` — the standard clock/metadata font.

The headless contract: nothing here calls ``pygame.display.set_mode()``.
Only ``pygame.font`` and plain ``Surface`` blits are used, so the pipeline
works on servers without any display server.
"""

import logging
import os
import time
from pathlib import Path

logger = logging.getLogger("pictureframe.render_pipeline")



# Wallpaper placement styles accepted by compose_background().
# They mirror the classic desktop wallpaper options:
DISPLAY_STYLES = ("fill", "fit", "stretch", "span", "center", "tile")

# Imported lazily-safe: importing local_slideshow only executes constant
# definitions, logger setup and an OverlayDataCache instantiation — never
# pygame.display calls. The heavy pygame display loop lives inside
# start_slideshow() which we do not call.
from local_slideshow import (  # noqa: E402  (local_slideshow is a root script)
    draw_overlay,
    build_playlist,
    get_path_to_display,
    load_filter_states,
    load_favorites,
)
from utils.slideshow_fonts import load_font
from platform_utils import get_default_font_path

# Set when the slideshow prepares its default playlist sources.
from local_slideshow import PREPARED_BASE_DIR, VIDEO_EXTENSIONS  # noqa: E402

try:
    import pygame
    PYGAME_AVAILABLE = True
except ImportError:  # pragma: no cover - pygame is a core requirement
    PYGAME_AVAILABLE = False


def ensure_font_init():
    """Initialize the minimal pygame subsystems required for off-screen rendering."""
    if not pygame.get_init():
        pygame.init()
    if not pygame.font.get_init():
        pygame.font.init()


def load_main_font(config):
    """Return the font used by draw_overlay for clock/date/metadata text."""
    font_path = config.get("clock_font_path", get_default_font_path())
    font_size = int(config.get("clock_font_size", 72))
    return load_font(font_path, font_size)


def warm_up_overlays(config, timeout=8):
    """Block briefly until the first weather/tide snapshot is ready.

    The overlay data cache fetches asynchronously: the first compose call
    would render without weather/tides. The background updater renders far
    less often than the slideshow (once per repaint cycle), so give the
    first fetch a chance to complete before the first wallpaper is drawn.
    Never raises; a timeout only means the overlay starts empty.
    """
    from local_slideshow import overlay_data

    needs_weather = bool(config.get("show_weather"))
    needs_tides = bool(config.get("show_clock") and config.get("show_tides"))
    if not (needs_weather or needs_tides):
        return

    deadline = time.monotonic() + max(0, float(timeout))
    overlay_data.get(config)
    while time.monotonic() < deadline:
        weather, tides = overlay_data.get(config)
        if (weather is not None or not needs_weather) and \
           (tides is not None or not needs_tides):
            return
        time.sleep(0.25)


def fit_photo_to_style(pil_image, width, height, style="fit"):
    """Place ``pil_image`` on a ``width × height`` canvas using a wallpaper style.

    Styles mirror the classic desktop wallpaper placement options:

    - ``fill``:    scale to cover, center-crop (no distortion, no bars)
    - ``fit``:     scale to fit, black bars on the remaining edges
    - ``stretch``: scale to exactly the canvas size (distorts aspect ratio)
    - ``span``:    like ``fill``; one image sized for all screens
    - ``center``:  original size, centered on a black canvas
    - ``tile``:    original size, repeated from the top-left corner

    Any unknown style falls back to ``fit``. Always returns an RGB image
    of exactly ``width × height`` pixels.
    """
    from PIL import Image

    image = pil_image.convert("RGB")

    if image.size == (width, height):
        return image

    if style == "stretch":
        return image.resize((width, height), Image.Resampling.LANCZOS)

    if style == "center":
        canvas = Image.new("RGB", (width, height), (0, 0, 0))
        canvas.paste(image, ((width - image.width) // 2,
                             (height - image.height) // 2))
        return canvas

    if style == "tile":
        canvas = Image.new("RGB", (width, height), (0, 0, 0))
        for x in range(0, width, image.width):
            for y in range(0, height, image.height):
                canvas.paste(image, (x, y))
        return canvas

    if style in ("fill", "span"):
        scale = max(width / image.width, height / image.height)
        scaled = image.resize((max(width, round(image.width * scale)),
                               max(height, round(image.height * scale))),
                              Image.Resampling.LANCZOS)
        left = (scaled.width - width) // 2
        top = (scaled.height - height) // 2
        return scaled.crop((left, top, left + width, top + height))

    # Default: "fit" (same placement as the slideshow).
    fitted = image.copy()
    fitted.thumbnail((width, height), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (width, height), (0, 0, 0))
    canvas.paste(fitted, ((width - fitted.width) // 2,
                          (height - fitted.height) // 2))
    return canvas


def compose_background(photo_path, width, height, config, main_font,
                       photo_metadata=None, bottom_inset=0):
    """Compose a photo with overlays onto an off-screen surface.

    Args:
        photo_path: image file to render (already prepared / filter variant).
        width: target canvas width (monitor width).
        height: target canvas height (monitor height).
        config: current configuration dictionary.
        main_font: pygame font for overlay text.
        photo_metadata: optional metadata dict (as from
            ``utils.metadata_utils.get_photo_metadata``) for the metadata
            overlay.
        bottom_inset: pixels to reserve at the bottom (e.g. Windows taskbar)
            so overlays are not hidden behind it.

    Returns:
        A ``pygame.Surface`` of exactly ``width × height`` pixels, or ``None``
        when the photo cannot be read.
    """
    from PIL import Image

    try:
        with Image.open(photo_path) as image:
            style = config.get("background_display_style", "fit")
            if style not in DISPLAY_STYLES:
                style = "fit"
            pil_image = fit_photo_to_style(image, width, height, style)
    except Exception as exc:
        logger.error("Cannot read photo %s: %s", photo_path, exc)
        return None

    surface = pygame.image.fromstring(
        pil_image.tobytes(), pil_image.size, pil_image.mode)
    draw_overlay(surface, width, height, config, main_font, photo_metadata,
                 bottom_inset=bottom_inset)
    return surface


def save_surface_atomic(surface, output_path):
    """Write ``surface`` to ``output_path`` without exposing partial files.

    Writes to a temporary file in the same directory first, then atomically
    replaces the destination (``os.replace``), so the OS wallpaper APIs never
    read a half-written image.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Keep the real extension on the temp file: pygame.image.save picks its
    # encoder from the extension, and an unknown suffix falls back to BMP.
    tmp_path = output_path.with_name(
        f"{output_path.stem}.tmp{output_path.suffix or '.png'}")
    try:
        pygame.image.save(surface, str(tmp_path))
        os.replace(tmp_path, output_path)
        return True
    except Exception as exc:
        logger.error("Failed to save %s: %s", output_path, exc)
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def build_media_playlist(config):
    """Build the photo playlist for the background updater.

    Mirrors the slideshow's default playlist: scan every configured source in
    ``static/prepared/``, apply per-photo filter variants, expand favorites /
    anniversary boosts, then shuffle.

    Returns:
        A shuffled list of photo paths (videos already replaced by their
        prepared thumbnails).
    """
    import random

    from utils.metadata_utils import get_photo_metadata  # noqa: F401 (re-export use)

    filter_states = load_filter_states()
    favorites = load_favorites()
    display_sources = config.get("display_sources", ["usb", "smartphone", "guests"])

    all_media = []
    for source in display_sources:
        source_dir = PREPARED_BASE_DIR / source
        if not source_dir.is_dir():
            continue
        for entry in sorted(source_dir.iterdir()):
            if not entry.is_file():
                continue
            suffix = entry.suffix.lower()
            if suffix in VIDEO_EXTENSIONS:
                # A video cannot be a wallpaper: use its prepared thumbnail.
                thumbnail = entry.with_name(f"{entry.stem}_thumbnail.jpg")
                if thumbnail.exists():
                    all_media.append(str(thumbnail))
                continue
            if suffix not in (".jpg", ".jpeg", ".png"):
                continue
            if entry.name.endswith(("_polaroid.jpg", "_postcard.jpg")):
                continue
            all_media.append(get_path_to_display(entry, source, filter_states))

    playlist = build_playlist(all_media, config, favorites)
    random.shuffle(playlist)
    return playlist


def collect_video_thumbnail(video_path):
    """Return the prepared thumbnail path for a video, or None."""
    entry = Path(video_path)
    thumbnail = entry.with_name(f"{entry.stem}_thumbnail.jpg")
    return str(thumbnail) if thumbnail.exists() else None
