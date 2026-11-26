"""Generate the two startup images (boot + app start) with version and URL.

* splash_boot.png  - Plymouth boot splash ("Booting PictureFrame")
* splash.png       - sway wallpaper while the app starts ("Starting up...")

Both carry the app version and the web UI address at the bottom.
"""
import socket
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
LOGO = ROOT / "static" / "logo.png"
SIZE = (1920, 1080)


def app_version() -> str:
    try:
        for line in (ROOT / "version.py").read_text(encoding="utf-8").splitlines():
            if "__version__" in line:
                return line.split("=", 1)[1].strip().strip('"\'')
    except OSError:
        pass
    return "?"


def local_ip() -> str:
    # Prefer the WiFi interface: that is the address used to reach the web UI.
    try:
        import subprocess

        output = subprocess.run(['ip', '-4', '-o', 'addr', 'show', 'wlan0'],
                                capture_output=True, text=True, timeout=3).stdout
        for token in output.split():
            if token.count('.') == 3 and '/' in token:
                return token.split('/')[0]
    except Exception:
        pass
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("8.8.8.8", 80))
            return probe.getsockname()[0]
        finally:
            probe.close()
    except OSError:
        return "127.0.0.1"


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


def compose(subtitle: str, dots: bool, version: str, url: str) -> Image.Image:
    canvas = background(SIZE)
    logo = Image.open(LOGO).convert("RGBA")
    logo.thumbnail((320, 320), Image.LANCZOS)
    x = (SIZE[0] - logo.width) // 2
    y = (SIZE[1] - logo.height) // 2 - 70
    canvas.alpha_composite(logo, (x, y))

    draw = ImageDraw.Draw(canvas)
    title_font = font(64)
    subtitle_font = font(32)
    footer_font = font(26)

    title = "PictureFrame"
    draw.text(((SIZE[0] - draw.textlength(title, font=title_font)) / 2,
               y + logo.height + 24), title, font=title_font, fill=(232, 238, 246))

    subtitle_width = draw.textlength(subtitle, font=subtitle_font)
    subtitle_y = y + logo.height + 112
    draw.text(((SIZE[0] - subtitle_width) / 2, subtitle_y), subtitle,
              font=subtitle_font, fill=(150, 168, 188))

    if dots:
        dot_y = subtitle_y + 72
        for index in range(3):
            cx = SIZE[0] / 2 + (index - 1) * 34
            draw.ellipse((cx - 7, dot_y - 7, cx + 7, dot_y + 7), fill=(150, 168, 188))

    footer = f"v{version}   |   {url}"
    footer_width = draw.textlength(footer, font=footer_font)
    draw.text(((SIZE[0] - footer_width) / 2, SIZE[1] - 96), footer,
              font=footer_font, fill=(110, 128, 148))
    return canvas


def main():
    variant = sys.argv[1] if len(sys.argv) > 1 else "all"
    version = app_version()
    url = f"http://{local_ip()}"
    targets = {
        "boot": ("splash_boot.png", "Booting PictureFrame", True),
        "app": ("splash.png", "Starting up...", False),
    }
    for key, (filename, subtitle, dots) in targets.items():
        if variant not in ("all", key):
            continue
        image = compose(subtitle, dots, version, url)
        path = ROOT / "static" / filename
        image.convert("RGB").save(path, quality=92)
        print("written:", path.name, f"v{version} | {url}", path.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
