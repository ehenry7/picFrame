import ast
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from jinja2 import Environment
from utils import config_manager


ROOT = Path(__file__).resolve().parents[1]


class SambaRemovalTests(unittest.TestCase):
    def test_application_and_setup_have_no_samba_integration(self):
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        functions = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
        for token in ("samba", "smbclient", "smbprotocol", "smb_"):
            self.assertNotIn(token, source)
        self.assertIn("import_immich", functions)
        self.assertIn("import_usb", functions)
        self.assertIn("import_smartphone", functions)
        self.assertFalse((ROOT / "utils" / "import_samba.py").exists())
        for filename in ("setup.sh", "requirements.txt", "requirements-pi.txt"):
            text = (ROOT / filename).read_text(encoding="utf-8")
            for token in ("smbclient", "smbprotocol", "cifs-utils"):
                self.assertNotIn(token, text)

    def test_ui_keeps_other_photo_sources(self):
        source = (ROOT / "templates" / "configure.html.jinja").read_text(encoding="utf-8")
        Environment(extensions=["jinja2.ext.i18n"]).parse(source)
        self.assertNotIn("samba", source.lower())
        self.assertNotIn("smb_", source)
        for token in ("immich-import-btn", "usb-import-btn", "photo-folder-input"):
            self.assertIn(token, source)

    def test_retired_configuration_is_removed_on_load_and_save(self):
        settings = {
            "smb_host": "old-host", "smb_share": "photos", "smb_user": "old-user",
            "smb_password": "placeholder", "smb_auto_update": True,
            "smb_update_interval_hours": 24, "smb_path": "/photos",
            "display_sources": ["immich", "samba", "usb", "smartphone"],
            "max_photos_to_download": {"immich": 30, "samba": 100},
            "immich_url": "https://photos.example", "display_duration": 12,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps(settings), encoding="utf-8")
            with patch.object(config_manager, "CONFIG_PATH", str(path)), \
                    patch.object(config_manager, "_config_cache", None), \
                    patch.object(config_manager, "_last_config_load", 0):
                loaded = config_manager.load_config()
                self.assertFalse(any(key.startswith("smb_") for key in loaded))
                self.assertEqual(loaded["display_sources"], ["immich", "usb", "smartphone"])
                self.assertEqual(loaded["max_photos_to_download"], {"immich": 30})
                self.assertEqual(loaded["immich_url"], "https://photos.example")
                self.assertEqual(loaded["display_duration"], 12)
                config_manager.save_config(settings)
                saved = json.loads(path.read_text(encoding="utf-8"))
                expected = {key: value for key, value in settings.items()
                            if not key.startswith("smb_")}
                expected["display_sources"] = ["immich", "usb", "smartphone"]
                expected["max_photos_to_download"] = {"immich": 30}
                self.assertEqual(saved, expected)
