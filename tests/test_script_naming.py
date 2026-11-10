from pathlib import Path
import tempfile
import unittest

from utils.migrate_frame_names import migrate_frame_names


ROOT = Path(__file__).resolve().parents[1]


class ScriptNamingTests(unittest.TestCase):
    def test_shell_script_names_and_content_use_pictureframe(self):
        self.assertFalse((ROOT / "start_pimmich.sh").exists())
        self.assertTrue((ROOT / "start_pictureframe.sh").exists())
        for path in ROOT.rglob("*.sh"):
            if any(part in {"venv", ".git"} for part in path.parts):
                continue
            self.assertNotIn("pimmich", path.name.lower())
            self.assertNotIn("pimmich", path.read_text(encoding="utf-8").lower())
        startup = (ROOT / "start_pictureframe.sh").read_text(encoding="utf-8")
        for token in ("pictureframe_app.lock", "pictureframe_slideshow.pid", "pictureframe.log"):
            self.assertIn(token, startup)
        setup = (ROOT / "setup.sh").read_text(encoding="utf-8")
        for token in ("start_pictureframe.sh", "sites-available/pictureframe",
                      "sites-enabled/pictureframe", "pictureframe-auth",
                      "migrate_frame_names.py"):
            self.assertIn(token, setup)

    def test_existing_installation_names_migrate_idempotently(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            files = {
                "etc/nginx/sites-available/pimmich": "server config",
                "etc/nginx/sites-enabled/pimmich": "server config",
                "etc/sudoers.d/pimmich-auth": "sudo rules",
                "home/.config/sway/config": "bindsym Mod4+Return exec xterm\nexec_always /frame/start_pimmich.sh\n",
            }
            for name, content in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            for _ in range(2):
                migrate_frame_names(root, home)
                self.assertEqual((root / "etc/nginx/sites-available/pictureframe").read_text(), "server config")
                self.assertEqual((root / "etc/sudoers.d/pictureframe-auth").read_text(), "sudo rules")
                self.assertFalse((root / "etc/nginx/sites-enabled/pimmich").exists())
                self.assertEqual((home / ".config/sway/config").read_text(),
                                 "bindsym Mod4+Return exec xterm\nexec_always /frame/start_pictureframe.sh\n")

    def test_conflicting_files_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent = root / "etc/nginx/sites-available"
            parent.mkdir(parents=True)
            old, new = parent / "pimmich", parent / "pictureframe"
            old.write_text("old custom settings")
            new.write_text("new custom settings")
            with self.assertRaisesRegex(RuntimeError, "Conflicting deployment files"):
                migrate_frame_names(root, root / "home")
            self.assertEqual(old.read_text(), "old custom settings")
            self.assertEqual(new.read_text(), "new custom settings")

    def test_fresh_installation_needs_no_migration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            migrate_frame_names(root, root / "home")
            self.assertEqual(list(root.iterdir()), [])
