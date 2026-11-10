"""Content hashing shared by local and browser photo imports."""

import hashlib
from pathlib import Path

PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".heif"}


def photo_digest(path: Path) -> str:
    with path.open("rb") as file:
        return stream_digest(file)


def stream_digest(stream) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()
