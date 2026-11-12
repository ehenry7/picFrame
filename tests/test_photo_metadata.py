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
from utils.path_utils import to_static_url_path


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

    def test_missing_metadata_falls_back_to_file_date(self):
        path = self.original("smartphone", "photo.jpg")
        Image.new("RGB", (20, 15)).save(path)
        # No EXIF date → falls back to file modification time
        result = metadata_utils.get_photo_metadata(self.prepared("smartphone", "photo.jpg"))
        self.assertIn("dateTimeOriginal", result)
        self.assertEqual(result.get("dateSource"), "file")
        # Truly missing file → empty dict
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

    def test_preview_location_missing_partial_and_country_code(self):
        translate = lambda message: message
        for metadata, expected in (
                ({}, "No location metadata"),
                ({"city": "Paris"}, "Paris"),
                ({"country": "France"}, "\U0001f1eb\U0001f1f7 France"),
                ({"city": "Paris", "countryCode": "FR"}, "\U0001f1eb\U0001f1f7 Paris, France"),
                ({"country": "fr"}, "\U0001f1eb\U0001f1f7 France"),
                ({"country": "Unknown"}, "Unknown")):
            with self.subTest(metadata=metadata):
                self.assertEqual(metadata_utils.format_preview_location(metadata, translate), expected)

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
            "is_display_process_running": lambda: running[0],
            "CURRENT_PHOTO_FILE": status_file, "os": os, "BASE_DIR": self.root,
            "url_for": url_for, "get_photo_metadata": metadata_utils.get_photo_metadata,
            "format_photo_metadata": metadata_utils.format_photo_metadata,
            "format_preview_location": metadata_utils.format_preview_location,
            "to_static_url_path": to_static_url_path,
            "load_config": lambda: config, "_": lambda message: message,
            "logger": logging.getLogger(__name__),
            "get_app_mode": lambda _config=None: "picture_frame",
            "BACKGROUND_STATUS_FILE": self.root / "background_status.json",
        }
        source = Path(__file__).resolve().parents[1] / "app.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        route = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                     and node.name == "current_photo_status")
        exec(compile(ast.Module(body=[route], type_ignores=[]), str(source), "exec"), namespace)
        client = Client(app, Response)
        response = client.get("/current_photo_status")
        self.assertEqual(response.json["metadata_text"], "2020-06-15")
        self.assertEqual(response.json["location_text"], "No location metadata")
        with patch.object(metadata_utils.IptcImagePlugin, "getiptcinfo",
                          return_value={(2, 90): b"Paris", (2, 101): b"France"}):
            metadata_utils.read_local_metadata.cache_clear()
            self.assertEqual(client.get("/current_photo_status").json["location_text"],
                             "\U0001f1eb\U0001f1f7 Paris, France")
        metadata_utils.read_local_metadata.cache_clear()
        config["photo_date_format"] = "%d/%m/%Y - %H:%M"
        self.assertEqual(client.get("/current_photo_status").json["metadata_text"],
                         "15/06/2020 - 12:34")
        config["show_photo_date"] = False
        self.assertEqual(client.get("/current_photo_status").json["metadata_text"], "No Metadata")
        status_file.write_text("")
        self.assertEqual(client.get("/current_photo_status").json["metadata_text"], "")
        running[0] = False
        self.assertEqual(client.get("/current_photo_status").json["status"], "stopped")

    def test_preview_tiles_include_formatted_metadata(self):
        self.original("smartphone", "photo.jpg")
        prepared = self.prepared("smartphone", "photo.jpg")
        prepared.parent.mkdir(parents=True)
        Image.new("RGB", (20, 15)).save(prepared)
        Image.new("RGB", (20, 15)).save(prepared.with_name("empty.jpg"))
        config = {"show_photo_date": True, "photo_date_format": "%Y-%m-%d",
                  "anniversary_boost_enabled": False}
        namespace = {
            "PREPARED_DIR": prepared.parent.parent, "load_config": lambda: config,
            "load_filter_states": lambda: {}, "load_favorites": lambda: ["smartphone/photo.jpg"],
            "load_polaroid_texts": lambda: {}, "load_text_states": lambda: {},
            "VIDEO_EXTENSIONS": (".mp4",), "get_photo_metadata": metadata_utils.get_photo_metadata,
            "format_photo_metadata": metadata_utils.format_photo_metadata,
            "format_preview_location": metadata_utils.format_preview_location,
            "_": lambda message: message,
        }
        source = Path(__file__).resolve().parents[1] / "app.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                        and node.name == "get_prepared_photos_by_source")
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), namespace)
        media = namespace["get_prepared_photos_by_source"]()["smartphone"]
        by_name = {item["path"]: item for item in media}
        self.assertEqual(by_name["smartphone/photo.jpg"]["metadata_text"], "2020-06-15")
        self.assertTrue(by_name["smartphone/photo.jpg"]["is_favorite"])
        # empty.jpg has no EXIF but now falls back to file date
        self.assertNotEqual(by_name["smartphone/empty.jpg"]["metadata_text"], "No Metadata")
        self.assertRegex(by_name["smartphone/empty.jpg"]["metadata_text"], r"^\d{4}-\d{2}-\d{2}$")

    def test_photo_date_format_save_and_reload(self):
        from flask import request
        from utils import config_manager
        source = Path(__file__).resolve().parents[1] / "app.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        saving = next(node for node in ast.walk(tree) if isinstance(node, ast.For)
                      and isinstance(node.iter, ast.List)
                      and any(isinstance(value, ast.Constant) and value.value == "photo_date_format"
                              for value in node.iter.elts))
        app = Flask(__name__)
        config = {}
        namespace = {"config": config, "request": request}
        with app.test_request_context(method="POST", data={"photo_date_format": "%d/%m/%Y - %H:%M"}):
            exec(compile(ast.Module(body=[saving], type_ignores=[]), str(source), "exec"), namespace)
        with patch.object(config_manager, "CONFIG_PATH", str(self.root / "config.json")), \
             patch.object(config_manager, "_config_cache", None), \
             patch.object(config_manager, "_last_config_load", 0):
            config_manager.save_config(config)
            config_manager._config_cache = None
            reloaded = config_manager.load_config()
        self.assertEqual(reloaded["photo_date_format"], "%d/%m/%Y - %H:%M")
        self.assertEqual(metadata_utils.format_photo_metadata(
            {"dateTimeOriginal": "2020-06-15T12:34:56"},
            {**reloaded, "show_photo_date": True, "anniversary_boost_enabled": False},
            lambda message: message), "15/06/2020 - 12:34")


if __name__ == "__main__":
    unittest.main()
