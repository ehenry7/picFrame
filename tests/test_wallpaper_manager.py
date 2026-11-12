import unittest
from unittest.mock import patch

from utils import wallpaper_manager


class SafeFailContractTests(unittest.TestCase):
    def test_set_wallpaper_missing_file_returns_false(self):
        self.assertFalse(wallpaper_manager.set_wallpaper(
            r"C:\definitely\not\here\missing.png"))

    def test_set_wallpaper_never_raises_on_missing_file(self):
        with patch.object(wallpaper_manager, "IS_WINDOWS", False), \
             patch.object(wallpaper_manager, "IS_LINUX", False):
            self.assertFalse(wallpaper_manager.set_wallpaper("whatever.png"))

    def test_get_monitors_returns_non_empty_list(self):
        monitors = wallpaper_manager.get_monitors()
        self.assertGreater(len(monitors), 0)
        for width, height in monitors:
            self.assertGreater(width, 0)
            self.assertGreater(height, 0)

    def test_get_monitors_config_fallback(self):
        with patch.object(wallpaper_manager, "_windows_monitors", return_value=[]), \
             patch.object(wallpaper_manager, "_linux_monitors", return_value=[]):
            monitors = wallpaper_manager.get_monitors(
                {"display_width": 2560, "display_height": 1440})
            self.assertEqual(monitors, [(2560, 1440)])

    def test_get_monitors_hard_fallback(self):
        with patch.object(wallpaper_manager, "_windows_monitors", return_value=[]), \
             patch.object(wallpaper_manager, "_linux_monitors", return_value=[]):
            self.assertEqual(wallpaper_manager.get_monitors(),
                             [(1920, 1080)])

    def test_largest_monitor_size(self):
        size = wallpaper_manager.largest_monitor_size()
        self.assertIsInstance(size, tuple)
        self.assertEqual(len(size), 2)


class DesktopEnvironmentTests(unittest.TestCase):
    def test_windows_reports_empty(self):
        if wallpaper_manager.IS_WINDOWS:
            self.assertEqual(wallpaper_manager.desktop_environment(), "")

    def test_linux_detection_by_xdg(self):
        with patch.dict("os.environ",
                        {"XDG_CURRENT_DESKTOP": "GNOME"}):
            if wallpaper_manager.IS_LINUX:
                self.assertEqual(wallpaper_manager.desktop_environment(), "gnome")

    def test_plasma_maps_to_kde(self):
        with patch.dict("os.environ",
                        {"XDG_CURRENT_DESKTOP": "KDE Plasma"}), \
             patch.object(wallpaper_manager, "IS_LINUX", True), \
             patch.object(wallpaper_manager, "IS_WINDOWS", False):
            self.assertEqual(wallpaper_manager.desktop_environment(), "kde")


class LinuxSettersTests(unittest.TestCase):
    def test_unknown_de_returns_false_without_raising(self):
        with patch.object(wallpaper_manager, "IS_LINUX", True), \
             patch.object(wallpaper_manager, "IS_WINDOWS", False), \
             patch.object(wallpaper_manager, "desktop_environment",
                          return_value=""), \
             patch.object(wallpaper_manager, "_run", return_value=False):
            self.assertFalse(wallpaper_manager.set_wallpaper(__file__))


if __name__ == "__main__":
    unittest.main()
