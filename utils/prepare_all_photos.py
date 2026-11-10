import os
from PIL import Image, ImageFilter, ImageDraw, ImageFont, ImageOps
import json
try:
    import pillow_heif
    HEIF_SUPPORT = True
except ImportError:
    HEIF_SUPPORT = False
import subprocess, sys
from utils.config import load_config
import piexif
from utils.image_filters import create_polaroid_effect, create_postcard_effect
from utils.photo_crop import apply_crop, load_crops
import logging
import re
from pathlib import Path
from logging.handlers import RotatingFileHandler
from platform_utils import get_cancel_flag_path, get_pi_model as get_platform_pi_model

from .config_manager import load_config

# Configuration
SOURCE_DIR = "static/photos"

# Default target output resolution for prepared images
DEFAULT_OUTPUT_WIDTH = 1920
DEFAULT_OUTPUT_HEIGHT = 1080
VIDEO_EXTENSIONS = ('.mp4', '.mov', '.avi', '.mkv')

# Path to the cache of user-entered text.
USER_TEXT_MAP_CACHE_FILE = Path("cache") / "user_texts.json"

CANCEL_FLAG = get_cancel_flag_path()


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
logger = logging.getLogger("pictureframe.prepare_all_photos")

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
    '%(emoji)s🔄%(asctime)s %(message)s',
    datefmt='%d-%m %H:%M:%S'
)
file_handler.setFormatter(file_formatter)

# Add the handlers, avoiding duplicates if the module is re-imported.
if not logger.handlers:
    logger.addHandler(file_handler)

# Startup messages.
logger.debug("----------------Initializing Prepare All Photos----------------")
# Map message types to log levels.
TYPE_TO_LOGGER = {
    "progress": logger.info,
    "info": logger.info,
    "warning": logger.warning,
    "error": logger.error,
    "done": logger.info,
    "stats": logger.info,
}

def yield_and_log(msg_type: str, message: str, stage=None, percent=None, extra=None):
    """
    Build a dictionary to yield and send the corresponding log entry.
    
    Args:
        msg_type: Type de message ("progress", "info", "warning", "error", "done", "stats")
        message: The message to display.
        stage: Optional stage (e.g. "CLEANING", "PREPARING_PHOTO").
        percent: Optional progress percentage.
        extra: Optional dictionary of additional fields.
    
    Returns:
        A dictionary ready to yield with all required fields.
    """
    result = {"type": msg_type, "message": message}
    
    if stage is not None:
        result["stage"] = stage
    if percent is not None:
        result["percent"] = percent
    if extra:
        result.update(extra)
    
    # Log at the level corresponding to the message type.
    log_func = TYPE_TO_LOGGER.get(msg_type, logger.info)
    log_func(f"🔄{message}")
    
    return result



def get_pi_model():
    """Detect the Raspberry Pi model."""
    return get_platform_pi_model()

def prepare_photo(source_path, dest_path, output_width, output_height, source_type=None, caption=None, crop_selection="saved"):
    """Prepare a photo for display by resizing, applying EXIF rotation, and adding a blurred background."""
    config = load_config()
    screen_height_percent = int(config.get("screen_height_percent", "100"))
    effective_photo_height = int(output_height * (screen_height_percent / 100))
    
    try:
        # Handle HEIF/HEIC files.
        if source_path.lower().endswith(('.heic', '.heif')):
            if HEIF_SUPPORT:
                pillow_heif.register_heif_opener()
            else:
                logger.warning(f"HEIF support disabled (pillow-heif is not installed). Unable to process {source_path}")
                return None
        
        with Image.open(source_path) as source_image:
            img = ImageOps.exif_transpose(source_image)
        
        
        if crop_selection == "saved":
            crop_selection = load_crops().get(f"{source_type}/{Path(dest_path).name}")
        img = apply_crop(img, crop_selection)
        
        # Remove EXIF data after rotation
        if "exif" in img.info:
            img.info.pop("exif")
        if "icc_profile" in img.info:
            img.info.pop("icc_profile")
        
        # Convert to RGB if necessary
        if img.mode in ('RGBA', 'LA', 'P'):
            img = img.convert('RGB')
        
        # Determine if the image is portrait-like
        img_aspect_ratio = img.width / img.height
        display_area_aspect_ratio = output_width / effective_photo_height
        
        pi_model = get_pi_model()
        is_low_end = (pi_model in [1, 2, 3])
        resample_filter = Image.Resampling.BILINEAR if is_low_end else Image.Resampling.LANCZOS
        
        if img_aspect_ratio < display_area_aspect_ratio:
            # Portrait photo - add blurred background
            img_content = img.copy()
            scale = effective_photo_height / img.height
            new_width = int(img.width * scale)
            img_content = img_content.resize((new_width, effective_photo_height), resample_filter)
            
            # Create blurred background
            if is_low_end:
                # Optimized, low-memory background blur for Raspberry Pi 1, 2, 3
                bg_scale = max(160 / img.width, 90 / img.height)
                bg_new_width = int(img.width * bg_scale)
                bg_new_height = int(img.height * bg_scale)
                bg_img = img.resize((bg_new_width, bg_new_height), Image.Resampling.NEAREST)
                if bg_img.width > 160 or bg_img.height > 90:
                    left = (bg_img.width - 160) // 2
                    top = (bg_img.height - 90) // 2
                    bg_img = bg_img.crop((left, top, left + 160, top + 90))
                bg_img = bg_img.filter(ImageFilter.GaussianBlur(radius=3))
                bg_img = bg_img.resize((output_width, output_height), Image.Resampling.BILINEAR)
            else:
                bg_img = img.copy()
                bg_scale = max(output_width / img.width, output_height / img.height)
                bg_new_width = int(img.width * bg_scale)
                bg_new_height = int(img.height * bg_scale)
                bg_img = bg_img.resize((bg_new_width, bg_new_height), Image.Resampling.LANCZOS)
                if bg_img.width > output_width or bg_img.height > output_height:
                    left = (bg_img.width - output_width) // 2
                    top = (bg_img.height - output_height) // 2
                    bg_img = bg_img.crop((left, top, left + output_width, top + output_height))
                bg_img = bg_img.filter(ImageFilter.GaussianBlur(radius=50))
            
            final_img = Image.new('RGB', (output_width, output_height), (0, 0, 0))
            final_img.paste(bg_img, (0, 0))
            
            x_offset = (output_width - img_content.width) // 2
            y_offset = (output_height - img_content.height) // 2
            final_img.paste(img_content, (x_offset, y_offset))
        else:
            # Landscape or square photo
            img_content = img.copy()
            scale = effective_photo_height / img.height
            new_width = int(img.width * scale)
            img_content = img_content.resize((new_width, effective_photo_height), resample_filter)
            
            final_img = Image.new('RGB', (output_width, output_height), (0, 0, 0))
            x_offset = (output_width - img_content.width) // 2
            y_offset = (output_height - img_content.height) // 2
            final_img.paste(img_content, (x_offset, y_offset))
        
        # Prepare EXIF metadata with content coordinates
        exif_bytes_to_add = None
        try:
            exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}
            bbox_str = f"pictureframe_bbox:{x_offset},{y_offset},{img_content.width},{img_content.height}"
            exif_dict["Exif"][piexif.ExifIFD.UserComment] = bbox_str.encode('ascii')
            exif_bytes_to_add = piexif.dump(exif_dict)
        except Exception as exif_e:
            print(f"[EXIF] Warning: Unable to create metadata for {os.path.basename(source_path)}: {exif_e}")
        
        # Generate Polaroid version
        try:
            polaroid_content = create_polaroid_effect(img_content.copy())
            polaroid_final_img = final_img.copy()
            polaroid_final_img.paste(polaroid_content, (x_offset, y_offset))
            
            dest_path_obj = Path(dest_path)
            polaroid_dest_path = dest_path_obj.with_name(f"{dest_path_obj.stem}_polaroid.jpg")
            polaroid_final_img.save(polaroid_dest_path, 'JPEG', quality=90, optimize=True, exif=exif_bytes_to_add)
        except Exception as polaroid_e:
            print(f"[Polaroid] Warning: Unable to create the Polaroid version for {os.path.basename(source_path)}: {polaroid_e}")
        
        # Generate Postcard version
        try:
            postcard_img_content = img_content.copy()
            scale_factor = 0.85
            postcard_img_content.thumbnail(
                (int(output_width * scale_factor), int(output_height * scale_factor)),
                resample_filter
            )
            
            postcard_content = create_postcard_effect(postcard_img_content, caption=caption)
            postcard_final_img = final_img.copy()
            postcard_x_offset = (output_width - postcard_content.width) // 2
            postcard_y_offset = (output_height - postcard_content.height) // 2
            postcard_final_img.paste(postcard_content, (postcard_x_offset, postcard_y_offset), postcard_content)
            
            dest_path_obj = Path(dest_path)
            postcard_dest_path = dest_path_obj.with_name(f"{dest_path_obj.stem}_postcard.jpg")
            postcard_final_img.save(postcard_dest_path, 'JPEG', quality=90, optimize=True, exif=exif_bytes_to_add)
        except Exception as postcard_e:
            print(f"--- POSTCARD CREATION ERROR for {os.path.basename(source_path)} ---")
            print(f"Error details: {postcard_e}")
            print("Check that the fonts (static/fonts) and stamps (static/stamps) are present and accessible.")
            print("--------------------------------------------------------------------")
        
        # Save main prepared image
        img_to_save = final_img
        if exif_bytes_to_add:
            img_to_save.save(dest_path, 'JPEG', quality=85, optimize=True, exif=exif_bytes_to_add)
        else:
            img_to_save.save(dest_path, 'JPEG', quality=85, optimize=True)
    
    except Exception as e:
        raise Exception(f"Error processing image '{os.path.basename(source_path)}': {e}")

def prepare_video(source_path, dest_path, output_width, output_height):
    """Prepare a video for display and generate its thumbnail."""
    try:
        # --- MODIFICATION SIGALOU 29/01/2026 (2) ---
        # Improved encoding logic for Pi 4/5 and better error handling.
        encoder = 'libx264'
        encoder_params = ['-preset', 'veryfast', '-crf', '23', '-profile:v', 'high', '-level', '4.0']
        pi_model = get_pi_model()
        
        try:
            result = subprocess.run(['ffmpeg', '-encoders'], capture_output=True, text=True, check=True, timeout=20)
            available_encoders = result.stdout
            
            # Prefer the modern v4l2m2m hardware encoder on Raspberry Pi models 3, 4, and 5.
            if pi_model and 'h264_v4l2m2m' in available_encoders:
                encoder = 'h264_v4l2m2m'
                encoder_params = ['-b:v', '8M']
                print(f"[Video Prep] Raspberry Pi {pi_model} detected. Using hardware encoder: h264_v4l2m2m")
            elif pi_model and 'h264_omx' in available_encoders:
                encoder = 'h264_omx'
                encoder_params = ['-b:v', '8M']
                print(f"[Video Prep] Raspberry Pi {pi_model} detected. Using legacy hardware encoder: h264_omx")
            else:
                print("[Video Prep] No hardware encoder found; using software encoder: libx264")
        except Exception as e:
            print(f"[Video Prep] Warning: Unable to detect encoders ({e}). Using the default software encoder.")
        
        command = [
            'ffmpeg', '-i', source_path, '-vf', f"scale='min({output_width},iw)':'min({output_height},ih)':force_original_aspect_ratio=decrease,pad={output_width}:{output_height}:(ow-iw)/2:(oh-ih)/2",
            '-c:v', encoder, *encoder_params,
            '-pix_fmt', 'yuv420p',  # Improve compatibility.
            '-c:a', 'aac', '-b:a', '128k',
            '-y', dest_path
        ]
        
        result = subprocess.run(command, check=False, capture_output=True, text=True, encoding='utf-8')
        
        if result.returncode != 0:
            raise Exception(f"ffmpeg failed with code {result.returncode}. Error: {result.stderr.strip()}")
    
    except Exception as video_e:
        raise Exception(f"Error processing video '{os.path.basename(source_path)}': {video_e}")
    
    # Generate thumbnail
    try:
        dest_path_obj = Path(dest_path)
        thumbnail_path = dest_path_obj.with_name(f"{dest_path_obj.stem}_thumbnail.jpg")
        thumb_command = [
            'ffmpeg', '-i', source_path, '-ss', '00:00:01.000', '-vframes', '1', '-q:v', '2', str(thumbnail_path), '-y'
        ]
        subprocess.run(thumb_command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as thumb_e:
        print(f"[Thumbnail] Warning: Unable to create thumbnail for {os.path.basename(source_path)}: {thumb_e}")

def prepare_all_photos_with_progress(screen_width=None, screen_height=None, source_type="unknown", description_map=None):
    """Prepare photos and return structured objects for tracking."""
    if description_map is None:
        description_map = {}
    
    # Load the text entered by the user.
    user_text_map = {}
    if USER_TEXT_MAP_CACHE_FILE.exists():
        try:
            with open(USER_TEXT_MAP_CACHE_FILE, 'r', encoding='utf-8') as f:
                user_text_map = json.load(f)
        except (json.JSONDecodeError, IOError):
            print(f"Warning: Unable to load user text file {USER_TEXT_MAP_CACHE_FILE}")
    
    actual_output_width = screen_width if screen_width is not None else DEFAULT_OUTPUT_WIDTH
    actual_output_height = screen_height if screen_height is not None else DEFAULT_OUTPUT_HEIGHT
    
    SOURCE_DIR_FOR_PREP = Path("static") / "photos" / source_type
    PREPARED_SOURCE_DIR = Path("static") / "prepared" / source_type
    
    if not SOURCE_DIR_FOR_PREP.is_dir():
        yield yield_and_log("error", f"Source directory '{SOURCE_DIR_FOR_PREP}' does not exist.")
        return
    
    PREPARED_SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    
    # Smart synchronization logic
    source_files = {f: os.path.splitext(f)[0] for f in os.listdir(SOURCE_DIR_FOR_PREP) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.heic', '.heif') + VIDEO_EXTENSIONS)}
    source_basenames = set(source_files.values())
    
    # Reliably detect already-prepared basenames (non-empty and at least as recent as the source).
    prepared_basenames = set()
    if PREPARED_SOURCE_DIR.exists():
        for filename, basename in source_files.items():
            ext = ".mp4" if filename.lower().endswith(VIDEO_EXTENSIONS) else ".jpg"
            prep_path = PREPARED_SOURCE_DIR / f"{basename}{ext}"
            src_path = SOURCE_DIR_FOR_PREP / filename
            
            # Robust checks:
            # 1. The main prepared file exists.
            # 2. Its size is greater than 0 bytes (not corrupted or truncated during import).
            # 3. It is at least as recent as the source photo.
            try:
                if prep_path.is_file() and prep_path.stat().st_size > 0:
                    prepared_basenames.add(basename)
            except Exception:
                pass  # If stat data cannot be read, treat it as unprepared for safety.

    # Get all basenames currently present on disk in prepared/.
    all_prepared_basenames_on_disk = set()
    if PREPARED_SOURCE_DIR.exists():
        for f in PREPARED_SOURCE_DIR.iterdir():
            if f.is_file():
                base = re.sub(r'(_polaroid|_postcard|_thumbnail)$', '', f.stem)
                all_prepared_basenames_on_disk.add(base)
    
    # Delete obsolete media (except for smartphone source)
    basenames_to_delete = set()
    if source_type != "smartphone":
        basenames_to_delete = all_prepared_basenames_on_disk - source_basenames
    
    if basenames_to_delete:
        yield yield_and_log(
            "progress",
            f"Suppression de {len(basenames_to_delete)} médias obsolètes...",
            stage="CLEANING",
            percent=25
        )
        
        for basename in basenames_to_delete:
            for file_to_delete in PREPARED_SOURCE_DIR.glob(f"{basename}*"):
                try:
                    if file_to_delete.is_file():
                        file_to_delete.unlink()
                except OSError as e:
                    yield yield_and_log("warning", f"Unable to delete {file_to_delete.name}: {e}")
            
            backup_dir = PREPARED_SOURCE_DIR.parent.parent / '.backups' / source_type
            if backup_dir.exists():
                for backup_file_to_delete in backup_dir.glob(f"{basename}*"):
                    if backup_file_to_delete.is_file():
                        backup_file_to_delete.unlink()
    
    # Determine files to prepare (new ones)
    basenames_to_prepare = source_basenames - prepared_basenames
    files_to_prepare = [f for f, basename in source_files.items() if basename in basenames_to_prepare]
    total = len(files_to_prepare)
    
    if total == 0:
        yield yield_and_log("info", "No new photos to prepare. The directory is up to date.")
        yield yield_and_log(
            "done",
            "No new photos to prepare.",
            stage="PREPARING_COMPLETE",
            percent=100
        )
        return
    
    yield yield_and_log(
        "stats",
        f"Starting preparation of {total} new photos...",
        stage="PREPARING_START",
        percent=22,
        extra={"total": total}
    )
    
    for i, filename in enumerate(files_to_prepare, start=1):
        # Check for cancellation
        if CANCEL_FLAG.exists():
            yield yield_and_log("warning", "Preparation cancelled by the user.")
            return
        
        src_path = os.path.join(SOURCE_DIR_FOR_PREP, filename)
        
        try:
            base_name, extension = os.path.splitext(filename)
            current_preview = ""
            
            if extension.lower() in VIDEO_EXTENSIONS:
                # Video processing
                dest_filename = f"{base_name}.mp4"
                dest_path = PREPARED_SOURCE_DIR / dest_filename
                prepare_video(src_path, str(dest_path), actual_output_width, actual_output_height)
                message_type = "video"
                current_preview = f"{base_name}_thumbnail.jpg"
            else:
                # Image processing
                dest_filename = f"{base_name}.jpg"
                dest_path = PREPARED_SOURCE_DIR / dest_filename
                relative_path_key = f"{source_type}/{dest_filename}"
                
                # Sigalou change 2026-01-25: use JSON metadata only.
                # Priority 1: User text
                caption = user_text_map.get(relative_path_key)
                
                # Cached descriptions are used only when there is no user text.
                if caption is None:
                    cached_data = description_map.get(filename)
                    if cached_data and isinstance(cached_data, dict):
                        caption = cached_data.get("description")
                    elif isinstance(cached_data, str):
                        caption = cached_data
                # Fin Modification Sigalou 25/01/2026
                
                prepare_photo(src_path, str(dest_path), actual_output_width, actual_output_height, source_type=source_type, caption=caption)
                message_type = "photo"
                current_preview = f"{base_name}.jpg"
            
            if i == 1:
                percent = 25  # Sigalou change: start the loop after 21% cleanup.
            else:
                percent = 25 + int(((i - 1) / total) * 75)  # Sigalou change: progress from 25% to 100%.
            
            yield yield_and_log(
                "progress",
                f"New media prepared ({message_type}): {filename} ({i}/{total})",
                stage="PREPARING_PHOTO",
                percent=percent,
                extra={"current": i, "total": total, "current_photo_path": current_preview}
            )
        
        except Exception as e:
            yield yield_and_log("warning", f"Error preparing {filename}: {e}")
    
    yield yield_and_log(
        "done",
        "Preparation of new photos complete.",
        stage="PREPARING_COMPLETE",
        percent=100
    )

def prepare_all_photos(status_callback=None):
    """Original callback-based version, retained for compatibility."""
    for update in prepare_all_photos_with_progress():
        message = update.get("message", str(update))
        if status_callback:
            status_callback(message)
        else:
            print(message)

if __name__ == "__main__":
    print("Testing photo preparation...")
    prepare_all_photos()
    print("Done!")