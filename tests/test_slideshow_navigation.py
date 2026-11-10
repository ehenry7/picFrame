import ast
from concurrent.futures import Future, ThreadPoolExecutor
import os
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame
from PIL import Image
from utils import slideshow_controls


ROOT = Path(__file__).resolve().parents[1]


class SlideshowNavigationTests(unittest.TestCase):
    def setUp(self):
        pygame.display.init()
        self.addCleanup(pygame.display.quit)
        self.screen = pygame.display.set_mode((320, 240))
        pygame.event.clear()
        slideshow_controls._visible_until = 0
        names = {
            "signal_handler_next", "signal_handler_previous", "signal_handler_pause_toggle",
            "handle_slideshow_events", "read_slideshow_photo", "load_slideshow_photo",
            "perform_transition", "fit_photo_to_screen",
        }
        source = ROOT / "local_slideshow.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        functions = [node for node in tree.body
                     if isinstance(node, ast.FunctionDef) and node.name in names]
        self.assertEqual(len(functions), len(names))
        self.state = {
            "pygame": pygame, "Image": Image, "sys": sys, "logger": Mock(),
            "IS_LINUX": True, "paused": False, "next_photo_requested": False,
            "previous_photo_requested": False, "update_status_file": Mock(),
            "get_pi_model": lambda: 4, "get_photo_metadata": lambda _: {},
            "draw_overlay": Mock(),
            "draw_pause_icon": lambda screen, w, h: slideshow_controls.draw(
                screen, w, h, self.state["paused"]),
        }
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(source), "exec"), self.state)

    def post_key(self, key, **kwargs):
        pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=key, **kwargs))

    def test_keyboard_navigation_reveals_controls_and_latest_direction_wins(self):
        for key, action in ((pygame.K_LEFT, "previous"), (pygame.K_RIGHT, "next")):
            self.post_key(key)
            self.state["handle_slideshow_events"](320)
            self.assertTrue(self.state[f"{action}_photo_requested"])
            other = "next" if action == "previous" else "previous"
            self.assertFalse(self.state[f"{other}_photo_requested"])
            self.assertTrue(slideshow_controls.visible())

    def test_space_toggles_pause_without_repeating(self):
        self.post_key(pygame.K_SPACE)
        self.state["handle_slideshow_events"](320)
        self.assertTrue(self.state["paused"])
        self.post_key(pygame.K_SPACE, repeat=True)
        self.state["handle_slideshow_events"](320)
        self.assertTrue(self.state["paused"])
        self.post_key(pygame.K_SPACE)
        self.state["handle_slideshow_events"](320)
        self.assertFalse(self.state["paused"])
        self.assertEqual(self.state["update_status_file"].call_count, 2)

    def test_native_touch_ignores_synthetic_mouse_duplicate(self):
        slideshow_controls.reveal()
        pos = slideshow_controls.buttons(320, 240)["pause"].center
        pygame.event.post(pygame.event.Event(
            pygame.FINGERDOWN, x=pos[0] / 320, y=pos[1] / 240))
        pygame.event.post(pygame.event.Event(
            pygame.MOUSEBUTTONDOWN, button=1, pos=pos, touch=True))
        self.state["handle_slideshow_events"](320)
        self.assertTrue(self.state["paused"])
        self.state["update_status_file"].assert_called_once()

    def test_navigation_interrupts_each_transition_before_completion(self):
        image = Image.new("RGB", (320, 240), "blue")
        for effect in ("fade", "slide_left", "slide_right", "slide_up", "slide_down"):
            for key, action in ((pygame.K_LEFT, "previous"), (pygame.K_RIGHT, "next")):
                with self.subTest(effect=effect, key=key):
                    self.state["next_photo_requested"] = False
                    self.state["previous_photo_requested"] = False
                    frames = []

                    def flip():
                        frames.append(pygame.image.tostring(self.screen, "RGB"))
                        if len(frames) == 2:
                            self.post_key(key)

                    with patch.object(pygame.display, "flip", side_effect=flip), \
                            patch.object(Image, "open", side_effect=AssertionError("Reloaded photo")):
                        result = self.state["perform_transition"](
                            self.screen, pygame.Surface((320, 240)), "unused.jpg", 5,
                            320, 240, None, {"transition_fps": "60"}, effect,
                            prepared_image=image)
                    self.assertIs(result, image)
                    self.assertEqual(len(frames), 2)
                    self.assertTrue(self.state[f"{action}_photo_requested"])
                    self.assertNotEqual(frames[-1], image.tobytes())

    def test_navigation_returns_while_photo_worker_is_still_loading(self):
        for key, action in ((pygame.K_LEFT, "previous"), (pygame.K_RIGHT, "next")):
            with self.subTest(key=key):
                self.state["next_photo_requested"] = False
                self.state["previous_photo_requested"] = False
                entered = threading.Event()
                release = threading.Event()

                def slow_load(*args):
                    entered.set()
                    release.wait(5)
                    return Image.new("RGB", (320, 240), "blue")

                def flip():
                    self.assertTrue(entered.wait(1))
                    self.post_key(key)

                with ThreadPoolExecutor(max_workers=1) as loader:
                    self.state["read_slideshow_photo"] = slow_load
                    try:
                        with patch.object(pygame.display, "flip", side_effect=flip):
                            result = self.state["load_slideshow_photo"](
                                self.screen, "slow.jpg", 320, 240, loader)
                        self.assertIsNone(result)
                        self.assertFalse(release.is_set())
                        self.assertTrue(self.state[f"{action}_photo_requested"])
                    finally:
                        release.set()

    def test_photo_load_errors_propagate(self):
        future = Future()
        future.set_exception(OSError("Cannot read photo"))
        loader = Mock()
        loader.submit.return_value = future
        with self.assertRaisesRegex(OSError, "Cannot read photo"):
            self.state["load_slideshow_photo"](self.screen, "broken.jpg", 320, 240, loader)

    def test_errors_from_skipped_running_loads_are_logged(self):
        future = Future()
        future.set_running_or_notify_cancel()
        loader = Mock()
        loader.submit.return_value = future
        self.post_key(pygame.K_RIGHT)
        self.assertIsNone(self.state["load_slideshow_photo"](
            self.screen, "skipped.jpg", 320, 240, loader))
        future.set_exception(OSError("Cannot read skipped photo"))
        self.state["logger"].error.assert_called_once()

    def test_pause_freezes_fade_and_navigation_still_interrupts(self):
        image = Image.new("RGB", (320, 240), "blue")
        frames = []

        def flip():
            frames.append(pygame.image.tostring(self.screen, "RGB"))
            if len(frames) in (1, 3):
                self.post_key(pygame.K_SPACE)
            elif len(frames) == 5:
                self.post_key(pygame.K_LEFT)
            elif len(frames) > 5:
                self.fail("Navigation failed to interrupt the transition")

        with patch.object(pygame.display, "flip", side_effect=flip):
            self.state["perform_transition"](
                self.screen, pygame.Surface((320, 240)), "unused.jpg", 5,
                320, 240, None, {"transition_fps": "60"}, "fade",
                prepared_image=image)
        self.assertEqual(len(frames), 5)
        self.assertEqual(frames[1], frames[2])
        self.assertFalse(self.state["paused"])
        self.assertTrue(self.state["previous_photo_requested"])

    def test_ready_photo_is_returned(self):
        image = Image.new("RGB", (320, 240), "blue")
        future = Future()
        future.set_result(image)
        loader = Mock()
        loader.submit.return_value = future
        self.assertIs(self.state["load_slideshow_photo"](
            self.screen, "ready.jpg", 320, 240, loader), image)
