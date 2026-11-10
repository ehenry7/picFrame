from pathlib import Path
import unittest

from jinja2 import Environment


ROOT = Path(__file__).resolve().parents[1]


class CreditsRemovalTests(unittest.TestCase):
    def test_ui_has_no_author_links_or_credits(self):
        source = (ROOT / "templates" / "configure.html.jinja").read_text(encoding="utf-8")
        Environment(extensions=["jinja2.ext.i18n"]).parse(source)
        for token in ("github.com/gotenash", "github.com/Sigalou", "gadgetaulab.fr",
                      "gotenash.jpg", "sigalou.png", "logo_gadgeto.png",
                      'class="credits"', '_("Crédits")'):
            self.assertNotIn(token, source)
        self.assertIn("pictureframe_logo.svg", source)
        self.assertIn('id="live-preview-container"', source)

    def test_readmes_remove_promotional_credits_but_license_is_preserved(self):
        source = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertNotIn("ko-fi.com", source)
        self.assertNotIn("💖", source)
        license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
        self.assertIn("Copyright (c) 2025 gotenash", license_text)
        self.assertIn("MIT License", license_text)
