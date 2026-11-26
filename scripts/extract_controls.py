"""Extract media buttons from a reference image into transparent PNGs.

The source image shows three dark circular buttons on a checkerboard
("fake transparency") background. For each third of the image we:

1. find the disc as the dark region (luminance threshold),
2. build a feathered alpha channel inside a circle fitted to that region,
3. drop the baked-in drop shadow (it never becomes fully opaque),
4. save ``control_<action>.png`` and synthesize a play glyph on a clean disc.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

SOURCE = Path("/tmp/ref_controls.jpg")
OUT_DIR = Path("static/icons")
ACTIONS = ("previous", "pause", "next")


def clamp(value, low, high):
    return max(low, min(high, value))


def extract_discs(image: Image.Image):
    grey = image.convert("L")
    width, height = grey.size
    pixels = grey.load()
    third = width // 3
    discs = []
    for index in range(3):
        left, right = index * third, (index + 1) * third
        min_x, min_y, max_x, max_y = right, height, left, 0
        for y in range(height):
            for x in range(left, right):
                if pixels[x, y] < 110:
                    min_x, max_x = min(min_x, x), max(max_x, x)
                    min_y, max_y = min(min_y, y), max(max_y, y)
        if max_x <= min_x:
            continue
        cx = (min_x + max_x) / 2
        cy = (min_y + max_y) / 2
        radius = max(max_x - min_x, max_y - min_y) / 2
        discs.append((cx, cy, radius + 6))
    return discs


def extract(image: Image.Image, cx, cy, radius):
    size = int(radius * 2)
    crop = image.crop((int(cx - radius), int(cy - radius),
                       int(cx - radius) + size, int(cy - radius) + size))
    grey = crop.convert("L")
    rgb = crop.convert("RGB")

    alpha = Image.new("L", crop.size, 0)
    alpha_pixels = alpha.load()
    grey_pixels = grey.load()
    width, height = crop.size
    centre = size / 2
    for y in range(height):
        for x in range(width):
            distance = ((x - centre) ** 2 + (y - centre) ** 2) ** 0.5
            if distance > radius - 2:
                continue
            luminance = grey_pixels[x, y]
            # Dark disc -> opaque; light checkerboard -> transparent.
            value = clamp((205 - luminance) / 145, 0.0, 1.0)
            if distance > radius - 8:
                value *= clamp((radius - 2 - distance) / 6, 0.0, 1.0)
            alpha_pixels[x, y] = int(value * 255)

    result = rgb.convert("RGBA")
    result.putalpha(alpha)
    return result


def make_play(pause: Image.Image) -> Image.Image:
    """Paint a play triangle over a clean copy of the pause disc."""
    play = pause.copy()
    size = play.size[0]
    draw = ImageDraw.Draw(play)
    centre = size / 2

    # Cover the pause bars with the surrounding disc colour.
    sample_box = (int(size * 0.30), int(size * 0.18), int(size * 0.70), int(size * 0.28))
    patch = play.crop(sample_box).convert("RGB")
    colours = patch.getdata()
    red = sum(c[0] for c in colours) // len(colours)
    green = sum(c[1] for c in colours) // len(colours)
    blue = sum(c[2] for c in colours) // len(colours)
    cover = Image.new("RGBA", play.size, (0, 0, 0, 0))
    ImageDraw.Draw(cover).ellipse(
        (centre - size * 0.22, centre - size * 0.24,
         centre + size * 0.22, centre + size * 0.24),
        fill=(red, green, blue, 255))
    play.alpha_composite(cover.filter(ImageFilter.GaussianBlur(size * 0.02)))

    # Triangle, same black as the reference glyphs.
    icon = size * 0.16
    points = [(centre - icon * 0.62, centre - icon * 0.95),
              (centre - icon * 0.62, centre + icon * 0.95),
              (centre + icon * 0.95, centre)]
    ImageDraw.Draw(play).polygon(points, fill=(14, 16, 20, 255))
    return play


def main():
    image = Image.open(SOURCE)
    discs = extract_discs(image)
    print("discs:", discs)
    assert len(discs) == 3, f"expected 3 discs, found {len(discs)}"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for action, (cx, cy, radius) in zip(ACTIONS, discs):
        disc = extract(image, cx, cy, radius)
        disc.save(OUT_DIR / f"control_{action}.png")
        print(action, disc.size)
        if action == "pause":
            make_play(disc).save(OUT_DIR / "control_play.png")
            print("play", disc.size)


if __name__ == "__main__":
    main()
