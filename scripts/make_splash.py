"""Generate the boot splash image shown by sway before the app is ready."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
LOGO = ROOT / "static" / "logo.png"
OUT = ROOT / "static" / "splash.png"
SIZE = (1920, 1080)


def background(size):
    width, height = size
    top, bottom = (16, 24, 38), (30, 42, 58)
    image = Image.new("RGB", size)
    draw = ImageDraw.Draw(image)
    for y in range(height):
        ratio = y / height
        colour = tuple(int(top[i] * (1 - ratio) + bottom[i] * ratio) for i in range(3))
        draw.line((0, y, width, y), fill=colour)
    glow = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((-width * 0.2, -height * 0.5, width * 1.2, height * 0.7),
                                 fill=(40, 90, 150, 70))
    return Image.alpha_composite(image.convert("RGBA"),
                                 glow.filter(ImageFilter.GaussianBlur(120)))


def font(size):
    for name in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def main():
    canvas = background(SIZE)
    logo = Image.open(LOGO).convert("RGBA")
    logo.thumbnail((320, 320), Image.LANCZOS)
    x = (SIZE[0] - logo.width) // 2
    y = (SIZE[1] - logo.height) // 2 - 60
    canvas.alpha_composite(logo, (x, y))

    draw = ImageDraw.Draw(canvas)
    title_font = font(64)
    subtitle_font = font(28)
    title = "PictureFrame"
    title_width = draw.textlength(title, font=title_font)
    draw.text(((SIZE[0] - title_width) / 2, y + logo.height + 24), title,
              font=title_font, fill=(232, 238, 246))
    subtitle = "Starting up…"
    subtitle_width = draw.textlength(subtitle, font=subtitle_font)
    draw.text(((SIZE[0] - subtitle_width) / 2, y + logo.height + 108), subtitle,
              font=subtitle_font, fill=(140, 158, 178))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(OUT, quality=92)
    print("splash written:", OUT, OUT.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
