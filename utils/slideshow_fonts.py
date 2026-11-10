"""Cache slideshow fonts and remember unavailable custom font paths."""

import logging

import pygame


logger = logging.getLogger(__name__)
_fonts = {}
_unavailable_paths = set()


def clear_font_cache():
    """Discard font objects after Pygame reinitialization, keeping failed paths."""
    _fonts.clear()


def load_font(path, size):
    key = (path, size)
    if key not in _fonts:
        font = None
        if path not in _unavailable_paths:
            try:
                font = pygame.font.Font(path, size)
            except (OSError, pygame.error) as error:
                _unavailable_paths.add(path)
                logger.warning("Cannot load font %r: %s. Using a system font for this session.",
                               path, error)
        if font is None:
            font = pygame.font.SysFont("Arial", size)
        _fonts[key] = font
    return _fonts[key]
