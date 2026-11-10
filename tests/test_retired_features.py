import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

import polib
from utils import config_manager


ROOT = Path(__file__).resolve().parents[1]


class RetiredFeaturesTests(unittest.TestCase):
    def test_code_setup_and_documentation_have_no_removed_integrations(self):
        paths = [ROOT / name for name in (
            "app.py", "local_slideshow.py", "setup.sh", "start_pimmich.sh",
            "requirements.txt", "requirements-pi.txt", "README.md", "README_en.md",
            "FAQ.md", "FAQ_en.md", "AGENTS.md", "procedure_trad.md",
            "enable_auto_frame_start.sh", "disable_auto_frame_start.sh",
        )]
        paths += list((ROOT / "templates").glob("*.jinja"))
        paths += list((ROOT / "static").glob("*.js"))
        paths += [path for path in (ROOT / "utils").glob("*.py")
                  if path.name != "config_manager.py"]
        retired = re.compile(
            r"telegram|porcupine|picovoice|vosk|\bvoice_control|\bcontrôle vocal|"
            r"\bvoice control|samba|\bsmbclient|\bsmbprotocol|cifs-utils|"
            r"immich-sync|immich_update_worker|immich_update_status|"
            r"update_script\.sh|update\.html\.jinja|/api/update_app|update-app-btn",
            re.I,
        )
        for path in paths:
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertIsNone(retired.search(path.read_text(encoding="utf-8")))
        for filename in ("voice_control.py", "utils/voice_control_manager.py",
                         "utils/import_samba.py", "utils/telegram_bot.py",
                         "update_script.sh", "templates/update.html.jinja"):
            self.assertFalse((ROOT / filename).exists(), filename)

    def test_catalogs_do_not_keep_retired_feature_strings(self):
        for path in [ROOT / "translations" / "messages.pot",
                     *ROOT.glob("translations/*/LC_MESSAGES/messages.po")]:
            for entry in polib.pofile(str(path)):
                with self.subTest(catalog=path, msgid=entry.msgid):
                    self.assertIsNone(re.search(
                        r"telegram|porcupine|picovoice|vosk|\bvocal|\bvoice|samba|\bsmb",
                        entry.msgid, re.I))
                    if entry.obsolete:
                        self.assertIsNone(re.search(r"mise[s]? à jour|update", entry.msgid, re.I))

    def test_legacy_telegram_settings_are_discarded_not_guest_uploads(self):
        settings = {"telegram_bot_token": "placeholder", "telegram_bot_enabled": True,
                    "telegram_authorized_users": [], "display_sources": ["invités", "usb"],
                    "display_duration": 10}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps(settings), encoding="utf-8")
            with patch.object(config_manager, "CONFIG_PATH", str(path)), \
                    patch.object(config_manager, "_config_cache", None), \
                    patch.object(config_manager, "_last_config_load", 0):
                loaded = config_manager.load_config()
                self.assertFalse(any(key.startswith("telegram_") for key in loaded))
                config_manager.save_config(settings)
                self.assertEqual(json.loads(path.read_text(encoding="utf-8")),
                                 {"display_sources": ["invités", "usb"], "display_duration": 10})
