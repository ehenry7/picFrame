import tempfile
import unittest
import gettext
from pathlib import Path

import piexif
from jinja2 import Environment
from PIL import Image, ImageChops

from utils.image_filters import apply_filter_to_image


FILTERS = ("auto_enhance", "vivid", "warm", "cool", "dramatic_bw",
           "soft_glow", "sharpen", "duotone", "posterize", "matte", "film_grain",
           "pencil_sketch", "selective_red", "selective_green", "selective_blue", "tilt_shift",
           "cinematic", "cross_process", "watercolor", "dark_vignette")


class PhotoFilterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / "static" / "prepared" / "smartphone" / "photo.jpg"
        self.path.parent.mkdir(parents=True)
        image = Image.new("RGB", (96, 64))
        image.putdata([(30 + (x * 7 + y * 3) % 190,
                        40 + (x * 2 + y * 5) % 170,
                        50 + (x * 4 + y * 7) % 150)
                       for y in range(64) for x in range(96)])
        self.exif = piexif.dump({"Exif": {
            piexif.ExifIFD.UserComment: b"pimmich_bbox:0,0,96,64"}})
        image.save(self.path, quality=95, exif=self.exif)
        self.original = self.path.read_bytes()

    def test_all_presets_change_image_and_preserve_exif_and_backup(self):
        for name in (*FILTERS, "vignette"):
            with self.subTest(filter=name):
                apply_filter_to_image(str(self.path), name)
                backup = self.root / "static" / ".backups" / "smartphone" / "photo.jpg"
                self.assertEqual(backup.read_bytes(), self.original)
                with Image.open(self.path) as result, Image.open(backup) as original:
                    self.assertEqual(result.size, original.size)
                    self.assertEqual(result.mode, "RGB")
                    self.assertEqual(result.info["exif"], self.exif)
                    self.assertIsNotNone(ImageChops.difference(result, original).getbbox())
                first_result = self.path.read_bytes()
                apply_filter_to_image(str(self.path), name)
                self.assertEqual(self.path.read_bytes(), first_result)
        apply_filter_to_image(str(self.path), "original")
        restored = self.path.read_bytes()
        apply_filter_to_image(str(self.path), "original")
        self.assertEqual(self.path.read_bytes(), restored)

    def test_warm_cool_and_monochrome_characteristics(self):
        Image.new("RGB", (96, 64), (120, 120, 120)).save(self.path, quality=95)
        for name in ("warm", "cool", "dramatic_bw"):
            apply_filter_to_image(str(self.path), name)
            with Image.open(self.path) as image:
                red, green, blue = image.getpixel((40, 30))
            if name == "warm":
                self.assertGreater(red, blue)
            elif name == "cool":
                self.assertGreater(blue, red)
            else:
                self.assertEqual(red, green)
                self.assertEqual(green, blue)

    def test_both_dropdowns_offer_presets_and_restore_selection(self):
        source = (Path(__file__).resolve().parents[1] / "templates" /
                  "configure.html.jinja").read_text(encoding="utf-8")
        self.assertEqual(source.count("{{ extra_filter_options(active_filter) }}"), 2)
        start = source.index("{% macro extra_filter_options")
        end = source.index("{% endmacro %}", start) + len("{% endmacro %}")
        environment = Environment(extensions=["jinja2.ext.i18n"])
        environment.install_null_translations(newstyle=True)
        template = environment.from_string(source[start:end] +
                                           "{{ extra_filter_options(active_filter) }}")
        for name in FILTERS:
            rendered = template.render(active_filter=name)
            self.assertIn(f'value="{name}" selected', rendered)
            self.assertEqual(rendered.count("<option"), len(FILTERS))

    def test_selective_colors_keep_only_chosen_color(self):
        image = Image.new("RGB", (96, 64))
        image.paste((220, 30, 30), (0, 0, 32, 64))
        image.paste((30, 220, 30), (32, 0, 64, 64))
        image.paste((30, 30, 220), (64, 0, 96, 64))
        image.save(self.path, quality=100, subsampling=0)
        for selected, name in enumerate(("selective_red", "selective_green", "selective_blue")):
            apply_filter_to_image(str(self.path), name)
            with Image.open(self.path) as result:
                for index in range(3):
                    pixel = result.getpixel((16 + index * 32, 32))
                    if index == selected:
                        self.assertGreater(pixel[index], min(pixel) + 100)
                    else:
                        self.assertLessEqual(max(pixel) - min(pixel), 2)

    def test_tilt_shift_preserves_center_and_blurs_edges(self):
        image = Image.new("RGB", (96, 64))
        image.putdata([((x % 2) * 255,) * 3 for y in range(64) for x in range(96)])
        image.save(self.path, quality=100)
        apply_filter_to_image(str(self.path), "tilt_shift")
        with Image.open(self.path) as result:
            center_contrast = abs(result.getpixel((40, 32))[0] - result.getpixel((41, 32))[0])
            edge_contrast = abs(result.getpixel((40, 2))[0] - result.getpixel((41, 2))[0])
        self.assertGreater(center_contrast, 200)
        self.assertLess(edge_contrast, 20)

    def test_cinematic_has_teal_shadows_and_warm_highlights(self):
        image = Image.new("RGB", (96, 64), (45, 45, 45))
        image.paste((210, 210, 210), (48, 0, 96, 64))
        image.save(self.path, quality=100)
        apply_filter_to_image(str(self.path), "cinematic")
        with Image.open(self.path) as result:
            shadow = result.getpixel((20, 32))
            highlight = result.getpixel((75, 32))
        self.assertGreater(shadow[2], shadow[0] + 8)
        self.assertGreater(shadow[1], shadow[0] + 5)
        self.assertGreater(highlight[0], highlight[2] + 8)

    def test_cross_process_channel_curves(self):
        Image.new("RGB", (96, 64), (50, 50, 50)).save(self.path, quality=100)
        apply_filter_to_image(str(self.path), "cross_process")
        with Image.open(self.path) as result:
            red, green, blue = result.getpixel((48, 32))
        self.assertLess(red, green)
        self.assertLess(green, blue)

    def test_watercolor_smooths_fine_detail_but_preserves_large_edges(self):
        image = Image.new("RGB", (96, 64))
        image.putdata([((40 if x < 48 else 200) + (x % 2) * 30,) * 3
                       for y in range(64) for x in range(96)])
        image.save(self.path, quality=100)
        apply_filter_to_image(str(self.path), "watercolor")
        with Image.open(self.path) as result:
            self.assertLess(abs(result.getpixel((20, 32))[0] - result.getpixel((21, 32))[0]), 10)
            self.assertGreater(result.getpixel((75, 32))[0] - result.getpixel((20, 32))[0], 120)

    def test_vignette_keeps_center_bright_and_darkens_edges(self):
        Image.new("RGB", (96, 64), (200, 200, 200)).save(self.path, quality=100)
        apply_filter_to_image(str(self.path), "dark_vignette")
        with Image.open(self.path) as result:
            center = result.getpixel((48, 32))[0]
            corner = result.getpixel((0, 0))[0]
            edge = result.getpixel((48, 0))[0]
            self.assertGreaterEqual(center, 195)
            self.assertLess(corner, 120)
            self.assertLess(corner, edge)
            self.assertLess(edge, center)
            self.assertLessEqual(abs(corner - result.getpixel((95, 63))[0]), 2)

    def test_new_presets_support_tiny_images(self):
        for size in ((1, 1), (1, 5), (5, 1), (2, 2)):
            path = self.path.with_name(f"tiny_{size[0]}_{size[1]}.jpg")
            Image.new("RGB", size, (120, 80, 40)).save(path)
            for name in ("cinematic", "cross_process", "watercolor", "vignette", "dark_vignette"):
                with self.subTest(size=size, filter=name):
                    apply_filter_to_image(str(path), name)
                    with Image.open(path) as result:
                        self.assertEqual(result.size, size)

    def test_bw_background_preserves_color_foreground(self):
        image = Image.new("RGB", (96, 64), (190, 60, 30))
        exif = piexif.dump({"Exif": {
            piexif.ExifIFD.UserComment: b"pimmich_bbox:32,0,32,64"}})
        image.save(self.path, quality=100, exif=exif)
        apply_filter_to_image(str(self.path), "vignette")
        with Image.open(self.path) as result:
            background = result.getpixel((10, 32))
            foreground = result.getpixel((48, 32))
            self.assertLessEqual(max(background) - min(background), 2)
            self.assertGreater(foreground[0], foreground[2] + 100)
            self.assertEqual(result.info["exif"], exif)
        first_result = self.path.read_bytes()
        apply_filter_to_image(str(self.path), "vignette")
        self.assertEqual(self.path.read_bytes(), first_result)

    def test_bw_background_without_bounds_uses_color_center(self):
        Image.new("RGB", (96, 64), (190, 60, 30)).save(self.path, quality=100)
        apply_filter_to_image(str(self.path), "vignette")
        with Image.open(self.path) as result:
            corner = result.getpixel((0, 0))
            center = result.getpixel((48, 32))
            self.assertLessEqual(max(corner) - min(corner), 2)
            self.assertGreater(center[0], center[2] + 100)

    def test_bw_background_full_frame_bounds_still_desaturates_surroundings(self):
        image = Image.new("RGB", (96, 64), (190, 60, 30))
        image.save(self.path, quality=100, exif=self.exif)
        apply_filter_to_image(str(self.path), "vignette")
        with Image.open(self.path) as result:
            corner = result.getpixel((0, 0))
            center = result.getpixel((48, 32))
            self.assertLessEqual(max(corner) - min(corner), 2)
            self.assertGreater(center[0], center[2] + 100)

    def test_dark_vignette_keeps_edge_colors(self):
        Image.new("RGB", (96, 64), (200, 100, 50)).save(self.path, quality=100)
        apply_filter_to_image(str(self.path), "dark_vignette")
        with Image.open(self.path) as result:
            red, green, blue = result.getpixel((0, 0))
            self.assertGreater(red, green)
            self.assertGreater(green, blue)
            self.assertLess(red, 120)

    def test_distinct_labels_in_compiled_translations(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "templates" / "configure.html.jinja").read_text(encoding="utf-8")
        self.assertEqual(source.count('_("B&W Background")'), 2)
        for language in ("en", "fr", "he"):
            with self.subTest(language=language):
                translations = gettext.translation("messages", str(root / "translations"), [language])
                background = translations.gettext("B&W Background")
                vignette = translations.gettext("Vignette - Dark Edges")
                self.assertNotEqual(background, vignette)
                environment = Environment(extensions=["jinja2.ext.i18n"])
                environment.install_gettext_translations(translations, newstyle=True)
                rendered = environment.from_string(
                    '{{ _("B&W Background") }} | {{ _("Vignette - Dark Edges") }}').render()
                self.assertIn(vignette, rendered)


if __name__ == "__main__":
    unittest.main()
