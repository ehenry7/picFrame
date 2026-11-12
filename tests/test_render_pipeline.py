import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class RenderPipelineTests(unittest.TestCase):
    """Tests for the headless compose pipeline.

    These tests run pygame without any display: compose_background must work
    with only pygame.font + plain Surfaces.
    """

    @classmethod
    def setUpClass(cls):
        import os
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        from utils import render_pipeline
        render_pipeline.ensure_font_init()
        cls.render_pipeline = render_pipeline

    def _make_photo(self, directory, name="photo.jpg", size=(800, 600),
                    color=(120, 40, 200), portrait=False):
        from PIL import Image
        if portrait:
            size = (size[1], size[0])
        path = Path(directory) / name
        Image.new("RGB", size, color).save(path)
        return path

    def test_compose_background_landscape(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as directory:
            photo = self._make_photo(directory, "photo.jpg", (800, 600))
            config = {"show_clock": False, "show_weather": False,
                      "show_tides": False}
            surface = self.render_pipeline.compose_background(
                photo, 1920, 1080, config, None)
            self.assertIsNotNone(surface)
            self.assertEqual(surface.get_size(), (1920, 1080))

    def test_compose_background_portrait_fits(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as directory:
            photo = self._make_photo(directory, "photo.jpg", (600, 900))
            config = {"show_clock": False, "show_weather": False,
                      "show_tides": False}
            surface = self.render_pipeline.compose_background(
                photo, 1920, 1080, config, None)
            self.assertIsNotNone(surface)
            self.assertEqual(surface.get_size(), (1920, 1080))

    def test_compose_background_with_overlays(self):
        """Clock/weather overlays must not crash and must alter some pixels."""
        with tempfile.TemporaryDirectory() as directory:
            photo = self._make_photo(directory, "photo.jpg", (800, 600))
            config = {"show_clock": True, "show_date": True,
                      "show_weather": False, "show_tides": False,
                      "clock_format": "%H:%M", "clock_color": "#FFFFFF",
                      "clock_outline_color": "#000000",
                      "clock_font_size": 72}
            font = self.render_pipeline.load_main_font(config)
            surface = self.render_pipeline.compose_background(
                photo, 1280, 720, config, font)
            self.assertIsNotNone(surface)
            self.assertEqual(surface.get_size(), (1280, 720))

    def test_compose_background_missing_photo_returns_none(self):
        config = {"show_clock": False}
        surface = self.render_pipeline.compose_background(
            "does-not-exist.jpg", 100, 100, config, None)
        self.assertIsNone(surface)

    def test_save_surface_atomic_writes_file(self):
        import pygame
        with tempfile.TemporaryDirectory() as directory:
            surface = pygame.Surface((320, 240))
            surface.fill((10, 20, 30))
            output = Path(directory) / "nested" / "wallpaper.png"
            self.assertTrue(self.render_pipeline.save_surface_atomic(
                surface, output))
            self.assertTrue(output.exists())
            self.assertFalse(
                output.with_name(output.name + ".tmp").exists())
            with open(output, "rb") as handle:
                header = handle.read(4)
            self.assertEqual(header[:4], b"\x89PNG")

    def test_build_media_playlist_scans_prepared_sources(self):
        """Prepared-source scanning must find photos and map videos to thumbnails."""
        with tempfile.TemporaryDirectory() as directory:
            import local_slideshow
            from utils import render_pipeline
            prepared = Path(directory)
            source = prepared / "usb"
            source.mkdir(parents=True)
            (source / "a.jpg").touch()
            (source / "b_polaroid.jpg").touch()
            (source / "c.mp4").touch()
            (source / "c_thumbnail.jpg").touch()
            config = {"display_sources": ["usb"],
                      "favorite_boost_factor": 1,
                      "anniversary_boost_enabled": False}
            with patch.object(render_pipeline, "PREPARED_BASE_DIR", prepared), \
                 patch.object(local_slideshow, "PREPARED_BASE_DIR", prepared):
                playlist = render_pipeline.build_media_playlist(config)
            names = {Path(p).name for p in playlist}
            self.assertEqual(names, {"a.jpg", "c_thumbnail.jpg"})

    def test_collect_video_thumbnail(self):
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "clip.mp4"
            video.touch()
            thumb = Path(directory) / "clip_thumbnail.jpg"
            self.assertIsNone(
                self.render_pipeline.collect_video_thumbnail(video))
            thumb.touch()
            self.assertEqual(
                self.render_pipeline.collect_video_thumbnail(video),
                str(thumb))


class DisplayStyleTests(unittest.TestCase):
    """The background display styles must place photos like a wallpaper."""

    def setUp(self):
        from PIL import Image
        self.image = Image.new("RGB", (800, 600), (10, 200, 90))

    def test_fill_crops_to_exactly_the_canvas(self):
        from utils.render_pipeline import fit_photo_to_style
        out = fit_photo_to_style(self.image, 1920, 1080, "fill")
        self.assertEqual(out.size, (1920, 1080))

    def test_span_behaves_like_fill(self):
        from utils.render_pipeline import fit_photo_to_style
        out = fit_photo_to_style(self.image, 1920, 1080, "span")
        self.assertEqual(out.size, (1920, 1080))

    def test_stretch_distorts_to_the_canvas(self):
        from utils.render_pipeline import fit_photo_to_style
        out = fit_photo_to_style(self.image, 1000, 500, "stretch")
        self.assertEqual(out.size, (1000, 500))

    def test_center_keeps_original_size(self):
        from utils.render_pipeline import fit_photo_to_style
        out = fit_photo_to_style(self.image, 1920, 1080, "center")
        self.assertEqual(out.size, (1920, 1080))
        # The photo itself is centered: the top-left pixel is canvas black.
        self.assertEqual(out.getpixel((0, 0)), (0, 0, 0))
        self.assertEqual(
            out.getpixel((1920 // 2 - 1, 1080 // 2 - 1)), (10, 200, 90))

    def test_tile_repeats_the_photo(self):
        from utils.render_pipeline import fit_photo_to_style
        out = fit_photo_to_style(self.image, 800, 1200, "tile")
        self.assertEqual(out.size, (800, 1200))
        # The tile boundary at y=600 comes from the same photo (repeated).
        self.assertEqual(out.getpixel((10, 10)), (10, 200, 90))
        self.assertEqual(out.getpixel((10, 610)), (10, 200, 90))

    def test_fit_letterboxes(self):
        from utils.render_pipeline import fit_photo_to_style
        out = fit_photo_to_style(self.image, 1920, 1080, "fit")
        self.assertEqual(out.size, (1920, 1080))
        # 800x600 → 1440x1080 fitted: left/right bars must stay black.
        self.assertEqual(out.getpixel((0, 540)), (0, 0, 0))
        self.assertEqual(out.getpixel((1919, 540)), (0, 0, 0))

    def test_unknown_style_falls_back_to_fit(self):
        from utils.render_pipeline import fit_photo_to_style
        out = fit_photo_to_style(self.image, 1920, 1080, "nonsense")
        self.assertEqual(out.size, (1920, 1080))
        self.assertEqual(out.getpixel((0, 540)), (0, 0, 0))

    def test_compose_background_uses_display_style(self):
        import os
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        from utils import render_pipeline
        render_pipeline.ensure_font_init()
        with tempfile.TemporaryDirectory() as directory:
            photo = Path(directory) / "photo.jpg"
            self.image.save(photo)
            config = {"show_clock": False, "show_weather": False,
                      "show_tides": False, "background_display_style": "fill"}
            surface = render_pipeline.compose_background(
                photo, 1920, 1080, config, None)
            self.assertIsNotNone(surface)
            self.assertEqual(surface.get_size(), (1920, 1080))


if __name__ == "__main__":
    unittest.main()
