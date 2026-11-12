import faulthandler
import logging
import os
import sys
import time
from pathlib import Path
from logging.handlers import RotatingFileHandler

_startup_started = time.monotonic()
_bootstrap_handlers = []
if __name__ == '__main__':
    _startup_log_dir = Path(__file__).resolve().parent / "logs"
    _startup_log_dir.mkdir(exist_ok=True)
    _bootstrap_handlers = [
        logging.StreamHandler(),
        RotatingFileHandler(
            _startup_log_dir / "pictureframe.log",
            maxBytes=10 * 1024 * 1024, backupCount=3, encoding="utf-8"
        ),
    ]
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(process)d:%(threadName)s] %(levelname)s %(message)s",
        handlers=_bootstrap_handlers,
    )
    _startup_trace_file = (_startup_log_dir / "startup_threads.log").open("a", encoding="utf-8")
    faulthandler.dump_traceback_later(30, file=_startup_trace_file)
    logging.info("Startup: PID=%s Python=%s cwd=%s", os.getpid(), sys.executable, Path.cwd())
    logging.info("Startup: if startup stalls for 30s, thread stacks will be written to %s",
                 _startup_log_dir / "startup_threads.log")
    logging.info("Startup: loading Flask and third-party dependencies")

    def log_unhandled_exception(exc_type, exc_value, exc_traceback):
        logging.critical("Unhandled application exception",
                         exc_info=(exc_type, exc_value, exc_traceback))

    sys.excepthook = log_unhandled_exception

from flask import Flask, g, render_template, request, redirect, url_for, session, flash, stream_with_context, Response, jsonify, send_from_directory
import json
import re
from flask_babel import Babel, _
import subprocess
import psutil
import glob
import requests
import threading
import collections
import shutil
import io
import tempfile
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
from werkzeug.security import check_password_hash
import secrets
import signal
import traceback

logging.getLogger(__name__).info("Startup: loading photo download and slideshow managers")
from utils.auth import login_required # type: ignore
# Mode-aware display process control: these resolve to the Pygame
# slideshow in picture_frame mode and to background_updater.py in
# background_updater mode.
from utils.slideshow_manager import (
    is_display_process_running,
    start_display_process,
    stop_display_process,
    restart_display_process,
    restart_display_process_for_update,
    switch_app_mode,
)
from utils.app_mode import get_app_mode
from utils.config_manager import load_config, save_config
from utils.playlist_manager import load_playlists, save_playlists
logging.getLogger(__name__).info("Startup: loading authentication, network, and display utilities")
from utils.auth_manager import change_password
from utils.network_manager import get_interface_status, set_interface_state
from utils.wifi_manager import set_wifi_config # Import the new utility
from utils.display_manager import get_display_output_name, set_display_power
logging.getLogger(__name__).info("Startup: loading photo preparation and import utilities")
from utils.prepare_all_photos import prepare_all_photos_with_progress
from utils.import_usb_photos import import_usb_photos  # Moved to utils.
from utils.metadata_utils import get_photo_metadata, format_photo_metadata, format_preview_location
from utils.photo_import import PHOTO_EXTENSIONS, photo_digest, stream_digest
from utils.photo_crop import original_photo, oriented_image, validate_crop, load_crops, save_crops, CROP_LOCK
from utils.image_filters import apply_filter_to_image, add_text_to_polaroid, add_text_to_image, create_polaroid_effect
from utils.weather_cities import CITIES as WEATHER_CITIES
from utils.path_utils import to_static_url_path
import secrets
from platform_utils import (
    IS_LINUX,
    get_cancel_flag_path,
    get_credentials_path,
    get_status_file,
    enqueue_slideshow_command,
)

APP_INSTANCE_ID = secrets.token_hex(8)

# ============================================================
# Configure logging with emojis.
# ============================================================
# Load configuration.
config = load_config()
# Create the log directory.
LOGS_DIR = Path(__file__).resolve().parent / "logs"
LOGS_DIR.mkdir(exist_ok=True)

class StripAnsiFormatter(logging.Formatter):
    """Formatter qui retire les codes ANSI (couleurs) des logs."""
    ANSI_ESCAPE = re.compile(r'\x1b\[[0-9;]*m')
    
    def format(self, record):
        formatted = super().format(record)
        return self.ANSI_ESCAPE.sub('', formatted)


class EmojiFormatter(StripAnsiFormatter):
    """Custom formatter that adds a level-specific emoji without ANSI codes."""
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


class CleanWerkzeugFormatter(EmojiFormatter):
    """Werkzeug formatter that cleans up HTTP logs."""
    
    def format(self, record):
        # If this is a Werkzeug log with the standard HTTP format.
        if record.name == 'werkzeug' and ' - - [' in record.getMessage():
            message = record.getMessage()
            match = re.search(r'"([^"]+)"\s+(\d+)\s+(.*)$', message)
            if match:
                record.msg = f'🌐 "{match.group(1)}" {match.group(2)}'
                record.args = ()
                emoji = self.EMOJI_MAP.get(record.levelname, "")
                record.emoji = emoji
                return StripAnsiFormatter.format(self, record)
        
        return super().format(record)

# >>> NEW: get the log level from config.
level_name = config.get("level_log", "INFO")
level = getattr(logging, level_name.upper(), logging.INFO)

# Create the root logger for the application.
root_logger = logging.getLogger()
root_logger.setLevel(level)

# Handler 1: Rotating file handler (10 MB max, 5 backups).
file_handler = RotatingFileHandler(
    LOGS_DIR / "pictureframe.log",
    maxBytes=10 * 1024 * 1024,
    backupCount=3,
    encoding="utf-8"
)
file_handler.setLevel(level)
file_formatter = CleanWerkzeugFormatter(
    '%(emoji)s🟨%(asctime)s [%(process)d:%(threadName)s] %(levelname)s %(message)s',
    datefmt='%d-%m %H:%M:%S'
)
file_handler.setFormatter(file_formatter)

# Handler 2: Console (stdout/stderr), for compatibility with start_pictureframe.sh [may be removed later].
console_handler = logging.StreamHandler()
console_handler.setLevel(level)
console_formatter = CleanWerkzeugFormatter(
    '%(asctime)s [%(process)d:%(threadName)s] %(levelname)s %(emoji)s %(message)s',
    datefmt='%d-%m %H:%M:%S'
)
console_handler.setFormatter(console_formatter)

# Add handlers to the root logger.
for _handler in _bootstrap_handlers:
    root_logger.removeHandler(_handler)
    _handler.close()
root_logger.addHandler(file_handler)
root_logger.addHandler(console_handler)

# Logger specific to app.py.
logger = logging.getLogger("pictureframe.app")
logger.info("Startup: dependencies and logging initialized in %.2fs; log file: %s",
            time.monotonic() - _startup_started, LOGS_DIR / "pictureframe.log")

# Werkzeug-specific configuration.
werkzeug_logger = logging.getLogger('werkzeug')
werkzeug_logger.setLevel(logging.INFO)


# ============================================================
# Create the Flask application.
# ============================================================

app = Flask(__name__)

@app.before_request
def log_request_start():
    g.request_started = time.monotonic()
    logger.info("HTTP started: %s %s", request.method, request.path)

@app.after_request
def log_request_finished(response):
    elapsed = time.monotonic() - g.request_started
    log = logger.warning if elapsed >= 2 else logger.info
    log("HTTP finished: %s %s status=%s duration=%.3fs",
        request.method, request.path, response.status_code, elapsed)
    # Prevent browser caching of pages and API responses
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

@app.teardown_request
def log_request_failure(error):
    if error is not None:
        logger.error("HTTP failed: %s %s", request.method, request.path,
                     exc_info=(type(error), error, error.__traceback__))

# --- Secret key ---
try:
    from utils.credentials_manager import load_credentials
    credentials = load_credentials()
    app.secret_key = credentials.get('flask_secret_key', 'supersecretkey_fallback_should_be_changed')
except Exception:
    app.secret_key = 'supersecretkey_fallback_should_be_changed'

# --- Limit upload size ---
# Set high enough to allow large photo batch imports (500 MB).
# Flask returns HTTP 413 when this is exceeded.
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024


def get_locale():
    # Check whether this is an HTTP request context.
    # If called from a background worker thread, return the default language.
    from flask import has_request_context
    if not has_request_context():
        return app.config.get('BABEL_DEFAULT_LOCALE', 'fr')

    # 1. If a 'lang' argument is passed in the URL.
    lang = request.args.get('lang')
    if lang and lang in app.config['LANGUAGES']:
        session['lang'] = lang
        return lang
    # 2. If the user has a language set in their session.
    if 'lang' in session and session['lang'] in app.config['LANGUAGES']:
        return session['lang']
    # 3. From the browser's 'Accept-Language' header.
    return request.accept_languages.best_match(list(app.config['LANGUAGES'].keys()))

# --- Babel configuration (i18n) ---
app.config['LANGUAGES'] = {'fr': 'Français', 'en': 'English', 'he': 'עברית'}
app.config['BABEL_DEFAULT_LOCALE'] = 'fr'
babel = Babel(app, locale_selector=get_locale)

# --- End of Babel configuration ---

@app.context_processor
def inject_locale():
    """Inject the get_locale function into the template context."""
    return dict(get_locale=get_locale)

@app.context_processor
def inject_instance_id():
    """Inject the instance ID for restart tracking."""
    return dict(APP_INSTANCE_ID=APP_INSTANCE_ID)


# Chemins de base
BASE_DIR = Path(__file__).resolve().parent
# Chemins de config
VIDEO_EXTENSIONS = ('.mp4', '.mov', '.avi', '.mkv')
PENDING_UPLOADS_DIR = BASE_DIR / "static" / "pending_uploads"
CONFIG_PATH = 'config/config.json'
CREDENTIALS_PATH = str(get_credentials_path())
FILTER_STATES_PATH = 'config/filter_states.json'
FAVORITES_PATH = 'config/favorites.json'
POLAROID_TEXTS_PATH = 'config/polaroid_texts.json'
TEXT_STATES_PATH = 'config/text_states.json'
CUSTOM_PLAYLIST_FILE = str(get_status_file("pictureframe_custom_playlist.json"))
CURRENT_PHOTO_FILE = str(get_status_file("pictureframe_current_photo.txt"))
SLIDESHOW_PID_FILE = get_status_file("pictureframe_slideshow.pid")
SLIDESHOW_STATUS_FILE = get_status_file("pictureframe_slideshow_status.json")
BACKGROUND_PID_FILE = get_status_file("pictureframe_background.pid")
BACKGROUND_STATUS_FILE = get_status_file("pictureframe_background_status.json")
CANCEL_FLAG_PATH = get_cancel_flag_path()
PREPARED_DIR = BASE_DIR / "static" / "prepared"

# Central dictionary for log files.
LOG_FILES_MAP = {
    "app": {"path": "logs/pictureframe.log", "name_key": "PictureFrame (Serveur Web & Supervisor)"},
}



# History for the CPU temperature chart (keep the last 60 readings).
cpu_temp_history = collections.deque(maxlen=60)
# NEW: History for the CPU usage chart.
cpu_usage_history = collections.deque(maxlen=60)
# NEW: History for the RAM usage chart.
ram_usage_history = collections.deque(maxlen=60)
# NEW: History for the disk usage chart.
disk_usage_history = collections.deque(maxlen=60)

def get_screen_resolution():
    """
    Détecte la résolution de l'écran principal via swaymsg.
    Retourne (width, height) ou (1920, 1080) en cas d'erreur.
    """
    # Load config to get a reliable fallback resolution.
    config = load_config()
    default_width = int(config.get('display_width', 1920))
    default_height = int(config.get('display_height', 1080))
    try:
        # Ensure SWAYSOCK is set.
        if "SWAYSOCK" not in os.environ:
            user_id = os.getuid()
            # Use glob to find the socket because its name can vary.
            sock_path_pattern = f"/run/user/{user_id}/sway-ipc.*"
            socks = glob.glob(sock_path_pattern)
            if socks:
                os.environ["SWAYSOCK"] = socks[0]
            else:
                logger.warning("SWAYSOCK not found; using the fallback resolution from config.")
                return default_width, default_height

        # Use HDMI_OUTPUT from slideshow_manager to target the correct output.
        # Or find the active output if HDMI_OUTPUT is not sufficient.
        # For now, use the active output.
        result = subprocess.run(['swaymsg', '-t', 'get_outputs'], capture_output=True, text=True, check=True, env=os.environ)
        outputs = json.loads(result.stdout)
        
        # --- MODIFICATION ---
        # Find the first output with a configured mode, whether active or not.
        # This is more reliable because the display may be off or asleep.
        for output in outputs:
            if output.get('current_mode'):
                mode = output['current_mode']
                logger.info(f"Resolution detected on output '{output.get('name')}': {mode['width']}x{mode['height']} (Active: {output.get('active', False)})")
                return mode['width'], mode['height']
        
        logger.info("😒 No output with a configured mode found (display asleep?); using the fallback resolution from config.")
        return default_width, default_height
    except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError, IndexError) as e:
        logger.info(f"😒 Error detecting the display resolution: {e}. Using the fallback resolution from config.")
        return default_width, default_height
    except Exception as e:
        logger.info(f"😒 Unexpected error detecting the resolution: {e}. Using the fallback resolution from config.")
        return default_width, default_height

def get_photo_previews():
    photo_dir = BASE_DIR / "static" / "photos"
    return sorted([f.name for f in photo_dir.glob("*") if f.suffix.lower() in [".jpg", ".jpeg", ".png", ".gif"]])

def load_credentials():
    try:
        with open(CREDENTIALS_PATH, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        # Fallback if file is missing or corrupt. setup.sh should create it.
        # Legacy fallback credentials for installations without a credentials file.
        return {"username": "admin", "password_hash": "pbkdf2:sha256:600000$YgWJtLgqgBqYvRzS$b2185c72e38933b3c655b7a748c928b1b88b1d62480579f4a1f9b1b1c8e8c8d2"}

def check_credentials(username, password):
    credentials = load_credentials()
    stored_username = credentials.get("username")
    stored_hash = credentials.get("password_hash")

    if not stored_username or not stored_hash:
        # Handle legacy plaintext password for backward compatibility
        stored_password = credentials.get("password")
        if stored_password and username == stored_username and password == stored_password:
            print("WARNING: The password is stored in plaintext. Change it to secure the account.")
            return True
        return False

    return username == stored_username and check_password_hash(stored_hash, password)

def load_filter_states():
    """Load filter states from a JSON file."""
    if not os.path.exists(FILTER_STATES_PATH):
        return {}
    try:
        with open(FILTER_STATES_PATH, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}

def save_filter_states(states):
    """Save filter states to a JSON file."""
    try:
        with open(FILTER_STATES_PATH, 'w') as f:
            json.dump(states, f, indent=4)
    except Exception as e:
        logger.info(f"Error saving filter states: {e}")

def load_favorites():
    """Load the favorites list from a JSON file."""
    if not os.path.exists(FAVORITES_PATH):
        return []
    try:
        with open(FAVORITES_PATH, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []

def save_favorites(favorites_list):
    """Save the favorites list to a JSON file."""
    try:
        with open(FAVORITES_PATH, 'w') as f:
            json.dump(favorites_list, f, indent=2)
    except Exception as e:
        logger.info(f"😒 Error saving favorites: {e}")

def load_polaroid_texts():
    """Load Polaroid text from a JSON file."""
    if not os.path.exists(POLAROID_TEXTS_PATH):
        return {}
    try:
        with open(POLAROID_TEXTS_PATH, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}

def save_polaroid_texts(texts_dict):
    """Save Polaroid text to a JSON file."""
    try:
        with open(POLAROID_TEXTS_PATH, 'w') as f:
            json.dump(texts_dict, f, indent=2)
    except Exception as e:
        logger.info(f"😒 Error saving Polaroid text: {e}")

def load_text_states():
    """Load photo text from a JSON file."""
    if not os.path.exists(TEXT_STATES_PATH):
        return {}
    try:
        with open(TEXT_STATES_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}

def save_text_states(states):
    """Save photo text to a JSON file."""
    try:
        with open(TEXT_STATES_PATH, 'w', encoding='utf-8') as f:
            json.dump(states, f, indent=4)
    except IOError as e:
        logger.info(f"😒 Error saving text states: {e}")

def get_photo_source_labels(sources):
    from utils.migrate_frame_names import is_legacy_photo_source
    return {source: (_("Imported photos") if is_legacy_photo_source(source) else source.capitalize())
            for source in sorted(sources)}


def get_prepared_photos_by_source():
    """
    Récupère les médias préparés (photos et vidéos), organisés par leur source.
    Retourne un dictionnaire où les clés sont les noms des sources et les valeurs sont des listes de dictionnaires.
    Ex: {'usb': [{'path': 'usb/media.jpg', 'type': 'image', 'has_polaroid': True}, ...]}
    """
    # Load the configuration to get guest names.
    config = load_config()

    base_prepared_dir = PREPARED_DIR
    media_by_source = {}
    filter_states = load_filter_states()
    favorites = load_favorites()
    polaroid_texts = load_polaroid_texts()
    text_states = load_text_states()
    
    # Load config for anniversary boost.
    app_config = load_config()
    anniversary_boost_enabled = app_config.get("anniversary_boost_enabled", False)
    if base_prepared_dir.exists():
        for source_dir in base_prepared_dir.iterdir():
            if source_dir.is_dir():
                source_name = source_dir.name
                
                # List all files (images and videos).
                all_files_in_dir = list(source_dir.iterdir())
                all_filenames = {f.name for f in all_files_in_dir}
                
                # Identify base media (not Polaroid, thumbnail, or postcard variants).
                base_media = sorted(
                    [f for f in all_files_in_dir if f.is_file() and not f.name.endswith(('_polaroid.jpg', '_thumbnail.jpg', '_postcard.jpg'))]
                )

                media_data_list = []
                for media_path_obj in base_media:
                    media_name = media_path_obj.name
                    media_relative_path = f"{source_name}/{media_name}"
                    media_type = 'video' if media_path_obj.suffix.lower() in VIDEO_EXTENSIONS else 'image'
                    
                    media_item = {
                        "path": media_relative_path,
                        "type": media_type,
                        "is_favorite": media_relative_path in favorites,
                        "is_anniversary": False # Default to False
                    }
                    photo_metadata = get_photo_metadata(media_path_obj) if media_type == 'image' else {}
                    media_item["metadata_text"] = format_photo_metadata(photo_metadata, config, _) or _("No Metadata")
                    media_item["location_text"] = format_preview_location(photo_metadata, _)

                    # Check whether this is an anniversary photo.
                    if anniversary_boost_enabled and media_type == 'image':
                        if photo_metadata:
                            date_priority = [
                                "subSecDateTimeOriginal", "dateTimeOriginal", "SubSecDateTimeOriginal", "DateTimeOriginal",
                                "subSecCreateDate", "createDate", "SubSecCreateDate", "CreateDate",
                                "subSecModifyDate", "modifyDate", "SubSecModifyDate",
                                "mediaCreateDate", "dateTimeCreated", "MediaCreateDate", "DateTimeCreated",
                                "fileModifiedAt", "fileCreatedAt"
                            ]
                            date_taken_str = next((photo_metadata.get(field) for field in date_priority if photo_metadata.get(field)), None)
                            
                            if date_taken_str:
                                try:
                                    photo_date = datetime.fromisoformat(date_taken_str.replace('Z', '+00:00'))
                                    if photo_date.month == datetime.now().month and photo_date.day == datetime.now().day:
                                        media_item["is_anniversary"] = True
                                except Exception as e:
                                    logger.debug(f"Error reading the date for the anniversary icon: {e}")

                    # Filter options apply only to images.
                    if media_type == 'image':
                        base_name = media_path_obj.stem
                        has_polaroid = f"{base_name}_polaroid.jpg" in all_filenames
                        has_postcard = f"{base_name}_postcard.jpg" in all_filenames
                        media_item["has_polaroid"] = has_polaroid
                        media_item["has_postcard"] = has_postcard
                        media_item["polaroid_text"] = polaroid_texts.get(media_relative_path, "")
                        media_item["text"] = text_states.get(media_relative_path, "")
                        media_item["active_filter"] = filter_states.get(media_relative_path, "none")
                    elif media_type == 'video':
                        # Find the corresponding video thumbnail.
                        thumbnail_name = f"{media_path_obj.stem}_thumbnail.jpg"
                        if thumbnail_name in all_filenames:
                            media_item["thumbnail_path"] = f"{source_name}/{thumbnail_name}"
                    
                    media_data_list.append(media_item)
                
                if media_data_list:
                    media_by_source[source_name] = media_data_list
                    
    return media_by_source

# --- Routes principales ---

@app.route('/upload', methods=['GET'])
def upload_page():
    """Display the public page for uploading photos."""
    return render_template('upload.html.jinja')

@app.route('/handle_upload', methods=['POST'])
def handle_upload():
    """Handle file uploads from the public page."""
    if 'photos' not in request.files:
        flash(_("No files selected."), "error")
        return redirect(url_for('upload_page'))

    files = request.files.getlist('photos')
    if not files or files[0].filename == '':
        flash(_("No files selected."), "error")
        return redirect(url_for('upload_page'))

    PENDING_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    
    count = 0
    for file in files:
        if file:
            # Sanitize the filename.
            filename = secure_filename(file.filename)
            # Handle filename collisions by adding a timestamp and random string.
            base, ext = os.path.splitext(filename)
            unique_suffix = f"{int(time.time())}_{secrets.token_hex(2)}"
            final_path = PENDING_UPLOADS_DIR / f"{base}_{unique_suffix}{ext}"
            file.save(final_path)
            logger.info(f"[Upload] New file received from guest and awaiting approval: {final_path.name}")
            count += 1

    flash(_('%(count)s photo(s) sent for validation successfully!', count=count), "success")
    return redirect(url_for('upload_page'))

@app.route('/api/get_pending_photos')
@login_required
def get_pending_photos():
    """Return the list of photos awaiting approval."""
    try:
        # Ensure the directory exists to avoid errors.
        if not PENDING_UPLOADS_DIR.exists():
            PENDING_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

        logger.debug(f"Listing pending photos in: {PENDING_UPLOADS_DIR}")

        # List files in the pending uploads directory.
        files_with_mtime = []
        for f in PENDING_UPLOADS_DIR.iterdir():
            if f.is_file() and not f.name.startswith('.'): # Ignore hidden files.
                try:
                    files_with_mtime.append((f.name, f.stat().st_mtime))
                except OSError as e:
                    logger.debug(f"Error reading file {f.name}: {e}")

        # Sort by modification date (newest first).
        files_with_mtime.sort(key=lambda x: x[1], reverse=True)
        pending_files = [f[0] for f in files_with_mtime]
        
        logger.debug(f"Found {len(pending_files)} pending photos.")

        # Return a structured response and add no-cache headers.
        response = jsonify({"success": True, "photos": pending_files})
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response
    except Exception as e:
        logger.info(f"[ERROR] get_pending_photos failed: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/manage_pending_photo', methods=['POST'])
@login_required
def manage_pending_photo():
    """Approve or reject a pending photo."""
    data = request.get_json()
    filename = data.get('filename')
    action = data.get('action')

    if not filename or not action in ['approve', 'reject']:
        return jsonify({"success": False, "message": "Invalid data."}), 400

    pending_path = PENDING_UPLOADS_DIR / secure_filename(filename)

    if not pending_path.is_file():
        return jsonify({"success": False, "message": "File not found."}), 404

    if action == 'reject':
        try:
            pending_path.unlink()
            return jsonify({"success": True, "message": _("Previous photo")})
        except Exception as e:
            return jsonify({"success": False, "message": f"Erreur: {e}"}), 500

    if action == 'approve':
        # Processus d'approbation rendu plus robuste :
        # 1. Copy the photo to the staging directory instead of moving it.
        # 2. Start preparation.
        # 3. If preparation succeeds, remove the photo from the pending directory.
        # Use a dedicated 'guests' directory to avoid mixing or deleting other photos.
        target_source = "guests"
        source_dir = BASE_DIR / "static" / "photos" / target_source
        source_dir.mkdir(parents=True, exist_ok=True)

        # Copy the photo for processing.
        shutil.copy(str(pending_path), str(source_dir / pending_path.name))

        # Start preparation.
        config = load_config()
        screen_width, screen_height = config.get("display_width", 1920), config.get("display_height", 1080)
        try:
            preparation_successful = False
            # Use the correct imported function and the 'guests' source.
            for update in prepare_all_photos_with_progress(screen_width, screen_height, source_type=target_source):
                # Check that preparation completed successfully by reading the event stream.
                if update.get("type") == "done":
                    preparation_successful = True
            
            if preparation_successful:
                pending_path.unlink() # Delete the original only if everything succeeded.

                # --- NEW: Automatically enable the 'invites' source if it is not already enabled ---
                # This ensures the approved photo will be shown in the slideshow.
                current_sources = config.get('display_sources', [])
                if 'guests' not in current_sources:
                    current_sources.append('guests')
                    config['display_sources'] = current_sources
                    save_config(config)

                # Restart the slideshow to include the new photo immediately.
                if is_display_process_running():
                    restart_display_process_for_update()

                return jsonify({"success": True, "message": _("Photo approved and prepared. The slideshow has been updated.")})
            else:
                return jsonify({"success": False, "message": _("Photo preparation failed. The photo remains pending.")}), 500
        except Exception as e:
            return jsonify({"success": False, "message": f"Error during preparation: {e}"}), 500

    return jsonify({"success": False, "message": _("Activation in progress...")}), 400

@app.route('/debug/pending')
@login_required
def debug_pending():
    """Diagnostic route for viewing raw files."""
    if not PENDING_UPLOADS_DIR.exists():
        return f"Le dossier {PENDING_UPLOADS_DIR} n'existe pas."
    files = [f.name for f in PENDING_UPLOADS_DIR.iterdir()]
    return f"Fichiers dans le dossier d'attente : {files}"

@app.route('/')
def home():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if username and password and check_credentials(username, password):
            session['logged_in'] = True
            flash(_("Successful connection"), "success")
            return redirect(url_for('configure'))
        else:
            flash(_("Invalid identifiers"), "error")
    return render_template('login.html.jinja')

@app.route('/logout', methods=['GET', 'POST'])
def logout():
    session.pop('logged_in', None)
    flash(_("Successful disconnection"), "success")
    return redirect(url_for('login'))


# --- Configuration & slideshow management ---

# Fallback timezone list used when zoneinfo.available_timezones() returns
# empty (Windows without the tzdata package).  Covers major regions so the
# selector is usable; the full list is available once tzdata is installed.
_FALLBACK_TIMEZONES = [
    "Africa/Cairo", "Africa/Casablanca", "Africa/Johannesburg", "Africa/Nairobi",
    "America/Anchorage", "America/Argentina/Buenos_Aires", "America/Chicago",
    "America/Denver", "America/Halifax", "America/Los_Angeles", "America/Mexico_City",
    "America/New_York", "America/Phoenix", "America/Sao_Paulo", "America/Toronto",
    "America/Vancouver",
    "Asia/Bangkok", "Asia/Beirut", "Asia/Calcutta", "Asia/Colombo", "Asia/Damascus",
    "Asia/Dhaka", "Asia/Dubai", "Asia/Hong_Kong", "Asia/Jakarta", "Asia/Jerusalem",
    "Asia/Kabul", "Asia/Karachi", "Asia/Kathmandu", "Asia/Kolkata", "Asia/Kuala_Lumpur",
    "Asia/Manila", "Asia/Pyongyang", "Asia/Seoul", "Asia/Shanghai", "Asia/Singapore",
    "Asia/Taipei", "Asia/Tehran", "Asia/Tokyo",
    "Atlantic/Reykjavik",
    "Australia/Adelaide", "Australia/Brisbane", "Australia/Darwin",
    "Australia/Hobart", "Australia/Perth", "Australia/Sydney",
    "Europe/Amsterdam", "Europe/Athens", "Europe/Berlin", "Europe/Brussels",
    "Europe/Budapest", "Europe/Copenhagen", "Europe/Dublin", "Europe/Helsinki",
    "Europe/Istanbul", "Europe/Lisbon", "Europe/London", "Europe/Luxembourg",
    "Europe/Madrid", "Europe/Moscow", "Europe/Oslo", "Europe/Paris", "Europe/Prague",
    "Europe/Rome", "Europe/Stockholm", "Europe/Vienna", "Europe/Warsaw", "Europe/Zurich",
    "Pacific/Auckland", "Pacific/Honolulu",
    "UTC",
]


def get_available_timezones(current_timezone=None):
    """Return every IANA time zone name, sorted, for the selector.

    ``current_timezone`` (from the saved config) is kept in the list even
    when it is missing from the system's tz database, so the selector
    always shows a valid entry for the configured value.

    On Windows without the ``tzdata`` package, ``zoneinfo.available_timezones()``
    returns an empty set.  A built-in fallback list of common time zones
    ensures the dropdown is never empty in that case.
    """
    try:
        from zoneinfo import available_timezones
        timezones = set(available_timezones())
    except Exception as exc:  # pragma: no cover - depends on tzdata
        logger.warning(f"Could not list system time zones: {exc}")
        timezones = set()

    if not timezones:
        # Fallback: tzdata not installed (common on Windows).  Provide a
        # curated list of common IANA zones so the selector is usable.
        logger.info("System timezone list empty; using built-in fallback.")
        timezones = set(_FALLBACK_TIMEZONES)

    if current_timezone:
        timezones.add(current_timezone)
    return sorted(timezones)


@app.route('/configure', methods=['GET', 'POST'])
@login_required
def configure():
    # --- DEBUG: Check for pending files when the page loads ---
    try:
        if PENDING_UPLOADS_DIR.exists():
            pending_files = [f.name for f in PENDING_UPLOADS_DIR.iterdir() if f.is_file() and not f.name.startswith('.')]
            logger.info(f"🔳 {len(pending_files)} guest photo(s) awaiting approval in {PENDING_UPLOADS_DIR}: {pending_files}")
        else:
            logger.warning(f"🔳️ Le dossier {PENDING_UPLOADS_DIR} n'existe pas encore.")
    except Exception as e:
        logger.error(f"🔳️ Error listing pending files: {e}")

    config = load_config()

    # Get the list of pending photos for the template.
    pending_photos_list = []
    if PENDING_UPLOADS_DIR.exists():
        pending_photos_list = sorted(
            [f.name for f in PENDING_UPLOADS_DIR.iterdir() if f.is_file() and not f.name.startswith('.')],
            key=lambda p: os.path.getmtime(PENDING_UPLOADS_DIR / p),
            reverse=True
        )

    if request.method == 'POST':
        for key in [
            'display_duration', 
            'active_start_weekday', 'active_end_weekday',
            'active_start_weekend', 'active_end_weekend',
            'screen_height_percent', 'clock_font_size', 'clock_color',
            'clock_format', 'clock_offset_x', 'clock_offset_y',
            'clock_background_color',
            'clock_outline_color', 'clock_font_path', 'clock_position',
            'display_width', 'display_height', # Add the new keys.
            'transition_enabled', # Added transition_enabled
            'transition_type', 'home_assistant_token',
            'transition_duration', # Added transition_duration
            'transition_fps', # Added transition_fps
            'pan_zoom_factor', 'pan_zoom_start_factor', 'favorite_boost_factor',
            'date_format',
            'weather_city', 'weather_units', 'weather_update_interval_minutes', 'anniversary_boost_factor',
            'smart_plug_on_url', 'smart_plug_off_url', 'smart_plug_on_delay', 'smart_plug_status_url',
            'video_audio_output', 'video_audio_volume',
            'screen_orientation'
            # New fields
            , 'wifi_ssid', 'wifi_password', 'info_display_duration',
            'tide_latitude', 'tide_longitude', 'stormglass_api_key', 'tide_offset_x', 'tide_offset_y'
            , 'button_pin',
            'timezone'
            # Background updater settings (app_mode itself is switched
            # through the dedicated /api/app_mode route).
            , 'background_update_interval', 'background_output_format',
            'background_resolution_mode', 'background_display_style'
        ]:
            if key in request.form:
                value = request.form.get(key)
                # Handle numeric fields.
                if key in ['display_duration', 'clock_offset_x', 'clock_offset_y', 'clock_font_size', 'weather_update_interval_minutes', 'display_width', 'display_height', 'info_display_duration', 'tide_offset_x', 'tide_offset_y', 'video_audio_volume', 'favorite_boost_factor',
                           'button_pin', 'smart_plug_on_delay', 'anniversary_boost_factor',
                           'background_update_interval']: # Integer fields
                    try:
                        config[key] = int(value)
                    except (ValueError, TypeError):
                        config[key] = 0 # Set a default value if an error occurs.
                elif key in ['pan_zoom_factor', 'pan_zoom_start_factor']: # Float fields
                    try:
                        config[key] = float(value)
                    except (ValueError, TypeError): # type: ignore
                        config[key] = 1.0 # Default to no zoom
                elif key in ['transition_duration']: # Float fields
                    try:
                        config[key] = float(value)
                    except (ValueError, TypeError):
                        config[key] = 0.0 # Default to no transition
                else: # Handle text fields.
                    config[key] = value
        
        # Apply the time zone to the system if it changed.
        if 'timezone' in request.form:
            new_tz = request.form.get('timezone')
            if new_tz and new_tz != config.get('timezone', 'Europe/Paris'):
                try:
                    from platform_utils import set_timezone
                    if not set_timezone(new_tz):
                        raise RuntimeError("The system timezone could not be changed.")
                    logger.info(f"📅 System time zone updated: {new_tz}")
                except Exception as e:
                    logger.error(f"❌ Error setting the time zone: {e}")

        # Process metadata keys (style and positioning).
        # Text/select fields.
        for key in ['photo_date_format', 'country_flag_size', 'photo_location_format', 'photo_metadata_color', 'photo_metadata_outline_color', 'photo_metadata_font_path', 'photo_metadata_position', 'photo_metadata_background_color', 'country_flag_position']:
            if key in request.form:
                config[key] = request.form.get(key)
        
        # Integer metadata fields.
        for key in ['photo_metadata_font_size', 'photo_metadata_offset_x', 'photo_metadata_offset_y', 'country_flag_offset_x', 'country_flag_offset_y']:
            if key in request.form:
                try:
                    config[key] = int(request.form.get(key))
                except (ValueError, TypeError):
                    config[key] = 0

        # Float metadata fields.
        if 'country_flag_opacity' in request.form:
            try:
                config['country_flag_opacity'] = float(request.form.get('country_flag_opacity'))
            except (ValueError, TypeError):
                config['country_flag_opacity'] = 1.0
        
        # Prefer the resolution submitted in the form; otherwise detect it automatically.
        form_width = request.form.get('display_width')
        form_height = request.form.get('display_height')
        if form_width and form_height:
            try:
                config['display_width'] = int(form_width)
                config['display_height'] = int(form_height)
            except (ValueError, TypeError):
                detected_width, detected_height = get_screen_resolution()
                config['display_width'] = detected_width
                config['display_height'] = detected_height
        else:
            detected_width, detected_height = get_screen_resolution()
            config['display_width'] = detected_width
            config['display_height'] = detected_height

        # --- Orientation management ---
        # If the user forces an orientation, ensure width/height match.
        target_orientation = config.get('screen_orientation', 'landscape')
        if target_orientation == 'portrait':
            # Si on est en portrait mais que la largeur est plus grande que la hauteur, on inverse
            if config['display_width'] > config['display_height']:
                config['display_width'], config['display_height'] = config['display_height'], config['display_width']
                logger.info(f"Forced portrait orientation: dimensions swapped to {config['display_width']}x{config['display_height']}")
        else: # landscape
            # Si on est en paysage mais que la hauteur est plus grande que la largeur, on inverse
            if config['display_height'] > config['display_width']:
                config['display_width'], config['display_height'] = config['display_height'], config['display_width']
                logger.info(f"Forced landscape orientation: dimensions swapped to {config['display_width']}x{config['display_height']}")

        logger.info(f"Configured display resolution: {config['display_width']}x{config['display_height']}. Saving to config.")
        # Handle the display_sources key (checkboxes).
        # request.form.getlist() returns an empty list if no checkbox with this name is selected.
        config['display_sources'] = request.form.getlist('display_sources')
        config["pan_zoom_enabled"] = 'pan_zoom_enabled' in request.form # New checkbox handling
        config["button_enabled"] = 'button_enabled' in request.form
        config["smart_plug_enabled"] = 'smart_plug_enabled' in request.form
        config["transition_enabled"] = 'transition_enabled' in request.form # New checkbox handling
        config["clock_background_enabled"] = 'clock_background_enabled' in request.form
        config["slideshow_video_enabled"] = 'slideshow_video_enabled' in request.form
        config["video_audio_enabled"] = 'video_audio_enabled' in request.form
        config["video_hwdec_enabled"] = 'video_hwdec_enabled' in request.form

        config["anniversary_boost_enabled"] = 'anniversary_boost_enabled' in request.form
        # Process checkboxes.
        config["show_clock"] = 'show_clock' in request.form

        config["show_date"] = 'show_date' in request.form
        config["show_weather"] = 'show_weather' in request.form
        config["show_tides"] = 'show_tides' in request.form
        # Metadata checkboxes
        config["show_photo_date"] = 'show_photo_date' in request.form
        config["show_photo_location"] = 'show_photo_location' in request.form
        config["show_country_flag"] = 'show_country_flag' in request.form
        config["photo_metadata_background_enabled"] = 'photo_metadata_background_enabled' in request.form
        save_config(config)
        restart_display_process() # Restart only the slideshow process.
        flash(_("Configuration saved. The slideshow was restarted to apply the changes."), "success")
        return redirect(url_for('configure'))

    slideshow_running = any(
        'local_slideshow.py' in (p.info['cmdline'] or []) for p in psutil.process_iter(attrs=['cmdline'])
    )

    # Test the Wi-Fi connection when the page loads.
    wifi_status = "Inconnu"
    try:
        # This is a very basic check; it could be improved by checking wlan0
        # or pinging an external address. For now, only check that the fields are filled in.
        if config.get("wifi_ssid"):
            wifi_status = "Configured (status not verified)"
        else:
            wifi_status = "Not configured"
    except Exception as e:
        wifi_status = f"Error checking status: {e}"

    prepared_media_by_source = get_prepared_photos_by_source()
    source_labels = get_photo_source_labels(
        set(prepared_media_by_source) | set(config.get("display_sources", [])))

    # --- NEW: Create a flat favorites list for the new tab ---
    favorite_photos = []
    for source, media_list in prepared_media_by_source.items():
        for media in media_list:
            if media.get('is_favorite'):
                favorite_photos.append(media)

    return render_template(
        'configure.html.jinja',
        config=config,
        prepared_photos_by_source=prepared_media_by_source, # Le template utilise ce nom de variable
        source_labels=source_labels,
        favorite_photos=favorite_photos, # Nouvelle variable pour l'onglet des favoris
        slideshow_running=slideshow_running,
        pending_photos=pending_photos_list,
        weather_cities=WEATHER_CITIES,
        available_timezones=get_available_timezones(config.get('timezone'))
    )

@app.route("/import-usb")
@login_required
def import_usb():
    # Clear the cancellation flag before starting.
    cancel_flag = CANCEL_FLAG_PATH
    if cancel_flag.exists(): cancel_flag.unlink()

    @stream_with_context
    def generate():
        def stream_event(data):
            """Format data as a Server-Sent Event (SSE)."""
            return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
        try:
            for update in import_usb_photos():
                yield stream_event(update)
        except Exception as e:
            yield stream_event({"type": "error", "message": f"Erreur critique : {str(e)}"})

    return Response(generate(), mimetype='text/event-stream', headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})

@app.route("/import-smartphone", methods=['POST'])
@login_required
def import_smartphone():
    uploaded_files = request.files.getlist('photos')
    # Clear the cancellation flag before starting.
    cancel_flag = CANCEL_FLAG_PATH
    if cancel_flag.exists(): cancel_flag.unlink()

    """
    Gère l'upload de photos depuis un smartphone via un formulaire web.
    """
    @stream_with_context
    def generate():
        def stream_event(data):
            return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

        config = load_config()
        screen_width, screen_height = config.get("display_width", 1920), config.get("display_height", 1080)
        source_dir = BASE_DIR / "static" / "photos" / "smartphone"

        try:
            # --- Step 1: Receive and save files ---
            yield stream_event({"type": "progress", "stage": "UPLOADING", "percent": 5, "message": "Receiving files..."})

            source_dir.mkdir(parents=True, exist_ok=True)

            if not uploaded_files or not uploaded_files[0].filename:
                yield stream_event({"type": "error", "message": "No files selected."})
                return

            existing_digests = {
                photo_digest(path) for path in source_dir.iterdir()
                if path.is_file() and path.suffix.lower() in PHOTO_EXTENSIONS
            }
            used_stems = {path.stem.casefold() for path in source_dir.iterdir()}
            imported = skipped = 0
            for file in uploaded_files:
                filename = secure_filename((file.filename or "").replace("\\", "/").rsplit("/", 1)[-1])
                if Path(filename).suffix.lower() not in PHOTO_EXTENSIONS:
                    yield stream_event({"type": "error", "message": _("Unsupported photo file: %(name)s", name=filename)})
                    return
                digest = stream_digest(file.stream)
                file.stream.seek(0)
                if digest in existing_digests:
                    skipped += 1
                    continue
                target = source_dir / filename
                suffix = 1
                while target.stem.casefold() in used_stems:
                    target = source_dir / f"{Path(filename).stem}_{suffix}{Path(filename).suffix}"
                    suffix += 1
                with target.open("xb") as output:
                    shutil.copyfileobj(file.stream, output)
                used_stems.add(target.stem.casefold())
                existing_digests.add(digest)
                imported += 1

            yield stream_event({"type": "progress", "stage": "PREPARING", "percent": 80,
                                "message": _("%(imported)s photos imported; %(skipped)s duplicates skipped.",
                                             imported=imported, skipped=skipped)})

            # --- Step 2: Prepare photos ---
            completed = False
            failed = False
            for update in prepare_all_photos_with_progress(screen_width, screen_height, source_type="smartphone"):
                if update["type"] in {"warning", "error"}:
                    failed = True
                if update["type"] == "done":
                    completed = True
                    continue
                # Add the preview URL.
                if update.get("current_photo_path"):
                    update["current_photo_url"] = url_for('static', filename=to_static_url_path(f"prepared/smartphone/{update['current_photo_path']}"))
                yield stream_event(update)
            prepared_dir = BASE_DIR / "static" / "prepared" / "smartphone"
            for photo in source_dir.iterdir():
                if photo.is_file() and photo.suffix.lower() in PHOTO_EXTENSIONS:
                    output = prepared_dir / f"{photo.stem}.jpg"
                    if not output.is_file() or output.stat().st_size == 0:
                        failed = True
            if failed or not completed:
                yield stream_event({"type": "error", "message": _("Photo preparation failed or was cancelled.")})
                return
            config = load_config()
            sources = config.setdefault("display_sources", [])
            if "smartphone" not in sources:
                sources.append("smartphone")
            save_config(config)
            if is_display_process_running():
                restart_display_process_for_update()
            yield stream_event({"type": "done", "percent": 100,
                                "message": _("%(imported)s photos imported; %(skipped)s duplicates skipped.",
                                             imported=imported, skipped=skipped),
                                "imported": imported, "skipped": skipped})

        except Exception as e:
            logger.exception("[Import Smartphone] Import failed")
            yield stream_event({"type": "error", "message": f"Erreur critique lors de l'import : {str(e)}"})

    return Response(generate(), mimetype='text/event-stream', headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})


@app.route('/prepare-photos')
@login_required
def prepare_photos():
    # Clear the cancellation flag before starting.
    cancel_flag = CANCEL_FLAG_PATH
    if cancel_flag.exists(): cancel_flag.unlink()

    """
    Route pour lancer la préparation des photos pour une source donnée.
    Utilise Server-Sent Events (SSE) pour streamer le progrès.
    """
    source = request.args.get('source')
    if not source:
        def error_stream():
            error_update = {"type": "error", "message": "The 'source' parameter is missing."}
            yield f"data: {json.dumps(error_update)}\n\n"
        return Response(stream_with_context(error_stream()), mimetype='text/event-stream')

    def generate_preparation_stream():
        """Generate progress events with keep-alive pings."""
        import queue
        import threading
        
        q = queue.Queue()
        
        def run_preparation():
            try:
                config = load_config()
                screen_width = config.get('display_width')
                screen_height = config.get('display_height')

                from utils.metadata_utils import load_photo_metadata_cache
                from utils.migrate_frame_names import is_legacy_photo_source
                base_description_map = load_photo_metadata_cache() if is_legacy_photo_source(source) else {}

                # 2. Load PictureFrame's manual captions.
                manual_captions = load_text_states()

                # 3. Merge, giving priority to manual captions.
                final_caption_map = base_description_map.copy()
                for path, caption in manual_captions.items():
                    filename = Path(path).name
                    final_caption_map[filename] = caption

                # Start preparation and send updates to the queue.
                for update in prepare_all_photos_with_progress(screen_width, screen_height, source_type=source, description_map=final_caption_map):
                    q.put(update)
                q.put(None) # Marqueur de fin
            except Exception as e:
                q.put({"type": "error", "message": f"Server error during preparation: {str(e)}"})
                q.put(None)

        # Start processing in a background thread.
        t = threading.Thread(target=run_preparation)
        t.daemon = True
        t.start()

        # Read the queue and stream to the client with keep-alive.
        while True:
            try:
                # Use a 10-second timeout to force a keep-alive.
                update = q.get(timeout=10)
                if update is None:
                    break
                
                # Add the prepared image URL in the main thread (which has the active Flask request context).
                if update.get("current_photo_path"):
                    update["current_photo_url"] = url_for('static', filename=to_static_url_path(f"prepared/{source}/{update['current_photo_path']}"))
                
                yield f"data: {json.dumps(update, ensure_ascii=False)}\n\n"
                
                if update.get("type") == "error":
                    break
            except queue.Empty:
                # Nginx/proxies and browsers close SSE connections when idle.
                # Send a keep-alive ping (ignored by the browser's EventSource API).
                yield ": keep-alive\n\n"

    return Response(stream_with_context(generate_preparation_stream()), mimetype='text/event-stream', headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})

@app.route('/test-stormglass-api', methods=['POST'])
@login_required
def test_stormglass_api():
    """Test the connection to the StormGlass API."""
    data = request.get_json()
    api_key = data.get("api_key")
    lat = data.get("lat")
    lon = data.get("lon")

    if not all([api_key, lat, lon]):
        return jsonify({"success": False, "message": "The API key, latitude, and longitude are required."})

    try:
        # Test with a very short time window to minimize data usage.
        start_time_utc = datetime.utcnow()
        end_time_utc = start_time_utc + timedelta(hours=1)

        headers = {'Authorization': api_key}
        params = { 'lat': lat, 'lng': lon, 'start': start_time_utc.isoformat(), 'end': end_time_utc.isoformat() }
        
        response = requests.get('https://api.stormglass.io/v2/tide/extremes/point', params=params, headers=headers, timeout=10)

        if response.status_code == 200:
            return jsonify({"success": True, "message": "Connected to StormGlass successfully!"})
        elif response.status_code == 401:
            return jsonify({"success": False, "message": "Invalid API key."})
        elif response.status_code == 402:
            return jsonify({"success": False, "message": "API credits exhausted or plan is insufficient."})
        elif response.status_code == 429:
            return jsonify({"success": False, "message": "Too many requests. Please try again later."})
        else:
            try:
                error_details = response.json().get('errors', {})
                message = f"Erreur de l'API ({response.status_code}): {error_details}"
            except json.JSONDecodeError:
                message = f"Erreur de l'API ({response.status_code})"
            return jsonify({"success": False, "message": message})
    except requests.exceptions.RequestException as e:
        return jsonify({"success": False, "message": f"Erreur de connexion : {e}"})

@app.route('/api/test_smart_plug', methods=['POST'])
@login_required
def test_smart_plug():
    """Test a smart plug URL."""
    data = request.get_json()
    url = data.get("url")

    if not url:
        return jsonify({"success": False, "message": "L'URL est requise."})

    try:
        # Use a short timeout to avoid blocking the interface.
        response = requests.post(url, timeout=5)
        if 200 <= response.status_code < 300:
            return jsonify({"success": True, "message": f"Success! The smart plug responded with code {response.status_code}."})
        else:
            return jsonify({"success": False, "message": f"Failed. The smart plug returned error code {response.status_code}."})
    except requests.exceptions.Timeout:
        return jsonify({"success": False, "message": "Failed. The request timed out. Check the smart plug's IP address."})
    except requests.exceptions.RequestException as e:
        return jsonify({"success": False, "message": f"Failed. Connection error: {e}"})

@app.route('/api/force_tide_update', methods=['POST'])
@login_required
def force_tide_update():
    """Force a tide data update by calling the API and writing to the cache."""
    config = load_config()
    api_key = config.get("stormglass_api_key")
    lat = config.get("tide_latitude")
    lon = config.get("tide_longitude")
    tide_cache_path = Path('cache/tides.json')

    if not all([api_key, lat, lon]):
        return jsonify({"success": False, "message": "StormGlass configuration is incomplete."})

    try:
        start_time_utc = datetime.utcnow()
        # --- CHANGE: Fetch 7 days of data to match the slideshow ---
        end_time_utc = start_time_utc + timedelta(days=7)

        headers = {'Authorization': api_key}
        params = {'lat': lat, 'lng': lon, 'start': start_time_utc.isoformat(), 'end': end_time_utc.isoformat()}
        
        response = requests.get('https://api.stormglass.io/v2/tide/extremes/point', params=params, headers=headers, timeout=15)
        response.raise_for_status()
        
        extremes_data = response.json().get('data', [])
        now_utc = datetime.utcnow().replace(tzinfo=None)
        future_extremes = [e for e in extremes_data if datetime.fromisoformat(e['time'].replace('Z', '+00:00')).replace(tzinfo=None) > now_utc]

        if not future_extremes:
            return jsonify({"success": False, "message": "No future tides found by the API."})

        # --- FIX: Save all upcoming tides, not just the next two ---
        data_to_cache = {'data': future_extremes, 'timestamp': datetime.now().isoformat()}
        
        tide_cache_path.parent.mkdir(exist_ok=True)
        with open(tide_cache_path, 'w') as f:
            json.dump(data_to_cache, f, indent=2)

        return jsonify({"success": True, "message": "Tide data updated successfully!"})

    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 402:
            # --- IMPROVEMENT: Write a cooldown state to the cache ---
            cooldown_data = {'data': [], 'timestamp': datetime.now().isoformat(), 'cooldown': True}
            try:
                with open(tide_cache_path, 'w') as f: json.dump(cooldown_data, f, indent=2)
            except Exception: pass
            return jsonify({"success": False, "message": "StormGlass API quota exceeded."})
        return jsonify({"success": False, "message": f"Erreur API ({e.response.status_code})."})
    except Exception as e:
        return jsonify({"success": False, "message": f"Erreur inattendue : {e}"})




# --- Slideshow scheduling ---


def schedule_worker():
    """
    Background thread that starts and stops the slideshow
    based on the configured active hours.
    """
    logger.debug("📅️🔄 Starting the slideshow scheduling worker")
    
    # --- One-time startup sequence ---
    # This section runs only once when the application starts.
    try:
        logger.info("📅 Initial startup sequence.")
        # Wait for the system to stabilize before changing the display.
        time.sleep(5)
        config = load_config()
        output_name = get_display_output_name()
        if output_name:
            width = config.get('display_width', 1920)
            height = config.get('display_height', 1080)
            logger.info(f"📅 Forcing resolution {width}x{height} on display '{output_name}' at startup.")
            try:
                # ⭐ NEW FIX: Force the resolution via swaymsg at startup.
                subprocess.run(
                    ['swaymsg', 'output', output_name, 'mode', f'{width}x{height}'],
                    check=True,
                    timeout=10,
                    env=os.environ  # Important pour SWAYSOCK
                )
                time.sleep(2)  # Allow the display time to stabilize.
                logger.info(f"📅 Resolution {width}x{height} successfully applied to {output_name}")
            except Exception as e:
                logger.error(f"❌ Failed to force the resolution at startup: {e}")
        
        # Calculate active hours based on the day (weekday vs. weekend).
        now = datetime.now()
        is_weekend = now.weekday() in (4, 5)
        
        if is_weekend:
            start_str = config.get("active_start_weekend", config.get("active_start", "07:00"))
            end_str = config.get("active_end_weekend", config.get("active_end", "23:00"))
        else:
            start_str = config.get("active_start_weekday", config.get("active_start", "07:00"))
            end_str = config.get("active_end_weekday", config.get("active_end", "22:00"))

        now_time = now.time()
        start_time = datetime.strptime(start_str, "%H:%M").time()
        end_time = datetime.strptime(end_str, "%H:%M").time()
        in_schedule_at_boot = (start_time <= end_time and start_time <= now_time <= end_time) or \
                              (start_time > end_time and (now_time >= start_time or now_time <= end_time))

        # In background_updater mode, always start the display process at
        # boot (the desktop wallpaper should update regardless of active hours).
        if in_schedule_at_boot or get_app_mode(config) == "background_updater":
            logger.info(f"📅 Launching the display process (mode={get_app_mode(config)}).")
            start_display_process()
    except Exception as e:
        logger.error(f"❌ Critical error in the startup sequence: {e}", exc_info=True)

    last_schedule_state = None
    while True:
        try:
            config = load_config()
            
            now = datetime.now()
            is_weekend = now.weekday() in (4, 5)
            
            if is_weekend:
                start_str = config.get("active_start_weekend", config.get("active_start", "07:00"))
                end_str = config.get("active_end_weekend", config.get("active_end", "23:00"))
            else:
                start_str = config.get("active_start_weekday", config.get("active_start", "07:00"))
                end_str = config.get("active_end_weekday", config.get("active_end", "22:00"))

            now_time = now.time()
            start_time = datetime.strptime(start_str, "%H:%M").time()
            end_time = datetime.strptime(end_str, "%H:%M").time()

            if start_time <= end_time:
                in_schedule = start_time <= now_time <= end_time
            else:
                in_schedule = now_time >= start_time or now_time <= end_time

            # Reset the manual override when the active-hours window changes (e.g. night to day).
            if last_schedule_state is not None and last_schedule_state != in_schedule:
                logger.info("📅 Schedule change detected; resetting the manual override.")
                config['manual_override'] = None
                save_config(config)

            last_schedule_state = in_schedule
            manual_override = config.get('manual_override')
            slideshow_is_running = is_display_process_running()

            # In background_updater mode, the active-hours schedule is less
            # meaningful (the desktop wallpaper should update regardless of
            # the time of day).  Only apply the schedule in picture_frame mode,
            # or when the user has explicitly set a manual override.
            skip_schedule = (get_app_mode(config) == "background_updater")

            # Automatically stop only when there is no "start" override.
            if not skip_schedule and not in_schedule and slideshow_is_running and manual_override != "start":
                logger.info("📅 Inactive hours detected while the slideshow is running. Stopping...")
                stop_display_process()
            # Automatically start only when there is no "stop" override.
            elif (skip_schedule or in_schedule) and not slideshow_is_running and manual_override != "stop":
                logger.info("📅 Active hours detected while the slideshow is stopped. Starting...")
                if not skip_schedule:
                    # Picture-frame mode: ensure the display is on (via DPMS
                    # if there is no smart plug) and force the resolution.
                    set_display_power(on=True)
                    time.sleep(5)
                    output_name = get_display_output_name()
                    if output_name:
                        width = config.get('display_width', 1920)
                        height = config.get('display_height', 1080)
                        logger.info(f"📅 Forcing resolution {width}x{height} on display '{output_name}' after wake.")
                        try:
                            subprocess.run(
                                ['swaymsg', 'output', output_name, 'mode', f'{width}x{height}'],
                                check=True, timeout=10, env=os.environ
                            )
                            time.sleep(2) # Allow the display time to stabilize.
                        except Exception as e:
                            logger.error(f"❌ Failed to force the resolution after wake: {e}")

                # Start the display process (slideshow or background updater).
                start_display_process()

        except Exception as e:
            logger.error(f"📅❌ Error in the scheduling worker: {e}", exc_info=True)

        # Wait 60 seconds before checking again.
        time.sleep(60)



# --- USB import ---

@app.route("/import_usb_progress")
@login_required
def import_usb_progress():
    @stream_with_context
    def generate(): # type: ignore
        try:
            yield "Importing from USB drive...\n"
            import_usb_photos()
            yield "Preparing photos...\n"
            prepare_all_photos()
            yield "Done. (100%)\n"
        except Exception as e:
            yield f"Erreur : {str(e)}\n"
    return Response(generate(), mimetype="text/plain")


# --- Slideshow management ---

@app.route("/slideshow")
@login_required
def slideshow():
    return render_template("slideshow.html.jinja")

@app.route('/slideshow_view')
def slideshow_view():
    all_media = [media for source_media in get_prepared_photos_by_source().values() for media in source_media]
    return render_template('slideshow_view.html.jinja', photos=all_media) # The template likely expects a 'photos' variable.

@app.route('/toggle_slideshow', methods=['POST'])
@login_required
def toggle_slideshow():
    config = load_config()

    # Read the current slideshow state.
    running = is_display_process_running()

    # Stop the slideshow if it is running; otherwise start it.
    if running:
        stop_display_process()
        config['manual_override'] = "stop"  # The user requested a stop.
    else:
        set_display_power(on=True)
        time.sleep(1)
        start_display_process()
        config['manual_override'] = "start"  # The user requested a start.

    save_config(config) # Save config after manual override

    return redirect(url_for('configure'))
    
# --- Suppression photo ---
@app.route('/delete_photo/<path:photo>', methods=['DELETE'])
@login_required
def delete_photo(photo):
    try:
        # The relative path has the form 'source/photo_name.jpg'.
        photo_path_obj = Path('static/prepared') / photo
        
        # Determine the paths for alternate versions and the backup.
        polaroid_path = photo_path_obj.with_name(f"{photo_path_obj.stem}_polaroid.jpg")
        postcard_path = photo_path_obj.with_name(f"{photo_path_obj.stem}_postcard.jpg")
        backup_path = Path('static/.backups') / photo

        # Delete all associated files.
        if photo_path_obj.is_file():
            photo_path_obj.unlink()
        if polaroid_path.is_file():
            polaroid_path.unlink()
        if postcard_path.is_file():
            postcard_path.unlink()
        if backup_path.is_file():
            backup_path.unlink()
        
        # Delete the filter state for this photo.
        states = load_filter_states()
        if states.pop(photo, None):
            save_filter_states(states)
        with CROP_LOCK:
            crops = load_crops()
            if crops.pop(photo, None) is not None:
                save_crops(crops)

        # Remove the photo from favorites, if present.
        favorites = load_favorites()
        if photo in favorites:
            favorites.remove(photo)
            save_favorites(favorites)

        return '', 204
    except Exception as e:
        return str(e), 500
# --- System control ---

@app.route('/delete_source_photos/<source_name>', methods=['DELETE'])
@login_required
def delete_source_photos(source_name):
    """Delete all prepared photos for a source, including backups."""
    if not re.match(r'^[a-zA-Z0-9_-]+$', source_name):
        return jsonify({"success": False, "message": "Nom de source invalide."}), 400

    prepared_dir = PREPARED_DIR / source_name
    backup_dir = BASE_DIR / 'static' / '.backups' / source_name

    try:
        if prepared_dir.is_dir():
            shutil.rmtree(prepared_dir)
            logger.info(f"Deleted prepared directory: {prepared_dir}")
        
        if backup_dir.is_dir():
            shutil.rmtree(backup_dir)
            logger.info(f"Deleted backup directory: {backup_dir}")

        # Delete filter states for this source.
        states = load_filter_states()
        keys_to_delete = [key for key in states if key.startswith(f"{source_name}/")]
        if keys_to_delete:
            for key in keys_to_delete:
                del states[key]
            save_filter_states(states)
        return jsonify({"success": True, "message": "Photos deleted."}), 200
    except Exception as e:
        logger.info(f"Error deleting photos from source {source_name}: {e}")
        return jsonify({"success": False, "message": f"Erreur serveur : {e}"}), 500

@app.route('/shutdown', methods=['POST'])
@login_required
def shutdown():
    if not IS_LINUX:
        flash(_("System shutdown unavailable on this platform."), "warning")
        return redirect(url_for('configure'))
    from platform_utils import system_shutdown
    if not system_shutdown():
        flash(_("Unable to load data."), "warning")
    return redirect(url_for('configure'))

@app.route('/reboot', methods=['POST'])
@login_required
def reboot():
    if not IS_LINUX:
        flash(_("System reboot unavailable on this platform."), "warning")
        return redirect(url_for('configure'))
    from platform_utils import system_reboot
    if not system_reboot():
        flash(_("Unable to initiate system reboot."), "warning")
    return redirect(url_for('configure'))

@app.route('/system_reboot', methods=['POST'])
@login_required
def system_reboot():
    """Display the restart page and initiate reboot after one second."""
    # Delete the log file if selected.
    if request.form.get('delete_logs'):
        log_file = BASE_DIR / 'logs' / 'pictureframe.log'
        if os.path.exists(log_file):
            try:
                os.remove(log_file)
                print("pictureframe.log deleted")
            except Exception as e:
                print(f"Erreur suppression log: {e}")    
    
    
    
    
    return render_template('rebooting.html.jinja')


@app.route('/rebooting', methods=['GET'])
def rebooting():
    """Display the restart page (available via GET for redirects)."""
    return render_template('rebooting.html.jinja')

@app.route('/api/trigger_reboot', methods=['POST'])
@login_required
def trigger_reboot():
    """Run the system reboot command."""
    if not IS_LINUX:
        return jsonify({"success": False, "message": "System reboot is unavailable on this platform."}), 501
    try:
        # Reboot in the background so the HTTP response can be sent.
        import threading
        def delayed_reboot():
            time.sleep(1)  # Attendre 1 seconde pour que la page se charge
            from platform_utils import system_reboot
            if not system_reboot():
                logger.error("Unable to initiate system reboot.")
        
        reboot_thread = threading.Thread(target=delayed_reboot)
        reboot_thread.daemon = True
        reboot_thread.start()
        
        return jsonify({"success": True, "message": "Restart initiated."})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/ping', methods=['GET'])
def ping():
    """Simple endpoint to check whether the server is available."""
    # Calculate the active-hours window for the update page.
    config = load_config()
    now = datetime.now()
    is_weekend = now.weekday() in (4, 5)
    if is_weekend:
        start_str = config.get("active_start_weekend", config.get("active_start", "07:00"))
        end_str = config.get("active_end_weekend", config.get("active_end", "23:00"))
    else:
        start_str = config.get("active_start_weekday", config.get("active_start", "07:00"))
        end_str = config.get("active_end_weekday", config.get("active_end", "22:00"))
    
    is_active = True
    try:
        start_t = datetime.strptime(start_str, "%H:%M").time()
        end_t = datetime.strptime(end_str, "%H:%M").time()
        now_t = now.time()
        is_active = (start_t <= now_t <= end_t) if start_t <= end_t else (now_t >= start_t or now_t <= end_t)
    except: pass

    return jsonify({
        "status": "ok",
        "instance": APP_INSTANCE_ID,
        "slideshow_running": is_display_process_running(),
        "is_active_hours": is_active
    })


# ── Application Update (git pull) ─────────────────────────────────

@app.route('/api/update_status', methods=['GET'])
@login_required
def update_status():
    """Return git repo status and backup info for the update UI."""
    try:
        from platform_utils import is_git_repo, git_get_info, git_has_updates, git_backup_exists
        if not is_git_repo():
            return jsonify({"is_git_repo": False})
        has_updates, info = git_has_updates()
        return jsonify({
            "is_git_repo": True,
            "has_updates": has_updates,
            "commit": info.get("commit", ""),
            "branch": info.get("branch", ""),
            "behind_count": info.get("behind_count", 0),
            "new_commits": info.get("new_commits", []),
            "backup_exists": git_backup_exists(),
        })
    except Exception as e:
        logger.error("update_status failed: %s", e)
        return jsonify({"is_git_repo": False, "error": str(e)}), 500


@app.route('/api/trigger_update', methods=['POST'])
@login_required
def trigger_update():
    """Generate and launch the update script, then exit the app."""
    from platform_utils import is_git_repo, generate_update_script
    if not is_git_repo():
        return jsonify({"success": False, "message": _("The application is not in a git repository.")}), 400
    try:
        script_path, _script_content = generate_update_script(BASE_DIR)
        if not script_path:
            raise RuntimeError(_("Unable to generate the update script."))

        import subprocess
        log_file = str(BASE_DIR / "logs" / "update.log")
        with open(log_file, "a") as lf:
            subprocess.Popen(
                [sys.executable, script_path],
                stdout=lf, stderr=lf,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
        logger.info("Update script launched: %s", script_path)

        # Exit the app so the script can restart it.
        RESTART_EXIT_CODE = 42
        def do_exit():
            time.sleep(2)
            sys.exit(RESTART_EXIT_CODE)

        threading.Thread(target=do_exit, daemon=True).start()
        return jsonify({"success": True, "message": _("Update in progress...")})
    except Exception as e:
        logger.error("trigger_update failed: %s", e)
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/delete_backup', methods=['POST'])
@login_required
def delete_backup():
    """Delete the update backup directory."""
    from platform_utils import git_delete_backup, git_backup_exists
    if not git_backup_exists():
        return jsonify({"success": False, "message": _("No backup file selected.")}), 400
    if git_delete_backup():
        return jsonify({"success": True, "message": _("Backup deleted.")})
    return jsonify({"success": False, "message": _("Error deleting photo.")}), 500


@app.route('/api/revert_to_backup', methods=['POST'])
@login_required
def revert_to_backup():
    """Revert to the backup by launching the update script with rollback."""
    from platform_utils import git_backup_exists, generate_update_script
    if not git_backup_exists():
        return jsonify({"success": False, "message": _("No backup to restore.")}), 400

    try:
        script_path, _script_content = generate_update_script(BASE_DIR)
        if not script_path:
            raise RuntimeError(_("Unable to generate the script."))

        # Modify: skip git pull for revert (just restore the backup).
        with open(script_path, 'r') as f:
            content = f.read()
        content = content.replace("if git_pull():", "if False:  # skip git pull for revert")
        with open(script_path, 'w') as f:
            f.write(content)

        import subprocess
        log_file = str(BASE_DIR / "logs" / "update.log")
        with open(log_file, "a") as lf:
            subprocess.Popen(
                [sys.executable, script_path],
                stdout=lf, stderr=lf,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )

        RESTART_EXIT_CODE = 42
        def do_exit():
            time.sleep(2)
            sys.exit(RESTART_EXIT_CODE)

        threading.Thread(target=do_exit, daemon=True).start()
        return jsonify({"success": True, "message": _("Restoration in progress... The application will restart.")})
    except Exception as e:
        logger.error("revert_to_backup failed: %s", e)
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/restart_app', methods=['POST'])
@login_required
def restart_app():
    """Restart only the Flask web application."""
    # Special exit code that tells the shell script to restart the application.
    RESTART_EXIT_CODE = 42
    def do_restart():
        # Allow the browser to receive the response before terminating the process.
        time.sleep(2)
        print("[Restart] Web application restart requested by the user.")
        sys.exit(RESTART_EXIT_CODE)
        os._exit(RESTART_EXIT_CODE)

    # Start the restart in a thread so it does not block the HTTP response.
    restart_thread = threading.Thread(target=do_restart)
    restart_thread.start()
    
    flash(_("The web application is rebooting... the page will be inaccessible for a few seconds."), "success")
    return redirect(url_for('configure'))

@app.route('/api/slideshow/restart_for_update', methods=['POST'])
@login_required
def restart_slideshow_for_update_route():
    """Restart the slideshow to apply content updates without turning off the display."""
    try:
        if is_display_process_running():
            restart_display_process_for_update()
        return jsonify({"success": True, "message": "Restart command sent."})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/cancel_import', methods=['POST'])
@login_required
def cancel_import():
    """Create a flag file to signal cancellation to import/preparation processes."""
    try:
        CANCEL_FLAG_PATH.touch()
        return jsonify({"success": True, "message": "Cancellation signal sent."})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/playlists/play', methods=['POST'])
def play_playlist():
    # Security: accept requests only from this machine or an authenticated user.
    if not session.get('logged_in') and request.remote_addr != '127.0.0.1':
        return jsonify({"success": False, "message": "Unauthorized access."}), 403

    data = request.get_json()
    playlist_id = data.get('id')
    if not playlist_id:
        return jsonify({"success": False, "message": "ID de playlist manquant."}), 400

    try:
        playlists = load_playlists()
        target_playlist = next((p for p in playlists if p.get('id') == playlist_id), None)

        if not target_playlist:
            return jsonify({"success": False, "message": "Playlist not found."}), 404

        if not target_playlist.get('photos'):
            return jsonify({"success": False, "message": "La playlist est vide."}), 400

        # FIX: Create a JSON object with the name, photos, and music.
        playlist_data_to_save = {
            "name": target_playlist.get('name', 'Playlist'),
            "photos": target_playlist.get('photos', []),
            "music_file": target_playlist.get('music_file') # Nouveau champ optionnel
        }

        # Write the data to the temporary file that the slideshow will read.
        with open(CUSTOM_PLAYLIST_FILE, 'w') as f:
            json.dump(playlist_data_to_save, f)
        
        # Restart the slideshow to load the new playlist without turning off the display.
        restart_display_process_for_update()

        return jsonify({"success": True, "message": f"Lancement du diaporama pour la playlist '{target_playlist.get('name')}'."})
    except Exception as e:
        logger.info(f"Error starting playlist: {e}")
        return jsonify({"success": False, "message": "Erreur interne du serveur."}), 500

@app.route('/api/slideshow/restart_standard', methods=['POST'])
def restart_standard_slideshow():
    """Stop any running slideshow and start a new one in standard mode."""
    try:
        # Ensure the custom playlist file is removed.
        if os.path.exists(CUSTOM_PLAYLIST_FILE):
            os.remove(CUSTOM_PLAYLIST_FILE)
        
        # Restart the slideshow in standard mode without turning off the display.
        restart_display_process_for_update()
        return jsonify({"success": True, "message": "Standard slideshow restarted."})
    except Exception as e:
        logger.info(f"Error restarting the standard slideshow: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/slideshow/toggle_sleep', methods=['POST'])
def toggle_sleep_api():
    """Toggle the slideshow state (active/sleep). Used by the physical button."""
    # Security: accept requests only from this machine.
    if request.remote_addr != '127.0.0.1':
        logger.warning(f"Unauthorized access attempt to toggle_sleep from {request.remote_addr}")
        return jsonify({"success": False, "message": "Unauthorized access."}), 403
    
    try:
        if is_display_process_running():
            logger.info("API toggle_sleep: slideshow running -> stopping.")
            stop_display_process()
            message = "Diaporama mis en veille."
        else:
            logger.info("API toggle_sleep: slideshow stopped -> starting.")
            start_display_process()
            message = "Slideshow resumed."
        return jsonify({"success": True, "message": message})
    except Exception as e:
        logger.error(f"Error toggling sleep via API: {e}", exc_info=True)
        return jsonify({"success": False, "message": str(e)}), 500

# --- Playlist management API ---

@app.route('/api/playlists', methods=['GET'])
def get_playlists():
    """Return the list of all playlists."""
    playlists = load_playlists()
    return jsonify(playlists)

@app.route('/api/playlists', methods=['POST'])
@login_required
def create_playlist():
    """Create a new playlist."""
    data = request.get_json()
    name = data.get('name')
    music_file = data.get('music_file') # This line must remain outside the 'if' block.
    if not name or not name.strip():
        return jsonify({"success": False, "message": "Le nom de la playlist est requis."}), 400

    playlists = load_playlists()
    
    # Check whether a playlist with the same name already exists.
    if any(p['name'].lower() == name.strip().lower() for p in playlists):
        return jsonify({"success": False, "message": "A playlist with this name already exists."}), 409

    new_playlist = {
        "id": secrets.token_hex(8),
        "name": name.strip(),
        "photos": [],
        "music_file": music_file
    }
    playlists.append(new_playlist)
    save_playlists(playlists)
    return jsonify({"success": True, "playlist": new_playlist}), 201

@app.route('/api/playlists/<playlist_id>/update_music', methods=['POST'])
@login_required
def update_playlist_music(playlist_id):
    """Update the music file for an existing playlist."""
    data = request.get_json()
    music_file = data.get('music_file')

    playlists = load_playlists()
    found = False
    for playlist in playlists:
        if playlist.get('id') == playlist_id:
            playlist['music_file'] = music_file
            found = True
            break
    
    if not found:
        return jsonify({"success": False, "message": "Playlist not found."}), 404

    save_playlists(playlists)
    return jsonify({"success": True, "message": "Playlist music updated."})

@app.route('/api/music_files', methods=['GET'])
@login_required
def get_music_files():
    """Returns a list of available music files in static/music/."""
    music_dir = BASE_DIR / "static" / "music"
    music_files = []
    if music_dir.exists():
        for f in music_dir.iterdir():
            if f.is_file() and f.suffix.lower() in ['.mp3', '.wav']:
                music_files.append(f.name)
    return jsonify({"success": True, "files": sorted(music_files)})

@app.route('/api/music_files/<filename>', methods=['DELETE'])
@login_required
def delete_music_file(filename):
    """Delete a music file from static/music/."""
    # The filename was already sanitized during upload and is passed as-is from the file list.
    # secure_filename() is unnecessary here and can cause problems if the name changes during
    # sanitization (e.g. spaces replaced by underscores).
    music_path = BASE_DIR / "static" / "music" / filename
    
    if music_path.exists() and music_path.is_file():
        try:
            music_path.unlink()
            logger.info(f"🎵 Music deleted: {filename}")
            return jsonify({"success": True, "message": f"File '{filename}' deleted successfully."})
        except Exception as e:
            return jsonify({"success": False, "message": f"Erreur lors de la suppression : {str(e)}"}), 500
    else:
        logger.warning(f"❌ Attempt to delete missing file: {music_path}")
        return jsonify({"success": False, "message": "Fichier introuvable."}), 404

@app.route('/api/upload_music', methods=['POST'])
@login_required
def upload_music():
    """Upload a new music file to static/music/."""
    if 'music_file' not in request.files:
        return jsonify({"success": False, "message": "No file selected."}), 400
    
    file = request.files['music_file']
    if file.filename == '':
        return jsonify({"success": False, "message": "No file selected."}), 400
    
    if file and file.filename.lower().endswith(('.mp3', '.wav')):
        filename = secure_filename(file.filename)
        music_dir = BASE_DIR / "static" / "music"
        music_dir.mkdir(parents=True, exist_ok=True)
        file.save(music_dir / filename)
        logger.info(f"🎵 New music imported: {filename}")
        return jsonify({"success": True, "message": f"File '{filename}' uploaded successfully."})
    else:
        return jsonify({"success": False, "message": "Unsupported file format. MP3 or WAV only."}), 400

@app.route('/api/playlists/<playlist_id>', methods=['DELETE'])
def delete_playlist(playlist_id):
    """Delete a playlist."""
    playlists = load_playlists()
    playlists = [p for p in playlists if p.get('id') != playlist_id]
    save_playlists(playlists)
    return jsonify({"success": True})

@app.route('/api/playlists/<playlist_id>/rename', methods=['POST'])
def rename_playlist(playlist_id):
    """Renomme une playlist."""
    data = request.get_json()
    new_name = data.get('name')
    if not new_name or not new_name.strip():
        return jsonify({"success": False, "message": "The new name cannot be empty."}), 400

    playlists = load_playlists()
    
    if any(p['name'].lower() == new_name.strip().lower() and p.get('id') != playlist_id for p in playlists):
        return jsonify({"success": False, "message": "Another playlist with this name already exists."}), 409

    found = False
    for playlist in playlists:
        if playlist.get('id') == playlist_id:
            playlist['name'] = new_name.strip()
            found = True
            break
    
    save_playlists(playlists)
    return jsonify({"success": True, "message": "Playlist renamed."})

@app.route('/api/playlists/<playlist_id>/photos', methods=['POST'])
def add_photo_to_playlist(playlist_id):
    """Add a photo to a playlist."""
    data = request.get_json()
    photo_path = data.get('photo_path')
    if not photo_path:
        return jsonify({"success": False, "message": "Chemin de la photo manquant."}), 400

    playlists = load_playlists()
    for playlist in playlists:
        if playlist.get('id') == playlist_id:
            if photo_path not in playlist['photos']:
                playlist['photos'].append(photo_path)
            save_playlists(playlists)
            return jsonify({"success": True})
    return jsonify({"success": False, "message": "Playlist not found."}), 404

@app.route('/api/playlists/<playlist_id>/photos/<path:photo_path>', methods=['DELETE'])
def remove_photo_from_playlist(playlist_id, photo_path):
    """Remove a photo from a playlist."""
    playlists = load_playlists()
    for playlist in playlists:
        if playlist.get('id') == playlist_id:
            if photo_path in playlist['photos']:
                playlist['photos'].remove(photo_path)
            save_playlists(playlists)
            return jsonify({"success": True})
    return jsonify({"success": False, "message": "Playlist not found."}), 404

@app.route('/api/playlists/<playlist_id>/reorder', methods=['POST'])
def reorder_playlist(playlist_id):
    """
    Reorder photos in a specific playlist.
    Accepts a list of photo paths in the new order.
    """
    data = request.get_json()
    if not data or 'photos' not in data:
        return jsonify({"success": False, "message": "Missing data."}), 400

    new_photo_order = data['photos']

    try:
        playlists = load_playlists() 
        
        playlist_found = False
        for playlist in playlists:
            if playlist.get('id') == playlist_id:
                # Security check: ensure the new order contains exactly the same photos
                # as the original order, with no additions or removals.
                original_photos_set = set(playlist['photos'])
                new_photos_set = set(new_photo_order)

                if original_photos_set != new_photos_set:
                     return jsonify({"success": False, "message": "Photo list mismatch."}), 400

                playlist['photos'] = new_photo_order
                playlist_found = True
                break
        
        if not playlist_found:
            return jsonify({"success": False, "message": "Playlist not found."}), 404

        save_playlists(playlists) 

        return jsonify({"success": True, "message": "Playlist order saved."})

    except Exception as e:
        logger.info(f"Error reordering the playlist: {e}")
        return jsonify({"success": False, "message": "Erreur interne du serveur."}), 500






# --- System and slideshow control APIs ---

@app.route('/api/system/shutdown', methods=['POST'])
def system_shutdown():
    """Shut down the system."""
    # Security: accept requests only from this machine.
    if request.remote_addr != '127.0.0.1':
        return jsonify({"success": False, "message": "Unauthorized access."}), 403
    if not IS_LINUX:
        return jsonify({"success": False, "message": "System shutdown is unavailable on this platform."}), 501
    print("System shutdown requested via API.")
    from platform_utils import system_shutdown
    if not system_shutdown():
        return jsonify({"success": False, "message": "Unable to initiate system shutdown."}), 500
    return jsonify({"success": True, "message": "Shutting down."})

@app.route('/api/display/power', methods=['POST'])
def display_power():
    """Turn the display on or off."""
    if request.remote_addr != '127.0.0.1':
        return jsonify({"success": False, "message": "Unauthorized access."}), 403
    
    data = request.get_json()
    state = data.get('state') # 'on' or 'off'

    if state not in ['on', 'off']:
        return jsonify({"success": False, "message": "Invalid state. Use 'on' or 'off'."}), 400

    # The logic is now in slideshow_manager.
    if state == 'on':
        if not is_display_process_running():
            start_display_process()
        success, message = True, "Start command sent."
    else: # off
        if is_display_process_running():
            stop_display_process()
        success, message = True, "Stop command sent."

    return jsonify({"success": success, "message": message})

@app.route('/api/sources/play/<source_name>', methods=['POST'])
def play_source_as_playlist(source_name):
    """Play all photos from a source as a playlist."""
    if request.remote_addr != '127.0.0.1':
        return jsonify({"success": False, "message": "Unauthorized access."}), 403

    source_dir = PREPARED_DIR / source_name
    source_label = get_photo_source_labels([source_name])[source_name]
    if not source_dir.is_dir():
        return jsonify({"success": False, "message": f"La source '{source_label}' n'existe pas."}), 404

    photos = [
        f"{source_name}/{f.name}" for f in source_dir.iterdir() 
        if f.is_file() and not f.name.endswith(('_polaroid.jpg', '_thumbnail.jpg', '_postcard.jpg'))
    ]

    if not photos:
        return jsonify({"success": False, "message": f"La source '{source_label}' est vide."}), 400

    playlist_data = {"name": f"Source: {source_label}", "photos": photos}
    
    try:
        with open(CUSTOM_PLAYLIST_FILE, 'w', encoding='utf-8') as f:
            json.dump(playlist_data, f)
        
        stop_display_process()
        time.sleep(1.5) # Allow a little more time for shutdown.
        start_display_process()
        
        return jsonify({"success": True, "message": f"Lancement du diaporama pour la source '{source_label}'."})
    except Exception as e:
        return jsonify({"success": False, "message": f"Erreur lors du lancement de la playlist source: {e}"}), 500

@app.route('/api/sources/toggle', methods=['POST'])
def toggle_source():
    """Enable or disable a source in the configuration."""
    app.logger.info(f"API /api/sources/toggle request received from {request.remote_addr}")
    if request.remote_addr != '127.0.0.1':
        app.logger.warning(f"Unauthorized access to /api/sources/toggle from {request.remote_addr}")
        return jsonify({"success": False, "message": "Unauthorized access."}), 403
        
    data = request.get_json()
    source_name = data.get('source')
    state = data.get('state') # 'on' or 'off'
    app.logger.info(f"Requested action: '{state}' for source '{source_name}'")

    if not source_name or state not in ['on', 'off']:
        app.logger.error(f"Invalid parameters received: source='{source_name}', state='{state}'")
        return jsonify({"success": False, "message": "Invalid 'source' or 'state' parameters."}), 400

    try:
        config = load_config()
        original_sources = config.get('display_sources', [])
        app.logger.info(f"Sources avant modification : {original_sources}")
        display_sources = set(original_sources)

        if state == 'on':
            display_sources.add(source_name)
            action_msg = "enabled"
        else: # off
            display_sources.discard(source_name)
            action_msg = "disabled"

        new_sources_list = sorted(list(display_sources))
        config['display_sources'] = new_sources_list
        app.logger.info(f"Sources after update (before saving): {new_sources_list}")
        save_config(config)
        app.logger.info("Configuration successfully saved to config.json.")
        
        # The slideshow detects the change automatically on its next cycle.
        # It no longer needs a forced restart, which caused the timeout.
        source_label = get_photo_source_labels([source_name])[source_name]
        return jsonify({"success": True, "message": f"Source '{source_label}' {action_msg}. The change will be applied to the slideshow."})
    except Exception as e:
        app.logger.error(f"Error in toggle_source: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"Erreur lors de la modification de la source : {e}"}), 500

@app.route('/api/slideshow/set_duration', methods=['POST'])
def set_slideshow_duration():
    """Change the photo display duration and restart the slideshow."""
    # Security: accept requests only from this machine.
    if request.remote_addr != '127.0.0.1':
        return jsonify({"success": False, "message": "Unauthorized access."}), 403
    
    data = request.get_json()
    duration = data.get('duration')

    if not isinstance(duration, int) or duration <= 0:
        return jsonify({"success": False, "message": "Invalid duration. A positive integer is required."}), 400

    try:
        config = load_config()
        # Duration is mode-specific: photo rotation in background mode,
        # on-screen display duration in picture-frame mode.
        if get_app_mode(config) == "background_updater":
            config['background_update_interval'] = duration
        else:
            config['display_duration'] = duration
        save_config(config)
        
        # Restart the slideshow to apply the new duration.
        if is_display_process_running():
            stop_display_process()
            time.sleep(1) # Laisser le temps au processus de se terminer
        
        start_display_process()
        
        return jsonify({"success": True, "message": f"Display duration set to {duration} seconds."})
    except Exception as e:
        app.logger.error(f"Error changing the display duration: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"Erreur interne du serveur : {e}"}), 500

def _display_pid_file():
    """Return the PID file of the display process matching the current run mode."""
    if get_app_mode(load_config()) == "background_updater":
        return BACKGROUND_PID_FILE
    return SLIDESHOW_PID_FILE


def _display_status_file():
    """Return the status file of the display process matching the current run mode."""
    if get_app_mode(load_config()) == "background_updater":
        return BACKGROUND_STATUS_FILE
    return SLIDESHOW_STATUS_FILE


def _send_slideshow_command(command, sig):
    """Send display-process controls through POSIX signals or the cross-platform command queue."""
    if not is_display_process_running():
        return jsonify({"success": False, "message": "Le diaporama n'est pas en cours."}), 404
    try:
        if IS_LINUX:
            with _display_pid_file().open("r", encoding="utf-8") as pid_file:
                pid = int(pid_file.read())
            os.kill(pid, sig)
        else:
            process = ("background"
                       if get_app_mode(load_config()) == "background_updater"
                       else "slideshow")
            enqueue_slideshow_command(command, process=process)
        return jsonify({"success": True})
    except (OSError, ValueError) as e:
        return jsonify({"success": False, "message": f"Impossible de communiquer avec le diaporama : {e}"}), 500

@app.route('/api/slideshow/next', methods=['POST'])
def slideshow_next():
    return _send_slideshow_command("next", getattr(signal, "SIGUSR1", None))

@app.route('/api/slideshow/previous', methods=['POST'])
def slideshow_previous():
    return _send_slideshow_command("previous", getattr(signal, "SIGUSR2", None))

@app.route('/api/slideshow/toggle_pause', methods=['POST'])
def slideshow_toggle_pause():
    return _send_slideshow_command("toggle_pause", getattr(signal, "SIGTSTP", None))

@app.route('/api/slideshow/toggle_notifications', methods=['POST'])
def toggle_notifications_api():
    """Toggle notification display in the slideshow."""
    if not session.get('logged_in') and request.remote_addr != '127.0.0.1':
        return jsonify({"success": False, "message": "Unauthorized access."}), 403
    
    try:
        config = load_config()       
        return jsonify({"success": True, "enabled": new_state})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/slideshow/status')
def slideshow_status():
    if not is_display_process_running():
        return jsonify({"running": False, "paused": False})
    try:
        with _display_status_file().open("r", encoding="utf-8") as f:
            status = json.load(f)
        config = load_config()
        return jsonify({"running": True, "notifications_enabled":  True, **status})
    except (FileNotFoundError, json.JSONDecodeError):
        return jsonify({"running": True, "paused": False, "notifications_enabled": True})


@app.route('/api/app_mode', methods=['GET'])
def get_app_mode_route():
    """Return the current top-level run mode (picture frame / background updater)."""
    return jsonify({"app_mode": get_app_mode(load_config())})


@app.route('/api/app_mode', methods=['POST'])
def set_app_mode_route():
    """Switch the top-level run mode and restart the display process.

    Accepts JSON: {"app_mode": "picture_frame" | "background_updater"}.
    Switching modes stops the active display process, persists the new mode
    to config.json and starts the newly selected one. Display power is never
    touched during the switch.
    """
    if not session.get('logged_in') and request.remote_addr != '127.0.0.1':
        return jsonify({"success": False, "message": "Unauthorized access."}), 403
    data = request.get_json(silent=True) or {}
    new_mode = data.get("app_mode")
    effective = switch_app_mode(new_mode)
    if effective != new_mode:
        return jsonify({"success": False,
                        "message": "Mode d'exécution invalide."}), 400
    return jsonify({"success": True, "app_mode": effective})

@app.route('/api/get_available_resolutions')
@login_required
def get_available_resolutions():
    """
    Récupère les résolutions disponibles pour la sortie d'affichage principale.
    """
    try:
        output_name = get_display_output_name()
        if not output_name:
            return jsonify({"success": False, "message": "No main display output found."})

        result = subprocess.run(['swaymsg', '-t', 'get_outputs'], capture_output=True, text=True, check=True, env=os.environ)
        outputs = json.loads(result.stdout)

        resolutions = []
        for output in outputs:
            if output.get('name') == output_name and 'modes' in output:
                for mode in output['modes']:
                    resolutions.append({
                        "width": mode['width'],
                        "height": mode['height'],
                        "refresh": mode['refresh'] / 1000, # Convert from mHz to Hz.
                        "text": f"{mode['width']}x{mode['height']} @ {mode['refresh']/1000:.2f}Hz"
                    })
                # Reverse the list to put the highest resolutions first.
                resolutions.reverse()
                return jsonify({"success": True, "resolutions": resolutions})

        return jsonify({"success": False, "message": "No mode found for the main output."})

    except Exception as e:
        return jsonify({"success": False, "message": f"Error retrieving resolutions: {e}"})

@app.route('/api/set_resolution', methods=['POST'])
@login_required
def set_resolution():
    """
    Applique une nouvelle résolution à l'écran et la sauvegarde dans la configuration.
    """
    data = request.get_json()
    width = data.get('width')
    height = data.get('height')

    if not width or not height:
        return jsonify({"success": False, "message": "Largeur et hauteur requises."}), 400

    try:
        output_name = get_display_output_name()
        if not output_name:
            return jsonify({"success": False, "message": "No display output to configure."})

        # Apply the resolution via swaymsg.
        subprocess.run(['swaymsg', 'output', output_name, 'resolution', f'{width}x{height}'], check=True)

        # Save to the configuration for persistence.
        config = load_config()
        config['display_width'] = int(width)
        config['display_height'] = int(height)
        save_config(config)

        # Restart the slideshow so it picks up the new resolution.
        if is_display_process_running():
            stop_display_process()
            start_display_process()
            message = _("Applied resolution: %(width) SX %(height)s. The slideshow has been restarted.", width=width, height=height)
        else:
            message = _("Applied resolution: %(width) SX %(height)s. The slideshow was not in progress.", width=width, height=height)

        return jsonify({"success": True, "message": message})
    except Exception as e:
        return jsonify({"success": False, "message": f"Error applying resolution: {e}"}), 500

@app.route('/api/smart_plug/status', methods=['GET'])
@login_required
def get_smart_plug_status():
    """
    Query the smart plug status URL and return its state.
    """
    config = load_config()
    if not config.get("smart_plug_enabled") or not config.get("smart_plug_status_url"):
        return jsonify({"status": "disabled", "message": "Smart plug status is not configured."})

    status_url = config.get("smart_plug_status_url")
    token = config.get("home_assistant_token") # The config key is 'home_assistant_token'.

    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        response = requests.get(status_url, headers=headers, timeout=5)
        response.raise_for_status() # Raise an exception for HTTP error codes (4xx or 5xx).
        
        data = response.json()
        # For Home Assistant, the state is in the 'state' key.
        plug_state = data.get('state', 'unknown').lower()

        return jsonify({"status": plug_state, "message": f"Smart plug status: {plug_state}"})

    except requests.exceptions.Timeout:
        return jsonify({"status": "unreachable", "message": "Timed out while connecting to the smart plug."})
    except requests.exceptions.HTTPError as e:
        # Handle authentication errors specifically to provide better feedback.
        if e.response.status_code == 401:
            return jsonify({"status": "error", "message": "Error 401: Unauthorized. Check your Home Assistant access token."})
        return jsonify({"status": "error", "message": f"Erreur HTTP: {str(e)}"})
    except requests.exceptions.RequestException as e:
        # Return a more explicit error.
        return jsonify({"status": "error", "message": f"Erreur de connexion: {str(e)}"})

@app.route('/get_current_resolution')
@login_required
def get_current_resolution_route():
    """
    Endpoint pour récupérer la résolution de l'écran si le diaporama est actif.
    """
    width, height = get_screen_resolution()
    
    if width and height:
         return jsonify({"success": True, "width": width, "height": height})
    else:
         # This should no longer occur because get_screen_resolution has a fallback, but keep it as a safeguard.
         return jsonify({"success": False, "message": "Unable to detect the resolution. Is the display connected?"})

@app.route('/current_photo_status')
@login_required
def current_photo_status():
    """Return the path of the currently displayed photo."""
    if not is_display_process_running():
        return jsonify({"current_photo": None, "status": "stopped", "metadata_text": ""})

    try:
        photo_path = ""
        if get_app_mode(load_config()) == "background_updater":
            # The background updater reports its current photo through its
            # status file; it never writes CURRENT_PHOTO_FILE.
            try:
                with open(BACKGROUND_STATUS_FILE, "r", encoding="utf-8") as f:
                    photo_path = (json.load(f) or {}).get("current_photo") or ""
            except (FileNotFoundError, json.JSONDecodeError, OSError):
                photo_path = ""
        elif os.path.exists(CURRENT_PHOTO_FILE):
            with open(CURRENT_PHOTO_FILE, "r", encoding="utf-8") as f:
                photo_path = f.read().strip()
        if photo_path:
            # The background updater writes an absolute path (e.g.
            # C:\...\static\prepared\smartphone\photo.jpg); url_for('static')
            # needs a path relative to the static/ directory.
            # Try to resolve relative to BASE_DIR/static first; fall back to
            # string-based stripping for paths that already use forward slashes.
            from pathlib import Path as _Path
            try:
                abs_path = _Path(photo_path)
                if abs_path.is_absolute():
                    static_dir = (_Path(BASE_DIR) / "static").resolve()
                    resolved = abs_path.resolve()
                    rel = resolved.relative_to(static_dir)
                    photo_path = to_static_url_path(rel)
                else:
                    photo_path = to_static_url_path(photo_path)
            except (ValueError, OSError):
                # Path is not under static/ — fall back to string stripping.
                photo_path = to_static_url_path(photo_path)
                static_marker = "/static/"
                if static_marker in photo_path:
                    photo_path = photo_path.split(static_marker, 1)[1]
                elif photo_path.startswith("static/"):
                    photo_path = photo_path[len("static/"):]
            # If the path is still absolute or not under static/, we cannot
            # serve it via url_for('static'); return None to avoid a 404.
            if _Path(photo_path).is_absolute() or not photo_path:
                return jsonify({"current_photo": None, "status": "running",
                                "metadata_text": ""})
            # Build the full URL for the image src attribute.
            metadata_path = BASE_DIR / "static" / photo_path
            metadata = get_photo_metadata(metadata_path)
            metadata_text = format_photo_metadata(metadata, load_config(), _)
            return jsonify({"current_photo": url_for('static', filename=photo_path),
                            "status": "running", "metadata_text": metadata_text or _("No Metadata"),
                            "location_text": format_preview_location(metadata, _)})
    except Exception as e:
        logger.info(f"Error reading current photo file: {e}")

    return jsonify({"current_photo": None, "status": "running", "metadata_text": ""})

@app.route('/save_wifi_settings', methods=['POST'])
@login_required
def save_wifi_settings():
    ssid = request.form.get('wifi_ssid')
    password = request.form.get('wifi_password')
    country = request.form.get('wifi_country') # Get the country code

    if not ssid or not country: # Country is now required
        flash(_("SSID and Wi-Fi country are mandatory."), "danger")
        return redirect(url_for('configure'))

    try:
        # Save the settings to config.json.
        config = load_config()
        config['wifi_ssid'] = ssid
        config['wifi_password'] = password
        config['wifi_country'] = country # Save country to config
        save_config(config)

        # Apply the Wi-Fi settings to the system.
        set_wifi_config(ssid, password, country) # Pass country to the function
        flash(_("Wi-Fi settings applied. The network service has been restarted to force connection. Please wait a minute and check the status."), "success")
    except Exception as e:
        flash(_("Error applying Wi-Fi settings: %(error)s", error=e), "danger")
    return redirect(url_for('configure'))

def get_wifi_status():
    """
    Retrieve Wi-Fi connection status efficiently with a single nmcli call.
    This is more robust and faster than making multiple calls to different commands.
    """
    interface = "wlan0" # Assume wlan0 is the Wi-Fi interface.
    
    # Quickly check whether the Wi-Fi interface exists on the system to avoid running
    # a slow or blocking nmcli command when Wi-Fi is unavailable (e.g. on Pi 2).
    if not os.path.exists(f"/sys/class/net/{interface}"):
        return {"is_connected": False, "ssid": "N/A (Pas de carte Wi-Fi)", "ip_address": "N/A"}

    try:
        # Optimized command to retrieve all information at once in terse mode (-t).
        cmd = ['nmcli', '-t', '-f', 'GENERAL.STATE,GENERAL.CONNECTION,IP4.ADDRESS', 'dev', 'show', interface]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=5)
        
        output_map = {}
        for line in result.stdout.strip().split('\n'):
            if ':' in line:
                key, value = line.split(':', 1)
                output_map[key] = value

        state_code_str = output_map.get('GENERAL.STATE', '0').split(' ')[0]
        state_code = int(state_code_str) if state_code_str.isdigit() else 0
        is_connected = (state_code == 100)
        
        if is_connected:
            ssid = output_map.get('GENERAL.CONNECTION', 'Inconnu')
            ip_address = output_map.get('IP4.ADDRESS[1]', 'N/A').split('/')[0]
            return {"is_connected": True, "ssid": ssid, "ip_address": ip_address}
        else:
            return {"is_connected": False, "ssid": "Not connected", "ip_address": "N/A"}

    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired, IndexError, ValueError) as e:
        logger.info(f"Error retrieving Wi-Fi status: {e}")
        return {"is_connected": False, "ssid": "Erreur", "ip_address": "N/A"}

@app.route('/api/wifi_status')
@login_required
def get_wifi_status_api():
    """Return the current Wi-Fi connection status."""
    status = get_wifi_status()
    return jsonify({"success": True, **status})

@app.route('/change_password', methods=['POST'])
@login_required
def change_password_route():
    """Handle a change to the interface password."""
    new_password = request.form.get('new_password')
    confirm_password = request.form.get('confirm_password')

    if not new_password or not confirm_password:
        flash(_("Both password fields are required."), "danger")
        return redirect(url_for('configure'))

    if new_password != confirm_password:
        flash(_("The passwords do not match."), "danger")
        return redirect(url_for('configure'))
    
    if len(new_password) < 6:
        flash(_("Password must contain at least 6 characters."), "warning")
        return redirect(url_for('configure'))

    try:
        change_password(new_password)
        flash(_("Password successfully updated. It will be required for your next login."), "success")
    except Exception as e:
        flash(_("Error changing password:%(error)s", error=e), "danger")

    return redirect(url_for('configure'))

@app.route('/api/interface_status/<interface_name>')
@login_required
def get_interface_status_api(interface_name):
    """Return the status of a specific network interface."""
    # Validate the interface name for security.
    if not re.match(r'^[a-zA-Z0-9-]+$', interface_name):
        return jsonify({"success": False, "message": "Nom d'interface invalide."}), 400
    
    status = get_interface_status(interface_name)
    return jsonify({"success": True, **status})

@app.route('/api/set_interface_state', methods=['POST'])
@login_required
def set_interface_state_api():
    """Enable or disable a network interface."""
    data = request.get_json()
    interface_name = data.get('interface')
    state = data.get('state')

    if not interface_name or not state in ['up', 'down']:
        return jsonify({"success": False, "message": "Invalid data."}), 400
    
    if not re.match(r'^[a-zA-Z0-9-]+$', interface_name):
        return jsonify({"success": False, "message": "Nom d'interface invalide."}), 400

    try:
        set_interface_state(interface_name, state)
        return jsonify({"success": True, "message": f"Interface {interface_name} set to '{state}'."})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
# --- Lancement de l'application ---

@app.route('/api/backup_settings')
@login_required
def backup_settings_api():
    """Allow the current configuration file to be downloaded."""
    try:
        backup_name = f'PictureFrame_backup_{datetime.now().strftime("%Y-%m-%d")}.json'
        return send_from_directory('config', 'config.json', as_attachment=True, download_name=backup_name)
    except FileNotFoundError:
        flash(_("The configuration file was not found."), "danger")
        return redirect(url_for('configure'))

@app.route('/api/restore_settings', methods=['POST'])
@login_required
def restore_settings_api():
    """Restore the configuration from a backup file."""
    if 'backup_file' not in request.files:
        flash(_("No backup file selected."), "warning")
        return redirect(url_for('configure'))

    file = request.files['backup_file']
    if file.filename == '':
        flash(_("No backup file selected."), "warning")
        return redirect(url_for('configure'))

    try:
        # Read and validate the JSON content.
        content = file.stream.read().decode("utf-8")
        new_config_data = json.loads(content)

        # Save the new configuration.
        save_config(new_config_data)
        flash(_("Configuration successfully restored! The slideshow will restart to apply the changes."), "success")
    except (json.JSONDecodeError, UnicodeDecodeError):
        flash(_("Invalid or corrupted backup file. This is not a valid JSON file."), "danger")
    except Exception as e:
        flash(_("Restore error: %(error)s", error=e), "danger")
    
    return redirect(url_for('configure'))

def get_cpu_temperature():
    """
    Tente de récupérer la température du CPU en utilisant plusieurs méthodes.
    Retourne la température formatée ou "N/A" en cas d'échec.
    """
    # Method 1: vcgencmd (Raspberry Pi-specific).
    try:
        temp_output = subprocess.check_output(['vcgencmd', 'measure_temp']).decode('utf-8')
        match = re.search(r"temp=([\d\.]*)'C", temp_output)
        if match:
            return float(match.group(1))
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass  # If the command fails, try the next method.

    # Method 2: sysfs thermal_zone0 (generic Linux).
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            temp_raw = int(f.read())
            return temp_raw / 1000.0
    except (FileNotFoundError, ValueError):
        pass # If the file does not exist or is invalid, continue.

    return None # Default value if all methods fail.

@app.route('/api/system_info')
@login_required
def get_system_info_api():
    """Return system information (temperature, CPU, RAM, storage) as JSON."""
    try:
        # Get the time once for both readings.
        current_time_str = datetime.now().strftime("%H:%M:%S")

        # CPU temperature.
        current_temp_float = get_cpu_temperature()
        
        # Add the reading to history if it is valid.
        if current_temp_float is not None:
            cpu_temp_history.append({
                "time": current_time_str,
                "temp": current_temp_float
            })
            cpu_temp_str = f"{current_temp_float:.1f}°C"
        else:
            cpu_temp_str = "N/A"

        # CPU usage.
        # interval=None makes this non-blocking and compares with the previous call; ideal for polling.
        current_cpu_usage_float = psutil.cpu_percent(interval=None)
        cpu_usage_history.append({
            "time": current_time_str,
            "usage": current_cpu_usage_float
        })
        cpu_usage_str = f"{current_cpu_usage_float}%"

        # RAM usage.
        ram = psutil.virtual_memory()
        ram_usage_percent_float = ram.percent
        ram_usage_history.append({
            "time": current_time_str,
            "usage": ram_usage_percent_float
        })
        ram_usage_str = f"{ram.percent}% ({ram.used / (1024**3):.1f}GB / {ram.total / (1024**3):.1f}GB)"

        # Disk usage.
        disk = psutil.disk_usage('/')
        disk_usage_percent_float = disk.percent
        disk_usage_history.append({
            "time": current_time_str,
            "usage": disk_usage_percent_float
        })
        disk_usage_str = f"{disk.percent}% ({disk.used / (1024**3):.1f}GB / {disk.total / (1024**3):.1f}GB)"

        return jsonify({
            "success": True,
            "cpu_temp": cpu_temp_str,
            "cpu_usage": cpu_usage_str,
            "ram_usage": ram_usage_str,
            "disk_usage": disk_usage_str,
            "cpu_temp_history": list(cpu_temp_history),
            "cpu_usage_history": list(cpu_usage_history),
            "ram_usage_history": list(ram_usage_history),
            "disk_usage_history": list(disk_usage_history) # Ajouter l'historique pour le graphique
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

@app.route('/api/list_logs', methods=['GET'])
@login_required
def list_logs():
    """Return the list of log files that actually exist."""
    available_logs = []
    # Iterate in a defined order for a consistent user interface.
    log_order = ["app"]
    for key in log_order:
        info = LOG_FILES_MAP.get(key)
        if info and os.path.exists(info["path"]):
            # Translate the name key during the request.
            available_logs.append({"key": key, "name": _(info["name_key"])})
    return jsonify({"success": True, "logs": available_logs})

@app.route('/api/logs')
@login_required
def get_logs_api():
    """Return the contents of the specified log file."""
    log_type = request.args.get('type', 'app')
    
    log_info = LOG_FILES_MAP.get(log_type)
    if not log_info:
        return jsonify({"success": False, "message": "Type de log invalide."})

    log_file_path = log_info['path']

    try:
        with open(log_file_path, 'r', encoding='utf-8', errors='ignore') as f:
            # Read only the last 500 lines of large log files for better performance
            # and a more responsive interface.
            lines = f.readlines()
            content = "".join(lines[-500:])
        return jsonify({"success": True, "content": content})
    except FileNotFoundError:
        # This is normal if the log has not been created yet; return empty content.
        return jsonify({"success": True, "content": ""})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

@app.route('/api/clear_logs', methods=['POST'])
@login_required
def clear_logs_api():
    """Clear the contents of the specified log file."""
    data = request.get_json()
    log_type = data.get('type')

    log_info = LOG_FILES_MAP.get(log_type)
    if not log_info:
        return jsonify({"success": False, "message": "Type de log invalide."}), 400
    log_file_path = log_info['path']

    try:
        if os.path.exists(log_file_path):
            with open(log_file_path, 'w') as f:
                f.truncate(0) # Efface le contenu du fichier
            return jsonify({"success": True, "message": f"Log '{log_type}' cleared."})
        else:
            return jsonify({"success": False, "message": f"Log file '{log_file_path}' not found."})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/expand_filesystem', methods=['POST'])
@login_required
def expand_filesystem():
    """
    Run the script that expands the root filesystem.
    """
    @stream_with_context
    def generate():
        def stream_event(data):
            return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

        script_path = Path(app.root_path) / 'utils' / 'expand_filesystem.sh'

        if not script_path.exists():
            yield stream_event({"type": "error", "message": "Le script 'utils/expand_filesystem.sh' est introuvable."})
            return

        try:
            os.chmod(script_path, 0o755)
        except OSError as e:
            yield stream_event({"type": "error", "message": f"Unable to make the script executable: {e}"})
            return

        command = ['/bin/bash', str(script_path)]

        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True,
            encoding='utf-8'
        )

        for line in iter(process.stdout.readline, ''):
            line = line.strip()
            if not line: continue

            parts = line.split(':', 2)
            if len(parts) == 3:
                yield stream_event({"type": parts[0], "stage": parts[1], "message": parts[2]})
            else:
                yield stream_event({"type": "raw", "message": line})

        process.stdout.close()
        process.wait()

    return Response(generate(), mimetype='text/event-stream', headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})


@app.route('/api/tide_info')
@login_required
def get_tide_info_api():
    """Return tide information from the cache file."""
    tide_cache_path = Path('cache/tides.json')
    if not tide_cache_path.exists():
        return jsonify({"success": False, "message": "Tide cache not found. The slideshow must run at least once."})

    try:
        with open(tide_cache_path, 'r') as f:
            cache_data = json.load(f)
        
        last_update_iso = cache_data.get('timestamp')
        last_update_dt = datetime.fromisoformat(last_update_iso)
        last_update_str = last_update_dt.strftime('%d/%m/%Y à %H:%M:%S')
        api_status = "OK"
        formatted_tides = []

        if cache_data.get('cooldown'):
            api_status = f"Cooldown active (API quota may have been reached). Next attempt after {(last_update_dt + timedelta(hours=12)).strftime('%H:%M')}."
        
        tides_data = cache_data.get('data', [])
        
        # --- FIX: Handle the legacy cache format (dictionary) ---
        if not tides_data or not isinstance(tides_data, list):
            api_status = "No valid tide data in the cache. Force an update."
            if isinstance(tides_data, dict):
                api_status = "Legacy cache format detected. Force an update."
        else:
            today = datetime.now().date()
            tomorrow = today + timedelta(days=1)
            day_map = {'Mon':'Lun', 'Tue':'Mar', 'Wed':'Mer', 'Thu':'Jeu', 'Fri':'Ven', 'Sat':'Sam', 'Sun':'Dim'}

            # Use only the next five tides for the web display.
            for tide in tides_data[:5]:
                tide_dt = datetime.fromisoformat(tide['time']).astimezone()
                tide_date = tide_dt.date()

                if tide_date == today: day_str = "Aujourd'hui"
                elif tide_date == tomorrow: day_str = "Demain"
                else: day_str = day_map.get(tide_dt.strftime('%a'), tide_dt.strftime('%a'))

                formatted_tides.append({
                    "type": "Pleine Mer" if tide['type'] == 'high' else "Basse Mer",
                    "time": f"{day_str} at {tide_dt.strftime('%H:%M')}",
                    "height": f"{tide['height']:.2f}m"
                })

        return jsonify({"success": True, "last_update": last_update_str, "tides": formatted_tides, "api_status": api_status})
    except (json.JSONDecodeError, KeyError, Exception) as e:
        return jsonify({"success": False, "message": f"Erreur lecture du cache: {str(e)}"})

@app.route('/api/apply_filter', methods=['POST'])
@login_required
def apply_filter_api():
    """Apply a filter to a prepared photo."""
    data = request.get_json()
    photo_relative_path = data.get('photo')
    filter_name = data.get('filter')

    if not photo_relative_path or not filter_name:
        return jsonify({"success": False, "message": "Chemin de la photo ou nom du filtre manquant."}), 400

    # The relative path has the form 'source/photo_name.jpg'.
    photo_full_path = PREPARED_DIR / photo_relative_path

    if not photo_full_path.resolve().is_relative_to(PREPARED_DIR.resolve()):
        logger.warning("Filter rejected: invalid photo path")
        return jsonify({"success": False, "message": "Invalid photo path."}), 400

    if not photo_full_path.is_file():
        return jsonify({"success": False, "message": f"Photo not found: {photo_full_path}"}), 404

    try:
        from utils.photo_edits import EDIT_LOCK, filter_strength, update_edit, validate_strength
        strength = validate_strength(data.get('strength', filter_strength(photo_full_path)))
        with EDIT_LOCK:
            previous_image = photo_full_path.read_bytes()
            previous_states = load_filter_states()
            try:
                apply_filter_to_image(str(photo_full_path), filter_name, strength,
                                      caption=load_text_states().get(photo_relative_path, ""))
                states = dict(previous_states)
                if filter_name in {'none', 'original'}:
                    states.pop(photo_relative_path, None)
                else:
                    states[photo_relative_path] = filter_name
                save_filter_states(states)
                update_edit(photo_relative_path, {"strength": strength})
            except Exception:
                photo_full_path.write_bytes(previous_image)
                save_filter_states(previous_states)
                raise
        # The path is unchanged, but return it to force the browser cache to refresh.
        new_url = url_for('static', filename=to_static_url_path(f'prepared/{photo_relative_path}'))
        return jsonify({"success": True, "message": "Filter applied!", "new_path": new_url})
    except ValueError as e: # Pour les noms de filtres invalides
        return jsonify({"success": False, "message": str(e)}), 400
    except Exception as e:
        logger.info(f"Error applying filter: {e}")
        return jsonify({"success": False, "message": f"Erreur interne du serveur : {e}"}), 500

@app.route('/api/photo_crop', methods=['GET', 'POST'])
@login_required
def photo_crop():
    crop_locked = False
    try:
        if request.method == 'POST':
            crop_locked = CROP_LOCK.acquire(blocking=False)
            if not crop_locked:
                logger.warning("Photo crop rejected: another crop is being prepared")
                return jsonify({"success": False, "message": _("Another crop is being prepared. Please wait.")}), 409
        data = request.get_json() if request.method == 'POST' else request.args
        if not isinstance(data, dict) and request.method == 'POST':
            raise ValueError("Invalid crop request.")
        photo = data.get("photo")
        original, prepared = original_photo(photo)
        image = oriented_image(original)
        config = load_config()
        width, height = int(config["display_width"]), int(config["display_height"])
        if width <= 0 or height <= 0:
            raise ValueError("Invalid display dimensions.")
        crops = load_crops()
        if request.method == 'GET':
            if request.args.get("image") == "1":
                image.thumbnail((1200, 1200))
                output = io.BytesIO()
                image.save(output, format="JPEG", quality=90)
                return Response(output.getvalue(), mimetype="image/jpeg",
                                headers={"Cache-Control": "no-store"})
            return jsonify({"width": image.width, "height": image.height,
                            "aspect_ratio": width / height, "crop": crops.get(photo)})
        crop = data.get("crop")
        if crop is not None:
            crop = validate_crop(crop, image.size, (width, height))
        from utils.prepare_all_photos import prepare_photo
        # Stage a complete set before replacing display files or crop settings.
        with tempfile.TemporaryDirectory(prefix="picframe-crop-") as directory:
            stage = Path(directory) / "static" / "prepared" / original.parent.name / prepared.name
            stage.parent.mkdir(parents=True)
            caption = load_text_states().get(photo, "")
            prepare_photo(str(original), str(stage), width, height,
                          source_type=original.parent.name, caption=caption, crop_selection=crop)
            outputs = [stage, stage.with_name(f"{stage.stem}_polaroid.jpg"),
                       stage.with_name(f"{stage.stem}_postcard.jpg")]
            if any(not path.is_file() or path.stat().st_size == 0 for path in outputs):
                raise RuntimeError("Crop preparation failed; existing images were not changed.")
            clean_backup = Path(directory) / "clean.jpg"
            shutil.copy2(stage, clean_backup)
            if caption:
                add_text_to_image(str(stage), caption)
            polaroid_caption = load_polaroid_texts().get(photo, "")
            if polaroid_caption:
                add_text_to_polaroid(str(outputs[1]), polaroid_caption)
            selected_filter = load_filter_states().get(photo, "none")
            if selected_filter not in {"none", "original", "polaroid", "postcard"}:
                # Filter the captioned image, without retaining its temporary backup.
                stage_backup = Path(directory) / "static" / ".backups" / original.parent.name / prepared.name
                if stage_backup.exists():
                    stage_backup.unlink()
                apply_filter_to_image(str(stage), selected_filter, caption=caption)
            targets = [prepared, prepared.with_name(outputs[1].name), prepared.with_name(outputs[2].name),
                       BASE_DIR / "static" / ".backups" / original.parent.name / prepared.name]
            replacements = [*outputs, clean_backup]
            previous = {}
            for index, target in enumerate(targets):
                if target.exists():
                    backup = Path(directory) / f"previous-{index}.jpg"
                    shutil.copy2(target, backup)
                    previous[target] = backup
            try:
                for replacement, target in zip(replacements, targets):
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(replacement, target)
                if crop is None:
                    crops.pop(photo, None)
                else:
                    crops[photo] = crop
                save_crops(crops)
            except Exception:
                for target in targets:
                    if target in previous:
                        shutil.copy2(previous[target], target)
                    elif target.exists():
                        target.unlink()
                raise
        if is_display_process_running():
            restart_display_process_for_update()
        return jsonify({"success": True, "message": _("Crop saved.")})
    except (ValueError, FileNotFoundError) as error:
        logger.warning("Photo crop rejected: %s", error)
        return jsonify({"success": False, "message": str(error)}), 400
    except Exception as error:
        logger.exception("Photo crop failed")
        return jsonify({"success": False, "message": str(error)}), 500
    finally:
        if crop_locked:
            CROP_LOCK.release()


from utils.photo_edit_routes import register_photo_edit_routes
register_photo_edit_routes(app, PREPARED_DIR, _)

@app.route('/api/set_photo_filter', methods=['POST'])
@login_required
def set_photo_filter():
    """Save the filter preference for a given photo."""
    data = request.get_json()
    photo_relative_path = data.get('photo')
    filter_name = data.get('filter')

    if not photo_relative_path or not filter_name:
        return jsonify({"success": False, "message": "Missing data."}), 400

    states = load_filter_states()
    
    if filter_name in ['none', 'original']:
        # Remove the filter from the state file if it is 'none' or 'original'.
        states.pop(photo_relative_path, None)
    else:
        states[photo_relative_path] = filter_name
    
    save_filter_states(states)
    return jsonify({"success": True, "message": "Filter preference saved."})

@app.route('/api/toggle_favorite', methods=['POST'])
@login_required
def toggle_favorite():
    """Add or remove a photo from the favorites list."""
    data = request.get_json()
    photo_relative_path = data.get('photo')

    if not photo_relative_path:
        return jsonify({"success": False, "message": "Chemin de la photo manquant."}), 400

    favorites = load_favorites()
    is_currently_favorite = photo_relative_path in favorites

    if is_currently_favorite:
        favorites.remove(photo_relative_path)
    else:
        favorites.append(photo_relative_path)
    
    save_favorites(favorites)
    
    return jsonify({"success": True, "is_favorite": not is_currently_favorite})

@app.route('/api/set_polaroid_text', methods=['POST'])
@login_required
def set_polaroid_text():
    """Apply text to a Polaroid image."""
    data = request.get_json()
    photo_relative_path = data.get('photo')
    text = data.get('text', '')

    if not photo_relative_path:
        return jsonify({"success": False, "message": "Chemin de la photo manquant."}), 400

    try:
        # Build the path to the Polaroid version of the image.
        path_obj = Path(photo_relative_path)
        polaroid_filename = f"{path_obj.stem}_polaroid.jpg"
        polaroid_relative_path = path_obj.with_name(polaroid_filename)
        polaroid_full_path = PREPARED_DIR / polaroid_relative_path

        if not polaroid_full_path.exists():
             return jsonify({"success": False, "message": "La version Polaroid de cette photo n'existe pas."}), 404

        # Call the function to add the text.
        add_text_to_polaroid(str(polaroid_full_path), text)

        # Save the text in the config file.
        texts = load_polaroid_texts()
        if text and text.strip():
            texts[photo_relative_path] = text
        else:
            texts.pop(photo_relative_path, None) # Remove the key if the text is empty.
        save_polaroid_texts(texts)

        return jsonify({"success": True, "message": "Text updated."})
    except Exception as e:
        return jsonify({"success": False, "message": f"Erreur interne du serveur : {e}"}), 500

@app.route('/api/set_image_text', methods=['POST'])
@login_required
def set_image_text():
    """Apply text to a generic image."""
    data = request.get_json()
    photo_relative_path = data.get('photo')
    text = data.get('text', '')

    if not photo_relative_path:
        return jsonify({"success": False, "message": "Chemin de la photo manquant."}), 400

    try:
        # The relative path has the form 'source/photo_name.jpg'.
        photo_full_path = PREPARED_DIR / photo_relative_path

        if not photo_full_path.is_file():
            return jsonify({"success": False, "message": f"Photo not found: {photo_full_path}"}), 404

        # Call the function to add the text.
        add_text_to_image(str(photo_full_path), text)
        selected_filter = load_filter_states().get(photo_relative_path, "none")
        if selected_filter not in {"none", "original", "polaroid", "postcard"}:
            apply_filter_to_image(str(photo_full_path), selected_filter, caption=text)

        # Save the text in the config file.
        texts = load_text_states()
        if text and text.strip():
            texts[photo_relative_path] = text
        else:
            texts.pop(photo_relative_path, None) # Remove the key if the text is empty.
        save_text_states(texts)

        return jsonify({"success": True, "message": "Text updated."})
    except Exception as e:
        return jsonify({"success": False, "message": f"Erreur interne du serveur : {e}"}), 500

@app.route('/api/scan_wifi', methods=['GET'])
@login_required
def scan_wifi():
    """Scan for available Wi-Fi networks and return them as JSON."""
    try:
        # --- Improvement for Pi Zero 2W ---
        # Step 1: Force a more reliable rescan.
        # This command returns no data but starts a background scan.
        # Ignore errors in case a scan is already running.
        # This is more reliable on lower-performance hardware such as the Pi Zero 2W.
        subprocess.run(['sudo', '-n', 'nmcli', 'device', 'wifi', 'rescan'], timeout=15, check=False)
        
        # Wait briefly for the scan to finish. Five seconds is a reasonable compromise.
        time.sleep(5)

        # Step 2: List the results of the scan just completed.
        cmd = ['sudo', '-n', 'nmcli', '--terse', '--fields', 'SSID,SIGNAL,SECURITY', 'dev', 'wifi', 'list']
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=10)
        
        output = result.stdout.strip()
        
        # Avoid duplicate SSIDs and keep only the strongest signal.
        seen_ssids = {}

        for line in output.split('\n'):
            if not line:
                continue
            
            # Handle SSIDs containing ':'; nmcli --terse escapes them as '\:'.
            # A simple split is insufficient, so join all but the last two parts.
            parts = line.split(':')
            if len(parts) < 3:
                continue
            
            security = parts[-1]
            signal = int(parts[-2])
            ssid = ":".join(parts[:-2]).replace('\\:', ':')

            if not ssid: # Ignore empty SSIDs (hidden networks).
                continue

            # If this SSID was already seen, keep only the entry with the strongest signal.
            if ssid not in seen_ssids or signal > seen_ssids[ssid]['signal']:
                seen_ssids[ssid] = {
                    "ssid": ssid,
                    "signal": signal,
                    "security": security if security else "Open"
                }
        
        networks = sorted(seen_ssids.values(), key=lambda x: x['signal'], reverse=True)

        return jsonify({"success": True, "networks": networks})

    except FileNotFoundError:
        return jsonify({"success": False, "message": "The 'nmcli' command was not found. Is NetworkManager installed and running?"}), 500
    except subprocess.CalledProcessError as e:
        return jsonify({"success": False, "message": f"Erreur lors du scan Wi-Fi : {e.stderr}"}), 500
    except subprocess.TimeoutExpired:
        return jsonify({"success": False, "message": "Le scan Wi-Fi a pris trop de temps (timeout)."}), 500
    except Exception as e:
        return jsonify({"success": False, "message": f"Erreur inattendue : {str(e)}"}), 500


def migrate_guest_folders():
    """Migrate the legacy 'invites' and 'invités' directories to the internal 'guests' source directory."""
    base_photos = BASE_DIR / "static" / "photos"
    base_prepared = BASE_DIR / "static" / "prepared"
    target_name = "guests"
    legacy_names = ["invites", "invités"]

    # Create target directories if they do not exist.
    (base_photos / target_name).mkdir(parents=True, exist_ok=True)
    (base_prepared / target_name).mkdir(parents=True, exist_ok=True)

    for legacy in legacy_names:
        # Migrate source photos.
        legacy_photos_dir = base_photos / legacy
        if legacy_photos_dir.exists() and legacy_photos_dir.is_dir():
            logger.info(f"[Migration] Moving photos from '{legacy}' to '{target_name}'...")
            for item in legacy_photos_dir.iterdir():
                dest = base_photos / target_name / item.name
                if not dest.exists():
                    shutil.move(str(item), str(dest))
            # Remove the source directory if it is empty.
            try:
                legacy_photos_dir.rmdir()
            except OSError:
                pass # The directory is not empty, so leave it in place.

        # Migrate prepared photos.
        legacy_prepared_dir = base_prepared / legacy
        if legacy_prepared_dir.exists() and legacy_prepared_dir.is_dir():
            logger.info(f"[Migration] Moving prepared files from '{legacy}' to '{target_name}'...")
            for item in legacy_prepared_dir.iterdir():
                dest = base_prepared / target_name / item.name
                if not dest.exists():
                    shutil.move(str(item), str(dest))
            try:
                legacy_prepared_dir.rmdir()
            except OSError:
                pass

    # Update the configuration to replace old sources with the new source.
    config = load_config()
    sources = config.get('display_sources', [])
    new_sources = set(sources)
    modified = False
    for legacy in legacy_names:
        if legacy in new_sources:
            new_sources.remove(legacy)
            new_sources.add(target_name)
            modified = True
    
    if modified:
        config['display_sources'] = list(new_sources)
        save_config(config)
        logger.info(f"[Migration] Configuration updated: sources {sources} -> {list(new_sources)}")

def log_thread_exception(args):
    logger.error("Background thread crashed: %s", args.thread.name,
                 exc_info=(args.exc_type, args.exc_value, args.exc_traceback))


def parse_cli_args():
    """Parse command-line arguments for app.py.

    ``--mode`` / ``--background`` force the run mode for this session without
    touching config.json: they set the ``PICTUREFRAME_APP_MODE`` environment
    variable, which takes precedence over the configuration everywhere
    (utils/app_mode.py) and is inherited by the child processes.
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="app.py",
        description="PictureFrame web server (slideshow / desktop background updater).")
    parser.add_argument(
        "--mode", "-m", dest="mode",
        choices=("picture_frame", "background_updater"),
        help="Force the run mode for this session: 'picture_frame' (fullscreen "
             "Pygame slideshow) or 'background_updater' (desktop wallpaper).")
    parser.add_argument(
        "--background", action="store_true",
        help="Shorthand for --mode background_updater.")
    return parser.parse_args()


def apply_forced_app_mode(args):
    """Honour the CLI mode flags before any worker or child process starts."""
    from utils.app_mode import ENV_APP_MODE
    mode = args.mode
    if args.background and not mode:
        mode = "background_updater"
    if mode:
        os.environ[ENV_APP_MODE] = mode
        logger.info("Startup: run mode forced via command line to %r", mode)
    return mode


def run_worker(target):
    logger.info("Worker entered: %s", threading.current_thread().name)
    target()
    logger.info("Worker exited: %s", threading.current_thread().name)


def log_server_readiness():
    from urllib.error import URLError
    from urllib.request import ProxyHandler, build_opener

    opener = build_opener(ProxyHandler({}))
    deadline = time.monotonic() + 30
    last_error = None
    while time.monotonic() < deadline:
        try:
            with opener.open("http://127.0.0.1:7090/api/ping", timeout=1) as response:
                if response.status == 200:
                    logger.info("HTTP server READY at http://127.0.0.1:7090 (startup %.2fs)",
                                time.monotonic() - _startup_started)
                    faulthandler.cancel_dump_traceback_later()
                    return
        except (URLError, TimeoutError, OSError) as error:
            last_error = error
        time.sleep(0.25)
    logger.error("HTTP server did not become ready within 30s: %s. See logs/startup_threads.log.",
                 last_error)


def main():
    threading.excepthook = log_thread_exception
    # CLI mode override must be applied before the scheduler and the child
    # processes read the run mode.
    apply_forced_app_mode(parse_cli_args())
    logger.info("Startup: migrating guest folders")
    migrate_guest_folders()
    logger.info("Startup: guest folder migration complete")

    # Check for git updates at startup (non-blocking, just logs a suggestion).
    try:
        from platform_utils import is_git_repo, git_has_updates
        if is_git_repo():
            has_updates, info = git_has_updates()
            if has_updates:
                count = info.get("behind_count", 0)
                logger.info("Startup: git repo is %d commit(s) behind origin. "
                           "An update is available in the Maintenance tab.", count)
            else:
                logger.info("Startup: git repo is up to date (commit %s).",
                           info.get("commit", "unknown"))
    except Exception as exc:
        logger.debug("Startup: git check skipped: %s", exc)

    for name, target in (
        ("slideshow-scheduler", schedule_worker),
    ):
        logger.info("Startup: starting worker %s", name)
        threading.Thread(name=name, target=run_worker, args=(target,), daemon=True).start()

    logger.info("Startup: binding HTTP server to 0.0.0.0:7090; local URL http://127.0.0.1:7090")
    threading.Thread(name="http-readiness", target=log_server_readiness, daemon=True).start()
    app.run(host='0.0.0.0', port=7090, use_reloader=False)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        logger.exception("Application startup or server failed")
        raise
    finally:
        faulthandler.cancel_dump_traceback_later()
        _startup_trace_file.close()
        logger.info("Application server stopped")
