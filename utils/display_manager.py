#!/usr/bin/env python3
import os
import subprocess
import time
import json
import glob
import requests
import logging
from pathlib import Path
from .config_manager import load_config

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
logger = logging.getLogger("pictureframe.display_manager")

# Get the log level from the configuration.
level_name = config.get("level_log", "INFO")
level = getattr(logging, level_name.upper(), logging.INFO)
logger.setLevel(level)
logger.propagate = False

# Rotating file handler (10 MB max, 3 backups).
from logging.handlers import RotatingFileHandler
file_handler = RotatingFileHandler(
    LOGSDIR / "pictureframe.log",
    maxBytes=10 * 1024 * 1024,
    backupCount=3,
    encoding="utf-8"
)
file_handler.setLevel(level)
file_formatter = EmojiFormatter(
    '%(emoji)s🟩%(asctime)s %(message)s',
    datefmt='%d-%m %H:%M:%S'
)
file_handler.setFormatter(file_formatter)

# Add the handler, avoiding duplicates if the module is re-imported.
if not logger.handlers:
    logger.addHandler(file_handler)

# Startup messages.
logger.debug("--------------------Starting Display_Manager----------------------")
logger.info(f"Active log level: {level_name}")
logger.debug("🔍=Debug")
logger.info("ℹ️=Info")
logger.warning("😒=Warning")
logger.error("❌=Error")
logger.info("🟨=App")
logger.info("🟪=Slideshow_Manager")
logger.info("🟦=Local_Slideshow")
logger.info("🟩=Display_Manager")

# ============================================================
# Module functions.
# ============================================================

def get_display_output_name():
    """Find the name of the active HDMI output (Wayfire/Sway)."""
    #logger.info("get_display_output_name() started")
    
    try:
        # Try wlr-randr (Wayfire/Pi OS).
        logger.debug("🖥 Test wlr-randr...")
        result = subprocess.run(
            ["wlr-randr"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5
        )
        #logger.debug(f"🖥 wlr-randr RC={result.returncode} STDOUT={result.stdout}")
        
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if line and not line[0].isspace():
                    output = line.split()[0]
                    logger.info(f"✅ Output detected: {output}")
                    #print(f"OUTPUT: {output}")  # User information.
                    return output
        
        # Fall back to Sway.
        logger.debug("🖥 Fallback sway...")
        env = os.environ.copy()
        if "SWAYSOCK" not in env:
            uid = os.getuid()
            socks = glob.glob(f"/run/user/{uid}/sway-ipc.*")
            if socks:
                env["SWAYSOCK"] = socks[0]
        
        result = subprocess.run(
            ["swaymsg", "-t", "get_outputs"],
            capture_output=True,
            text=True,
            env=env,
            timeout=5,
            check=False
        )
        
        if result.returncode == 0:
            outputs = json.loads(result.stdout)
            logger.debug(f"🖥 sway: {len(outputs)} outputs")
            
            for o in outputs:
                name = o.get("name", "?")
                active = o.get("active", False)
                logger.debug(f"sway: {name} active={active}")
                
                if active or o.get("current_mode"):
                    logger.info(f"✅ SWAY HDMI: {name}")
                    return name
        
        logger.warning("😒 0x0 - NO OUTPUT")
        return None
        
    except Exception as e:
        logger.error(f"❌ ERROR: {e}")
        return None


def send_smart_plug_command(url):
    """Send an HTTP command to the smart plug."""
    if not url:
        return False, "Pas d'URL"
    
    try:
        logger.info(f"Sending smart plug command: {url}")
        r = requests.post(url, timeout=5)
        logger.debug(f"Smart plug response: {r.status_code}")
        
        if 200 <= r.status_code < 300:
            print(f"Smart plug command sent: {url}")
            logger.info("✅ Smart plug command succeeded")
            return True, "OK"
        
        logger.warning(f"😒 HTTP error: {r.status_code}")
        return False, f"Error {r.status_code}"
        
    except Exception as e:
        logger.error(f"❌ Request exception: {e}")
        return False, str(e)


def set_display_power(on=True):
    """Turn the display on or off (smart plug or software)."""
    logger.info(f"⏻ set_display_power({on})")
    config = load_config()
    
    if config.get("smart_plug_enabled"):
        if on:
            # Turn on the smart plug.
            on_url = config.get("smart_plug_on_url")
            success, msg = send_smart_plug_command(on_url)
            
            if not success:
                logger.error(f"❌ Smart plug failed: {msg}")
                return False, f"Smart plug failed: {msg}"
            
            delay = int(config.get("smart_plug_on_delay", 5))
            logger.info(f"⏳ Waiting {delay}s for display initialization...")
            time.sleep(delay)
            
            # Reboot to stabilize HDMI.
            flag_path = LOGSDIR / "pictureframe_reboot_flag.tmp"
            flag_path.parent.mkdir(exist_ok=True)
            flag_path.touch()
            logger.info("✅ ⏻ Rebooting to apply HDMI resolution...")
            subprocess.run(["sudo", "-n", "reboot"], check=False)
            return True, "Reboot initiated"
        else:
            # Turn off DPMS, then the smart plug.
            logger.info("⏻ Turning off DPMS, then the smart plug")
            set_software_display_power(False)
            time.sleep(1)
            
            off_url = config.get("smart_plug_off_url")
            success, msg = send_smart_plug_command(off_url)
            
            if success:
                logger.info("✅ Smart plug turned off")
            else:
                logger.warning(f"😒 Failed to turn off smart plug: {msg}")
            
            return success, msg
    else:
        logger.info("⏻ No smart plug configured; using DPMS only.")
        return set_software_display_power(on)


def set_software_display_power(on=True):
    """Enable or disable DPMS via wlr-randr/swaymsg."""
    #logger.info(f"set_software_display_power({on})")
    output = get_display_output_name()
    
    if not output:
        logger.warning("🖥😒 Pas de HDMI.")
        return False, "Pas de HDMI"
    
    state = "on" if on else "off"
    
    try:
        # Try wlr-randr.
        cmd = ["wlr-randr", "--output", output, f"--{state}"]
        logger.info(f"🖥️ Commande: {' '.join(cmd)}")
        
        result = subprocess.run(
            cmd,
            timeout=5,
            capture_output=True,
            text=True,
            check=False
        )
        logger.debug(f"🖥️ wlr DPMS: RC={result.returncode} STDOUT={result.stdout.strip()} ERR={result.stderr.strip()}")
        
        if result.returncode == 0:
            logger.info(f"🖥️✅ Display {output} -> {state} via wlr-randr.")
            return True, "OK"
        
        # Fall back to swaymsg.
        logger.info("🖥️Fallback swaymsg DPMS...")
        result = subprocess.run(
            ["swaymsg", "output", output, "dpms", state],
            timeout=5,
            capture_output=True,
            text=True
        )
        logger.debug(f"🖥️sway DPMS: RC={result.returncode}")
        
        if result.returncode == 0:
            logger.info(f"🖥️✅ Display {output} -> {state} via swaymsg.")
            return True, "OK"
        else:
            logger.warning(f"🖥️😒 swaymsg DPMS failed: RC={result.returncode}")
            return False, "DPMS failed"
            
    except Exception as e:
        err_msg = f"🖥️DPMS error: {e}"
        logger.error(f"❌ {err_msg}")
        return False, err_msg
