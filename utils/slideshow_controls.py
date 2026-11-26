"""Transient on-screen slideshow controls (touch friendly).

Dark, matte circular buttons with black media glyphs, rendered once with
Pillow at 4x and cached as pygame surfaces.
"""

import time
from pathlib import Path

import pygame

VISIBLE_SECONDS = 8.0
_visible_until = 0.0

_ip_cache = {"ip": None, "at": 0.0}
_button_cache = {}
_ICON_DIR = Path(__file__).resolve().parent.parent / "static" / "icons"
_shadow_cache = {}
_NATIVE_SIZE = None
SQUASH_Y = 0.8  # buttons are 20% shorter on the Y axis


def reveal():
    global _visible_until
    _visible_until = time.monotonic() + VISIBLE_SECONDS


def visible():
    import os
    if os.environ.get("PICTUREFRAME_CONTROLS_ALWAYS") == "1":
        return True
    return time.monotonic() < _visible_until


def local_ip() -> str:
    """Best-effort LAN IP so the address can be shown on screen."""
    now = time.monotonic()
    cached = _ip_cache.get("ip")
    if cached and now - _ip_cache.get("at", 0) < 60:
        return cached
    ip = "127.0.0.1"
    try:
        import socket

        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("8.8.8.8", 80))
            ip = probe.getsockname()[0]
        finally:
            probe.close()
    except OSError:
        pass
    _ip_cache["ip"] = ip
    _ip_cache["at"] = now
    return ip


def _native_icon_size():
    """Native pixel size of the extracted icons (largest side)."""
    global _NATIVE_SIZE
    if _NATIVE_SIZE:
        return _NATIVE_SIZE
    path = _ICON_DIR / "control_pause.png"
    if path.exists():
        image = pygame.image.load(str(path))
        _NATIVE_SIZE = max(image.get_size())
    else:
        _NATIVE_SIZE = 130
    return _NATIVE_SIZE


def buttons(width, height):
    size = _native_icon_size()
    gap = max(4, int(size * 0.03))
    if 3 * size + 2 * gap > width * 0.92:
        size = int((width * 0.92 - 2 * gap) / 3)
        gap = max(4, int(size * 0.03))
    if size > height * 0.42:
        size = int(height * 0.42)
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


def _glyph(draw, action, paused, centre, icon, colour):
    """Black media glyph: double triangles for skip, bars for pause."""
    cx, cy = centre
    half_height = icon * 0.95

    if action == "pause" and not paused:
        bar_w = icon * 0.34
        gap = icon * 0.40
        radius = bar_w * 0.45
        for offset in (-gap - bar_w / 2, gap - bar_w / 2):
            draw.rounded_rectangle((cx + offset, cy - half_height,
                                    cx + offset + bar_w, cy + half_height),
                                   radius=radius, fill=colour)
        return

    if action == "pause":
        draw.polygon([(cx - icon * 0.62, cy - half_height),
                      (cx - icon * 0.62, cy + half_height),
                      (cx + icon * 0.95, cy)], fill=colour)
        return

    direction = -1 if action == "previous" else 1
    width = icon * 1.32
    gap = icon * 0.62
    half_span = (width + gap) / 2
    for step in (0, 1):
        base = cx + direction * (half_span - step * gap)
        draw.polygon([(base - direction * width, cy - half_height),
                      (base - direction * width, cy + half_height),
                      (base, cy)], fill=colour)


def _shadow_for(surface):
    """Blurred, offset silhouette of the icon itself (matches its shape)."""
    size = surface.get_width()
    width, height = surface.get_size()
    key = ("shadow", size, width, height)
    cached = _shadow_cache.get(key)
    if cached is not None:
        return cached

    margin = max(4, int(max(width, height) * 0.12))
    silhouette = pygame.Surface((width, height), pygame.SRCALPHA)
    silhouette.blit(surface, (0, 0))
    silhouette.fill((0, 0, 0, 255), special_flags=pygame.BLEND_RGBA_MULT)

    # Cheap blur: shrink then grow back.
    small_w = max(1, width // 6)
    small_h = max(1, height // 6)
    soft = pygame.transform.smoothscale(
        pygame.transform.smoothscale(silhouette, (small_w, small_h)), (width, height))
    soft.fill((255, 255, 255, 150), special_flags=pygame.BLEND_RGBA_MULT)

    total = (width + margin * 2, height + margin * 2)
    shadow = pygame.Surface(total, pygame.SRCALPHA)
    shift = max(2, int(size * 0.06))
    shadow.blit(soft, (margin + shift, margin + shift))

    _shadow_cache[key] = (shadow, margin)
    return _shadow_cache[key]


def _asset_surface(size, action, paused):
    """Return the PNG button (control_<name>.png); reloads if the file changes."""
    name = "play" if (action == "pause" and paused) else action
    path = _ICON_DIR / f"control_{name}.png"
    if not path.exists():
        return None
    try:
        stamp = path.stat().st_mtime
    except OSError:
        stamp = 0
    cached = _button_cache.get(("asset", name))
    if cached and cached[0] == stamp and cached[1] == size:
        return cached[2]
    image = pygame.image.load(str(path))
    try:
        image = image.convert_alpha()
    except Exception:
        pass  # no video mode yet; the PNG already carries alpha
    surface = image
    if max(image.get_size()) > size:  # only ever shrink, never upscale
        ratio = size / max(image.get_size())
        surface = pygame.transform.smoothscale(
            image, (max(1, int(image.get_width() * ratio)),
                    max(1, int(image.get_height() * ratio))))

    # User-tuned aspect: 25% shorter on the Y axis.
    target_height = max(1, int(surface.get_height() * SQUASH_Y))
    surface = pygame.transform.smoothscale(surface, (surface.get_width(), target_height))

    _button_cache[("asset", name)] = (stamp, size, surface)
    return surface


def _button_surface(size, action, paused):
    """Build (and cache) one dark matte button surface at ``size`` pixels."""
    key = (size, action, paused)
    cached = _button_cache.get(key)
    if cached is not None:
        return cached

    from PIL import Image, ImageDraw, ImageFilter, ImageOps

    scale = 4
    work = size * scale
    image = Image.new("RGBA", (work, work), (0, 0, 0, 0))
    centre = work / 2
    pad = work * 0.05
    radius = centre - pad

    # --- Soft shadow, offset to the bottom right ---------------------------
    shadow = Image.new("RGBA", (work, work), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).ellipse(
        (pad + work * 0.03, pad + work * 0.055, work - pad + work * 0.03, work - pad + work * 0.055),
        fill=(0, 0, 0, 130))
    image.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(work * 0.03)))

    # --- Matte slate disc with a diagonal gradient ------------------------
    gradient = ImageOps.invert(Image.linear_gradient("L").resize((work, work)))
    gradient = gradient.rotate(-45, resample=Image.BICUBIC)
    disc = ImageOps.colorize(gradient, black=(36, 39, 48), white=(78, 83, 96))
    mask = Image.new("L", (work, work), 0)
    ImageDraw.Draw(mask).ellipse((centre - radius, centre - radius,
                                  centre + radius, centre + radius), fill=255)
    image.paste(disc, (0, 0), mask)

    # --- Bevel: light top-left edge, dark bottom-right ---------------------
    bevel = Image.new("RGBA", (work, work), (0, 0, 0, 0))
    bevel_draw = ImageDraw.Draw(bevel)
    box = (centre - radius, centre - radius, centre + radius, centre + radius)
    bevel_draw.arc(box, start=150, end=305, fill=(255, 255, 255, 60),
                   width=max(2, int(work * 0.010)))
    bevel_draw.arc(box, start=330, end=120, fill=(0, 0, 0, 120),
                   width=max(2, int(work * 0.010)))
    image.alpha_composite(bevel.filter(ImageFilter.GaussianBlur(work * 0.006)))

    # --- Inner bevel ring (stepped edge like the reference) ---------------
    ring = Image.new("RGBA", (work, work), (0, 0, 0, 0))
    ring_draw = ImageDraw.Draw(ring)
    ring_radius = radius * 0.90
    ring_draw.ellipse((centre - ring_radius, centre - ring_radius,
                       centre + ring_radius, centre + ring_radius),
                      outline=(255, 255, 255, 34), width=max(2, int(work * 0.008)))
    ring_draw.ellipse((centre - ring_radius * 0.985, centre - ring_radius * 0.985,
                       centre + ring_radius * 0.985, centre + ring_radius * 0.985),
                      outline=(0, 0, 0, 45), width=max(1, int(work * 0.003)))
    image.alpha_composite(ring.filter(ImageFilter.GaussianBlur(work * 0.004)))

    # --- Very subtle sheen in the upper left ------------------------------
    sheen = Image.new("RGBA", (work, work), (0, 0, 0, 0))
    ImageDraw.Draw(sheen).ellipse(
        (centre - radius * 0.85, centre - radius * 0.95,
         centre + radius * 0.25, centre - radius * 0.05),
        fill=(255, 255, 255, 22))
    image.alpha_composite(Image.composite(
        sheen.filter(ImageFilter.GaussianBlur(work * 0.05)),
        Image.new("RGBA", (work, work), (0, 0, 0, 0)), mask))

    # --- Glyph ------------------------------------------------------------
    glyph_layer = Image.new("RGBA", (work, work), (0, 0, 0, 0))
    _glyph(ImageDraw.Draw(glyph_layer), action, paused, (centre, centre),
           work * 0.16, (14, 16, 20, 255))
    image.alpha_composite(glyph_layer)

    small = image.resize((size, size), Image.LANCZOS)
    surface = pygame.image.fromstring(small.tobytes(), (size, size), "RGBA").convert_alpha()
    _button_cache[key] = surface
    return surface


def draw(screen, width, height, paused):
    if not visible():
        return
    rects = buttons(width, height)
    for action, rect in rects.items():
        size = min(rect.width, rect.height)
        try:
            surface = _asset_surface(size, action, paused)
            if surface is None:
                surface = _button_surface(size, action, paused)
        except Exception:
            surface = None

        if surface is None:
            pygame.draw.circle(screen, (42, 45, 54), rect.center, size // 2)
            continue

        icon_w, icon_h = surface.get_size()
        icon_x = rect.centerx - icon_w // 2
        icon_y = rect.centery - icon_h // 2

        try:
            shadow, margin = _shadow_for(surface)
            screen.blit(shadow, (icon_x - margin, icon_y - margin))
        except Exception:
            pass

        screen.blit(surface, (icon_x, icon_y))

    # Address badge, shown together with the controls.
    try:
        label_size = max(20, min(34, rects["pause"].width // 4))
        font = pygame.font.SysFont("DejaVu Sans", label_size)
        text = font.render(f"http://{local_ip()}", True, (255, 255, 255))
        padding = max(8, label_size // 2)
        box = text.get_rect()
        box.inflate_ip(padding * 2, padding)
        top_row = min(rect.top for rect in rects.values())
        box.midbottom = (width // 2, top_row - 16)
        surface = pygame.Surface(box.size, pygame.SRCALPHA)
        pygame.draw.rect(surface, (0, 0, 0, 170), surface.get_rect(),
                         border_radius=max(8, padding))
        screen.blit(surface, box.topleft)
        screen.blit(text, text.get_rect(center=box.center))
    except Exception:
        pass
