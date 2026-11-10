"""Non-destructive crop selections, expressed in oriented original coordinates."""

import json
import math
import os
import threading
from pathlib import Path

from PIL import Image, ImageOps

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
    if (x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > 1.000001
            or y + height > 1.000001):
        raise ValueError("Crop must be inside the image.")
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
    left = max(0, round(crop["x"] * width))
    top = max(0, round(crop["y"] * height))
    right = min(width, round((crop["x"] + crop["width"]) * width))
    bottom = min(height, round((crop["y"] + crop["height"]) * height))
    if right <= left or bottom <= top:
        raise ValueError("Saved crop is empty.")
    return image.crop((left, top, right, bottom))
