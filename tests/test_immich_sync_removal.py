import ast
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from jinja2 import Environment
from utils import config_manager


ROOT = Path(__file__).resolve().parents[1]


class ImmichSyncRemovalTests(unittest.TestCase):
    def test_worker_removed_but_manual_import_and_scheduler_remain(self):
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        functions = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
        self.assertTrue({"immich_update_worker", "immich_update_status"}.isdisjoint(functions))
        for token in ("immich-sync", "immich_status_manager", "WorkerStatus",
                      "immich_auto_update", "immich_update_interval_hours",
                      "skip_initial_auto_import"):
            self.assertNotIn(token, source)
        for function in ("import_immich", "prepare_photos", "schedule_worker"):
            self.assertIn(function, functions)
        self.assertIn('("slideshow-scheduler", schedule_worker)', source)
        self.assertIn("download_and_extract_album(config)", source)

    def test_ui_keeps_manual_import_without_worker_settings_or_polling(self):
        source = (ROOT / "templates" / "configure.html.jinja").read_text(encoding="utf-8")
        Environment(extensions=["jinja2.ext.i18n"]).parse(source)
        for token in ("immich_auto_update", "immich_update_interval_hours",
                      "skip_initial_auto_import", "immich-worker-status",
                      "fetchWorkerStatus", "_update_status"):
            self.assertNotIn(token, source)
        for token in ("immich-import-btn", "immich_url", "immich_token",
                      "album_name", "max_photos_to_download_immich"):
            self.assertIn(token, source)

    def test_no_setup_or_documentation_references_to_removed_worker(self):
        for filename in ("setup.sh", "start_pictureframe.sh", "AGENTS.md",
                         "README.md", "README_en.md", "FAQ.md", "FAQ_en.md"):
            text = (ROOT / filename).read_text(encoding="utf-8")
            for token in ("immich-sync", "immich_update_worker", "immich_auto_update",
                          "immich_update_interval_hours", "skip_initial_auto_import"):
                self.assertNotIn(token, text)

    def test_legacy_auto_sync_settings_removed_on_load_and_save(self):
        retired = {"immich_auto_update": True, "immich_update_interval_hours": 1,
                   "skip_initial_auto_import": True}
        preserved = {"immich_url": "https://photos.example", "immich_token": "placeholder",
                     "album_name": "Family", "display_sources": ["immich", "usb"]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
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
