import unittest
from pathlib import Path

from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[1]


class RunModeCardTests(unittest.TestCase):
    """The Run mode card must render in both modes with its settings."""

    def _render(self, app_mode):
        template_text = (ROOT / "templates" / "configure.html.jinja").read_text(
            encoding="utf-8")
        fragment = template_text.split(
            '<div id="tab-affichage" class="tabcontent"', 1)[1]
        fragment = fragment.split('<div id="tab-heure"', 1)[0]
        fragment = '<div id="tab-affichage"' + fragment
        environment = Environment(extensions=["jinja2.ext.i18n"])
        environment.install_null_translations()
        return environment.from_string(fragment).render(
            config={"app_mode": app_mode,
                    "background_update_interval": 3600,
                    "background_output_format": "png",
                    "background_resolution_mode": "auto"})

    def test_picture_frame_mode_selected(self):
        rendered = self._render("picture_frame")
        self.assertIn("Run mode", rendered)
        self.assertIn('value="picture_frame"', rendered)
        self.assertIn('value="background_updater"', rendered)
        self.assertIn('id="apply-mode-btn"', rendered)
        self.assertIn("background-settings", rendered)
        # The background settings stay hidden in picture frame mode.
        self.assertIn('id="background-settings" class="mt-4 pt-4 border-t hidden"', rendered)

    def test_background_mode_selected(self):
        rendered = self._render("background_updater")
        self.assertIn('value="background_updater"', rendered)
        self.assertIn("background-settings", rendered)
        self.assertIn('name="background_update_interval"', rendered)
        self.assertIn('name="background_output_format"', rendered)
        self.assertIn('name="background_resolution_mode"', rendered)

    def test_mode_switch_javascript_calls_the_dedicated_api(self):
        template_text = (ROOT / "templates" / "configure.html.jinja").read_text(
            encoding="utf-8")
        self.assertIn("/api/app_mode", template_text)


if __name__ == "__main__":
    unittest.main()
