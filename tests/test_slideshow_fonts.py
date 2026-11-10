import unittest
import os
from unittest.mock import Mock, patch

from utils import slideshow_fonts


class SlideshowFontTests(unittest.TestCase):
    def setUp(self):
        slideshow_fonts.clear_font_cache()
        slideshow_fonts._unavailable_paths.clear()
        self.addCleanup(slideshow_fonts.clear_font_cache)
        self.addCleanup(slideshow_fonts._unavailable_paths.clear)

    def test_missing_font_is_only_attempted_once_across_sizes_and_reinitialization(self):
        with patch.object(slideshow_fonts.pygame.font, "Font", side_effect=FileNotFoundError("missing")) as custom, \
                patch.object(slideshow_fonts.pygame.font, "SysFont", side_effect=lambda *args: Mock()) as system, \
                patch.object(slideshow_fonts.logger, "warning") as warning:
            first = slideshow_fonts.load_font("missing.ttf", 23)
            for _ in range(100):
                self.assertIs(slideshow_fonts.load_font("missing.ttf", 23), first)
            slideshow_fonts.load_font("missing.ttf", 40)
            slideshow_fonts.clear_font_cache()
            self.assertIsNot(slideshow_fonts.load_font("missing.ttf", 23), first)
            custom.assert_called_once_with("missing.ttf", 23)
            warning.assert_called_once()
            self.assertEqual(system.call_count, 3)
            self.assertEqual(system.call_args.args, ("Arial", 23))

    def test_valid_fonts_are_cached_and_a_new_path_is_tried(self):
        with patch.object(slideshow_fonts.pygame.font, "Font", side_effect=lambda *args: Mock()) as custom:
            first = slideshow_fonts.load_font("valid.ttf", 23)
            self.assertIs(slideshow_fonts.load_font("valid.ttf", 23), first)
            slideshow_fonts.load_font("other.ttf", 23)
            self.assertEqual(custom.call_count, 2)

    def test_system_font_failure_is_not_hidden(self):
        with patch.object(slideshow_fonts.pygame.font, "Font", side_effect=OSError("missing")), \
                patch.object(slideshow_fonts.pygame.font, "SysFont", side_effect=RuntimeError("font subsystem unavailable")), \
                patch.object(slideshow_fonts.logger, "warning"):
            with self.assertRaisesRegex(RuntimeError, "font subsystem unavailable"):
                slideshow_fonts.load_font("missing.ttf", 23)

    def test_real_system_font_renders_after_missing_file(self):
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        slideshow_fonts.pygame.font.init()
        self.addCleanup(slideshow_fonts.pygame.font.quit)
        with patch.object(slideshow_fonts.logger, "warning") as warning:
            font = slideshow_fonts.load_font("__missing_pictureframe_font__.ttf", 23)
            self.assertGreater(font.render("Photo metadata", True, "white").get_width(), 0)
            self.assertIs(slideshow_fonts.load_font("__missing_pictureframe_font__.ttf", 23), font)
            warning.assert_called_once()
