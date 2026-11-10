import unittest
from unittest.mock import patch
import pygame
from utils import slideshow_controls as controls


class SlideshowControlsTests(unittest.TestCase):
    def setUp(self):
        controls._visible_until = 0

    def test_reveal_lasts_five_seconds_and_interactions_extend_it(self):
        with patch.object(controls.time, "monotonic", return_value=100):
            self.assertIsNone(controls.click((0, 0), 800, 600))
        with patch.object(controls.time, "monotonic", return_value=104.99):
            self.assertTrue(controls.visible())
            self.assertEqual(controls.click(controls.buttons(800, 600)["next"].center, 800, 600), "next")
        with patch.object(controls.time, "monotonic", return_value=109.98):
            self.assertTrue(controls.visible())
        with patch.object(controls.time, "monotonic", return_value=110):
            self.assertFalse(controls.visible())

    def test_buttons_hit_targets_and_rendering(self):
        screen = pygame.Surface((800, 600))
        with patch.object(controls.time, "monotonic", return_value=10):
            controls.reveal()
            for action, rect in controls.buttons(800, 600).items():
                self.assertEqual(controls.click(rect.center, 800, 600), action)
            controls.draw(screen, 800, 600, False)
            self.assertNotEqual(screen.get_at(controls.buttons(800, 600)["pause"].topleft)[:3], (255, 255, 255))
            self.assertIsNone(controls.click((0, 0), 800, 600))
