"""Extract glossy blue buttons from a white-background reference.

The reference (static/icons/c.png) shows three 3D squircle buttons in the
order previous, next, pause (the pause one is larger in the artwork).
Each button is cut out with a feathered alpha channel (white background
removed, white glyphs preserved), then scaled proportionally so the pause
button defines the target size. A matching play button is synthesised from
the pause button by inpainting the bars and drawing a white triangle.
"""
from collections import deque
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

SRC = Path("static/icons/c.png")
OUT = Path("static/icons")
TARGET = 190
ORDER = ("previous", "next", "pause")


def foreground_mask(image: Image.Image) -> Image.Image:
    """Foreground = everything the flood fill from the corners cannot reach."""
    width, height = image.size
    work = image.convert("RGB").copy()
    for corner in ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)):
        ImageDraw.floodfill(work, corner, (255, 0, 255), thresh=42)
    pixels = work.load()
    mask = Image.new("L", (width, height), 0)
    dst = mask.load()
    for y in range(height):
        for x in range(width):
            if pixels[x, y] != (255, 0, 255):
                dst[x, y] = 255
    return mask


def largest_components(mask: Image.Image, count: int = 3):
    """Return the bounding boxes of the largest blobs, ordered left to right."""
    width, height = mask.size
    src = mask.load()
    seen = bytearray(width * height)
    blobs = []
    for y in range(height):
        for x in range(width):
            if not src[x, y] or seen[y * width + x]:
                continue
            queue = deque([(x, y)])
            seen[y * width + x] = 1
            min_x = max_x = x
            min_y = max_y = y
            area = 0
            while queue:
                cx, cy = queue.popleft()
                area += 1
                min_x, max_x = min(min_x, cx), max(max_x, cx)
                min_y, max_y = min(min_y, cy), max(max_y, cy)
                for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                    if 0 <= nx < width and 0 <= ny < height:
                        index = ny * width + nx
                        if src[nx, ny] and not seen[index]:
                            seen[index] = 1
                            queue.append((nx, ny))
            blobs.append((area, min_x, min_y, max_x, max_y))
    blobs.sort(reverse=True)
    blobs = blobs[:count]
    blobs.sort(key=lambda blob: blob[1])
    assert len(blobs) == count, f"expected {count} buttons, found {len(blobs)}"
    return [(min_x, min_y, max_x, max_y) for _, min_x, min_y, max_x, max_y in blobs]


def cut_out(image: Image.Image, mask: Image.Image, box, target: int) -> Image.Image:
    """Crop one button to a square canvas with the white background removed."""
    width, height = image.size
    x0, y0, x1, y1 = box
    side = max(x1 - x0, y1 - y0) + 4
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    left = max(0, cx - side // 2)
    top = max(0, cy - side // 2)
    right = min(width, left + side)
    bottom = min(height, top + side)

    crop = image.crop((left, top, right, bottom)).convert("RGB")
    alpha = mask.crop((left, top, right, bottom)).filter(ImageFilter.GaussianBlur(1.1))

    rgba = crop.convert("RGBA")
    pixels = rgba.load()
    apixels = alpha.load()
    crop_w, crop_h = rgba.size
    for y in range(crop_h):
        for x in range(crop_w):
            a = apixels[x, y]
            if a == 0:
                pixels[x, y] = (0, 0, 0, 0)
                continue
            factor = a / 255
            r, g, b, _ = pixels[x, y]
            r = max(0, min(255, int((r - 255 * (1 - factor)) / max(factor, 0.02))))
            g = max(0, min(255, int((g - 255 * (1 - factor)) / max(factor, 0.02))))
            b = max(0, min(255, int((b - 255 * (1 - factor)) / max(factor, 0.02))))
            pixels[x, y] = (r, g, b, a)
    rgba.putalpha(alpha)

    # Letterbox instead of stretching: keep the button's aspect ratio.
    bbox = rgba.getbbox()
    if bbox:
        rgba = rgba.crop(bbox)
    width, height = rgba.size
    scale = target / max(width, height)
    scaled = rgba.resize((max(1, int(width * scale)), max(1, int(height * scale))),
                         Image.LANCZOS)
    canvas = Image.new("RGBA", (target, target), (0, 0, 0, 0))
    canvas.alpha_composite(scaled, ((target - scaled.width) // 2,
                                    (target - scaled.height) // 2))
    return canvas


def make_play(pause: Image.Image) -> Image.Image:
    """Paint a white play triangle where the pause bars were."""
    play = pause.copy()
    width, height = play.size
    pixels = play.load()

    glyph = Image.new("L", (width, height), 0)
    glyph_pixels = glyph.load()
    for y in range(height):
        for x in range(width):
            r, g, b, a = pixels[x, y]
            if a > 200 and min(r, g, b) > 205:
                glyph_pixels[x, y] = 255

    box = glyph.getbbox()
    if box:
        for y in range(box[1], box[3]):
            outside = [pixels[x, y] for x in range(width)
                       if pixels[x, y][3] > 200 and not glyph_pixels[x, y]]
            if not outside:
                continue
            avg = tuple(sum(p[i] for p in outside) // len(outside) for i in range(3))
            for x in range(box[0], box[2]):
                if glyph_pixels[x, y]:
                    pixels[x, y] = (*avg, 255)

    cx, cy = width / 2, height / 2
    half = width * 0.17
    shadow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).polygon(
        [(cx - half * 0.7 + 3, cy - half + 3),
         (cx - half * 0.7 + 3, cy + half + 3),
         (cx + half + 3, cy + 3)], fill=(10, 60, 130, 150))
    play.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(2)))
    ImageDraw.Draw(play).polygon(
        [(cx - half * 0.7, cy - half), (cx - half * 0.7, cy + half), (cx + half, cy)],
        fill=(250, 250, 252, 255))
    return play


def main():
    image = Image.open(SRC).convert("RGB")
    mask = foreground_mask(image)
    boxes = largest_components(mask)
    sides = [max(x1 - x0, y1 - y0) for x0, y0, x1, y1 in boxes]
    pause_side = sides[2]  # third button in the artwork is the pause one
    OUT.mkdir(parents=True, exist_ok=True)

    cut = {}
    for action, box, side in zip(ORDER, boxes, sides):
        target = max(1, int(round(TARGET * side / pause_side)))
        button = cut_out(image, mask, box, target)
        button.save(OUT / f"control_{action}.png")
        cut[action] = button
        print(action, button.size)

    play = make_play(cut["pause"])
    play.save(OUT / "control_play.png")
    print("play", play.size)


if __name__ == "__main__":
    main()
