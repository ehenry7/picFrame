"""Headless rendering tests without starting slideshow hardware and workers."""

import ast
import math
import os
import random
import tempfile
import time
import traceback
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame
from PIL import Image


class SlideshowFramingTests(unittest.TestCase):
    def setUp(self):
        pygame.display.init()
        self.addCleanup(pygame.display.quit)
        self.screen = pygame.display.set_mode((64, 48))
        source = Path(__file__).resolve().parents[1] / "local_slideshow.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        names = {"fit_photo_to_screen", "prepare_pan_zoom", "render_pan_zoom_frame", "perform_transition",
                 "display_photo_with_pan_zoom"}
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                     and node.name in names]
        self.assertEqual(len(functions), len(names))
        self.namespace = {
            "pygame": pygame, "Image": Image, "random": random, "math": math,
            "time": time, "traceback": traceback, "logger": Mock(),
            "get_pi_model": lambda: 4, "get_photo_metadata": lambda _: {},
            "draw_overlay": lambda *args: None,
            "handle_slideshow_events": lambda *args: None,
            "paused": False, "next_photo_requested": False,
            "previous_photo_requested": False,
        }
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(source), "exec"),
             self.namespace)
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.photo = Path(self.temporary.name) / "photo.png"
        image = Image.new("RGB", (96, 72))
        image.putdata([(x * 2, y * 3, (x + y) % 256)
                       for y in range(72) for x in range(96)])
        image.save(self.photo)
        self.base = self.namespace["fit_photo_to_screen"](image, 64, 48)
        self.config = {"pan_zoom_enabled": True, "pan_zoom_factor": 1.5,
                       "transition_fps": "30", "display_duration": 0}

    def pixels(self):
        return pygame.image.tostring(self.screen, "RGB")

    def test_transition_ends_at_exact_animation_start(self):
        for model in (3, 4):
            self.namespace["get_pi_model"] = lambda: model
            for effect in ("fade", "slide_left", "slide_right", "slide_up", "slide_down", "random"):
                with self.subTest(model=model, effect=effect):
                    plan = self.namespace["prepare_pan_zoom"](self.base, 64, 48, self.config)
                    base_surface = pygame.image.fromstring(plan[0].tobytes(), plan[0].size, plan[0].mode)
                    initial_frame = self.namespace["render_pan_zoom_frame"](base_surface, 64, 48, *plan[1:], 0)
                    initial = Image.frombytes("RGB", (64, 48), pygame.image.tostring(initial_frame, "RGB"))
                    old = pygame.Surface((64, 48))
                    old.fill("black")
                    self.namespace["perform_transition"](
                        self.screen, old, self.photo, 0.001, 64, 48, None,
                        self.config, effect, initial_image=initial)
                    transition_end = self.pixels()
                    self.assertEqual(transition_end, initial.tobytes())
                    frames = []
                    with patch.object(pygame.display, "flip", side_effect=lambda: frames.append(self.pixels())):
                        with patch.object(random, "choice", side_effect=AssertionError("Motion reselected")):
                            self.namespace["display_photo_with_pan_zoom"](
                                self.screen, self.base, 64, 48, self.config, None,
                                pan_zoom_plan=plan)
                    self.assertEqual(frames[0], transition_end)
                    self.assertFalse(any("Erreur" in str(call)
                                         for call in self.namespace["logger"].info.call_args_list))

    def test_static_display_keeps_fitted_framing(self):
        config = {**self.config, "pan_zoom_enabled": False}
        old = pygame.Surface((64, 48))
        result = self.namespace["perform_transition"](
            self.screen, old, self.photo, 0.001, 64, 48, None, config, "fade")
        transition_end = self.pixels()
        self.namespace["display_photo_with_pan_zoom"](
            self.screen, result, 64, 48, config, None)
        self.assertEqual(self.pixels(), transition_end)
        self.assertEqual(transition_end, self.base.tobytes())

    def test_unit_zoom_does_not_retry_identical_offsets(self):
        for factor in (1, 0.5):
            with self.subTest(factor=factor):
                plan = self.namespace["prepare_pan_zoom"](
                    self.base, 64, 48, {"pan_zoom_factor": factor})
                self.assertEqual(plan[0].size, (64, 48))
                self.assertEqual(plan[3:], (1.0, 1.0))
                surface = pygame.image.fromstring(self.base.tobytes(), self.base.size, self.base.mode)
                frame = self.namespace["render_pan_zoom_frame"](surface, 64, 48, *plan[1:], 0.5)
                self.assertEqual(pygame.image.tostring(frame, "RGB"), self.base.tobytes())

    def test_animation_moves_from_shared_start(self):
        plan = (self.base, (0, 0), (1, 1), 1.0, 1.5)
        config = {**self.config, "display_duration": 1}
        fake_time = Mock()
        fake_time.time.side_effect = [0, 0, 0, 0.5, 0.5, 1]
        fake_time.monotonic.return_value = 0
        self.namespace["time"] = fake_time
        frames = []
        with patch.object(pygame.display, "flip", side_effect=lambda: frames.append(self.pixels())):
            self.namespace["display_photo_with_pan_zoom"](
                self.screen, self.base, 64, 48, config, None, pan_zoom_plan=plan)
        self.assertEqual(len(frames), 3)
        self.assertEqual(frames[0], self.base.tobytes())
        self.assertEqual(frames[1], frames[0])
        self.assertNotEqual(frames[2], frames[0])

    def test_animation_reuses_overlay_between_refreshes(self):
        fake_time = Mock()
        fake_time.time.side_effect = [0, 0, 0, 0.25, 0.25, 0.5, 0.5, 1]
        fake_time.monotonic.side_effect = [0, 0.01, 0.26, 0.51]
        self.namespace["time"] = fake_time
        draw = Mock()
        self.namespace["draw_overlay"] = draw
        plan = (self.base, (0, 0), (1, 1), 1.0, 1.5)
        self.namespace["display_photo_with_pan_zoom"](
            self.screen, self.base, 64, 48, {**self.config, "display_duration": 1},
            None, pan_zoom_plan=plan)
        draw.assert_called_once()

    def test_overlay_refreshes_after_one_second(self):
        fake_time = Mock()
        fake_time.time.side_effect = [0, 0, 0, 1.1, 1.1, 2]
        fake_time.monotonic.side_effect = [0, 0.01, 1.1]
        self.namespace["time"] = fake_time
        draw = Mock()
        self.namespace["draw_overlay"] = draw
        plan = (self.base, (0, 0), (1, 1), 1.0, 1.5)
        self.namespace["display_photo_with_pan_zoom"](
            self.screen, self.base, 64, 48, {**self.config, "display_duration": 2},
            None, pan_zoom_plan=plan)
        self.assertEqual(draw.call_count, 2)

    def test_zoom_and_pan_change_together(self):
        base = pygame.image.fromstring(self.base.tobytes(), self.base.size, self.base.mode)
        rectangles = []
        sizes = []
        for progress in (0, 0.25, 0.5, 0.75, 1):
            frame = self.namespace["render_pan_zoom_frame"](base, 64, 48, (1, 1), (1, 1), 1.0, 1.5, progress)
            sizes.append(frame.get_parent().get_size())
            rectangles.append(frame.get_offset())
            self.assertEqual(frame.get_size(), (64, 48))
        self.assertEqual(sizes, [(64, 48), (72, 54), (80, 60), (88, 66), (96, 72)])
        self.assertEqual(rectangles, [(0, 0), (8, 6), (16, 12), (24, 18), (32, 24)])

    def test_all_pan_directions_stay_inside_scaled_image(self):
        base = pygame.image.fromstring(self.base.tobytes(), self.base.size, self.base.mode)
        for end in ((0, 0), (1, 0), (0, 1), (1, 1), (0.5, 1)):
            for progress in (0, 0.1, 0.5, 0.9, 1):
                frame = self.namespace["render_pan_zoom_frame"](base, 64, 48, (0, 0), end, 1.0, 1.5, progress)
                self.assertEqual(frame.get_size(), (64, 48))

    def test_start_zoom_matches_fade_and_animation(self):
        self.config["pan_zoom_start_factor"] = 1.25
        self.test_transition_ends_at_exact_animation_start()

    def test_small_start_zoom_matches_transition(self):
        self.config["pan_zoom_start_factor"] = 0.5
        self.test_transition_ends_at_exact_animation_start()

    def test_small_start_is_centered_on_black(self):
        plan = self.namespace["prepare_pan_zoom"](
            self.base, 64, 48, {**self.config, "pan_zoom_start_factor": 0.5})
        self.assertEqual(plan[3], 0.5)
        base = pygame.Surface((64, 48))
        base.fill("red")
        for progress in (0, 0.25, 0.5, 0.75, 1):
            frame = self.namespace["render_pan_zoom_frame"](base, 64, 48, *plan[1:], progress)
            self.assertEqual(frame.get_size(), (64, 48))
            self.assertGreaterEqual(frame.get_at((32, 24)).r, 250)
            self.assertEqual(frame.get_at((32, 24))[1:3], (0, 0))
            if progress == 0:
                self.assertEqual(frame.get_at((15, 24))[:3], (0, 0, 0))
                self.assertEqual(frame.get_at((16, 12))[:3], (255, 0, 0))
                self.assertEqual(frame.get_at((48, 36))[:3], (0, 0, 0))

    def test_zoom_out_and_constant_zoom(self):
        base = pygame.image.fromstring(self.base.tobytes(), self.base.size, self.base.mode)
        for start, end in ((1.5, 1.0), (1.5, 1.5)):
            sizes = []
            offsets = []
            for progress in (0, 0.5, 1):
                frame = self.namespace["render_pan_zoom_frame"](
                    base, 64, 48, (0, 0), (1, 1), start, end, progress)
                sizes.append(frame.get_parent().get_size())
                offsets.append(frame.get_offset())
            expected = [(96, 72), (80, 60), (64, 48)] if end == 1.0 else [(96, 72)] * 3
            self.assertEqual(sizes, expected)
            if start == end:
                self.assertEqual(offsets, [(0, 0), (16, 12), (32, 24)])


if __name__ == "__main__":
    unittest.main()
