import gettext
import unittest
from pathlib import Path

from jinja2 import Environment


class ZoomLabelTests(unittest.TestCase):
    def test_labels_render_with_newstyle_gettext_in_all_languages(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "templates" / "configure.html.jinja").read_text(encoding="utf-8")
        labels = "\n".join(line for line in source.splitlines()
                           if "<label" in line and ('for="pan_zoom_factor"' in line
                                                    or 'for="pan_zoom_start_factor"' in line))
        for language in ("en", "fr", "he"):
            with self.subTest(language=language):
                environment = Environment(extensions=["jinja2.ext.i18n"])
                translations = gettext.translation(
                    "messages", localedir=str(root / "translations"), languages=[language])
                environment.install_gettext_translations(translations, newstyle=True)
                rendered = environment.from_string(labels).render()
                self.assertIn("15%", rendered)
                self.assertNotIn("15%%", rendered)
                self.assertIn("1.00", rendered)


if __name__ == "__main__":
    unittest.main()
