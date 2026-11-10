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


def get_slideshow_command_dir() -> Path:
    """Return the cross-process command queue used when POSIX signals are unavailable."""
    return get_temp_dir() / "pictureframe_slideshow_commands"


def enqueue_slideshow_command(command: str) -> None:
    """Queue a slideshow command for platforms without the POSIX control signals."""
    if command not in {"next", "previous", "toggle_pause"}:
        raise ValueError(f"Unsupported slideshow command: {command}")

    command_dir = get_slideshow_command_dir()
    command_dir.mkdir(parents=True, exist_ok=True)
    command_file = command_dir / f"{uuid.uuid4().hex}.txt"
    command_file.write_text(command, encoding="utf-8")


def consume_slideshow_commands() -> list[str]:
    """Read and remove queued slideshow commands."""
    command_dir = get_slideshow_command_dir()
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
        status = {"ssid": "Non connecté", "ip_address": "N/A", "is_connected": False}

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
