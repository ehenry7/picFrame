"""Nonblocking flag lookup; disk and HTTP work run on one bounded worker."""

import json
import logging
import os
import queue
import threading
import time
from collections import OrderedDict
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image

logger = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parents[1]
SUPPORTED_SIZES = frozenset(("128x96", "192x144", "256x192"))


class CountryFlagCache:
    """Return a cached RGBA image or None, scheduling misses without waiting.

    Images returned by get() are shared and must not be modified by callers.
    Failed loads retry on subsequent lookups after exponential backoff.
    """

    def __init__(self, cache_dir=None, max_pending=32, max_images=128,
                 retry_seconds=30, max_retry_seconds=1800, clock=time.monotonic):
        if max_pending < 1 or max_images < 1:
            raise ValueError("Cache and queue limits must be positive")
        self.cache_dir = Path(cache_dir) if cache_dir is not None else BASE_DIR / "cache" / "country_flags"
        with (BASE_DIR / "static" / "flags" / "country_codes.json").open(encoding="utf-8") as handle:
            countries = json.load(handle)
        self._iso_codes = frozenset(countries)
        self._country_names = {name.strip().casefold(): iso for iso, name in countries.items()}
        self._images = OrderedDict()
        self._pending = set()
        self._failures = {}
        self._queue = queue.Queue(maxsize=max_pending)
        self._lock = threading.Lock()
        self._worker = None
        self._closed = False
        self._max_images = max_images
        self._retry_seconds = retry_seconds
        self._max_retry_seconds = max_retry_seconds
        self._clock = clock

    def get(self, iso_code, size="128x96"):
        """Only consult memory and enqueue work; never read disk or use HTTP."""
        if not isinstance(iso_code, str) or not isinstance(size, str):
            return None
        iso_code = iso_code.strip().casefold()
        iso_code = self._country_names.get(iso_code, iso_code)
        if iso_code not in self._iso_codes or size not in SUPPORTED_SIZES:
            return None
        key = (iso_code, size)
        with self._lock:
            image = self._images.get(key)
            if image is not None:
                self._images.move_to_end(key)
                return image
            if self._closed or key in self._pending:
                return None
            failure = self._failures.get(key)
            if failure is not None and self._clock() < failure[1]:
                return None
            try:
                self._queue.put_nowait(key)
            except queue.Full:
                return None
            self._pending.add(key)
            if self._worker is None:
                self._worker = threading.Thread(
                    target=self._run, name="country-flags", daemon=True)
                self._worker.start()
        return None

    def close(self):
        """Drain scheduled work and stop the worker (not for use while drawing)."""
        with self._lock:
            self._closed = True
            worker = self._worker
        if worker is not None:
            self._queue.join()
            self._queue.put(None)
            worker.join()
            with self._lock:
                self._worker = None

    @staticmethod
    def _decode(data, size):
        if len(data) > 1024 * 1024:
            raise ValueError("Flag image exceeds 1 MiB")
        with Image.open(BytesIO(data)) as image:
            if image.format != "PNG" or image.size != tuple(map(int, size.split("x"))):
                raise ValueError("Flag is not a PNG of the requested size")
            return image.convert("RGBA")

    def _load(self, iso_code, size):
        path = self.cache_dir / f"{iso_code}_{size}.png"
        try:
            return self._decode(path.read_bytes(), size)
        except FileNotFoundError:
            pass
        except Exception as error:
            logger.warning("Cannot read cached country flag %s: %s", path, error)

        response = requests.get(f"https://flagcdn.com/{size}/{iso_code}.png", timeout=(3, 5))
        try:
            response.raise_for_status()
            data = response.content
            image = self._decode(data, size)
        finally:
            response.close()

        staging = path.with_suffix(".png.part")
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            staging.write_bytes(data)
            os.replace(staging, path)
        except OSError as error:
            logger.warning("Cannot save country flag %s: %s", path, error)
        finally:
            try:
                staging.unlink(missing_ok=True)
            except OSError:
                logger.warning("Cannot remove country flag staging file %s", staging)
        return image

    def _run(self):
        while True:
            key = self._queue.get()
            try:
                if key is None:
                    return
                try:
                    image = self._load(*key)
                except Exception as error:
                    with self._lock:
                        attempts = min(self._failures.get(key, (0, 0))[0] + 1, 16)
                        delay = min(self._retry_seconds * 2 ** (attempts - 1),
                                    self._max_retry_seconds)
                        self._failures[key] = (attempts, self._clock() + delay)
                    logger.warning("Cannot load country flag %s/%s; retry in %ss: %s",
                                   *key, delay, error)
                else:
                    with self._lock:
                        self._images[key] = image
                        self._images.move_to_end(key)
                        while len(self._images) > self._max_images:
                            self._images.popitem(last=False)
                        self._failures.pop(key, None)
            finally:
                with self._lock:
                    self._pending.discard(key)
                self._queue.task_done()


country_flags = CountryFlagCache()
