import ast
import gettext
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import Mock, patch

from flask import Flask, jsonify, request
from jinja2 import Environment, FileSystemLoader
import polib
from werkzeug.test import Client
from werkzeug.wrappers import Response

from utils import config_manager
from utils.image_filters import _get_content_bbox
from PIL import Image
import piexif


ROOT = Path(__file__).resolve().parents[1]


class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = []

    def handle_data(self, data):
        self.text.append(data)

    def handle_starttag(self, tag, attrs):
        self.text.extend(value for key, value in attrs if key in {"title", "alt", "aria-label"} and value)


class PhotoServiceRemovalTests(unittest.TestCase):
    def source_labels(self, translate=lambda message: message):
        tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
        node = next(node for node in tree.body
                    if isinstance(node, ast.FunctionDef) and node.name == "get_photo_source_labels")
        namespace = {"_": translate}
        exec(compile(ast.Module(body=[node], type_ignores=[]), "app.py", "exec"), namespace)
        return namespace["get_photo_source_labels"]

    def test_application_has_no_service_routes_or_download_modules(self):
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        functions = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
        self.assertNotIn("import_immich", functions)
        self.assertNotIn("download_photos", functions)
        self.assertNotRegex(source.lower(), "immich|download_and_extract_album")
        for name in ("import_usb", "import_smartphone", "prepare_photos", "schedule_worker"):
            self.assertIn(name, functions)
        self.assertIn('("slideshow-scheduler", schedule_worker)', source)
        for name in ("download_album.py", "archive_manager.py"):
            self.assertFalse((ROOT / "utils" / name).exists())

    def test_ui_and_docs_no_longer_mention_service(self):
        paths = list((ROOT / "templates").glob("*.jinja"))
        paths += list((ROOT / "static").glob("*.js"))
        paths += [ROOT / name for name in
                  ("README.md", "FAQ.md", "AGENTS.md", "setup.sh")]
        for path in paths:
            with self.subTest(path=path):
                self.assertNotIn("immich", path.read_text(encoding="utf-8").lower())
        template = (ROOT / "templates" / "configure.html.jinja").read_text(encoding="utf-8")
        Environment(extensions=["jinja2.ext.i18n"]).parse(template)
        for token in ("usb-import-btn", "photo-folder-input", "import-smartphone-btn"):
            self.assertIn(token, template)
        for token in ("album_name", "random_content_in_album", "max_photos_to_download"):
            self.assertNotIn(token, template)
        self.assertIn("Smart Connected Photo Frame", (ROOT / "README.md").read_text(encoding="utf-8"))
        self.assertIn("Frequently Asked Questions", (ROOT / "FAQ.md").read_text(encoding="utf-8"))

    def test_retired_settings_removed_without_changing_existing_photo_references(self):
        retired = {"immich_url": "https://photos.example", "immich_token": "placeholder",
                   "immich_auto_update": True, "immich_update_interval_hours": 1,
                   "album_name": "Family", "random_content_in_album": True,
                   "max_photos_to_download": {"immich": 10}, "photo_source": "immich",
                   "skip_initial_auto_import": True}
        preserved = {"display_sources": ["immich", "usb"], "display_duration": 12,
                     "guest_names": {"family": "Family"}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            photo = Path(directory) / "static" / "prepared" / "immich" / "photo.jpg"
            photo.parent.mkdir(parents=True)
            photo.write_bytes(b"existing photo")
            path.write_text(json.dumps({**retired, **preserved}), encoding="utf-8")
            with patch.object(config_manager, "CONFIG_PATH", str(path)), \
                    patch.object(config_manager, "_config_cache", None), \
                    patch.object(config_manager, "_last_config_load", 0):
                loaded = config_manager.load_config()
                self.assertTrue(retired.keys().isdisjoint(loaded))
                for key, value in preserved.items():
                    self.assertEqual(loaded[key], value)
                config_manager.save_config({**retired, **preserved})
                self.assertEqual(json.loads(path.read_text(encoding="utf-8")), preserved)
                self.assertEqual(photo.read_bytes(), b"existing photo")
        defaults = config_manager.create_default_config()
        self.assertTrue(retired.keys().isdisjoint(defaults))
        self.assertEqual(defaults["display_sources"], ["usb", "smartphone", "invités"])

    def test_legacy_sources_render_with_generic_labels_and_keep_selected_paths(self):
        sources = ["immich", "ImmichPhotos", "usb", "smartphone"]
        labels = self.source_labels()(sources)
        self.assertEqual(labels["immich"], "Imported photos")
        self.assertEqual(labels["ImmichPhotos"], "Imported photos")
        self.assertEqual(labels["usb"], "Usb")
        template = (ROOT / "templates" / "configure.html.jinja").read_text(encoding="utf-8")
        fragment = template.split('<div id="tab-sources" class="tabcontent">', 1)[1]
        fragment = fragment.split('<div id="tab-metadata"', 1)[0]
        environment = Environment(extensions=["jinja2.ext.i18n"])
        environment.install_null_translations()
        rendered = environment.from_string(fragment).render(
            source_labels=labels, config={"display_sources": sources})
        visible = VisibleText()
        visible.feed(rendered)
        self.assertNotIn("immich", " ".join(visible.text).lower())
        self.assertIn('value="immich" checked', rendered)
        self.assertIn('value="ImmichPhotos" checked', rendered)
        self.assertIn('button.dataset.sourceLabel', template)

    def test_entire_settings_page_has_no_visible_brand_in_any_language(self):
        media = {"path": "immich/photo.jpg", "type": "image", "is_favorite": True,
                 "has_polaroid": False, "has_postcard": False, "active_filter": "none",
                 "text": "", "polaroid_text": "", "metadata_text": "", "location_text": ""}
        for language in ("en", "fr", "he"):
            with self.subTest(language=language):
                translations = gettext.translation("messages", str(ROOT / "translations"),
                                                   languages=[language])
                environment = Environment(loader=FileSystemLoader(str(ROOT / "templates")),
                                          extensions=["jinja2.ext.i18n"], autoescape=True)
                environment.install_gettext_translations(translations, newstyle=True)
                environment.globals.update(
                    get_locale=lambda: language, get_flashed_messages=lambda **kwargs: [],
                    url_for=lambda endpoint, **kwargs: "/" + endpoint,
                )
                config = config_manager.create_default_config()
                config["display_sources"] = ["immich", "usb"]
                rendered = environment.get_template("configure.html.jinja").render(
                    config=config, prepared_photos_by_source={"immich": [media]},
                    source_labels=self.source_labels(translations.gettext)(config["display_sources"]),
                    favorite_photos=[media], slideshow_running=False, pending_photos=[],
                    available_timezones=["Europe/Paris", "Asia/Jerusalem"])
                # Inline scripts contain preserved on-disk identifiers, not visible labels.
                visible_text = re.sub(r"<script\b[^>]*>.*?</script>", "", rendered, flags=re.S)
                visible = VisibleText()
                visible.feed(visible_text)
                self.assertFalse(re.search("immich", " ".join(visible.text), re.I))

    def test_source_playlist_title_is_generic_and_photo_paths_stay_unchanged(self):
        tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
        node = next(node for node in tree.body
                    if isinstance(node, ast.FunctionDef) and node.name == "play_source_as_playlist")
        node.decorator_list = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "immich"
            source.mkdir()
            (source / "photo.jpg").write_bytes(b"existing photo")
            playlist = root / "playlist.json"
            app = Flask(__name__)
            namespace = {
                "request": request, "jsonify": jsonify, "PREPARED_DIR": root,
                "CUSTOM_PLAYLIST_FILE": playlist, "json": json,
                "get_photo_source_labels": self.source_labels(),
                "stop_slideshow": Mock(), "start_slideshow": Mock(),
                "stop_display_process": Mock(), "start_display_process": Mock(),
                "time": Mock(),
            }
            exec(compile(ast.Module(body=[node], type_ignores=[]), "app.py", "exec"), namespace)
            app.add_url_rule("/play/<source_name>", view_func=namespace["play_source_as_playlist"],
                             methods=["POST"])
            response = Client(app, Response).post("/play/immich",
                                                environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("immich", response.get_json()["message"].lower())
            self.assertEqual(json.loads(playlist.read_text(encoding="utf-8")),
                             {"name": "Source: Imported photos", "photos": ["immich/photo.jpg"]})

    def test_catalogs_and_compiled_messages_have_no_service_brand(self):
        for path in [ROOT / "translations" / "messages.pot",
                     *ROOT.glob("translations/*/LC_MESSAGES/messages.po")]:
            with self.subTest(path=path):
                self.assertNotRegex(path.read_text(encoding="utf-8").lower(), "immich")
                if path.suffix == ".po":
                    compiled = polib.mofile(str(path.with_suffix(".mo")))
                    self.assertTrue(compiled.find("Imported photos").msgstr)
                    for entry in compiled:
                        self.assertIsNone(re.search("immich", entry.msgid + entry.msgstr, re.I))

    def test_new_and_legacy_bbox_metadata_remain_readable(self):
        for prefix in ("pictureframe_bbox:", "pimmich_bbox:"):
            with self.subTest(prefix=prefix):
                image = Image.new("RGB", (20, 20))
                image.info["exif"] = piexif.dump({"Exif": {
                    piexif.ExifIFD.UserComment: f"{prefix}1,2,10,12".encode("ascii")}})
                self.assertEqual(_get_content_bbox(image), (1, 2, 11, 14))
