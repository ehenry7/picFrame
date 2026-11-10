"""Non-destructive crop selections, expressed in oriented original coordinates."""

import json
import math
import os
import threading
from pathlib import Path

from PIL import Image, ImageOps, ImageFilter

from utils.photo_import import PHOTO_EXTENSIONS

BASE_DIR = Path(__file__).resolve().parent.parent
CROP_FILE = BASE_DIR / "config" / "crop_states.json"
CROP_LOCK = threading.Lock()


def load_crops():
    if not CROP_FILE.exists():
        return {}
    with CROP_FILE.open(encoding="utf-8") as file:
        crops = json.load(file)
    if not isinstance(crops, dict):
        raise ValueError("Invalid crop settings file.")
    return crops


def save_crops(crops):
    CROP_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = CROP_FILE.with_suffix(".json.tmp")
    try:
        temporary.write_text(json.dumps(crops, indent=4), encoding="utf-8")
        os.replace(temporary, CROP_FILE)
    finally:
        if temporary.exists():
            temporary.unlink()


def original_photo(photo):
    if not isinstance(photo, str) or "\\" in photo:
        raise ValueError("Invalid photo path.")
    parts = photo.split("/")
    if len(parts) != 2 or any(part in {"", ".", ".."} for part in parts):
        raise ValueError("Invalid photo path.")
    relative = Path(*parts)
    prepared = (BASE_DIR / "static" / "prepared" / relative).resolve()
    prepared_root = (BASE_DIR / "static" / "prepared").resolve()
    if not prepared.is_relative_to(prepared_root) or not prepared.is_file() or relative.suffix.lower() != ".jpg":
        raise ValueError("Prepared photo not found.")
    source_root = (BASE_DIR / "static" / "photos").resolve()
    source_dir = source_root / parts[0]
    if source_dir.is_dir():
        for candidate in sorted(source_dir.iterdir()):
            if (candidate.is_file() and candidate.suffix.lower() in PHOTO_EXTENSIONS
                    and candidate.stem.casefold() == relative.stem.casefold()
                    and candidate.resolve().is_relative_to(source_root)):
                return candidate, prepared
    raise ValueError("Original photo not found. Keep the original in static/photos.")


def oriented_image(path):
    if path.suffix.lower() in {".heic", ".heif"}:
        import pillow_heif
        pillow_heif.register_heif_opener()
    with Image.open(path) as image:
        return ImageOps.exif_transpose(image).convert("RGB")


def validate_crop(crop, image_size, screen_size):
    if not isinstance(crop, dict) or set(crop) != {"x", "y", "width", "height"}:
        raise ValueError("Invalid crop selection.")
    if any(isinstance(value, bool) or not isinstance(value, (int, float))
           or not math.isfinite(value) for value in crop.values()):
        raise ValueError("Crop coordinates must be finite numbers.")
    x, y, width, height = (crop[key] for key in ("x", "y", "width", "height"))
    ratio = screen_size[0] / screen_size[1]
    max_width = max(1, ratio * image_size[1] / image_size[0])
    max_height = max(1, image_size[0] / (ratio * image_size[1]))
    if (width <= 0 or height <= 0 or width > max_width + 0.000001
            or height > max_height + 0.000001):
        raise ValueError("Crop exceeds the full-photo selection.")
    for offset, extent in ((x, width), (y, height)):
        if extent <= 1:
            valid = offset >= -0.000001 and offset + extent <= 1.000001
        else:
            valid = math.isclose(offset, (1 - extent) / 2, abs_tol=0.000001)
        if not valid:
            raise ValueError("Crop must stay within the photo or center its padded edges.")
    pixel_width, pixel_height = width * image_size[0], height * image_size[1]
    if min(pixel_width, pixel_height) < 2:
        raise ValueError("Crop is too small.")
    if not math.isclose(pixel_width / pixel_height, screen_size[0] / screen_size[1], rel_tol=0.005):
        raise ValueError("Crop must match the slideshow screen aspect ratio.")
    return dict(crop)


def apply_crop(image, crop):
    if crop is None:
        return image
    width, height = image.size
    left = round(crop["x"] * width)
    top = round(crop["y"] * height)
    right = round((crop["x"] + crop["width"]) * width)
    bottom = round((crop["y"] + crop["height"]) * height)
    if right <= left or bottom <= top:
        raise ValueError("Saved crop is empty.")
    if left >= 0 and top >= 0 and right <= width and bottom <= height:
        return image.crop((left, top, right, bottom))
    output_width, output_height = right - left, bottom - top
    scale = min(1.0, 4096 / max(output_width, output_height))
    size = (max(1, round(output_width * scale)), max(1, round(output_height * scale)))
    background = ImageOps.fit(image.convert("RGB"), size, method=Image.Resampling.LANCZOS)
    background = background.filter(ImageFilter.GaussianBlur(radius=max(size) * 0.03))
    foreground = image.convert("RGB").resize(
        (max(1, round(width * scale)), max(1, round(height * scale))), Image.Resampling.LANCZOS)
    background.paste(foreground, (round(-left * scale), round(-top * scale)))
    return background
