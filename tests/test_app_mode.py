import unittest
from unittest.mock import patch

from utils import config_manager
from utils.app_mode import get_app_mode, VALID_APP_MODES, DEFAULT_APP_MODE


class AppConfigDefaultsTests(unittest.TestCase):
    def test_default_config_contains_background_mode_keys(self):
        config = config_manager.create_default_config()
        self.assertEqual(config["app_mode"], "picture_frame")
        self.assertEqual(config["background_update_interval"], 3600)
        self.assertEqual(config["background_output_format"], "png")
        self.assertEqual(config["background_resolution_mode"], "auto")


class GetAppModeTests(unittest.TestCase):
    def test_default_when_no_config_and_no_env(self):
        with patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("PICTUREFRAME_APP_MODE", None)
            self.assertEqual(get_app_mode(), "picture_frame")
            self.assertEqual(get_app_mode(None), "picture_frame")

    def test_config_value_is_used(self):
        self.assertEqual(get_app_mode({"app_mode": "background_updater"}),
                         "background_updater")
        self.assertEqual(get_app_mode({"app_mode": "picture_frame"}),
                         "picture_frame")

    def test_env_overrides_config(self):
        with patch.dict("os.environ", {"PICTUREFRAME_APP_MODE": "background_updater"}):
            self.assertEqual(
                get_app_mode({"app_mode": "picture_frame"}),
                "background_updater")

    def test_invalid_config_falls_back_to_default(self):
        self.assertEqual(get_app_mode({"app_mode": "screensaver"}), "picture_frame")
        self.assertEqual(get_app_mode({"app_mode": ""}), "picture_frame")

    def test_invalid_env_falls_back_to_config(self):
        with patch.dict("os.environ", {"PICTUREFRAME_APP_MODE": "nonsense"}):
            self.assertEqual(
                get_app_mode({"app_mode": "background_updater"}),
                "background_updater")

    def test_non_string_config_value_falls_back_to_default(self):
        self.assertEqual(get_app_mode({"app_mode": 42}), DEFAULT_APP_MODE)

    def test_valid_modes_are_exposed(self):
        self.assertEqual(tuple(VALID_APP_MODES),
                         ("picture_frame", "background_updater"))


if __name__ == "__main__":
    unittest.main()
