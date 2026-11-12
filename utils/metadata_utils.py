import json
from pathlib import Path
import re
import logging
import os
from datetime import datetime
from functools import lru_cache

from PIL import Image, IptcImagePlugin
from utils.migrate_frame_names import LEGACY_METADATA_CACHE, is_legacy_photo_source

# Define paths.
BASE_DIR = Path(__file__).resolve().parent.parent
_photo_metadata_cache = None
_photo_metadata_last_load = None
DESCRIPTION_MAP_CACHE_FILE = BASE_DIR / 'cache' / LEGACY_METADATA_CACHE

logger = logging.getLogger(__name__)

@lru_cache(maxsize=1)
def _preview_country_codes():
    path = Path(__file__).resolve().parent.parent / "static" / "flags" / "country_codes.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        logger.warning("[Metadata] Cannot load country codes for preview flags: %s", error)
        return {}


def format_preview_location(metadata, translate):
    city = (metadata.get("city") or "").strip()
    country = (metadata.get("country") or "").strip()
    code = (metadata.get("countryCode") or metadata.get("country_code") or "").strip().lower()
    codes = _preview_country_codes()
    if not code and country:
        code = next((iso for iso, name in codes.items()
                     if country.casefold() in (iso, name.casefold())), "")
    if country.lower() in codes:
        country = codes[country.lower()]
    elif not country and code in codes:
        country = codes[code]
    location = ", ".join(value for value in (city, country) if value)
    if not location:
        return translate("No location metadata")
    flag = "".join(chr(0x1F1E6 + ord(letter) - ord("a")) for letter in code) if code in codes else ""
    return f"{flag} {location}".strip()


def format_photo_metadata(metadata, config, translate):
    if not metadata:
        return ""
    date_fields = (
        "subSecDateTimeOriginal", "dateTimeOriginal", "SubSecDateTimeOriginal", "DateTimeOriginal",
        "subSecCreateDate", "createDate", "SubSecCreateDate", "CreateDate",
        "subSecModifyDate", "modifyDate", "SubSecModifyDate",
        "mediaCreateDate", "dateTimeCreated", "MediaCreateDate", "DateTimeCreated",
        "fileModifiedAt", "fileCreatedAt",
    )
    date_value = next((metadata.get(field) for field in date_fields if metadata.get(field)), None)
    elements = []
    if date_value:
        try:
            date = datetime.fromisoformat(date_value.replace("Z", "+00:00"))
        except (ValueError, TypeError, AttributeError) as error:
            logger.warning("[Metadata] Invalid capture date %r: %s", date_value, error)
        else:
            if config.get("show_photo_date", False):
                elements.append(date.strftime(config.get("photo_date_format", "%d %B %Y")))
            if config.get("anniversary_boost_enabled", True):
                now = datetime.now()
                years = now.year - date.year
                if (date.month, date.day) == (now.month, now.day) and years > 0:
                    message = "(Anniversaire) Il y a %(num)d an" if years == 1 else "(Anniversaire) Il y a %(num)d ans"
                    elements.append(translate(message) % {"num": years})
    if config.get("show_photo_location", False):
        city, country = metadata.get("city") or "", metadata.get("country") or ""
        location_format = config.get("photo_location_format", "city_country")
        location = city if location_format == "city" else country if location_format == "country" else ", ".join(
            value for value in (city, country) if value
        )
        if location:
            elements.append(location)
    return "  •  ".join(elements)


def load_photo_metadata_cache():
    """
    Load the photo metadata cache from the JSON file created during download.
    This file contains each photo's EXIF information (date, city, country, GPS coordinates).
    """
    global _photo_metadata_cache, _photo_metadata_last_load

    if not DESCRIPTION_MAP_CACHE_FILE.exists():
        return {}

    try:
        file_mtime = DESCRIPTION_MAP_CACHE_FILE.stat().st_mtime

        if _photo_metadata_last_load is None or file_mtime > _photo_metadata_last_load:
            with open(DESCRIPTION_MAP_CACHE_FILE, 'r', encoding='utf-8') as f:
                _photo_metadata_cache = json.load(f)
            _photo_metadata_last_load = file_mtime

        return _photo_metadata_cache

    except Exception as e:
        logger.error(f"[Metadata] Error loading cache: {e}")
        return {}

def get_photo_metadata(photo_path):
    from utils.photo_edits import location_override, date_override
    metadata = dict(_get_photo_metadata(photo_path))
    override = location_override(photo_path)
    if override is not None:
        metadata.pop("countryCode", None)
        metadata.pop("country_code", None)
        metadata.update(override)
    date_ov = date_override(photo_path)
    if date_ov:
        metadata["dateTimeOriginal"] = date_ov
        metadata.pop("dateSource", None)
    return metadata


def _get_photo_metadata(photo_path):
    """
    Retrieve a photo's metadata from the cache.
    Retourne un dictionnaire avec : date_taken, city, country, location, latitude, longitude
    """
    try:
        path = Path(photo_path)
        if not path.is_absolute():
            path = BASE_DIR / path
        prepared_root = BASE_DIR / "static" / "prepared"
        try:
            relative = path.relative_to(prepared_root)
        except ValueError:
            relative = None
        if relative is not None and len(relative.parts) == 2 and not is_legacy_photo_source(relative.parts[0]):
            return get_local_photo_metadata(path, relative)
        metadata_map = load_photo_metadata_cache()
        if not metadata_map:
            return get_local_photo_metadata(path, relative)
        filename = Path(photo_path).name
        filename_lower = filename.lower()
        for cached_filename, metadata in metadata_map.items():
            if cached_filename.lower() == filename_lower:
                return metadata
        base_filename = re.sub(r'(_polaroid|_postcard)\.(jpg|jpeg|png|JPG|JPEG|PNG)$', r'.\2', filename, flags=re.IGNORECASE)
        base_filename_lower = base_filename.lower()
        for cached_filename, metadata in metadata_map.items():
            if cached_filename.lower() == base_filename_lower:
                return metadata
        return get_local_photo_metadata(path, relative)
    except Exception as e:
        logger.error(f"[Metadata] Error extracting metadata for {photo_path}: {e}")
        return {}


def get_local_photo_metadata(path, relative):
    candidates = []
    if relative is not None and len(relative.parts) == 2:
        source_dir = BASE_DIR / "static" / "photos" / relative.parts[0]
        stem = re.sub(r"_(polaroid|postcard)$", "", path.stem, flags=re.IGNORECASE)
        if source_dir.is_dir():
            from utils.photo_import import PHOTO_EXTENSIONS
            candidates = sorted(
                photo for photo in source_dir.iterdir()
                if photo.is_file() and photo.stem.casefold() in {path.stem.casefold(), stem.casefold()}
                and photo.suffix.lower() in PHOTO_EXTENSIONS
            )
            candidates.sort(key=lambda photo: photo.stem.casefold() != path.stem.casefold())
    if not candidates and path.is_file():
        candidates = [path]
    for candidate in candidates:
        stat = candidate.stat()
        metadata = read_local_metadata(str(candidate), stat.st_mtime_ns, stat.st_size)
        if metadata:
            return dict(metadata)
    return {}


@lru_cache(maxsize=1024)
def read_local_metadata(filename, modified, size):
    metadata = {}
    exif_date_found = False
    try:
        with Image.open(filename) as image:
            exif = image.getexif()
            fields = exif.get_ifd(34665) if 34665 in exif else {}
            for value in (fields.get(36867), exif.get(36867),
                          fields.get(36868), exif.get(36868), exif.get(306)):
                if not value:
                    continue
                if isinstance(value, bytes):
                    value = value.decode("ascii", errors="replace")
                try:
                    date = datetime.strptime(str(value).strip("\x00 "), "%Y:%m:%d %H:%M:%S")
                except ValueError:
                    logger.warning("[Metadata] Invalid EXIF date in %s: %r", filename, value)
                    continue
                metadata["dateTimeOriginal"] = date.isoformat()
                exif_date_found = True
                break
            iptc = IptcImagePlugin.getiptcinfo(image) or {}
            for key, tag in (("city", (2, 90)), ("country", (2, 101))):
                value = iptc.get(tag)
                if isinstance(value, bytes):
                    value = value.decode("utf-8", errors="replace")
                if isinstance(value, str) and value.strip():
                    metadata[key] = value.strip()
    except (OSError, ValueError, TypeError, SyntaxError) as error:
        logger.warning("[Metadata] Cannot read original photo %s: %s", filename, error)

    # Fallback: use file modification time when no EXIF date is available.
    if not exif_date_found:
        try:
            from datetime import timezone
            file_time = datetime.fromtimestamp(modified / 1e9, tz=timezone.utc).replace(tzinfo=None)
            metadata["dateTimeOriginal"] = file_time.isoformat()
            metadata["dateSource"] = "file"
        except (OSError, ValueError, OverflowError):
            pass

    return metadata