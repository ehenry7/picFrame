import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils import slideshow_manager
from utils.slideshow_manager import (
    SLIDESHOW,
    BACKGROUND,
    is_slideshow_running,
    is_background_updater_running,
    switch_app_mode,
)


def sys_executable():
    return sys.executable


class ProcessSpecTests(unittest.TestCase):
    def test_specs_reference_expected_scripts(self):
        self.assertEqual(SLIDESHOW.script, "local_slideshow.py")
        self.assertEqual(BACKGROUND.script, "background_updater.py")
        self.assertNotEqual(SLIDESHOW.pid_file, BACKGROUND.pid_file)


class RunningCheckTests(unittest.TestCase):
    def test_not_running_without_pid_file(self):
        with patch.object(slideshow_manager.SLIDESHOW, "pid_file",
                          "definitely-missing.pid"):
            self.assertFalse(is_slideshow_running())
        with patch.object(slideshow_manager.BACKGROUND, "pid_file",
                          "definitely-missing.pid"):
            self.assertFalse(is_background_updater_running())

    def test_running_check_matches_script_in_cmdline(self):
        class FakeProcess:
            def is_running(self):
                return True

            def cmdline(self):
                return [sys_executable(), "local_slideshow.py"]

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pid",
                                          delete=False) as handle:
            handle.write("12345")
            pid_path = handle.name
        try:
            with patch.object(slideshow_manager.SLIDESHOW, "pid_file", pid_path), \
                 patch("psutil.pid_exists", return_value=True), \
                 patch("psutil.Process", return_value=FakeProcess()):
                self.assertTrue(is_slideshow_running())
        finally:
            Path(pid_path).unlink(missing_ok=True)

    def test_running_check_rejects_wrong_script(self):
        class FakeProcess:
            def is_running(self):
                return True

            def cmdline(self):
                return [sys_executable(), "some_other_script.py"]

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pid",
                                          delete=False) as handle:
            handle.write("12345")
            pid_path = handle.name
        try:
            with patch.object(slideshow_manager.SLIDESHOW, "pid_file", pid_path), \
                 patch("psutil.pid_exists", return_value=True), \
                 patch("psutil.Process", return_value=FakeProcess()):
                self.assertFalse(is_slideshow_running())
        finally:
            Path(pid_path).unlink(missing_ok=True)


class ModeAwareDispatchTests(unittest.TestCase):
    def test_start_display_process_dispatches_by_mode(self):
        with patch.object(slideshow_manager, "start_slideshow") as start_show, \
             patch.object(slideshow_manager, "start_background_updater") as start_bg, \
             patch.object(slideshow_manager, "_display_spec",
                          return_value=slideshow_manager.SLIDESHOW):
            slideshow_manager.start_display_process()
            start_show.assert_called_once()
            start_bg.assert_not_called()

        with patch.object(slideshow_manager, "start_slideshow") as start_show, \
             patch.object(slideshow_manager, "start_background_updater") as start_bg, \
             patch.object(slideshow_manager, "_display_spec",
                          return_value=slideshow_manager.BACKGROUND):
            slideshow_manager.start_display_process()
            start_bg.assert_called_once()
            start_show.assert_not_called()

    def test_stop_display_process_never_kills_display_in_background_mode(self):
        """Stopping the background updater must not touch display power."""
        with patch.object(slideshow_manager, "stop_background_updater") as stop_bg, \
             patch.object(slideshow_manager, "_display_spec",
                          return_value=slideshow_manager.BACKGROUND):
            slideshow_manager.stop_display_process()
            stop_bg.assert_called_once()


class SwitchAppModeTests(unittest.TestCase):
    def test_invalid_mode_is_ignored(self):
        with patch("utils.slideshow_manager.load_config", return_value={}):
            self.assertEqual(switch_app_mode("nonsense"), "picture_frame")

    def test_switch_persists_mode_and_restarts_processes(self):
        saved = {}

        def fake_save(config):
            saved.update(config)

        with patch("utils.slideshow_manager.load_config",
                   return_value={"app_mode": "picture_frame"}), \
             patch("utils.slideshow_manager.save_config",
                   side_effect=fake_save), \
             patch.object(slideshow_manager, "_stop_process_quietly") as stop_quiet, \
             patch.object(slideshow_manager, "start_slideshow") as start_show, \
             patch.object(slideshow_manager, "start_background_updater") as start_bg:
            result = switch_app_mode("background_updater")
            self.assertEqual(result, "background_updater")
            self.assertEqual(saved.get("app_mode"), "background_updater")
            self.assertEqual(stop_quiet.call_count, 2)
            start_bg.assert_called_once()
            start_show.assert_not_called()

    def test_switch_back_to_picture_frame(self):
        with patch("utils.slideshow_manager.load_config",
                   return_value={"app_mode": "background_updater"}), \
             patch("utils.slideshow_manager.save_config") as save, \
             patch.object(slideshow_manager, "_stop_process_quietly"), \
             patch.object(slideshow_manager, "start_slideshow") as start_show, \
             patch.object(slideshow_manager, "start_background_updater") as start_bg:
            result = switch_app_mode("picture_frame")
            self.assertEqual(result, "picture_frame")
            save.assert_called_once()
            start_show.assert_called_once()
            start_bg.assert_not_called()


class ProcessSpecPidFilesTests(unittest.TestCase):
    def test_pid_files_live_in_temp_dir(self):
        import platform_utils
        temp = platform_utils.get_temp_dir()
        self.assertIn(temp, slideshow_manager.SLIDESHOW.pid_file.parents)
        self.assertIn(temp, slideshow_manager.BACKGROUND.pid_file.parents)


if __name__ == "__main__":
    unittest.main()
