"""Transient on-screen slideshow controls."""

import time
import pygame

VISIBLE_SECONDS = 5.0
_visible_until = 0.0


def reveal():
    global _visible_until
    _visible_until = time.monotonic() + VISIBLE_SECONDS


def visible():
    return time.monotonic() < _visible_until


def buttons(width, height):
    size = max(30, min(56, width // 7, height // 5))
    gap = max(8, size // 4)
    left = (width - 3 * size - 2 * gap) // 2
    top = max(0, height - size - 24)
    return {action: pygame.Rect(left + index * (size + gap), top, size, size)
            for index, action in enumerate(("previous", "pause", "next"))}


def click(position, width, height):
    was_visible = visible()
    reveal()
    if was_visible:
        return next((action for action, rect in buttons(width, height).items()
                     if rect.collidepoint(position)), None)
    return None


def draw(screen, width, height, paused):
    if not visible():
        return
    for action, rect in buttons(width, height).items():
        pygame.draw.rect(screen, (35, 35, 35), rect, border_radius=8)
        cx, cy = rect.center
        radius = max(5, rect.width // 5)
        if action == "pause" and not paused:
            for offset in (-radius, radius // 3):
                pygame.draw.rect(screen, "white", (cx + offset, cy - radius, max(2, radius // 2), 2 * radius))
        else:
            direction = -1 if action == "previous" else 1
            pygame.draw.polygon(screen, "white", [
                (cx - direction * radius, cy - radius),
                (cx - direction * radius, cy + radius),
                (cx + direction * radius, cy)])
            if action != "pause":
                x = cx + direction * (radius + 2)
                pygame.draw.line(screen, "white", (x, cy - radius), (x, cy + radius), 3)
