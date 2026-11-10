import ast
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from jinja2 import Environment
from utils import config_manager


ROOT = Path(__file__).resolve().parents[1]


class VoiceRemovalTests(unittest.TestCase):
    def test_retired_settings_removed_while_media_audio_is_preserved(self):
        settings = {"voice_control_enabled": True, "voice_control_engine": "vosk",
                    "porcupine_access_key": "test-key", "voice_control_language": "en",
                    "notification_sound_volume": 20, "video_audio_volume": 65,
                    "video_audio_enabled": True, "playlist_music": "music.mp3"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps(settings))
            with patch.object(config_manager, "CONFIG_PATH", str(path)), \
                    patch.object(config_manager, "_config_cache", None), \
                    patch.object(config_manager, "_last_config_load", 0):
                loaded = config_manager.load_config()
                self.assertFalse(any(key.startswith(("voice_control_", "porcupine_"))
                                     for key in loaded))
                self.assertNotIn("notification_sound_volume", loaded)
                self.assertEqual(loaded["video_audio_volume"], 65)
                self.assertTrue(loaded["video_audio_enabled"])
                self.assertEqual(loaded["playlist_music"], "music.mp3")
                config_manager.save_config(settings)
                self.assertEqual(json.loads(path.read_text()),
                                 {"video_audio_volume": 65, "video_audio_enabled": True,
                                  "playlist_music": "music.mp3"})

    def test_application_has_no_voice_routes_or_imports(self):
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        functions = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
        self.assertTrue({"get_audio_devices", "get_audio_diagnostics",
                         "get_voice_control_status", "toggle_voice_control"}.isdisjoint(functions))
        self.assertNotIn("voice_control", source)
        self.assertIn("def get_music_files", source)
        self.assertFalse((ROOT / "voice_control.py").exists())
        self.assertFalse((ROOT / "utils" / "voice_control_manager.py").exists())

    def test_template_removes_voice_controls_but_retains_playback_audio(self):
        source = (ROOT / "templates" / "configure.html.jinja").read_text(encoding="utf-8")
        Environment(extensions=["jinja2.ext.i18n"]).parse(source)
        for token in ("tab-vocal", "voice_control", "porcupine", "/api/audio_devices",
                      "fetchVoiceControlStatus", "notification_sound_volume"):
            self.assertNotIn(token, source)
        self.assertIn("video_audio_volume", source)
        self.assertIn("new-playlist-music", source)
