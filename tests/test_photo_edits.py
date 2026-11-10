import tempfile
import unittest
import ast
import logging
from pathlib import Path
from unittest.mock import patch

from flask import Flask, request, jsonify, url_for
from PIL import Image
from werkzeug.test import Client
from werkzeug.wrappers import Response

from utils import photo_edits, metadata_utils
from utils.image_filters import apply_filter_to_image
from utils.photo_edit_routes import register_photo_edit_routes


class PhotoEditsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.prepared = self.root / "static" / "prepared"
        self.path = self.prepared / "usb" / "photo.jpg"
        self.path.parent.mkdir(parents=True)
        Image.new("RGB", (40, 30), (200, 80, 40)).save(self.path, quality=100)
        for module, attribute, value in (
                (photo_edits, "EDIT_FILE", self.root / "config" / "photo_edits.json"),
                (metadata_utils, "BASE_DIR", self.root)):
            patcher = patch.object(module, attribute, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.app = Flask(__name__)
        self.app.secret_key = "test"
        self.app.add_url_rule("/login", "login", lambda: "login")
        register_photo_edit_routes(self.app, self.prepared, lambda text: text)
        self.filter_states = {}
        def save_states(states):
            self.filter_states = dict(states)
        namespace = {
            "app": self.app, "login_required": lambda function: function,
            "request": request, "jsonify": jsonify, "url_for": url_for,
            "PREPARED_DIR": self.prepared, "apply_filter_to_image": apply_filter_to_image,
            "load_filter_states": lambda: dict(self.filter_states), "save_filter_states": save_states,
            "load_text_states": lambda: {},
            "logger": logging.getLogger(__name__),
        }
        source = Path(__file__).resolve().parents[1] / "app.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        route = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                     and node.name == "apply_filter_api")
        exec(compile(ast.Module(body=[route], type_ignores=[]), str(source), "exec"), namespace)
        self.client = Client(self.app, Response)
        serializer = self.app.session_interface.get_signing_serializer(self.app)
        self.client.set_cookie("session", serializer.dumps({"logged_in": True}))

    def test_strength_blending_saved_strength_and_validation(self):
        apply_filter_to_image(str(self.path), "grayscale", 0)
        with Image.open(self.path) as image:
            unchanged = image.getpixel((20, 15))
        photo_edits.update_edit("usb/photo.jpg", {"strength": 0.5})
        apply_filter_to_image(str(self.path), "grayscale")
        with Image.open(self.path) as image:
            halfway = image.getpixel((20, 15))
        apply_filter_to_image(str(self.path), "grayscale", 1)
        with Image.open(self.path) as image:
            full = image.getpixel((20, 15))
        self.assertGreater(unchanged[0] - unchanged[2], halfway[0] - halfway[2])
        self.assertGreater(halfway[0] - halfway[2], full[0] - full[2])
        for invalid in (-1, 2, float("nan"), True, "50"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                apply_filter_to_image(str(self.path), "grayscale", invalid)

    def test_manual_location_and_clear_preserve_photo_and_variants(self):
        original = self.path.read_bytes()
        response = self.client.post("/api/photo_edits", json={
            "photo": "usb/photo.jpg", "location": {"city": "Paris", "country": "FR"}})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["country"], "France")
        self.assertIn("Paris", response.json["location_text"])
        metadata = metadata_utils.get_photo_metadata(self.path.with_name("photo_polaroid.jpg"))
        self.assertEqual(metadata["city"], "Paris")
        self.assertEqual(self.path.read_bytes(), original)
        cleared = self.client.post("/api/photo_edits", json={"photo": "usb/photo.jpg", "location": None})
        self.assertFalse(cleared.json["manual_location"])
        self.assertEqual(cleared.json["location_text"], "No location metadata")

    def test_before_returns_clean_backup_and_requires_login(self):
        original = self.path.read_bytes()
        apply_filter_to_image(str(self.path), "grayscale")
        response = self.client.get("/api/photo_edits?photo=usb/photo.jpg&before=1")
        self.assertEqual(response.data, original)
        response.close()
        self.client.delete_cookie("session")
        self.assertEqual(self.client.get("/api/photo_edits?photo=usb/photo.jpg").status_code, 302)

    def test_invalid_location_and_paths(self):
        for data in (
                {"photo": "../outside.jpg", "location": None},
                {"photo": "usb/photo.jpg", "location": {"city": 2, "country": "France"}},
                {"photo": "usb/photo.jpg", "location": {"city": "Paris", "country": "Not a country"}}):
            with self.subTest(data=data):
                self.assertEqual(self.client.post("/api/photo_edits", json=data).status_code, 400)

    def test_apply_filter_route_saves_strength_and_rejects_invalid_strength(self):
        response = self.client.post("/api/apply_filter", json={
            "photo": "usb/photo.jpg", "filter": "grayscale", "strength": 0.4})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.filter_states["usb/photo.jpg"], "grayscale")
        self.assertEqual(self.client.get("/api/photo_edits?photo=usb/photo.jpg").json["strength"], 0.4)
        previous = self.path.read_bytes()
        invalid = self.client.post("/api/apply_filter", json={
            "photo": "usb/photo.jpg", "filter": "grayscale", "strength": 3})
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(self.path.read_bytes(), previous)

    def test_settings_failure_rolls_filter_image_and_preference_back(self):
        previous = self.path.read_bytes()
        with patch.object(photo_edits, "update_edit", side_effect=OSError("Simulated settings failure")):
            response = self.client.post("/api/apply_filter", json={
                "photo": "usb/photo.jpg", "filter": "grayscale", "strength": 0.4})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(self.path.read_bytes(), previous)
        self.assertEqual(self.filter_states, {})

    def test_caption_remains_visible_at_zero_strength(self):
        Image.new("RGB", (400, 300), (200, 80, 40)).save(self.path, quality=100)
        apply_filter_to_image(str(self.path), "grayscale", 0, caption="Caption")
        with Image.open(self.path) as image:
            corner = image.getpixel((10, 10))
            caption_pixel = image.getpixel((200, 280))
        self.assertGreater(corner[0], corner[2] + 100)
        self.assertNotEqual(corner, caption_pixel)
