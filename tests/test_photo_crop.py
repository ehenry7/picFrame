import ast
import io
import logging
import shutil
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import piexif
from flask import Flask, Response, jsonify, request
from PIL import Image, ImageOps
from werkzeug.test import Client

from utils import photo_crop
from utils.auth import login_required


ROOT = Path(__file__).resolve().parents[1]


def extract_functions(filename, names, namespace):
    tree = ast.parse((ROOT / filename).read_text(encoding="utf-8"))
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    if len(nodes) != len(names):
        raise AssertionError("Missing test target")
    exec(compile(ast.Module(body=nodes, type_ignores=[]), filename, "exec"), namespace)


class PhotoCropTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.photo = "smartphone/photo.jpg"
        self.original = self.root / "static" / "photos" / self.photo
        self.prepared = self.root / "static" / "prepared" / self.photo
        self.original.parent.mkdir(parents=True)
        self.prepared.parent.mkdir(parents=True)
        image = Image.new("RGB", (400, 200), "blue")
        image.paste("red", (0, 0, 200, 200))
        image.save(self.original)
        image.save(self.prepared)
        self.original_bytes = self.original.read_bytes()
        for name, value in (("BASE_DIR", self.root), ("CROP_FILE", self.root / "config" / "crop_states.json")):
            patcher = patch.object(photo_crop, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.crop = {"x": 0.05, "y": 0.1, "width": 0.4, "height": 0.8}
        self.config = {"display_width": 100, "display_height": 100, "screen_height_percent": 100}
        self.prepare_namespace = {
            "load_config": lambda: self.config, "Image": Image, "ImageOps": ImageOps,
            "Path": Path, "load_crops": photo_crop.load_crops, "apply_crop": photo_crop.apply_crop,
            "get_pi_model": lambda: 4, "piexif": piexif,
            "create_polaroid_effect": lambda image: image,
            "create_postcard_effect": lambda image, **kwargs: image.convert("RGBA"),
            "os": __import__("os"), "HEIF_SUPPORT": False,
            "logger": logging.getLogger(__name__),
        }
        extract_functions("utils/prepare_all_photos.py", {"prepare_photo"}, self.prepare_namespace)
        self.prepare = self.prepare_namespace["prepare_photo"]
        module = types.ModuleType("utils.prepare_all_photos")
        module.prepare_photo = self.prepare
        patcher = patch.dict("sys.modules", {"utils.prepare_all_photos": module})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.app = Flask(__name__)
        self.app.secret_key = "test-only"
        self.app.add_url_rule("/login", "login", lambda: "Login")
        self.restart = Mock()
        self.namespace = {
            "app": self.app, "login_required": login_required, "request": request,
            "jsonify": jsonify, "Response": Response, "io": io, "tempfile": tempfile,
            "shutil": shutil, "Path": Path, "BASE_DIR": self.root,
            "original_photo": photo_crop.original_photo, "oriented_image": photo_crop.oriented_image,
            "validate_crop": photo_crop.validate_crop, "load_crops": photo_crop.load_crops,
            "save_crops": photo_crop.save_crops, "load_config": lambda: self.config,
            "CROP_LOCK": photo_crop.CROP_LOCK,
            "load_text_states": lambda: {}, "load_polaroid_texts": lambda: {},
            "load_filter_states": lambda: {}, "is_slideshow_running": lambda: True,
            "restart_slideshow_for_update": self.restart, "_": lambda message: message,
            "logger": logging.getLogger(__name__), "add_text_to_image": Mock(),
            "add_text_to_polaroid": Mock(), "apply_filter_to_image": Mock(),
        }
        extract_functions("app.py", {"photo_crop"}, self.namespace)
        self.client = Client(self.app, Response)

    def login(self):
        serializer = self.app.session_interface.get_signing_serializer(self.app)
        self.client.set_cookie("session", serializer.dumps({"logged_in": True}))

    def test_authentication(self):
        self.assertEqual(self.client.get("/api/photo_crop", query_string={"photo": self.photo}).status_code, 302)
        self.assertEqual(self.client.post("/api/photo_crop", json={"photo": self.photo, "crop": self.crop}).status_code, 302)

    def test_save_reset_and_future_preparation(self):
        self.login()
        details = self.client.get("/api/photo_crop", query_string={"photo": self.photo}).json
        self.assertEqual((details["width"], details["height"], details["aspect_ratio"]), (400, 200, 1))
        preview = self.client.get("/api/photo_crop", query_string={"photo": self.photo, "image": "1"})
        self.assertEqual(preview.mimetype, "image/jpeg")
        response = self.client.post("/api/photo_crop", json={"photo": self.photo, "crop": self.crop})
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(photo_crop.load_crops()[self.photo], self.crop)
        self.assertEqual(self.original.read_bytes(), self.original_bytes)
        with Image.open(self.prepared) as image:
            self.assertGreater(image.getpixel((90, 50))[0], 200)
        self.prepare(str(self.original), str(self.prepared), 100, 100, source_type="smartphone")
        with Image.open(self.prepared) as image:
            self.assertGreater(image.getpixel((90, 50))[0], 200)
        reset = self.client.post("/api/photo_crop", json={"photo": self.photo, "crop": None})
        self.assertEqual(reset.status_code, 200, reset.json)
        self.assertNotIn(self.photo, photo_crop.load_crops())
        with Image.open(self.prepared) as image:
            self.assertGreater(image.getpixel((90, 50))[2], 200)
        self.assertEqual(self.original.read_bytes(), self.original_bytes)
        self.assertEqual(self.restart.call_count, 2)

    def test_invalid_selection_and_paths_are_rejected(self):
        self.login()
        bad_crops = [
            {}, {**self.crop, "x": -0.1}, {**self.crop, "width": 0},
            {**self.crop, "width": 1}, {**self.crop, "width": float("nan")},
            {**self.crop, "x": True}, {**self.crop, "height": 0.1},
        ]
        for crop in bad_crops:
            with self.subTest(crop=crop):
                result = self.client.post("/api/photo_crop", json={"photo": self.photo, "crop": crop})
                self.assertEqual(result.status_code, 400)
        for photo in ("../photo.jpg", "/etc/passwd", "smartphone/../photo.jpg",
                      "smartphone\\photo.jpg", "smartphone/missing.jpg"):
            self.assertEqual(self.client.get("/api/photo_crop", query_string={"photo": photo}).status_code, 400)
        self.assertEqual(self.prepared.read_bytes(), self.original_bytes)
        self.restart.assert_not_called()

    def test_failed_preparation_keeps_settings_and_images(self):
        self.login()
        with patch("utils.prepare_all_photos.prepare_photo", return_value=None):
            response = self.client.post("/api/photo_crop", json={"photo": self.photo, "crop": self.crop})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(photo_crop.load_crops(), {})
        self.assertEqual(self.prepared.read_bytes(), self.original_bytes)

    def test_settings_failure_restores_images(self):
        self.login()
        self.namespace["save_crops"] = Mock(side_effect=OSError("Disk full"))
        response = self.client.post("/api/photo_crop", json={"photo": self.photo, "crop": self.crop})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(self.prepared.read_bytes(), self.original_bytes)
        self.assertFalse(self.prepared.with_name("photo_polaroid.jpg").exists())

    def test_concurrent_crop_returns_busy(self):
        self.login()
        with photo_crop.CROP_LOCK:
            response = self.client.post("/api/photo_crop", json={"photo": self.photo, "crop": self.crop})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.prepared.read_bytes(), self.original_bytes)

    def test_portrait_full_selection_has_blurred_padding(self):
        image = Image.new("RGB", (200, 400), "red")
        image.paste("blue", (0, 0, 200, 30))
        image.paste("green", (0, 370, 200, 400))
        image.save(self.original)
        self.config.update(display_width=640, display_height=360)
        width = (16 / 9) * 2
        crop = {"x": (1 - width) / 2, "y": 0, "width": width, "height": 1}
        photo_crop.validate_crop(crop, image.size, (640, 360))
        result = photo_crop.apply_crop(image, crop)
        self.assertAlmostEqual(result.width / result.height, 16 / 9, places=2)
        self.assertEqual(result.getpixel((result.width // 2, 5)), (0, 0, 255))
        self.assertEqual(result.getpixel((result.width // 2, result.height - 5)), (0, 128, 0))
        self.assertNotEqual(result.getpixel((10, result.height // 2)), (0, 0, 0))
        self.login()
        response = self.client.post("/api/photo_crop", json={"photo": self.photo, "crop": crop})
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(photo_crop.load_crops()[self.photo], crop)

    def test_exif_orientation_matches_preparation(self):
        self.login()
        exif = piexif.dump({"0th": {piexif.ImageIFD.Orientation: 6}})
        Image.new("RGB", (400, 200), "red").save(self.original, exif=exif)
        response = self.client.get("/api/photo_crop", query_string={"photo": self.photo})
        self.assertEqual((response.json["width"], response.json["height"]), (200, 400))
        crop = {"x": 0.1, "y": 0.05, "width": 0.8, "height": 0.4}
        self.assertEqual(self.client.post("/api/photo_crop", json={"photo": self.photo, "crop": crop}).status_code, 200)

    def test_real_effects_filters_and_captions_are_preserved(self):
        from utils import image_filters
        self.login()
        self.prepare_namespace["create_polaroid_effect"] = image_filters.create_polaroid_effect
        self.prepare_namespace["create_postcard_effect"] = image_filters.create_postcard_effect
        self.config.update(display_width=640, display_height=640)
        self.namespace.update({
            "load_text_states": lambda: {self.photo: "Caption"},
            "load_polaroid_texts": lambda: {self.photo: "Polaroid caption"},
            "load_filter_states": lambda: {self.photo: "grayscale"},
            "add_text_to_image": image_filters.add_text_to_image,
            "add_text_to_polaroid": image_filters.add_text_to_polaroid,
            "apply_filter_to_image": image_filters.apply_filter_to_image,
        })
        with patch.object(image_filters, "USER_TEXT_MAP_CACHE_FILE", self.root / "user_texts.json"):
            result = self.client.post("/api/photo_crop", json={"photo": self.photo, "crop": self.crop})
        self.assertEqual(result.status_code, 200, result.json)
        for suffix in ("", "_polaroid", "_postcard"):
            with Image.open(self.prepared.with_name(f"photo{suffix}.jpg")) as image:
                self.assertEqual(image.size, (640, 640))
        with Image.open(self.prepared) as image:
            red, green, blue = image.getpixel((320, 100))
            self.assertLessEqual(abs(red - green), 2)
            self.assertLessEqual(abs(green - blue), 2)
        backup = self.root / "static" / ".backups" / self.photo
        with Image.open(backup) as image:
            self.assertGreater(image.getpixel((320, 100))[0], 200)
        self.assertEqual(self.original.read_bytes(), self.original_bytes)


if __name__ == "__main__":
    unittest.main()
