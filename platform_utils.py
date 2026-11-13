"""
platform_utils.py — OS-aware hardware abstraction for PictureFrame.

This module provides shared paths, platform detection, and platform-specific
operations. Hardware operations that are unavailable on the current platform
return an explicit unavailable result rather than reporting success.

Usage pattern (replace raw subprocess calls in app.py, utils/*.py, etc.):

    from platform_utils import set_display_power, system_reboot, IS_LINUX

    set_display_power(False)   # Returns unavailable on unsupported platforms.
    if IS_LINUX:
        # ... additional Linux-only logic ...

Design principles:
- Every function is safe to call on any OS — never raises on Windows.
- Return values match the real implementation's contract (True/False, dict, etc.).
- On non-Linux, log clearly when a hardware operation is unavailable.
- Keep this module dependency-free (stdlib only) so it always imports.
"""

import platform
import subprocess
import logging
import os
import tempfile
import uuid
from pathlib import Path

logger = logging.getLogger("pictureframe.platform_utils")

BASE_DIR = Path(__file__).resolve().parent

# ── Platform flags ──────────────────────────────────────────────
IS_LINUX = platform.system() == "Linux"
IS_WINDOWS = platform.system() == "Windows"
IS_RASPBERRY_PI = False

if IS_LINUX:
    try:
        with open("/proc/device-tree/model", "r") as f:
            _model = f.read()
            IS_RASPBERRY_PI = "Raspberry Pi" in _model
    except (FileNotFoundError, PermissionError, OSError):
        IS_RASPBERRY_PI = False


# ── Path helpers ────────────────────────────────────────────────

def get_temp_dir() -> Path:
    """Return the OS-appropriate temp directory as a Path.

    On Linux/Pi this is /tmp (matching the original hardcoded paths).
    On Windows this is the system temp (e.g. C:\\Users\\...\\AppData\\Local\\Temp).
    """
    return Path(tempfile.gettempdir())


def get_pid_file(name: str) -> Path:
    """Return a PID file path in the temp directory.

    Args:
        name: e.g. 'pictureframe_slideshow', 'pictureframe_app'
    """
    return get_temp_dir() / f"{name}.pid"


def get_status_file(name: str) -> Path:
    """Return a status file path in the temp directory.

    Args:
        name: e.g. 'pictureframe_slideshow_status', 'pictureframe_current_photo'
    """
    return get_temp_dir() / name


def get_credentials_path() -> Path:
    """Return the credentials file path.

    On Raspberry Pi: /boot/firmware/credentials.json (requires sudo to write).
    On Windows and other Linux systems: project-root/credentials.json.
    """
    if IS_RASPBERRY_PI:
        return Path("/boot/firmware/credentials.json")
    return Path(__file__).resolve().parent / "credentials.json"


def get_default_font_path() -> str:
    """Return a default font path for the current OS.

    On Linux/Pi: DejaVuSans-Bold (system font).
    On Windows: Arial (always available).
    """
    if IS_LINUX:
        return "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    windows_font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "arialbd.ttf"
    return str(windows_font) if windows_font.exists() else "arialbd.ttf"


def get_cancel_flag_path() -> Path:
    """Return the import cancellation flag file path."""
    return get_temp_dir() / "pictureframe_cancel_import.flag"


def get_slideshow_command_dir(process: str = "slideshow") -> Path:
    """Return the cross-process command queue used when POSIX signals are unavailable.

    Args:
        process: queue owner: "slideshow" (local_slideshow.py) or
            "background" (background_updater.py). Defaults to the slideshow
            queue for backward compatibility.
    """
    if process not in ("slideshow", "background"):
        raise ValueError(f"Unsupported process command queue: {process}")
    return get_temp_dir() / f"pictureframe_{process}_commands"


def enqueue_slideshow_command(command: str, process: str = "slideshow") -> None:
    """Queue a slideshow command for platforms without the POSIX control signals."""
    if command not in {"next", "previous", "toggle_pause"}:
        raise ValueError(f"Unsupported slideshow command: {command}")

    command_dir = get_slideshow_command_dir(process)
    command_dir.mkdir(parents=True, exist_ok=True)
    command_file = command_dir / f"{uuid.uuid4().hex}.txt"
    command_file.write_text(command, encoding="utf-8")


def consume_slideshow_commands(process: str = "slideshow") -> list[str]:
    """Read and remove queued slideshow commands."""
    command_dir = get_slideshow_command_dir(process)
    if not command_dir.is_dir():
        return []

    commands = []
    for command_file in sorted(command_dir.glob("*.txt")):
        try:
            command = command_file.read_text(encoding="utf-8").strip()
            command_file.unlink()
            if command in {"next", "previous", "toggle_pause"}:
                commands.append(command)
            else:
                logger.warning("Ignoring invalid slideshow command in %s", command_file)
        except FileNotFoundError:
            continue
        except OSError:
            logger.exception("Could not read slideshow command file %s", command_file)
    return commands


# ── Display / HDMI power ────────────────────────────────────────

def set_display_power(on: bool, config: dict = None):
    """Turn the display on or off.

    On Pi: uses wlr-randr / swaymsg DPMS, or smart plug HTTP commands.
    On non-Linux platforms: returns an explicit unavailable result.

    Returns:
        (success: bool, message: str)
    """
    if not IS_LINUX:
        message = "Display power control is unavailable on this platform."
        logger.warning(message)
        return False, message

    # --- Linux / Raspberry Pi implementation ---
    # Delegate to the existing display_manager logic
    try:
        from utils.display_manager import set_display_power as _pi_set_display_power
        return _pi_set_display_power(on)
    except Exception as e:
        logger.error(f"set_display_power failed: {e}")
        return False, str(e)


def get_display_output_name():
    """Detect the active HDMI output name.

    Returns:
        str: output name (e.g. 'HDMI-A-1') or None if not found / Windows.
    """
    if not IS_LINUX:
        logger.info("Display output detection is unavailable on this platform.")
        return None

    try:
        from utils.display_manager import get_display_output_name as _pi_get
        return _pi_get()
    except Exception as e:
        logger.error(f"get_display_output_name failed: {e}")
        return None


def set_display_resolution(width: int, height: int):
    """Set the display resolution via swaymsg.

    Returns:
        (success: bool, message: str)
    """
    if not IS_LINUX:
        message = "Display resolution control is unavailable on this platform."
        logger.warning(message)
        return False, message

    try:
        output = get_display_output_name()
        if not output:
            return False, "No display output found"
        subprocess.run(
            ["swaymsg", "output", output, "resolution", f"{width}x{height}"],
            check=True
        )
        return True, "OK"
    except Exception as e:
        logger.error(f"set_display_resolution failed: {e}")
        return False, str(e)


def get_available_resolutions():
    """Return list of available screen resolutions.

    Returns:
        list of dict: [{"width": w, "height": h, "refresh": r}, ...]
    """
    if not IS_LINUX:
        logger.info("Display mode enumeration is unavailable on this platform.")
        return []

    try:
        import json
        env = os.environ.copy()
        result = subprocess.run(
            ["swaymsg", "-t", "get_outputs"],
            capture_output=True, text=True, env=env, timeout=5, check=True
        )
        outputs = json.loads(result.stdout)
        resolutions = []
        for o in outputs:
            for mode in o.get("modes", []):
                resolutions.append({
                    "width": mode.get("width", 0),
                    "height": mode.get("height", 0),
                    "refresh": mode.get("refresh", 0)
                })
        return resolutions
    except Exception as e:
        logger.error(f"get_available_resolutions failed: {e}")
        return []


# ── System power ────────────────────────────────────────────────

def system_reboot():
    """Reboot the system.

    On Pi: sudo -n reboot
    On non-Linux platforms: returns an explicit unavailable result.
    """
    if not IS_LINUX:
        logger.warning("System reboot is unavailable on this platform.")
        return False

    return subprocess.run(["sudo", "-n", "reboot"], check=False).returncode == 0


def system_shutdown():
    """Shut down the system.

    On Pi: sudo -n shutdown now
    On non-Linux platforms: returns an explicit unavailable result.
    """
    if not IS_LINUX:
        logger.warning("System shutdown is unavailable on this platform.")
        return False

    return subprocess.run(["sudo", "-n", "shutdown", "now"], check=False).returncode == 0


def system_halt():
    """Halt the system (alias for shutdown)."""
    if not IS_LINUX:
        logger.warning("System halt is unavailable on this platform.")
        return False

    return subprocess.run(["sudo", "-n", "shutdown", "-h", "now"], check=False).returncode == 0


# ── CPU temperature ─────────────────────────────────────────────

def get_cpu_temperature():
    """Read the CPU temperature.

    On Pi: reads /sys/class/thermal/thermal_zone0/temp (millidegrees Celsius).
    On Windows: returns None (no standard interface).

    Returns:
        float: temperature in degrees Celsius, or None if unavailable.
    """
    if not IS_LINUX:
        logger.info("[WIN MOCK] CPU temperature not available on Windows")
        return None

    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            millideg = int(f.read().strip())
            return millideg / 1000.0
    except (FileNotFoundError, ValueError, PermissionError) as e:
        logger.error(f"get_cpu_temperature failed: {e}")
        return None


def get_cpu_temperature_vcgencmd():
    """Read CPU temperature via vcgencmd (Pi-specific).

    Returns:
        float: temperature in degrees Celsius, or None if unavailable.
    """
    if not IS_LINUX:
        logger.info("[WIN MOCK] vcgencmd not available on Windows")
        return None

    try:
        temp_output = subprocess.check_output(["vcgencmd", "measure_temp"]).decode("utf-8")
        # Output format: temp=48.3'C
        import re
        match = re.search(r'temp=(\d+\.\d+)', temp_output)
        if match:
            return float(match.group(1))
    except Exception as e:
        logger.error(f"get_cpu_temperature_vcgencmd failed: {e}")
    return None


# ── Pi model detection ──────────────────────────────────────────

def get_pi_model():
    """Detect the Raspberry Pi model.

    Returns:
        int: 1 (Pi 1/Zero), 2, 3, 4, 5, or None if not a Pi.
    """
    if not IS_LINUX:
        return None

    try:
        with open("/proc/device-tree/model", "r") as f:
            model_str = f.read()
            if "Raspberry Pi 4" in model_str:
                return 4
            if "Raspberry Pi 5" in model_str:
                return 5
            if "Raspberry Pi 3" in model_str:
                return 3
            if "Raspberry Pi 2" in model_str:
                return 2
            if "Zero" in model_str:
                return 1
            if "Raspberry Pi" in model_str:
                return 1
    except (FileNotFoundError, Exception):
        return None
    return None


# ── Network / Wi-Fi ─────────────────────────────────────────────

def get_interface_status(interface_name: str):
    """Get network interface status (UP/DOWN, IP address).

    Returns:
        dict: {"name": str, "state": str, "ip_address": str}
    """
    if not IS_LINUX:
        logger.info("Network interface management is unavailable on this platform.")
        return {"name": interface_name, "state": "UNAVAILABLE", "ip_address": "N/A"}

    try:
        import re
        status = {"name": interface_name, "state": "DOWN", "ip_address": "N/A"}
        ip_addr_output = subprocess.check_output(
            ["/usr/bin/ip", "addr", "show", interface_name],
            text=True, stderr=subprocess.DEVNULL
        ).strip()

        if "state UP" in ip_addr_output:
            status["state"] = "UP"

        ip_match = re.search(r"inet (\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", ip_addr_output)
        if ip_match:
            status["ip_address"] = ip_match.group(1)
        return status
    except Exception as e:
        logger.error(f"get_interface_status failed: {e}")
        return {"name": interface_name, "state": "NOT_FOUND", "ip_address": "N/A"}


def set_interface_state(interface_name: str, state: str):
    """Enable ('up') or disable ('down') a network interface.

    Returns:
        bool: True if successful.
    """
    if not IS_LINUX:
        logger.warning("Network interface management is unavailable on this platform.")
        return False

    action = "connect" if state == "up" else "disconnect"
    try:
        subprocess.run(
            ["sudo", "-n", "/usr/bin/nmcli", "device", action, interface_name],
            check=True, capture_output=True, text=True, timeout=10
        )
        return True
    except Exception as e:
        logger.error(f"set_interface_state failed: {e}")
        return False


def get_wifi_status():
    """Get Wi-Fi connection status.

    Returns:
        dict: {"ssid": str, "ip_address": str, "is_connected": bool}
    """
    if not IS_LINUX:
        logger.info("Wi-Fi status is unavailable on this platform.")
        return {"ssid": "UNAVAILABLE", "ip_address": "N/A", "is_connected": False}

    try:
        import re
        status = {"ssid": "Not connected", "ip_address": "N/A", "is_connected": False}

        if not os.path.exists("/sys/class/net/wlan0"):
            status["ssid"] = "N/A (No Wi-Fi)"
            return status

        cmd = ["/usr/bin/nmcli", "-t", "-f",
               "GENERAL.STATE,GENERAL.CONNECTION,IP4.ADDRESS", "dev", "show", "wlan0"]
        output = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL).strip()
        lines = output.split("\n")

        if len(lines) >= 3:
            if "100" in lines[0] or "connected" in lines[0]:
                status["is_connected"] = True
                ssid_match = re.search(r"GENERAL.CONNECTION:(.*)", lines[1])
                if ssid_match:
                    status["ssid"] = ssid_match.group(1)
                ip_match = re.search(r"IP4.ADDRESS\[1\]:(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", lines[2])
                if ip_match:
                    status["ip_address"] = ip_match.group(1)
        return status
    except Exception as e:
        logger.error(f"get_wifi_status failed: {e}")
        return {"ssid": "Error", "ip_address": "N/A", "is_connected": False}


def set_wifi_config(ssid: str, password: str, country_code: str = "FR"):
    """Configure Wi-Fi connection.

    Returns:
        bool: True if successful.
    """
    if not IS_LINUX:
        logger.warning("Wi-Fi configuration is unavailable on this platform.")
        return False

    try:
        # Set Wi-Fi country
        subprocess.run(
            ["sudo", "-n", "/usr/bin/raspi-config", "nonint", "do_wifi_country", country_code],
            check=True, capture_output=True, text=True, timeout=15
        )
        # Delete old connection
        subprocess.run(["sudo", "-n", "nmcli", "connection", "delete", ssid],
                       capture_output=True, check=False)
        # Connect
        cmd = ["sudo", "-n", "/usr/bin/nmcli", "device", "wifi", "connect", ssid]
        if password:
            cmd.extend(["password", password])
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=30)
        return True
    except Exception as e:
        logger.error(f"set_wifi_config failed: {e}")
        return False


def scan_wifi_networks():
    """Scan for available Wi-Fi networks.

    Returns:
        list: list of {"ssid": str, "signal": int, "security": str}
    """
    if not IS_LINUX:
        logger.info("Wi-Fi scanning is unavailable on this platform.")
        return []

    try:
        subprocess.run(["sudo", "-n", "nmcli", "device", "wifi", "rescan"],
                       timeout=15, check=False)
        import re
        result = subprocess.check_output(
            ["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "device", "wifi", "list"],
            text=True, stderr=subprocess.DEVNULL, timeout=15
        ).strip()
        networks = []
        seen = set()
        for line in result.split("\n"):
            parts = line.split(":")
            if len(parts) >= 3 and parts[0] and parts[0] not in seen:
                seen.add(parts[0])
                networks.append({
                    "ssid": parts[0],
                    "signal": int(parts[1]) if parts[1].isdigit() else 0,
                    "security": parts[2] if len(parts) > 2 else ""
                })
        return networks
    except Exception as e:
        logger.error(f"scan_wifi_networks failed: {e}")
        return []


def set_timezone(timezone: str):
    """Set the system timezone.

    Args:
        timezone: e.g. 'Europe/Paris', 'Asia/Shanghai'
    """
    if not IS_LINUX:
        logger.warning("System timezone configuration is unavailable on this platform.")
        return False

    try:
        subprocess.run(["sudo", "-n", "timedatectl", "set-timezone", timezone], check=True)
        return True
    except Exception as e:
        logger.error(f"set_timezone failed: {e}")
        return False


# ── Git / Application Update ──────────────────────────────────────

def is_git_repo(path=None):
    """Check whether *path* (defaults to BASE_DIR) is inside a git repository."""
    import subprocess
    if path is None:
        path = BASE_DIR
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=str(path), capture_output=True, text=True, timeout=5,
        )
        return result.returncode == 0 and result.stdout.strip() == "true"
    except Exception:
        return False


def git_get_info(path=None):
    """Return a dict with current commit hash, branch, and remote URL.

    Returns ``{}`` when *path* is not a git repo or git is unavailable.
    """
    import subprocess
    if path is None:
        path = BASE_DIR
    if not is_git_repo(path):
        return {}
    info = {}
    for key, args in (
        ("commit", ["git", "rev-parse", "--short", "HEAD"]),
        ("branch", ["git", "rev-parse", "--abbrev-ref", "HEAD"]),
        ("remote", ["git", "config", "--get", "remote.origin.url"]),
    ):
        try:
            result = subprocess.run(args, cwd=str(path), capture_output=True,
                                    text=True, timeout=5)
            info[key] = result.stdout.strip() if result.returncode == 0 else ""
        except Exception:
            info[key] = ""
    return info


def git_has_updates(path=None):
    """Check whether the remote has commits not yet in the local branch.

    Runs ``git fetch`` then compares.  Returns ``(has_updates: bool, info: dict)``.
    The *info* dict always contains ``commit`` and ``branch``; on success it
    also includes ``behind_count`` and ``new_commits`` (list of short logs).
    """
    import subprocess
    if path is None:
        path = BASE_DIR
    if not is_git_repo(path):
        return False, {}
    info = git_get_info(path)
    try:
        # Fetch without modifying working tree.
        subprocess.run(["git", "fetch", "--quiet"], cwd=str(path),
                       capture_output=True, timeout=30)
        branch = info.get("branch", "HEAD")
        # Count commits behind.
        result = subprocess.run(
            ["git", "rev-list", "--count", f"HEAD..origin/{branch}"],
            cwd=str(path), capture_output=True, text=True, timeout=5,
        )
        behind = int(result.stdout.strip()) if result.returncode == 0 and result.stdout.strip().isdigit() else 0
        info["behind_count"] = behind
        if behind > 0:
            log_result = subprocess.run(
                ["git", "log", "--oneline", f"HEAD..origin/{branch}", "--max-count=10"],
                cwd=str(path), capture_output=True, text=True, timeout=5,
            )
            info["new_commits"] = [line for line in log_result.stdout.strip().splitlines() if line]
        else:
            info["new_commits"] = []
        return behind > 0, info
    except Exception as e:
        logger.warning("git_has_updates failed: %s", e)
        return False, info


def git_create_backup(path=None):
    """Create a backup of the current code using git stash or file copy.

    Returns the backup directory path, or ``None`` on failure.
    The backup is stored in ``.update_backup/`` next to the repo.
    """
    import shutil
    if path is None:
        path = BASE_DIR
    backup_dir = path / ".update_backup"
    try:
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
        # Copy essential files (not .git, not __pycache__, not static/prepared)
        ignore_patterns = shutil.ignore_patterns(
            ".git", "__pycache__", "*.pyc", ".update_backup",
            "static", "logs", "cache", "config",
        )
        shutil.copytree(path, backup_dir, ignore=ignore_patterns)
        logger.info("Backup created at %s", backup_dir)
        return str(backup_dir)
    except Exception as e:
        logger.error("git_create_backup failed: %s", e)
        return None


def git_backup_exists(path=None):
    """Check if an update backup exists."""
    if path is None:
        path = BASE_DIR
    return (path / ".update_backup" / "app.py").is_file()


def git_delete_backup(path=None):
    """Delete the update backup directory."""
    import shutil
    if path is None:
        path = BASE_DIR
    backup_dir = path / ".update_backup"
    try:
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
            logger.info("Update backup deleted.")
            return True
        return False
    except Exception as e:
        logger.error("git_delete_backup failed: %s", e)
        return False


def generate_update_script(app_dir, startup_script="start_pictureframe.sh"):
    """Generate a self-contained Python update script (cross-platform).

    The script:
    1. Waits for the current server to exit
    2. Kills any remaining processes
    3. Creates a backup of the current code
    4. Runs ``git pull``
    5. Restarts the app
    6. Waits for the new instance to respond
    7. If health check fails, restores the backup and restarts again

    Returns ``(script_path: str, content: str)`` or ``(None, "")`` on failure.
    """
    import tempfile, os, json
    app_dir_str = str(app_dir)

    script_content = '''#!/usr/bin/env python3
"""Auto-generated PictureFrame update script. Runs independently after the web server exits."""
import os, sys, time, shutil, subprocess, signal, urllib.request, json

APP_DIR = r"%(APP_DIR)s"
LOG_FILE = os.path.join(APP_DIR, "logs", "update.log")
HEALTH_URL = "http://127.0.0.1:7090/api/ping"
BACKUP_DIR = os.path.join(APP_DIR, ".update_backup")
HEALTH_TIMEOUT = 60
HEALTH_INTERVAL = 3
IS_LINUX = sys.platform == "linux"
IS_WINDOWS = sys.platform == "win32"

FILES_TO_BACKUP = [
    "app.py", "local_slideshow.py", "platform_utils.py",
    "requirements.txt", "requirements-pi.txt", "setup.sh",
    "start_pictureframe.sh", "babel.cfg",
]
DIRS_TO_BACKUP = ["utils", "templates", "translations", "tests", "scripts"]

def log(msg):
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(time.strftime("%%Y-%%m-%%d %%H:%%M:%%S") + " [UPDATE] " + msg + "\\n")

def kill_remaining():
    """Kill any remaining app processes."""
    if IS_LINUX:
        pid_file = "/tmp/pictureframe_slideshow.pid"
        if os.path.exists(pid_file):
            try:
                with open(pid_file) as f:
                    pid = int(f.read().strip())
                os.kill(pid, signal.SIGTERM)
            except Exception:
                pass
            try:
                os.remove(pid_file)
            except Exception:
                pass
        subprocess.run(["pkill", "-f", "python3 -u app.py"], capture_output=True)
        subprocess.run(["pkill", "-f", "python3 app.py"], capture_output=True)
        subprocess.run(["pkill", "-f", "ffmpeg"], capture_output=True)
    elif IS_WINDOWS:
        subprocess.run(["taskkill", "/F", "/IM", "python.exe", "/FI",
                        "WINDOWTITLE eq PictureFrame*"], capture_output=True)
        # Also try to kill by command line match
        subprocess.run(
            ["wmic", "process", "where",
             "commandline like '%%app.py%%'", "call", "terminate"],
            capture_output=True)

def create_backup():
    """Copy current code to backup directory."""
    if os.path.exists(BACKUP_DIR):
        shutil.rmtree(BACKUP_DIR)
    os.makedirs(BACKUP_DIR)
    for item in FILES_TO_BACKUP:
        src = os.path.join(APP_DIR, item)
        if os.path.isfile(src):
            shutil.copy2(src, BACKUP_DIR)
    for d in DIRS_TO_BACKUP:
        src = os.path.join(APP_DIR, d)
        if os.path.isdir(src):
            dst = os.path.join(BACKUP_DIR, d)
            shutil.copytree(src, dst,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    log("Backup created at " + BACKUP_DIR)

def restore_backup():
    """Restore code from backup directory."""
    for item in FILES_TO_BACKUP:
        src = os.path.join(BACKUP_DIR, item)
        if os.path.isfile(src):
            shutil.copy2(src, APP_DIR)
    for d in DIRS_TO_BACKUP:
        src = os.path.join(BACKUP_DIR, d)
        dst = os.path.join(APP_DIR, d)
        if os.path.isdir(src):
            if os.path.isdir(dst):
                shutil.rmtree(dst)
            shutil.copytree(src, dst)

def git_pull():
    """Run git pull, return True on success."""
    try:
        result = subprocess.run(
            ["git", "pull"],
            cwd=APP_DIR, capture_output=True, text=True, timeout=60)
        log("git pull stdout: " + result.stdout[:500])
        if result.returncode == 0:
            return True
        log("git pull failed (rc=" + str(result.returncode) + "): " + result.stderr[:500])
        return False
    except Exception as e:
        log("git pull exception: " + str(e))
        return False

def install_deps():
    """Install dependencies from requirements.txt after git pull."""
    req_file = os.path.join(APP_DIR, "requirements.txt")
    if not os.path.isfile(req_file):
        log("No requirements.txt found, skipping dependency install.")
        return
    # Determine pip command: use venv if present, else global with --break-system-packages.
    venv_pip = os.path.join(APP_DIR, "venv", "bin", "pip")
    if os.path.isfile(venv_pip):
        pip_cmd = [venv_pip, "install", "-r", req_file]
    elif IS_LINUX:
        # PEP 668: --break-system-packages on Debian 12+/Pi OS Bookworm.
        pip_cmd = [sys.executable, "-m", "pip", "install", "--break-system-packages", "-r", req_file]
    else:
        pip_cmd = [sys.executable, "-m", "pip", "install", "-r", req_file]
    log("Installing dependencies: " + " ".join(pip_cmd))
    try:
        result = subprocess.run(pip_cmd, capture_output=True, text=True, timeout=300)
        if result.stdout:
            log("pip stdout: " + result.stdout[-500:])
        if result.stderr:
            log("pip stderr: " + result.stderr[-500:])
        if result.returncode == 0:
            log("Dependencies installed successfully.")
        else:
            log("pip install failed (rc=" + str(result.returncode) + ")")
    except Exception as e:
        log("pip install exception: " + str(e))

    # Also install Pi-specific requirements if on a Pi.
    pi_req = os.path.join(APP_DIR, "requirements-pi.txt")
    if os.path.isfile(pi_req) and IS_LINUX and os.path.exists("/proc/device-tree/model"):
        log("Installing Pi-specific dependencies...")
        if os.path.isfile(venv_pip):
            pi_cmd = [venv_pip, "install", "-r", pi_req]
        else:
            pi_cmd = [sys.executable, "-m", "pip", "install", "--break-system-packages", "-r", pi_req]
        try:
            result = subprocess.run(pi_cmd, capture_output=True, text=True, timeout=300)
            if result.returncode == 0:
                log("Pi-specific dependencies installed.")
            else:
                log("Pi pip install failed (rc=" + str(result.returncode) + ")")
        except Exception as e:
            log("Pi pip install exception: " + str(e))

def restart_app():
    """Restart the application."""
    if IS_LINUX:
        lock_file = "/tmp/pictureframe_app.lock"
        if os.path.exists(lock_file):
            try:
                os.remove(lock_file)
            except Exception:
                pass
        start_script = os.path.join(APP_DIR, "start_pictureframe.sh")
        if os.path.isfile(start_script):
            subprocess.Popen(
                ["bash", start_script],
                stdout=open(LOG_FILE, "a"),
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True)
        else:
            subprocess.Popen(
                [sys.executable, "app.py"],
                cwd=APP_DIR,
                stdout=open(LOG_FILE, "a"),
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True)
    elif IS_WINDOWS:
        subprocess.Popen(
            [sys.executable, "app.py"],
            cwd=APP_DIR,
            stdout=open(LOG_FILE, "a"),
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
    log("Restart command sent.")

def health_check(timeout=HEALTH_TIMEOUT):
    """Poll health endpoint, return True if server responds."""
    elapsed = 0
    while elapsed < timeout:
        try:
            req = urllib.request.Request(HEALTH_URL)
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(HEALTH_INTERVAL)
        elapsed += HEALTH_INTERVAL
    return False

# --- Main ---
os.makedirs(os.path.join(APP_DIR, "logs"), exist_ok=True)
log("Starting update process...")

log("Waiting for current processes to exit...")
time.sleep(3)

log("Cleaning up remaining processes...")
kill_remaining()
time.sleep(2)

log("Creating backup...")
create_backup()

log("Running git pull...")
if git_pull():
    log("Git pull succeeded.")
else:
    log("Git pull FAILED. Restoring backup.")
    restore_backup()
    log("Backup restored after git pull failure.")

log("Installing/updating dependencies...")
install_deps()

log("Restarting application...")
restart_app()

log("Waiting for new instance to respond (timeout: " + str(HEALTH_TIMEOUT) + "s)...")
if health_check():
    log("Update successful! New instance is responding.")
    sys.exit(0)

log("Health check failed. Rolling back to backup...")
kill_remaining()
time.sleep(2)
restore_backup()

log("Reinstalling dependencies from backup...")
install_deps()

log("Backup restored. Restarting...")
restart_app()

if health_check():
    log("Rollback successful! Previous version is running.")
    sys.exit(0)

log("CRITICAL: Rollback also failed! Manual intervention required.")
log("Try running: cd " + APP_DIR + " && python3 -m pip install -r requirements.txt && python3 app.py")
sys.exit(1)
''' % {"APP_DIR": app_dir_str}

    try:
        suffix = "_update.py"
        script_path = tempfile.NamedTemporaryFile(
            mode='w', suffix=suffix, delete=False, dir=app_dir_str)
        script_path.write(script_content)
        script_path.close()
        return script_path.name, script_content
    except Exception as e:
        logger.error("generate_update_script failed: %s", e)
        return None, ""


# ── USB ─────────────────────────────────────────────────────────

def find_and_mount_usb():
    """Find a USB device and mount it if necessary.

    Returns:
        tuple: (mount_path: Path or None, device_path: str or None, mounted_by_script: bool)
    """
    if not IS_LINUX:
        logger.info("USB device mounting is unavailable on this platform.")
        return None, None, False

    try:
        import json
        import tempfile
        result = subprocess.run(
            ["/usr/bin/lsblk", "-J", "-o", "NAME,MOUNTPOINT,TRAN,PATH"],
            capture_output=True, text=True, check=True, timeout=10
        )
        data = json.loads(result.stdout)

        for device in data.get("blockdevices", []):
            if device.get("tran") == "usb":
                for partition in device.get("children", []):
                    mountpoint = partition.get("mountpoint")
                    device_path = partition.get("path")
                    if not device_path:
                        continue
                    if mountpoint:
                        return Path(mountpoint), device_path, False
                    temp_mount_dir = tempfile.mkdtemp(prefix="pictureframe_usb_")
                    subprocess.run(
                        ["sudo", "-n", "/usr/bin/mount", device_path, temp_mount_dir],
                        check=True, capture_output=True, text=True, timeout=15
                    )
                    return Path(temp_mount_dir), device_path, True
    except Exception as e:
        logger.error(f"find_and_mount_usb failed: {e}")

    return None, None, False


def unmount_usb(mount_path: str):
    """Unmount a USB device.

    Returns:
        bool: True if successful.
    """
    if not IS_LINUX:
        logger.warning("USB device unmounting is unavailable on this platform.")
        return False

    try:
        subprocess.run(
            ["sudo", "-n", "/usr/bin/umount", str(mount_path)],
            check=True, capture_output=True, text=True, timeout=15
        )
        return True
    except Exception as e:
        logger.error(f"unmount_usb failed: {e}")
        return False


# ── Sway / Wayland helpers ──────────────────────────────────────

def get_sway_socket():
    """Find the Sway IPC socket path.

    Returns:
        str: socket path or None.
    """
    if not IS_LINUX:
        return None

    import glob
    try:
        uid = os.getuid()
        socks = glob.glob(f"/run/user/{uid}/sway-ipc.*")
        return socks[0] if socks else None
    except Exception:
        return None


def reload_sway_config():
    """Reload the Sway compositor configuration."""
    if not IS_LINUX:
        logger.info("Sway is unavailable on this platform.")
        return

    try:
        socket_path = get_sway_socket()
        env = os.environ.copy()
        if socket_path:
            env["SWAYSOCK"] = socket_path
        subprocess.run(["swaymsg", "reload"], env=env, check=False)
    except Exception as e:
        logger.error(f"reload_sway_config failed: {e}")


# ── Video / ffmpeg ──────────────────────────────────────────────

def get_ffmpeg_encoders():
    """List available ffmpeg encoders.

    Returns:
        str: raw ffmpeg -encoders output, or empty string if unavailable.
    """
    try:
        result = subprocess.run(
            ["ffmpeg", "-encoders"],
            capture_output=True, text=True, check=True, timeout=20
        )
        return result.stdout
    except Exception as e:
        logger.warning(f"ffmpeg not available: {e}")
        return ""


def has_ffmpeg() -> bool:
    """Check if ffmpeg is available on the system."""
    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True, check=True, timeout=10
        )
        return True
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


# ── System info ─────────────────────────────────────────────────

def get_system_info():
    """Gather system information for the web dashboard.

    Returns:
        dict: CPU percent, memory, disk, temperature, uptime info.
    """
    import psutil

    info = {
        "cpu_percent": psutil.cpu_percent(interval=1),
        "memory": psutil.virtual_memory()._asdict(),
        "disk": psutil.disk_usage("/")._asdict() if IS_LINUX else psutil.disk_usage("C:\\")._asdict(),
        "temperature": get_cpu_temperature(),
        "is_raspberry_pi": IS_RASPBERRY_PI,
        "platform": platform.system(),
        "pi_model": get_pi_model(),
    }
    return info


# ── Pygame mode helper ──────────────────────────────────────────

def get_pygame_display_flags():
    """Return appropriate Pygame display flags for the current OS.

    On Pi: FULLSCREEN | NOFRAME (kiosk mode).
    On Windows: windowed mode (no flags) for dev/testing.
    """
    import pygame

    if IS_LINUX:
        return pygame.FULLSCREEN | pygame.NOFRAME
    else:
        # Windowed mode for Windows development
        return 0  # No special flags = windowed


def get_pygame_display_size():
    """Return the display size for Pygame.

    On Pi: fullscreen (auto-detect from display).
    On Windows: fixed 1280x720 window for dev convenience.
    """
    if IS_LINUX:
        import pygame
        display_was_initialized = pygame.display.get_init()
        if not display_was_initialized:
            pygame.display.init()
        info = pygame.display.Info()
        size = (info.current_w, info.current_h)
        if not display_was_initialized:
            pygame.display.quit()
        return size
    else:
        return (1280, 720)
