import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
HELPERS = (
    "add_photos.py", "reset_admin_password.py", "_extract.py", "check_eng.py",
    "check_hardcoded.py", "check_js.py", "check_pot.py", "check_translations.py",
    "test_babel.py", "verify_he.py", "enable_auto_frame_start.sh",
    "disable_auto_frame_start.sh",
)


class ScriptsLayoutTests(unittest.TestCase):
    def test_helpers_have_moved_and_main_entry_points_remain(self):
        for name in HELPERS:
            self.assertFalse((ROOT / name).exists(), name)
            self.assertTrue((ROOT / "scripts" / name).is_file(), name)
        self.assertEqual(list(ROOT.glob("check_*.py")), [])
        for name in ("app.py", "local_slideshow.py", "setup.sh", "start_pictureframe.sh"):
            self.assertTrue((ROOT / name).is_file(), name)

    def test_read_only_helpers_run_outside_project_directory(self):
        helpers = ("check_eng.py", "check_hardcoded.py", "check_js.py",
                   "check_pot.py", "check_translations.py", "test_babel.py", "verify_he.py")
        with tempfile.TemporaryDirectory() as directory:
            for name in helpers:
                with self.subTest(script=name):
                    result = subprocess.run(
                        [sys.executable, str(ROOT / "scripts" / name)],
                        cwd=directory, env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                        capture_output=True, text=True, encoding="utf-8", timeout=30,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "add_photos.py"), "--help"],
                cwd=directory, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("folder", result.stdout)
