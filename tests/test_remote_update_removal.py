import ast
from pathlib import Path
import unittest

from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[1]


class RemoteUpdateRemovalTests(unittest.TestCase):
    def test_self_update_routes_and_files_removed(self):
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        functions = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
        self.assertTrue({"update_app", "update_view"}.isdisjoint(functions))
        for token in ("'/api/update_app'", "'/update'", "update_script.sh"):
            self.assertNotIn(token, source)
        self.assertFalse((ROOT / "update_script.sh").exists())
        self.assertFalse((ROOT / "templates" / "update.html.jinja").exists())
        for function in ("restart_app", "import_immich"):
            self.assertIn(function, functions)

    def test_configuration_keeps_sync_without_remote_update_link(self):
        source = (ROOT / "templates" / "configure.html.jinja").read_text(encoding="utf-8")
        Environment(extensions=["jinja2.ext.i18n"]).parse(source)
        self.assertNotIn('href="/update"', source)
        self.assertNotIn("/api/update_app", source)
        self.assertIn("immich-import-btn", source)

    def test_setup_and_supervisor_do_not_install_updater(self):
        for filename in ("setup.sh", "start_pimmich.sh"):
            source = (ROOT / filename).read_text(encoding="utf-8")
            self.assertNotIn("update_script", source)
            self.assertNotIn("git reset", source)
