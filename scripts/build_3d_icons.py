"""Build clean, genuinely 3D media buttons (procedural glyphs).

Renders glossy blue squircle buttons with white extruded/embossed glyphs:
previous (double triangle), pause (two bars), play (triangle), next.
Saved as transparent PNGs in static/icons/ for the slideshow controls.
"""
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

OUT_DIR = Path("static/icons")
FINAL = 190          # displayed at native size; 50% of the previous 380 px
WORK = FINAL * 4     # supersampled render, downscaled for clean edges


def squircle(size: int, radius_ratio: float = 0.26) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, size - 1, size - 1), radius=int(size * radius_ratio), fill=255)
    return mask


def gradient(size: int, top, bottom) -> Image.Image:
    ramp = Image.linear_gradient("L").resize((size, size))
    return ImageOps.colorize(ramp, black=bottom, white=top)


def _soften(mask: Image.Image, work: int) -> Image.Image:
    """Tiny blur + threshold keeps edges crisp but smooth after downscaling."""
    blurred = mask.filter(ImageFilter.GaussianBlur(work * 0.0018))
    return blurred.point(lambda v: 255 if v > 110 else 0)


def previous_glyph(work: int) -> Image.Image:
    mask = Image.new("L", (work, work), 0)
    draw = ImageDraw.Draw(mask)
    cx = cy = work / 2
    h = work * 0.16
    w = h * 1.05
    gap = h * 0.55
    left_tip = cx - (2 * w + gap) / 2
    for index in range(2):
        tip = left_tip + index * (w + gap)
        draw.polygon([(tip + w, cy - h), (tip + w, cy + h), (tip, cy)], fill=255)
    return _soften(mask, work)


def next_glyph(work: int) -> Image.Image:
    mask = Image.new("L", (work, work), 0)
    draw = ImageDraw.Draw(mask)
    cx = cy = work / 2
    h = work * 0.16
    w = h * 1.05
    gap = h * 0.55
    right_tip = cx + (2 * w + gap) / 2
    for index in range(2):
        tip = right_tip - index * (w + gap)
        draw.polygon([(tip - w, cy - h), (tip - w, cy + h), (tip, cy)], fill=255)
    return _soften(mask, work)


def pause_glyph(work: int) -> Image.Image:
    mask = Image.new("L", (work, work), 0)
    draw = ImageDraw.Draw(mask)
    cx = cy = work / 2
    h = work * 0.17
    bar_w = work * 0.075
    gap = work * 0.075
    for offset in (-gap / 2 - bar_w, gap / 2):
        draw.rounded_rectangle((cx + offset, cy - h, cx + offset + bar_w, cy + h),
                               radius=bar_w * 0.42, fill=255)
    return _soften(mask, work)


def play_glyph(work: int) -> Image.Image:
    mask = Image.new("L", (work, work), 0)
    draw = ImageDraw.Draw(mask)
    cx = cy = work / 2
    h = work * 0.17
    draw.polygon([(cx - h * 0.75, cy - h), (cx - h * 0.75, cy + h), (cx + h, cy)], fill=255)
    return _soften(mask, work)


def build_button(glyph: Image.Image, work: int, final: int) -> Image.Image:
    shape = squircle(work)
    body = Image.new("RGBA", (work, work), (0, 0, 0, 0))

    body.paste(gradient(work, (96, 196, 255), (6, 68, 170)), (0, 0), shape)

    # Volume shading at the bottom.
    shade = Image.new("RGBA", (work, work), (0, 0, 0, 0))
    ImageDraw.Draw(shade).ellipse(
        (-work * 0.25, work * 0.45, work * 1.25, work * 1.4), fill=(0, 18, 66, 130))
    body.alpha_composite(Image.composite(
        shade.filter(ImageFilter.GaussianBlur(work * 0.05)),
        Image.new("RGBA", (work, work), (0, 0, 0, 0)), shape))

    # Squircle bevel: light top rim, dark bottom rim.
    ring_width = max(3, int(work * 0.013))
    inner = squircle(work - ring_width * 2)
    inner_padded = Image.new("L", (work, work), 0)
    inner_padded.paste(inner, (ring_width, ring_width))
    outline = ImageChops.subtract(shape, inner_padded)

    light = gradient(work, (255, 255, 255), (150, 185, 235)).convert("RGBA")
    light.putalpha(ImageChops.multiply(outline, Image.new("L", (work, work), 155)))
    body.alpha_composite(light.filter(ImageFilter.GaussianBlur(work * 0.004)))

    dark = Image.new("RGBA", (work, work), (6, 34, 88, 255))
    dark.putalpha(ImageChops.multiply(outline, Image.new("L", (work, work), 120)))
    body.alpha_composite(ImageOps.flip(dark).filter(ImageFilter.GaussianBlur(work * 0.006)))

    # Gloss.
    gloss = Image.new("RGBA", (work, work), (0, 0, 0, 0))
    ImageDraw.Draw(gloss).ellipse(
        (work * 0.10, work * 0.04, work * 0.90, work * 0.50), fill=(255, 255, 255, 78))
    body.alpha_composite(Image.composite(
        gloss.filter(ImageFilter.GaussianBlur(work * 0.03)),
        Image.new("RGBA", (work, work), (0, 0, 0, 0)), shape))

    # Glyph: contact shadow, extrusion, white face, rim light.
    glyph = glyph.resize((work, work), Image.LANCZOS)
    depth = int(work * 0.022)

    contact = Image.new("RGBA", (work, work), (0, 0, 0, 0))
    contact.paste((4, 36, 100, 160), (0, 0), glyph)
    body.alpha_composite(contact.filter(ImageFilter.GaussianBlur(work * 0.012)),
                         (depth // 2, depth))

    for step in range(depth, 0, -1):
        layer = Image.new("RGBA", (work, work), (0, 0, 0, 0))
        layer.paste((52, 118, 186, 255), (0, 0), glyph)
        body.alpha_composite(layer, (step, int(step * 1.2)))

    face = Image.new("RGBA", (work, work), (0, 0, 0, 0))
    face.paste((252, 252, 254, 255), (0, 0), glyph)
    body.alpha_composite(face)

    rim = Image.new("RGBA", (work, work), (0, 0, 0, 0))
    rim.paste((255, 255, 255, 230), (0, 0), glyph)
    rim = ImageChops.subtract(rim, face)
    body.alpha_composite(rim.filter(ImageFilter.GaussianBlur(work * 0.003)), (-1, -1))

    return body.resize((final, final), Image.LANCZOS)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    builders = {
        "previous": previous_glyph,
        "pause": pause_glyph,
        "play": play_glyph,
        "next": next_glyph,
    }
    for action, builder in builders.items():
        button = build_button(builder(WORK), WORK, FINAL)
        button.save(OUT_DIR / f"control_{action}.png")
        print(action, button.size)


if __name__ == "__main__":
    main()
