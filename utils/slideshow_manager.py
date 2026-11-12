import os
import glob
import psutil
import subprocess
import sys
import time
import logging
from pathlib import Path
from logging.handlers import RotatingFileHandler

from .display_manager import set_display_power
from .config_manager import load_config, save_config
from .app_mode import get_app_mode, VALID_APP_MODES
from platform_utils import IS_LINUX, get_status_file

# ============================================================
# Configure logging with emojis.
# ============================================================
LOGSDIR = Path(__file__).resolve().parent.parent / "logs"
LOGSDIR.mkdir(exist_ok=True)

class EmojiFormatter(logging.Formatter):
    """Custom formatter that adds an emoji for each log level."""
    EMOJI_MAP = {
        "DEBUG": "🔍",
        "INFO": "ℹ️",
        "WARNING": "😒",
        "ERROR": "❌",
        "CRITICAL": "🔥"
    }

    def format(self, record):
        emoji = self.EMOJI_MAP.get(record.levelname, "")
        record.emoji = emoji
        return super().format(record)

# Load configuration.
config = load_config()

# Create a logger for this module.
logger = logging.getLogger("pictureframe.slideshow_manager")

# Get the log level from the configuration.
level_name = config.get("level_log", "INFO")
level = getattr(logging, level_name.upper(), logging.INFO)
logger.setLevel(level)
logger.propagate = False

# Rotating file handler (10 MB max, 3 backups).
file_handler = RotatingFileHandler(
    LOGSDIR / "pictureframe.log",
    maxBytes=10 * 1024 * 1024,
    backupCount=3,
    encoding="utf-8"
)
file_handler.setLevel(level)

# Use the updated format with an emoji at the beginning of each line.
file_formatter = EmojiFormatter(
    '%(emoji)s🟪%(asctime)s %(message)s',
    datefmt='%d-%m %H:%M:%S'
)
file_handler.setFormatter(file_formatter)

# Add the handlers, avoiding duplicates if the module is re-imported.
if not logger.handlers:
    logger.addHandler(file_handler)

# Startup messages.
logger.debug("----------------Initializing Slideshow Manager----------------")

# ============================================================
# Constants
# ============================================================
PID_FILE = get_status_file("pictureframe_slideshow.pid")


class ProcessSpec:
    """Description of a display process managed by this module."""

    def __init__(self, script, pid_name):
        self.script = script
        self.pid_file = get_status_file(f"{pid_name}.pid")

    def __repr__(self):  # pragma: no cover - debugging aid
        return f"ProcessSpec({self.script!r})"


# The two top-level run modes each have their own child process.
SLIDESHOW = ProcessSpec("local_slideshow.py", "pictureframe_slideshow")
BACKGROUND = ProcessSpec("background_updater.py", "pictureframe_background")


# ============================================================
# Generic process management
# ============================================================
def _is_process_running(spec):
    """Check whether the process described by ``spec`` is currently running."""
    if not os.path.exists(spec.pid_file):
        return False

    try:
        with open(spec.pid_file, "r") as f:
            pid = int(f.read().strip())

        if not psutil.pid_exists(pid):
            logger.debug(f"{spec.script} PID {pid} no longer exists")
            return False

        p = psutil.Process(pid)
        is_running = p.is_running() and any(spec.script in s for s in p.cmdline())
        logger.debug(f"{spec.script} running? {is_running} (PID: {pid})")
        return is_running
    except (psutil.NoSuchProcess, FileNotFoundError, ValueError) as e:
        logger.error(f"Error checking {spec.script}: {e}")
        return False


def _start_process(spec):
    """Start the process described by ``spec`` robustly."""
    logger.debug(f"📟 ✅ Start {spec.script}")

    # ✅ Step 1: Clean up zombie processes before checking the PID.
    logger.debug(f"📟 Proactively cleaning up {spec.script} zombie processes")
    for proc in psutil.process_iter(attrs=["pid", "cmdline", "status"]):
        try:
            cmdline = proc.info.get("cmdline")
            status = proc.info.get("status")
            if cmdline and any(spec.script in part for part in cmdline):
                if status == psutil.STATUS_ZOMBIE:
                    logger.warning(f"📟 Zombie found: PID {proc.pid}; cleaning up...")
                    proc.kill()
                    proc.wait(timeout=1)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired):
            continue

    # ✅ Step 2: Clean up a stale PID file if no process is active.
    if os.path.exists(spec.pid_file):
        try:
            with open(spec.pid_file, "r") as f:
                pid = int(f.read().strip())

            if not psutil.pid_exists(pid):
                os.remove(spec.pid_file)
                logger.info(f"📟 Removed stale PID file {pid}")
            else:
                # Check that this PID is running the target script.
                try:
                    proc = psutil.Process(pid)
                    if proc.is_running() and any(spec.script in s for s in proc.cmdline()):
                        logger.info(f"📟 {spec.script} already running (PID {pid}); not starting another")
                        return
                except psutil.NoSuchProcess:
                    pass
        except Exception as e:
            logger.debug(f"📟 Error cleaning up PID: {e}")
            try:
                os.remove(spec.pid_file)
            except OSError:
                pass

    # Check again whether the process is already running.
    if _is_process_running(spec):
        logger.info(f"📟 {spec.script} already running; not starting another")
        return

    # ✅ Step 3: Prepare the environment.
    python_executable = sys.executable

    # ✅ Step 4: Start the process (simple and reliable method).
    try:
        proc = subprocess.Popen(
            [python_executable, "-u", spec.script],
            env=os.environ.copy()
        )

        # Save the new process PID.
        with open(spec.pid_file, "w") as f:
            f.write(str(proc.pid))

        logger.debug(f"📟 ✅ {spec.script} started with PID {proc.pid}")
    except Exception as e:
        logger.error(f"📟 ❌ Failed to start {spec.script}: {e}")


def _stop_process_by_pid(spec, pid):
    """Stop a process described by ``spec`` by its PID."""
    if psutil.pid_exists(pid):
        logger.info(f"📟 Stopping {spec.script} process {pid}...")
        p = psutil.Process(pid)
        p.terminate()
        try:
            p.wait(timeout=3)
            logger.info(f"📟 Process {pid} stopped gracefully")
        except psutil.TimeoutExpired:
            logger.warning(f"📟 Process {pid} did not respond; forcing termination")
            p.kill()
            logger.info(f"📟 Process {pid} forcefully terminated")


def _kill_stray_processes(spec):
    """Terminate any remaining processes running ``spec.script`` (safety net)."""
    for proc in psutil.process_iter(attrs=["pid", "cmdline"]):
        try:
            if proc.info["cmdline"] and any(spec.script in part for part in proc.info["cmdline"]):
                logger.warning(f"📟 Cleaning up stray {spec.script} process (PID: {proc.pid})")
                proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue


def _stop_process(spec):
    """Stop the process described by ``spec`` and wait for it to exit."""
    logger.info(f"📟 {spec.script} stop requested")

    if os.path.exists(spec.pid_file):
        try:
            with open(spec.pid_file, "r") as f:
                pid = int(f.read().strip())
            _stop_process_by_pid(spec, pid)
        except (IOError, ValueError, psutil.NoSuchProcess) as e:
            logger.error(f"📟 Warning while stopping {spec.script}: {e}")
        finally:
            # Ensure the PID file is removed.
            if os.path.exists(spec.pid_file):
                os.remove(spec.pid_file)
                logger.debug("📟 PID file deleted")

    # Extra safety: terminate any remaining processes that might be zombies.
    _kill_stray_processes(spec)


# ============================================================
# Public API — slideshow (unchanged behavior)
# ============================================================

def is_slideshow_running():
    """Check whether a slideshow process is currently running."""
    return _is_process_running(SLIDESHOW)


def start_slideshow():
    """Start the slideshow process robustly."""
    _start_process(SLIDESHOW)


def stop_slideshow():
    """Stop the slideshow process robustly and wait for it to exit."""
    _stop_process(SLIDESHOW)

    # Turn off the display cleanly (via smart plug or DPMS).
    logger.info("📟 Turning off the display")
    set_display_power(on=False)


def restart_slideshow_for_update():
    """
    Restart the slideshow after a content update without turning off the display.
    Used after imports and photo edits.
    """
    logger.info("📟 Restarting slideshow to apply content updates")

    # 1. Stop the existing process (without calling set_display_power).
    if os.path.exists(SLIDESHOW.pid_file):
        try:
            with open(SLIDESHOW.pid_file, "r") as f:
                pid = int(f.read().strip())
            _stop_process_by_pid(SLIDESHOW, pid)
            if os.path.exists(SLIDESHOW.pid_file):
                os.remove(SLIDESHOW.pid_file)
        except Exception as e:
            logger.error(f"📟 Warning while stopping for update: {e}")

    # 2. Start a new process.
    _start_process(SLIDESHOW)
    logger.info("📟 Slideshow restarted to apply content updates")


def restart_slideshow_process():
    """
    Restart only the slideshow process without affecting display power.
    Ideal for applying configuration changes without a full restart cycle.
    """
    logger.info("📟 Slideshow process restart requested")

    # 1. Stop the existing process (without calling set_display_power).
    if os.path.exists(SLIDESHOW.pid_file):
        try:
            with open(SLIDESHOW.pid_file, "r") as f:
                pid = int(f.read().strip())
            _stop_process_by_pid(SLIDESHOW, pid)
        except Exception as e:
            logger.error(f"📟 Error stopping process: {e}")

        if os.path.exists(SLIDESHOW.pid_file):
            try:
                os.remove(SLIDESHOW.pid_file)
            except OSError as e:
                logger.warning(f"📟 Unable to delete PID file: {e}")

    # Display a restart message on screen.
    try:
        python_executable = sys.executable
        message = "Redémarrage du diaporama..."

        # Use Popen to avoid blocking and ensure the environment is correct.
        env = os.environ.copy()
        if IS_LINUX and "SWAYSOCK" not in env:
            user_id = os.getuid()
            socks = glob.glob(f"/run/user/{user_id}/sway-ipc.*")
            if socks:
                env["SWAYSOCK"] = socks[0]

        subprocess.Popen([python_executable, "utils/display_message.py", message], env=env)
        time.sleep(1)  # Allow the message to appear.
        logger.info("📟 Restart message displayed")
    except Exception as e:
        logger.warning(f"📟 Unable to display restart message: {e}")

    # 2. Start a new process.
    _start_process(SLIDESHOW)
    logger.info("📟 ✅ Slideshow process restarted")


# ============================================================
# Public API — background updater
# ============================================================

def is_background_updater_running():
    """Check whether the background updater process is currently running."""
    return _is_process_running(BACKGROUND)


def start_background_updater():
    """Start the background updater process robustly."""
    _start_process(BACKGROUND)


def stop_background_updater():
    """Stop the background updater process.

    Unlike stopping the slideshow, this never touches display power:
    the machine is a regular desktop, not a photo frame.
    """
    _stop_process(BACKGROUND)


def restart_background_updater_for_update():
    """Restart the background updater after a content update."""
    logger.info("📟 Restarting background updater to apply content updates")
    if os.path.exists(BACKGROUND.pid_file):
        try:
            with open(BACKGROUND.pid_file, "r") as f:
                pid = int(f.read().strip())
            _stop_process_by_pid(BACKGROUND, pid)
            if os.path.exists(BACKGROUND.pid_file):
                os.remove(BACKGROUND.pid_file)
        except Exception as e:
            logger.error(f"📟 Warning while stopping for update: {e}")
    _start_process(BACKGROUND)
    logger.info("📟 Background updater restarted to apply content updates")


# ============================================================
# Public API — mode-aware display process control
# ============================================================

def _display_spec():
    """Return the ProcessSpec matching the current run mode."""
    from .config_manager import load_config as _load
    if get_app_mode(_load()) == "background_updater":
        return BACKGROUND
    return SLIDESHOW


def start_display_process():
    """Start the display process matching the current run mode."""
    spec = _display_spec()
    if spec is BACKGROUND:
        start_background_updater()
    else:
        start_slideshow()


def stop_display_process():
    """Stop the display process matching the current run mode."""
    spec = _display_spec()
    if spec is BACKGROUND:
        stop_background_updater()
    else:
        stop_slideshow()


def is_display_process_running():
    """Check whether the display process matching the current run mode runs."""
    return _is_process_running(_display_spec())


def restart_display_process_for_update():
    """Restart the current display process after a content update."""
    if _display_spec() is BACKGROUND:
        restart_background_updater_for_update()
    else:
        restart_slideshow_for_update()


def restart_display_process():
    """Restart the current display process after a configuration change."""
    if _display_spec() is BACKGROUND:
        # No on-screen restart message exists for the background updater.
        restart_background_updater_for_update()
    else:
        restart_slideshow_process()


def _stop_process_quietly(spec):
    """Stop the process by its PID file without touching display power.

    Also terminates any stray instance of ``spec.script`` that is still
    running but was not tracked through the PID file (e.g. a slideshow
    window left open from before a mode switch).
    """
    if os.path.exists(spec.pid_file):
        try:
            with open(spec.pid_file, "r") as f:
                pid = int(f.read().strip())
            _stop_process_by_pid(spec, pid)
        except (IOError, ValueError, psutil.NoSuchProcess) as e:
            logger.error(f"📟 Warning while stopping {spec.script}: {e}")
        finally:
            if os.path.exists(spec.pid_file):
                os.remove(spec.pid_file)

    # Safety net: kill any remaining instance of this script.
    _kill_stray_processes(spec)


def switch_app_mode(new_mode):
    """Switch the top-level run mode and restart the display process.

    Validates ``new_mode``, stops whichever display process is currently
    active (in both modes, to avoid two renderers at once), persists the
    new mode to config.json and starts the newly selected process.
    Display power is never touched during a mode switch.

    Returns the effective mode (never raises on invalid input).
    """
    if new_mode not in VALID_APP_MODES:
        logger.warning("switch_app_mode: invalid mode %r; ignoring", new_mode)
        return get_app_mode()

    # Stop both processes so no stale renderer survives the switch.
    # Use the quiet stop: switching modes must not power off the display.
    _stop_process_quietly(SLIDESHOW)
    _stop_process_quietly(BACKGROUND)

    config = load_config()
    if config.get("app_mode") != new_mode:
        config["app_mode"] = new_mode
        save_config(config)
    logger.info("📟 App mode switched to %s", new_mode)

    # Start the newly selected display process.
    if new_mode == "background_updater":
        start_background_updater()
    else:
        start_slideshow()
    return new_mode
