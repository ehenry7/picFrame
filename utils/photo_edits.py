"""App-only per-photo strength, location and date overrides."""

import json
import math
import os
from pathlib import Path
import threading
from datetime import datetime

EDIT_FILE = Path(__file__).resolve().parent.parent / "config" / "photo_edits.json"
EDIT_LOCK = threading.RLock()


def load_edits():
    if not EDIT_FILE.exists():
        return {}
    data = json.loads(EDIT_FILE.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Invalid photo edit settings.")
    return data


def update_edit(photo, changes):
    with EDIT_LOCK:
        edits = load_edits()
        edit = edits.setdefault(photo, {})
        for key, value in changes.items():
            if value is None:
                edit.pop(key, None)
            else:
                edit[key] = value
        if not edit:
            edits.pop(photo, None)
        EDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
        temporary = EDIT_FILE.with_suffix(".json.tmp")
        try:
            temporary.write_text(json.dumps(edits, ensure_ascii=False, indent=4), encoding="utf-8")
            os.replace(temporary, EDIT_FILE)
        finally:
            temporary.unlink(missing_ok=True)


def validate_strength(value):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or not 0 <= value <= 1):
        raise ValueError("Filter strength must be between 0 and 1.")
    return float(value)


def photo_key(path):
    return "/".join(Path(path).parts[-2:])


def filter_strength(path):
    return validate_strength(load_edits().get(photo_key(path), {}).get("strength", 1.0))


def location_override(path):
    stem = Path(path).stem
    for suffix in ("_polaroid", "_postcard"):
        if stem.endswith(suffix):
            stem = stem[:-len(suffix)]
    key = f"{Path(path).parent.name}/{stem}.jpg"
    return load_edits().get(key, {}).get("location")


def date_override(path):
    """Return the manually overridden capture date (ISO string) or None."""
    stem = Path(path).stem
    for suffix in ("_polaroid", "_postcard"):
        if stem.endswith(suffix):
            stem = stem[:-len(suffix)]
    key = f"{Path(path).parent.name}/{stem}.jpg"
    return load_edits().get(key, {}).get("date")


def validate_date(value):
    """Validate and normalise a date string to ISO format YYYY-MM-DD."""
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError("Date must be a string.")
    value = value.strip()
    # Accept YYYY-MM-DD, YYYY:MM:DD, DD/MM/YYYY, DD-MM-YYYY
    for fmt in ("%Y-%m-%d", "%Y:%m:%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError("Date must be in YYYY-MM-DD format.")
