import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "configure_auto_frame", ROOT / "scripts" / "configure_auto_frame.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class AutoFrameConfigTests(unittest.TestCase):
    def test_repairs_old_launcher_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "frame project"
            project.mkdir()
            (project / "start_pictureframe.sh").touch()
            home = Path(directory) / "home"
            config = home / ".config" / "sway" / "config"
            config.parent.mkdir(parents=True)
            config.write_text("bindsym Mod4+Return exec xterm\nexec_always /old/start_pimmich.sh\n")
            for _ in range(2):
                module.configure_auto_frame(project, home)
                text = config.read_text()
                self.assertNotIn("start_pimmich", text)
                self.assertIn("start_pictureframe.sh", text)
                self.assertEqual(text.count("start_pictureframe.sh"), 1)
                self.assertIn("bindsym Mod4+Return exec xterm", text)
                self.assertEqual((home / ".bash_profile").read_text().count("exec sway"), 1)

    def test_missing_launcher_fails_before_modifying_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(FileNotFoundError):
                module.configure_auto_frame(root, root)
            self.assertFalse((root / ".bash_profile").exists())
