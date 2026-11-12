"""Run-mode resolution for PictureFrame.

PictureFrame supports two top-level run modes:

- ``picture_frame``     — the original behaviour: a fullscreen Pygame slideshow
  (``local_slideshow.py``) driven by the active-hours scheduler. This is the
  default and the Raspberry Pi kiosk target.
- ``background_updater`` — a headless process (``background_updater.py``) that
  composes a photo with the standard overlays (clock, date, weather, tides,
  photo metadata) into a single image file and sets it as the desktop
  wallpaper on all monitors (Windows/Linux desktops).

The effective mode is resolved from, in order of precedence:

1. the ``PICTUREFRAME_APP_MODE`` environment variable (for headless boot
   overrides and testing),
2. the ``app_mode`` key in ``config/config.json``,
3. the default, ``picture_frame``.

Invalid values never raise: they log a warning and fall back to the default,
following the project's graceful-degradation convention.
"""

import logging
import os

logger = logging.getLogger("pictureframe.app_mode")

VALID_APP_MODES = ("picture_frame", "background_updater")

ENV_APP_MODE = "PICTUREFRAME_APP_MODE"

DEFAULT_APP_MODE = "picture_frame"


def get_app_mode(config=None) -> str:
    """Return the effective run mode.

    Args:
        config: optional already-loaded configuration dictionary. When omitted
            or when its ``app_mode`` value is invalid, only the environment
            variable and the default are considered.

    Returns:
        One of ``VALID_APP_MODES`` (currently ``"picture_frame"`` or
        ``"background_updater"``).
    """
    env = os.environ.get(ENV_APP_MODE, "").strip().lower()
    if env in VALID_APP_MODES:
        return env
    if env:
        logger.warning("Invalid %s value %r; ignoring it", ENV_APP_MODE, env)

    mode = config.get("app_mode") if config else None
    if isinstance(mode, str):
        mode = mode.strip().lower()
        if mode in VALID_APP_MODES:
            return mode
        if mode:
            logger.warning("Invalid app_mode in config: %r; using %r",
                           mode, DEFAULT_APP_MODE)
    return DEFAULT_APP_MODE
