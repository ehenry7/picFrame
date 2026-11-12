import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import background_updater
import platform_utils
from platform_utils import get_status_file


class BackgroundUpdaterHelpersTests(unittest.TestCase):
    def test_wallpaper_output_path_default(self):
        config = {"background_output_format": "png"}
        path = background_updater.wallpaper_output_path(config)
        self.assertEqual(path.name, "desktop_background.png")
        self.assertEqual(path.parent.name, "cache")

    def test_wallpaper_output_path_invalid_format_falls_back(self):
        config = {"background_output_format": "bmp"}
        path = background_updater.wallpaper_output_path(config)
        self.assertEqual(path.name, "desktop_background.png")

    def test_wallpaper_output_path_alternates_between_two_files(self):
        """Consecutive cycles must produce different file names.

        Windows ignores re-applying the very same wallpaper path, which
        would freeze the clock overlay and the photo rotation.
        """
        config = {"background_output_format": "png"}
        first = background_updater.wallpaper_output_path(config, 0)
        second = background_updater.wallpaper_output_path(config, 1)
        third = background_updater.wallpaper_output_path(config, 2)
        self.assertEqual(first.name, "desktop_background.png")
        self.assertEqual(second.name, "desktop_background_alt.png")
        self.assertEqual(third.name, first.name)
        self.assertNotEqual(first, second)

    def test_resolve_render_size_manual(self):
        config = {"background_resolution_mode": "manual",
                  "display_width": 2560, "display_height": 1440}
        self.assertEqual(
            background_updater.resolve_render_size(config), (2560, 1440))

    def test_resolve_render_size_auto_uses_monitors(self):
        from utils.wallpaper_manager import largest_monitor_size
        config = {"background_resolution_mode": "auto"}
        self.assertEqual(background_updater.resolve_render_size(config),
                         largest_monitor_size(config))

    def test_load_custom_playlist_reads_and_removes(self):
        status_path = Path(get_status_file(
            "pictureframe_custom_playlist.json"))
        with tempfile.TemporaryDirectory() as directory:
            prepared = Path(directory) / "static" / "prepared"
            (prepared / "usb").mkdir(parents=True)
            (prepared / "usb" / "a.jpg").touch()
            playlist_file = Path(directory) / "playlist.json"
            playlist_file.write_text(json.dumps(
                {"name": "Trip", "photos": ["usb/a.jpg"]}), encoding="utf-8")
            with patch.object(background_updater, "CUSTOM_PLAYLIST_FILE",
                              str(playlist_file)), \
                 patch.object(background_updater, "BASE_DIR",
                              Path(directory)):
                loaded = background_updater.load_custom_playlist()
            self.assertEqual(loaded, [str(prepared / "usb" / "a.jpg")])
            # The playlist file must be consumed (removed) after loading.
            self.assertFalse(playlist_file.exists())
            self.assertIsNone(background_updater.load_custom_playlist())

    def test_load_custom_playlist_missing_file(self):
        self.assertIsNone(background_updater.load_custom_playlist())


class BackgroundUpdaterPidGuardTests(unittest.TestCase):
    """The single-instance guard must not kill the process the manager started."""

    def test_own_pid_is_not_a_second_instance(self):
        # Regression: the process manager writes our own PID into the PID
        # file right after spawning us; the guard must treat it as "us".
        import os
        pid_file = Path(background_updater.PID_FILE)
        try:
            with open(pid_file, "w", encoding="utf-8") as f:
                f.write(str(os.getpid()))
            # main() must proceed (reach start_background_updater) instead of
            # returning early. We detect that by making the updater loop fail
            # with a distinctive exception.
            class Started(Exception):
                pass

            def fake_start():
                raise Started()

            with patch.object(background_updater, "start_background_updater",
                              side_effect=fake_start):
                with self.assertRaises(Started):
                    background_updater.main()
            # A clean shutdown removes the PID file we own.
            self.assertFalse(pid_file.exists())
        finally:
            if pid_file.exists():
                pid_file.unlink(missing_ok=True)

    def test_is_background_updater_pid_rejects_foreign_process(self):
        # PID 0 / kernel-ish pid can never match our script name.
        self.assertFalse(background_updater._is_background_updater_pid(0))


class BackgroundUpdaterLoopTests(unittest.TestCase):
    """Single-cycle test of the updater loop with all side effects mocked."""

    maxDiff = None

    def _run_updater(self, wake_ups, commands=()):
        """Run the updater loop until the N-th sleep call.

        Returns the list of paths passed to set_wallpaper and to
        compose_background. Each sleep call queues the next entry of
        ``commands`` first, which simulates a user pressing "next" between
        two cycles (the real loop consumes the whole command queue at
        once, so all commands cannot be queued up-front).
        """
        class WakeUp(Exception):
            pass

        calls = {"set_wallpaper": [], "composed": []}
        commands = list(commands)

        def fake_sleep(_seconds):
            if commands:
                platform_utils.enqueue_slideshow_command(
                    "next", process="background")
            wake_ups.pop()
            if not wake_ups:
                raise WakeUp()

        def fake_compose(path, width, height, config, font, metadata=None, **kwargs):
            import pygame
            calls["composed"].append(Path(path).name)
            return pygame.Surface((width, height))

        with tempfile.TemporaryDirectory() as directory:
            photos = [Path(directory) / f"photo{i}.jpg" for i in range(3)]
            from PIL import Image
            for photo in photos:
                Image.new("RGB", (400, 300), (10, 200, 90)).save(photo)
            media = [str(p) for p in photos]

            with tempfile.TemporaryDirectory() as command_dir:
                def fake_command_dir(process="slideshow"):
                    return Path(command_dir)

                # start_background_updater() imports its helpers lazily from
                # utils.render_pipeline / utils.wallpaper_manager, so patch
                # there.
                with patch("utils.render_pipeline.build_media_playlist",
                                  side_effect=lambda config: media), \
                     patch("utils.render_pipeline.compose_background",
                           side_effect=fake_compose), \
                     patch("utils.render_pipeline.save_surface_atomic",
                           return_value=True), \
                     patch("utils.render_pipeline.warm_up_overlays"), \
                     patch("utils.wallpaper_manager.set_wallpaper_per_monitor",
                           side_effect=lambda imgs: calls["set_wallpaper"].extend(imgs) or True), \
                     patch("utils.wallpaper_manager.get_monitor_details",
                           return_value=[{"id": None, "width": 1920, "height": 1080,
                                          "taskbar_inset": 0}]), \
                     patch.object(background_updater, "load_custom_playlist",
                                  return_value=None), \
                     patch.object(background_updater, "_interruptible_sleep",
                                  side_effect=fake_sleep), \
                     patch.object(platform_utils, "get_slideshow_command_dir",
                                  side_effect=fake_command_dir):
                    for _ in commands:
                        platform_utils.enqueue_slideshow_command(
                            "next", process="background")
                    try:
                        background_updater.start_background_updater()
                    except WakeUp:
                        pass
        self.assertFalse(wake_ups)
        return calls

    def test_one_update_cycle(self):
        calls = self._run_updater(wake_ups=[None])
        self.assertEqual(len(calls["set_wallpaper"]), 1)

    def test_next_command_advances_the_photo(self):
        calls = self._run_updater(wake_ups=[None, None, None],
                                  commands=("next", "next"))
        self.assertEqual(calls["composed"], ["photo0.jpg", "photo1.jpg",
                                             "photo2.jpg"])
        # Consecutive wallpapers must alternate file names (see
        # wallpaper_output_path); all applied files must exist.
        # Each entry in calls["set_wallpaper"] is a (monitor_id, path) tuple.
        names = [Path(p[1]).name for p in calls["set_wallpaper"]]
        self.assertEqual(len(names), 3)
        self.assertNotEqual(names[0], names[1])
        self.assertEqual(names[2], names[0])

    def test_playlist_wraps_around_and_rebuilds(self):
        # 3 next-commands cycle back to the first photo, rebuilding the
        # playlist on wrap-around.
        calls = self._run_updater(wake_ups=[None] * 4,
                                  commands=("next",) * 3)
        self.assertEqual(calls["composed"],
                         ["photo0.jpg", "photo1.jpg", "photo2.jpg",
                          "photo0.jpg"])


if __name__ == "__main__":
    unittest.main()
