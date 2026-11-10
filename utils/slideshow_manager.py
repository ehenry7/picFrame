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
from .config_manager import load_config
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
# Constantes
# ============================================================
PID_FILE = get_status_file("pictureframe_slideshow.pid")

# ============================================================
# Fonctions
# ============================================================
def is_slideshow_running():
    """Check whether a slideshow process is currently running."""
    if not os.path.exists(PID_FILE):
        return False

    try:
        with open(PID_FILE, "r") as f:
            pid = int(f.read().strip())

        if not psutil.pid_exists(pid):
            logger.error(f"PID {pid} n'existe plus")
            return False

        p = psutil.Process(pid)
        is_running = p.is_running() and any("local_slideshow.py" in s for s in p.cmdline())
        logger.debug(f"Slideshow tourne ? {is_running} (PID: {pid})")
        return is_running
    except (psutil.NoSuchProcess, FileNotFoundError, ValueError) as e:
        logger.error(f"Error checking slideshow: {e}")
        return False

def start_slideshow():
    """Start the slideshow process robustly."""
    logger.debug("📟 ✅ Start Slideshow")

    # ✅ Step 1: Clean up zombie processes before checking the PID.
    logger.debug("📟 Proactively cleaning up local_slideshow.py zombie processes")
    for proc in psutil.process_iter(attrs=["pid", "cmdline", "status"]):
        try:
            cmdline = proc.info.get("cmdline")
            status = proc.info.get("status")
            if cmdline and any("local_slideshow.py" in part for part in cmdline):
                if status == psutil.STATUS_ZOMBIE:
                    logger.warning(f"📟 Zombie found: PID {proc.pid}; cleaning up...")
                    proc.kill()
                    proc.wait(timeout=1)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired):
            continue

    # ✅ Step 2: Clean up a stale PID file if no process is active.
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, "r") as f:
                pid = int(f.read().strip())

            if not psutil.pid_exists(pid):
                os.remove(PID_FILE)
                logger.info(f"📟 Removed stale PID file {pid}")
            else:
                # Check that this PID is running local_slideshow.py.
                try:
                    proc = psutil.Process(pid)
                    if proc.is_running() and any("local_slideshow.py" in s for s in proc.cmdline()):
                        logger.info(f"📟 Slideshow already running (PID {pid}); not starting another")
                        return
                except psutil.NoSuchProcess:
                    pass
        except Exception as e:
            logger.debug(f"📟 Error cleaning up PID: {e}")
            try:
                os.remove(PID_FILE)
            except:
                pass

    # Check again whether a slideshow is already running.
    if is_slideshow_running():
        logger.info("📟 Slideshow already running; not starting another")
        return

    # ✅ Step 3: Prepare the environment.
    python_executable = sys.executable

    # ✅ Step 4: Start the slideshow (simple and reliable method).
    try:
        proc = subprocess.Popen(
            [python_executable, "-u", "local_slideshow.py"],
            env=os.environ.copy()
        )

        # Save the new process PID.
        with open(PID_FILE, "w") as f:
            f.write(str(proc.pid))

        logger.debug(f"📟 ✅ Slideshow started with PID {proc.pid}")
    except Exception as e:
        logger.error(f"📟 ❌ Failed to start slideshow: {e}")

def _stop_process_by_pid(pid):
    """Stop a slideshow process by its PID."""
    if psutil.pid_exists(pid):
        logger.info(f"📟 Stopping slideshow process {pid}...")
        p = psutil.Process(pid)
        p.terminate()
        try:
            p.wait(timeout=3)
            logger.info(f"📟 Process {pid} stopped gracefully")
        except psutil.TimeoutExpired:
            logger.warning(f"📟 Process {pid} did not respond; forcing termination")
            p.kill()
            logger.info(f"📟 Process {pid} forcefully terminated")

def stop_slideshow():
    """Stop the slideshow process robustly and wait for it to exit."""
    config = load_config()
    is_smart_plug_enabled = config.get("smart_plug_enabled", False)

    logger.info("📟 Slideshow stop requested")

    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, "r") as f:
                pid = int(f.read().strip())
            _stop_process_by_pid(pid)
        except (IOError, ValueError, psutil.NoSuchProcess) as e:
            logger.error(f"📟 Warning while stopping slideshow: {e}")
        finally:
            # Ensure the PID file is removed.
            if os.path.exists(PID_FILE):
                os.remove(PID_FILE)
                logger.debug("📟 PID file deleted")

    # Extra safety: terminate any remaining processes that might be zombies.
    for proc in psutil.process_iter(attrs=["pid", "cmdline"]):
        try:
            if proc.info["cmdline"] and any("local_slideshow.py" in part for part in proc.info["cmdline"]):
                logger.warning(f"📟 Cleaning up zombie slideshow process (PID: {proc.pid})")
                proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

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
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, "r") as f:
                pid = int(f.read().strip())
            _stop_process_by_pid(pid)
            if os.path.exists(PID_FILE):
                os.remove(PID_FILE)
        except Exception as e:
            logger.error(f"📟 Warning while stopping for update: {e}")

    # 2. Start a new process.
    start_slideshow()
    logger.info("📟 Slideshow restarted to apply content updates")

def restart_slideshow_process():
    """
    Restart only the slideshow process without affecting display power.
    Ideal for applying configuration changes without a full restart cycle.
    """
    logger.info("📟 Slideshow process restart requested")

    # 1. Stop the existing process (without calling set_display_power).
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, "r") as f:
                pid = int(f.read().strip())
            _stop_process_by_pid(pid)
        except Exception as e:
            logger.error(f"📟 Error stopping process: {e}")

        if os.path.exists(PID_FILE):
            try:
                os.remove(PID_FILE)
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
    start_slideshow()
    logger.info("📟 ✅ Slideshow process restarted")
