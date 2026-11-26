"""Regenerate the play button cleanly from the pause button.

The pause glyph is removed by interpolating each row across the glyph run
(horizontal gradients survive), the patched area is blurred slightly, and a
rounded white triangle with a soft inner shadow is drawn in its place.
"""
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

OUT = Path("static/icons")
SIZE = 190


def glyph_mask(image: Image.Image) -> Image.Image:
    width, height = image.size
    mask = Image.new("L", (width, height), 0)
    src = image.load()
    dst = mask.load()
    for y in range(height):
        for x in range(width):
            r, g, b, a = src[x, y]
            if a > 200 and min(r, g, b) > 200:
                dst[x, y] = 255
    return mask.filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.GaussianBlur(1.5))


def inpaint(image: Image.Image, mask: Image.Image) -> Image.Image:
    """Interpolate masked pixels horizontally from their neighbours."""
    result = image.copy()
    pixels = result.load()
    mask_pixels = mask.load()
    width, height = image.size
    for y in range(height):
        x = 0
        while x < width:
            if mask_pixels[x, y] < 60:
                x += 1
                continue
            start = x
            while x < width and mask_pixels[x, y] >= 60:
                x += 1
            end = x  # exclusive
            left = pixels[start - 1, y] if start > 0 else None
            right = pixels[end, y] if end < width else None
            if left and right:
                span = end - start + 1
                for offset, index in enumerate(range(start, end)):
                    ratio = (offset + 1) / span
                    pixels[index, y] = tuple(
                        int(left[channel] * (1 - ratio) + right[channel] * ratio)
                        for channel in range(4))
            elif left or right:
                fill = left or right
                for index in range(start, end):
                    pixels[index, y] = fill
    blurred = result.filter(ImageFilter.GaussianBlur(2))
    return Image.composite(blurred, result, mask.filter(ImageFilter.GaussianBlur(1.0)))


def play_glyph(size: int, height_ratio: float = 0.185) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    cx = cy = size / 2
    half = size * height_ratio
    draw.polygon([(cx - half * 0.72, cy - half),
                  (cx - half * 0.72, cy + half),
                  (cx + half * 1.02, cy)], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(size * 0.008))
    return mask.point(lambda v: 255 if v > 120 else 0)


def main():
    pause = Image.open(OUT / "control_pause.png").convert("RGBA").resize((SIZE, SIZE), Image.LANCZOS)
    mask = glyph_mask(pause)
    play = inpaint(pause, mask)

    glyph = play_glyph(SIZE)

    # Soft contact shadow under the triangle.
    shadow = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    shadow.paste((10, 60, 130, 110), (2, 3), glyph)
    play.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(2)))

    # White face, faint vertical gradient for the 3D feel.
    ramp = Image.linear_gradient("L").resize((SIZE, SIZE))
    face = Image.composite(Image.new("RGBA", (SIZE, SIZE), (255, 255, 255, 255)),
                           Image.new("RGBA", (SIZE, SIZE), (243, 243, 245, 255)), ramp)
    play.paste(face, (0, 0), glyph)

    # Thin bright rim on the upper-left edge.
    eroded = glyph.filter(ImageFilter.MinFilter(7))
    rim = ImageChops.subtract(glyph, eroded)
    play.paste(Image.new("RGBA", (SIZE, SIZE), (255, 255, 255, 150)), (-1, -1), rim)

    play.save(OUT / "control_play.png")
    print("play regenerated", play.size)


if __name__ == "__main__":
    main()
