"""Decorative frame styles rendered on top of prepared photos.

Frames are non-destructive variants (like Polaroid/Postcard): the base
prepared photo stays untouched and every style is rendered into
``<stem>_<style>.jpg`` next to it.  ``filter_states.json`` stores which
variant is active for a photo.

All styles render to a full canvas of the requested size so the slideshow
can display them exactly like the base photo.
"""
from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FONTS_DIR = PROJECT_ROOT / "static" / "fonts"
BACKGROUNDS_DIR = PROJECT_ROOT / "static" / "backgrounds"

_FONT_CANDIDATES = {
    "hand": ["Caveat-Regular.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
    "sans": ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "DejaVuSans.ttf"],
    "sans_bold": ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "DejaVuSans-Bold.ttf"],
    "serif": ["/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf", "DejaVuSerif.ttf"],
    "mono": ["/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", "DejaVuSansMono.ttf"],
}

#: style id -> human label (used by the settings UI)
FRAME_STYLES: dict[str, str] = {
    "cork": "Cork board",
    "filmstrip": "Film strip",
    "slide": "35 mm slide",
    "mat": "Museum mat",
    "album": "Album corners",
    "torn": "Torn paper",
    "newspaper": "Newspaper clip",
    "datestamp": "Retro date stamp",
    "washi": "Washi tape",
    "gilded": "Gilded frame",
    "instax": "Instax mini",
    "lomo": "Lomo / toy camera",
}

#: corrections are baked into the prepared file instead of being variants
CORRECTION_FILTERS = {"grayscale", "sepia", "vignette", "vintage"}


def _font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    for name in _FONT_CANDIDATES.get(kind, _FONT_CANDIDATES["sans"]):
        for candidate in (FONTS_DIR / name, Path(name)):
            try:
                if candidate.exists():
                    return ImageFont.truetype(str(candidate), size)
            except OSError:
                continue
    return ImageFont.load_default()


def _fit(img: Image.Image, box_w: int, box_h: int) -> Image.Image:
    copy = img.copy()
    copy.thumbnail((box_w, box_h), Image.LANCZOS)
    return copy


def _shadow(img: Image.Image, blur: int = 18, offset: tuple[int, int] = (10, 14),
            opacity: int = 120) -> Image.Image:
    canvas = Image.new("RGBA", (img.width + abs(offset[0]) + blur * 2,
                                 img.height + abs(offset[1]) + blur * 2), (0, 0, 0, 0))
    alpha = img.split()[-1] if img.mode == "RGBA" else Image.new("L", img.size, 255)
    shade = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    black = Image.new("RGBA", img.size, (0, 0, 0, opacity))
    shade.paste(black, (offset[0] + blur, offset[1] + blur), alpha)
    return shade.filter(ImageFilter.GaussianBlur(blur))


def _paste_with_shadow(canvas: Image.Image, photo: Image.Image, xy: tuple[int, int],
                       shadow: tuple[int, int] = (12, 16), blur: int = 16,
                       opacity: int = 130) -> None:
    shade = _shadow(photo, blur=blur, offset=shadow, opacity=opacity)
    canvas.alpha_composite(shade, (xy[0] + shadow[0] - blur, xy[1] + shadow[1] - blur))
    canvas.alpha_composite(photo, xy)


def _paper(size: tuple[int, int], color: tuple[int, int, int],
           noise: int = 6) -> Image.Image:
    base = Image.new("RGB", size, color)
    if noise:
        rnd = random.Random(7)
        px = base.load()
        for _ in range(size[0] * size[1] // 40):
            x = rnd.randrange(size[0])
            y = rnd.randrange(size[1])
            d = rnd.randint(-noise, noise)
            r, g, b = px[x, y]
            px[x, y] = (max(0, min(255, r + d)), max(0, min(255, g + d)),
                        max(0, min(255, b + d)))
    return base


def _vignette(img: Image.Image, strength: float = 0.6) -> Image.Image:
    w, h = img.size
    mask = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((-w * 0.25, -h * 0.25, w * 1.25, h * 1.25), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(max(w, h) // 10))
    dark = ImageEnhance.Brightness(img).enhance(1 - strength)
    return Image.composite(img, dark, mask)


def _rounded(img: Image.Image, radius: int) -> Image.Image:
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, img.width - 1, img.height - 1),
                                           radius=radius, fill=255)
    out = img.convert("RGBA")
    out.putalpha(mask)
    return out


# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------

def _style_cork(photo: Image.Image, w: int, h: int, caption: str, date_text: str) -> Image.Image:
    canvas = Image.new("RGBA", (w, h), (198, 160, 112, 255))
    cork = BACKGROUNDS_DIR / "cork_background.jpg"
    if cork.exists():
        try:
            canvas.alpha_composite(Image.open(cork).convert("RGBA").resize((w, h), Image.LANCZOS))
        except OSError:
            pass
    else:
        canvas = Image.new("RGBA", (w, h), (196, 156, 106, 255))
    photo = _rotate_expand(_fit(photo, int(w * 0.62), int(h * 0.7)).convert("RGBA"), -2.2)
    x = (w - photo.width) // 2
    y = (h - photo.height) // 2 + 20
    _paste_with_shadow(canvas, photo, (x, y), shadow=(8, 12), blur=14, opacity=150)
    # Push pin.
    pin_x, pin_y = w // 2, y + 14
    draw = ImageDraw.Draw(canvas)
    draw.ellipse((pin_x - 16, pin_y - 16 + 6, pin_x + 16, pin_y + 16 + 6), fill=(0, 0, 0, 90))
    draw.ellipse((pin_x - 15, pin_y - 15, pin_x + 15, pin_y + 15), fill=(190, 40, 40, 255))
    draw.ellipse((pin_x - 9, pin_y - 9, pin_x + 2, pin_y + 2), fill=(230, 90, 90, 255))
    if caption:
        font = _font("hand", 46)
        draw.text((w // 2, h - 48), caption, font=font, fill=(60, 35, 20, 255), anchor="mm")
    return canvas


def _style_filmstrip(photo: Image.Image, w: int, h: int, caption: str, date_text: str) -> Image.Image:
    canvas = Image.new("RGBA", (w, h), (18, 18, 20, 255))
    window_h = int(h * 0.68)
    photo = _fit(photo, int(w * 0.82), window_h).convert("RGBA")
    x = (w - photo.width) // 2
    y = (h - photo.height) // 2
    canvas.alpha_composite(photo, (x, y))
    draw = ImageDraw.Draw(canvas)
    hole_w, hole_h, gap = 34, 24, 26
    for row_y in (y - 34, y + photo.height + 10):
        for hx in range(24, w - hole_w, gap + hole_w):
            draw.rounded_rectangle((hx, row_y, hx + hole_w, row_y + hole_h),
                                   radius=6, fill=(235, 235, 230, 255))
    label = caption or (date_text or "")
    if label:
        font = _font("mono", 30)
        draw.text((x + photo.width - 12, y + photo.height + 44), label,
                  font=font, fill=(255, 190, 60, 255), anchor="ra")
    return canvas


def _style_slide(photo: Image.Image, w: int, h: int, caption: str, date_text: str) -> Image.Image:
    canvas = Image.new("RGBA", (w, h), (240, 238, 232, 255))
    window_w, window_h = int(w * 0.7), int(h * 0.72)
    inner = _fit(photo, window_w, window_h)
    inner = ImageEnhance.Color(inner).enhance(1.08).convert("RGBA")
    inner = _rounded(inner, 16)
    x = (w - inner.width) // 2
    y = (h - inner.height) // 2 - 10
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((x - 8, y - 8, x + inner.width + 8, y + inner.height + 8),
                           radius=20, fill=(214, 212, 205, 255))
    canvas.alpha_composite(inner, (x, y))
    stamp = caption or date_text or ""
    draw.text((x + 4, y + inner.height + 22), stamp, font=_font("mono", 30),
              fill=(90, 90, 90, 255))
    draw.text((x + inner.width - 4, y - 34), "KODAK 64", font=_font("mono", 24),
              fill=(120, 120, 120, 255), anchor="ra")
    return canvas


def _style_mat(photo: Image.Image, w: int, h: int, caption: str, date_text: str) -> Image.Image:
    canvas = _paper((w, h), (246, 243, 236), noise=3).convert("RGBA")
    photo = _fit(photo, int(w * 0.6), int(h * 0.62)).convert("RGBA")
    x = (w - photo.width) // 2
    y = int(h * 0.14)
    canvas.alpha_composite(photo, (x, y))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((x - 10, y - 10, x + photo.width + 10, y + photo.height + 10),
                   outline=(180, 172, 158, 255), width=2)
    draw.text((w // 2, y + photo.height + 46),
              caption or date_text or "", font=_font("serif", 34),
              fill=(90, 86, 78, 255), anchor="ma")
    return canvas


def _style_album(photo: Image.Image, w: int, h: int, caption: str, date_text: str) -> Image.Image:
    canvas = _paper((w, h), (44, 44, 48), noise=4).convert("RGBA")
    photo = _rotate_expand(_fit(photo, int(w * 0.6), int(h * 0.66)).convert("RGBA"), 1.8)
    x = (w - photo.width) // 2
    y = (h - photo.height) // 2
    canvas.alpha_composite(_shadow(photo, blur=16, offset=(8, 10), opacity=160),
                           (x + 8 - 16, y + 10 - 16))
    canvas.alpha_composite(photo, (x, y))
    draw = ImageDraw.Draw(canvas)
    size = 54
    for cx, cy, sx, sy in ((x, y, 1, 1), (x + photo.width, y, -1, 1),
                           (x, y + photo.height, 1, -1),
                           (x + photo.width, y + photo.height, -1, -1)):
        draw.polygon([(cx, cy), (cx + sx * size, cy), (cx, cy + sy * size)],
                     fill=(20, 20, 22, 220))
    draw.text((w // 2, h - 46), caption or date_text or "", font=_font("hand", 44),
              fill=(220, 210, 190, 255), anchor="mm")
    return canvas


def _style_torn(photo: Image.Image, w: int, h: int, caption: str, date_text: str) -> Image.Image:
    canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    paper = _paper((w, h), (250, 246, 236), noise=5).convert("RGBA")
    photo = _fit(photo, int(w * 0.72), int(h * 0.72)).convert("RGBA")
    x = (w - photo.width) // 2
    y = (h - photo.height) // 2
    paper.alpha_composite(photo, (x, y))
    mask = Image.new("L", (w, h), 255)
    md = ImageDraw.Draw(mask)
    rnd = random.Random(3)
    depth = 16
    step = 10
    # Left and right edges.
    left = [(0, 0)] + [(rnd.randint(0, depth), y) for y in range(0, h, step)] + [(0, h)]
    right = [(w - 1, 0)] + [(w - 1 - rnd.randint(0, depth), y) for y in range(0, h, step)] + [(w - 1, h - 1)]
    top = [(0, 0)] + [(x, rnd.randint(0, depth)) for x in range(0, w, step)] + [(w - 1, 0)]
    bottom = [(0, h - 1)] + [(x, h - 1 - rnd.randint(0, depth)) for x in range(0, w, step)] + [(w - 1, h - 1)]
    for poly in (left, right, top, bottom):
        md.polygon(poly, fill=0)
    mask = mask.filter(ImageFilter.GaussianBlur(1.2))
    paper.putalpha(mask)
    canvas.alpha_composite(_shadow(paper, blur=20, offset=(0, 16), opacity=110), (0, 0))
    canvas.alpha_composite(paper, (0, 0))
    if caption:
        draw = ImageDraw.Draw(canvas)
        draw.text((w // 2, min(h - 40, y + photo.height + 34)), caption,
                  font=_font("serif", 32), fill=(70, 66, 58, 255), anchor="mm")
    return canvas


def _style_newspaper(photo: Image.Image, w: int, h: int, caption: str, date_text: str) -> Image.Image:
    base = photo.convert("RGB")
    base = Image.composite(base.convert("L"), base, Image.new("L", base.size, 110))
    base = ImageEnhance.Contrast(base).enhance(1.1).convert("RGBA")
    paper = _paper((int(h * 0.74), h), (245, 240, 226), noise=9).convert("RGBA")
    photo = _rotate_expand(_fit(base, paper.width - 72, paper.height - 170).convert("RGBA"), -1.2)
    paper.alpha_composite(photo, ((paper.width - photo.width) // 2, 70))
    draw = ImageDraw.Draw(paper)
    draw.text((48, 22), caption or "THE DAILY FRAME", font=_font("serif", 40), fill=(30, 30, 30, 255))
    draw.line((48, 64, paper.width - 48, 64), fill=(60, 60, 60, 255), width=3)
    draw.text((48, paper.height - 46), date_text or "", font=_font("serif", 24), fill=(80, 80, 80, 255))
    canvas = Image.new("RGBA", (w, h), (26, 24, 22, 255))
    canvas.alpha_composite(_shadow(paper, blur=18, offset=(0, 12), opacity=160),
                           ((w - paper.width) // 2, (h - paper.height) // 2 + 12))
    canvas.alpha_composite(paper, ((w - paper.width) // 2, (h - paper.height) // 2))
    return canvas


def _style_datestamp(photo: Image.Image, w: int, h: int, caption: str, date_text: str) -> Image.Image:
    canvas = Image.new("RGBA", (w, h), (0, 0, 0, 255))
    photo = _fit(photo, w, h).convert("RGBA")
    canvas.alpha_composite(photo, ((w - photo.width) // 2, (h - photo.height) // 2))
    draw = ImageDraw.Draw(canvas)
    text = date_text or ""
    if text:
        font = _font("mono", 44)
        x, y = w - 60, h - 70
        glow = (255, 120, 0, 120)
        for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
            draw.text((x + dx, y + dy), text, font=font, fill=glow, anchor="ra")
        draw.text((x, y), text, font=font, fill=(255, 150, 0, 255), anchor="ra")
    return canvas


def _style_washi(photo: Image.Image, w: int, h: int, caption: str, date_text: str) -> Image.Image:
    canvas = _paper((w, h), (252, 250, 246), noise=3).convert("RGBA")
    photo = _rotate_expand(_fit(photo, int(w * 0.6), int(h * 0.66)).convert("RGBA"), 2.4)
    x = (w - photo.width) // 2
    y = (h - photo.height) // 2
    _paste_with_shadow(canvas, photo, (x, y), shadow=(6, 10), blur=12, opacity=110)
    tape = Image.new("RGBA", (260, 70), (250, 240, 200, 150))
    strip = ImageDraw.Draw(tape)
    for i in range(0, 260, 36):
        strip.polygon([(i, 0), (i + 18, 0), (i + 18, 70), (i, 70)], fill=(252, 244, 210, 170))
    tape = tape.rotate(-8, expand=True)
    canvas.alpha_composite(tape, (x - 60, y - 26))
    tape2 = tape.rotate(10, expand=True)
    canvas.alpha_composite(tape2, (x + photo.width - 150, y + photo.height - 40))
    if caption:
        draw = ImageDraw.Draw(canvas)
        draw.text((w // 2, h - 44), caption, font=_font("hand", 42), fill=(90, 80, 70, 255), anchor="mm")
    return canvas


def _style_gilded(photo: Image.Image, w: int, h: int, caption: str, date_text: str) -> Image.Image:
    canvas = Image.new("RGBA", (w, h), (38, 26, 16, 255))
    photo = _fit(photo, int(w * 0.66), int(h * 0.66)).convert("RGBA")
    x = (w - photo.width) // 2
    y = (h - photo.height) // 2
    canvas.alpha_composite(photo, (x, y))
    draw = ImageDraw.Draw(canvas)
    gold = (196, 158, 84, 255)
    outer = 26
    draw.rectangle((outer, outer, w - outer, h - outer), outline=gold, width=10)
    draw.rectangle((outer + 18, outer + 18, w - outer - 18, h - outer - 18),
                   outline=(150, 118, 60, 255), width=3)
    for cx, cy in ((outer, outer), (w - outer, outer), (outer, h - outer), (w - outer, h - outer)):
        draw.ellipse((cx - 38, cy - 38, cx + 38, cy + 38), outline=gold, width=5)
        draw.ellipse((cx - 7, cy - 7, cx + 7, cy + 7), fill=gold)
    if caption:
        draw.text((w // 2, h - outer - 6), caption, font=_font("serif", 30),
                  fill=(214, 186, 130, 255), anchor="md")
    return canvas


def _style_instax(photo: Image.Image, w: int, h: int, caption: str, date_text: str) -> Image.Image:
    card_w = int(min(w * 0.62, h * 0.82))
    card_h = int(card_w * 1.24)
    card = Image.new("RGBA", (card_w, card_h), (252, 252, 250, 255))
    win = _fit(photo, card_w - 44, int(card_h * 0.74))
    win = ImageEnhance.Color(win).enhance(1.05).convert("RGBA")
    hold = Image.new("RGBA", (card_w - 20, int(card_h * 0.78)), (238, 238, 236, 255))
    card.alpha_composite(hold, (10, 10))
    card.alpha_composite(win, ((card_w - win.width) // 2, 12 + (hold.height - win.height) // 2))
    draw = ImageDraw.Draw(card)
    label = caption or date_text or ""
    if label:
        draw.text((card_w // 2, card_h - 46), label, font=_font("hand", 34),
                  fill=(60, 60, 70, 255), anchor="mm")
    canvas = Image.new("RGBA", (w, h), (30, 30, 34, 255))
    canvas.alpha_composite(_shadow(card, blur=24, offset=(0, 18), opacity=150),
                           ((w - card_w) // 2, (h - card_h) // 2 + 18))
    canvas.alpha_composite(card, ((w - card_w) // 2, (h - card_h) // 2))
    return canvas


def _style_lomo(photo: Image.Image, w: int, h: int, caption: str, date_text: str) -> Image.Image:
    base = photo.convert("RGB")
    base = ImageEnhance.Color(base).enhance(1.45)
    base = ImageEnhance.Contrast(base).enhance(1.15)
    base = _fit(base, w, h)
    frame = int(min(w, h) * 0.045)
    canvas = Image.new("RGB", (w, h), (8, 8, 10))
    canvas.paste(base, ((w - base.width) // 2, (h - base.height) // 2))
    canvas = _vignette(canvas, 0.55).convert("RGBA")
    leak = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ld = ImageDraw.Draw(leak)
    ld.ellipse((w * 0.72, -h * 0.35, w * 1.35, h * 0.55), fill=(255, 120, 40, 46))
    canvas.alpha_composite(leak.filter(ImageFilter.GaussianBlur(90)))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, w - 1, h - 1), outline=(10, 10, 12, 255), width=frame)
    if caption:
        draw.text((w // 2, h - frame // 2 - 2), caption, font=_font("mono", 26),
                  fill=(230, 230, 230, 255), anchor="mm")
    return canvas


_RENDERERS = {
    "cork": _style_cork,
    "filmstrip": _style_filmstrip,
    "slide": _style_slide,
    "mat": _style_mat,
    "album": _style_album,
    "torn": _style_torn,
    "newspaper": _style_newspaper,
    "datestamp": _style_datestamp,
    "washi": _style_washi,
    "gilded": _style_gilded,
    "instax": _style_instax,
    "lomo": _style_lomo,
}


def _rotate_expand(img: Image.Image, angle: float) -> Image.Image:
    return img.rotate(angle, expand=True, resample=Image.BICUBIC)


def render_frame(photo_path, style: str, size: tuple[int, int],
                 caption: str = "", date_text: str = "") -> Image.Image:
    """Render ``style`` around the photo at ``photo_path``; returns an RGB image.

    ``size`` is the full display canvas (the slideshow resolution).
    """
    if style not in _RENDERERS:
        raise ValueError(f"Unknown frame style: {style}")
    with Image.open(photo_path) as source:
        photo = source.convert("RGB")
    w, h = size
    result = _RENDERERS[style](photo, w, h, caption, date_text)
    return result.convert("RGB")
