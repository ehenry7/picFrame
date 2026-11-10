from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
BASH = shutil.which("bash")


@unittest.skipUnless(BASH, "Bash is required for shell script tests")
class AutoFrameStartTests(unittest.TestCase):
    def run_script(self, filename, setup):
        source = (ROOT / filename).read_text(encoding="utf-8")
        return subprocess.run(
            [BASH, "-c", setup + "\n" + source],
            capture_output=True, text=True, timeout=10,
        )

    def test_enable_and_disable_reboot_after_selecting_correct_boot_modes(self):
        for filename, mode in (("enable_auto_frame_start.sh", "B2"),
                               ("disable_auto_frame_start.sh", "B4")):
            with self.subTest(script=filename):
                result = self.run_script(filename, """
raspi-config() { :; }
sudo() { printf 'COMMAND: %s\\n' "$*"; }
""")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(f"COMMAND: raspi-config nonint do_boot_behaviour {mode}", result.stdout)
                commands = [line for line in result.stdout.splitlines()
                            if line.startswith("COMMAND:")]
                self.assertEqual(commands, [
                    f"COMMAND: raspi-config nonint do_boot_behaviour {mode}",
                    "COMMAND: reboot",
                ])
                self.assertIn("Rebooting now...", result.stdout)

    def test_command_failure_does_not_report_success(self):
        for filename in ("enable_auto_frame_start.sh", "disable_auto_frame_start.sh"):
            result = self.run_script(filename, """
raspi-config() { :; }
sudo() { echo "Permission denied" >&2; return 7; }
""")
            self.assertEqual(result.returncode, 7)
            self.assertIn("Permission denied", result.stderr)
            self.assertNotIn("for the next boot", result.stdout)
            self.assertNotIn("Rebooting now", result.stdout)

    def test_reboot_failure_is_reported(self):
        for filename in ("enable_auto_frame_start.sh", "disable_auto_frame_start.sh"):
            result = self.run_script(filename, """
raspi-config() { :; }
sudo() {
    if [ "$1" = reboot ]; then
        echo "Reboot failed" >&2
        return 9
    fi
}
""")
            self.assertEqual(result.returncode, 9)
            self.assertIn("Reboot failed", result.stderr)

    def test_missing_raspi_config_reports_error_without_sudo(self):
        for filename in ("enable_auto_frame_start.sh", "disable_auto_frame_start.sh"):
            result = self.run_script(filename, """
command() { return 1; }
sudo() { echo "Unexpected sudo" >&2; return 99; }
""")
            self.assertEqual(result.returncode, 1)
            self.assertIn("raspi-config is required", result.stderr)
            self.assertNotIn("Unexpected sudo", result.stderr)

    def test_scripts_use_lf_and_valid_bash_syntax(self):
        for filename in ("enable_auto_frame_start.sh", "disable_auto_frame_start.sh"):
            data = (ROOT / filename).read_bytes()
            self.assertNotIn(b"\r\n", data)
            result = subprocess.run([BASH, "-n"], input=data,
                                    capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
