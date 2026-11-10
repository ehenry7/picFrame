import gettext
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

from flask import Flask
from jinja2 import Environment
import polib
from werkzeug.test import Client
from werkzeug.wrappers import Response


ROOT = Path(__file__).resolve().parents[1]


class AppBrandingTests(unittest.TestCase):
    def test_templates_and_logo_use_pictureframe(self):
        environment = Environment(extensions=["jinja2.ext.i18n"])
        for path in (ROOT / "templates").glob("*.jinja"):
            source = path.read_text(encoding="utf-8")
            environment.parse(source)
            self.assertNotIn("Pimmich", source)
            self.assertNotIn("pimmich_logo.png", source)
            if "<title>" in source:
                self.assertIn("PictureFrame", source)
        logo = ROOT / "static" / "pictureframe_logo.svg"
        tree = ET.parse(logo)
        self.assertIn("PictureFrame", "".join(tree.getroot().itertext()))
        app = Flask(__name__, static_folder=str(ROOT / "static"))
        response = Client(app, Response).get("/static/pictureframe_logo.svg")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "image/svg+xml")
        response.close()

    def test_translations_use_the_new_brand(self):
        for locale in ("en", "fr", "he"):
            folder = ROOT / "translations" / locale / "LC_MESSAGES"
            catalog = polib.pofile(str(folder / "messages.po"))
            translator = gettext.translation("messages", ROOT / "translations", [locale])
            branded = [entry for entry in catalog if not entry.obsolete
                       and "PictureFrame" in entry.msgid]
            self.assertGreaterEqual(len(branded), 2)
            for entry in branded:
                translated = translator.gettext(entry.msgid)
                self.assertIn("PictureFrame", translated)
                self.assertNotIn("Pimmich", translated)

    def test_runtime_keeps_legacy_identifiers_and_uses_new_display_name(self):
        app_source = (ROOT / "app.py").read_text(encoding="utf-8")
        slideshow = (ROOT / "local_slideshow.py").read_text(encoding="utf-8")
        self.assertIn("PictureFrame_backup_", app_source)
        self.assertIn("PictureFrame (Serveur Web & Supervisor)", app_source)
        self.assertIn('message_font.render("PictureFrame"', slideshow)
        self.assertNotIn("pimmich_logo.png", slideshow)
        for source in (app_source, slideshow):
            self.assertIn("pimmich_slideshow_status.json", source)
        self.assertIn("pimmich_bbox:", (ROOT / "utils" / "image_filters.py").read_text(encoding="utf-8"))
        self.assertIn("pimmich_bbox:", (ROOT / "utils" / "prepare_all_photos.py").read_text(encoding="utf-8"))
