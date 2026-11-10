import tempfile
import unittest
import ast
import logging
import os
from pathlib import Path
from unittest.mock import patch

import piexif
from PIL import Image
from flask import Flask, jsonify, url_for
from werkzeug.test import Client
from werkzeug.wrappers import Response

from utils import metadata_utils


class PhotoMetadataTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.patch = patch.object(metadata_utils, "BASE_DIR", self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        metadata_utils.read_local_metadata.cache_clear()
        self.addCleanup(metadata_utils.read_local_metadata.cache_clear)

    def original(self, source, name, date=b"2020:06:15 12:34:56"):
        path = self.root / "static" / "photos" / source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        exif = {"0th": {}, "Exif": {piexif.ExifIFD.DateTimeOriginal: date}}
        Image.new("RGB", (20, 15), "red").save(path, exif=piexif.dump(exif))
        return path

    def prepared(self, source, name):
        return self.root / "static" / "prepared" / source / name

    def test_local_original_date_and_variants(self):
        self.original("smartphone", "photo.JPG")
        for name in ("photo.jpg", "photo_polaroid.jpg", "photo_postcard.jpg"):
            with self.subTest(name=name):
                result = metadata_utils.get_photo_metadata(self.prepared("smartphone", name))
                self.assertEqual(result["dateTimeOriginal"], "2020-06-15T12:34:56")

    def test_non_jpeg_original_and_relative_path(self):
        self.original("usb", "photo.png")
        result = metadata_utils.get_photo_metadata(Path("static") / "prepared" / "usb" / "photo.jpg")
        self.assertEqual(result["dateTimeOriginal"], "2020-06-15T12:34:56")

    def test_immich_cache_preserved_but_not_used_for_other_sources(self):
        self.original("smartphone", "photo.jpg")
        cached = {"photo.jpg": {"dateTimeOriginal": "2001-01-01", "city": "Paris"}}
        with patch.object(metadata_utils, "load_photo_metadata_cache", return_value=cached):
            self.assertEqual(metadata_utils.get_photo_metadata(
                self.prepared("immich", "photo_polaroid.jpg")), cached["photo.jpg"])
            local = metadata_utils.get_photo_metadata(self.prepared("smartphone", "photo.jpg"))
            self.assertEqual(local["dateTimeOriginal"], "2020-06-15T12:34:56")
            self.assertNotIn("city", local)

    def test_missing_metadata_is_not_fabricated(self):
        path = self.original("smartphone", "photo.jpg")
        Image.new("RGB", (20, 15)).save(path)
        self.assertEqual(metadata_utils.get_photo_metadata(self.prepared("smartphone", "photo.jpg")), {})
        self.assertEqual(metadata_utils.get_photo_metadata(self.prepared("smartphone", "missing.jpg")), {})

    def test_file_changes_invalidate_metadata_cache(self):
        self.original("smartphone", "photo.jpg")
        prepared = self.prepared("smartphone", "photo.jpg")
        self.assertEqual(metadata_utils.get_photo_metadata(prepared)["dateTimeOriginal"], "2020-06-15T12:34:56")
        self.original("smartphone", "photo.jpg", b"2022:07:16 01:02:03")
        self.assertEqual(metadata_utils.get_photo_metadata(prepared)["dateTimeOriginal"], "2022-07-16T01:02:03")

    def test_iptc_location_is_read(self):
        self.original("smartphone", "photo.jpg")
        with patch.object(metadata_utils.IptcImagePlugin, "getiptcinfo",
                          return_value={(2, 90): b"Paris", (2, 101): b"France"}):
            result = metadata_utils.get_photo_metadata(self.prepared("smartphone", "photo.jpg"))
        self.assertEqual((result["city"], result["country"]), ("Paris", "France"))

    def test_caption_formats_only_enabled_metadata(self):
        metadata = {"dateTimeOriginal": "2020-06-15T12:34:56", "city": "Paris", "country": "France"}
        config = {"show_photo_date": True, "show_photo_location": True,
                  "photo_date_format": "%Y-%m-%d", "anniversary_boost_enabled": False}
        translate = lambda message: message
        self.assertEqual(metadata_utils.format_photo_metadata(metadata, config, translate),
                         "2020-06-15  •  Paris, France")
        self.assertEqual(metadata_utils.format_photo_metadata(metadata, {
            **config, "show_photo_date": False, "photo_location_format": "city"
        }, translate), "Paris")
        self.assertEqual(metadata_utils.format_photo_metadata(metadata, {
            "anniversary_boost_enabled": False
        }, translate), "")
        self.assertEqual(metadata_utils.format_photo_metadata({}, config, translate), "")

    def test_preview_api_caption_and_empty_states(self):
        app = Flask(__name__)
        status_file = self.root / "current.txt"
        status_file.write_text("prepared/smartphone/photo.jpg")
        self.original("smartphone", "photo.jpg")
        running = [True]
        config = {"show_photo_date": True, "photo_date_format": "%Y-%m-%d",
                  "anniversary_boost_enabled": False}
        namespace = {
            "app": app, "login_required": lambda function: function,
            "is_slideshow_running": lambda: running[0], "jsonify": jsonify,
            "CURRENT_PHOTO_FILE": status_file, "os": os, "BASE_DIR": self.root,
            "url_for": url_for, "get_photo_metadata": metadata_utils.get_photo_metadata,
            "format_photo_metadata": metadata_utils.format_photo_metadata,
            "load_config": lambda: config, "_": lambda message: message,
            "logger": logging.getLogger(__name__),
        }
        source = Path(__file__).resolve().parents[1] / "app.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        route = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                     and node.name == "current_photo_status")
        exec(compile(ast.Module(body=[route], type_ignores=[]), str(source), "exec"), namespace)
        client = Client(app, Response)
        response = client.get("/current_photo_status")
        self.assertEqual(response.json["metadata_text"], "2020-06-15")
        config["show_photo_date"] = False
        self.assertEqual(client.get("/current_photo_status").json["metadata_text"], "No Metadata")
        status_file.write_text("")
        self.assertEqual(client.get("/current_photo_status").json["metadata_text"], "")
        running[0] = False
        self.assertEqual(client.get("/current_photo_status").json["status"], "stopped")


if __name__ == "__main__":
    unittest.main()
