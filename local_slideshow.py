import os
if __name__ == "__main__" and os.name == "nt":
    import truststore
    truststore.inject_into_ssl()

import random
import time
os.environ["PYGAME_BLEND_ALPHA_SDL2"] = "1"
import pygame
import traceback
import requests
from PIL import Image, ImageOps, ImageFilter, ImageDraw
import signal
import re
import socket
import subprocess, sys
import glob
import collections
import math
import queue
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import json
import qrcode
import psutil
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from utils.text_drawer import draw_text_with_outline
from utils.metadata_utils import get_photo_metadata, load_photo_metadata_cache, format_photo_metadata
from utils.config_manager import load_config
from utils.country_flags import country_flags
from utils.slideshow_fonts import load_font, clear_font_cache
from utils.weather_cities import get_city, WEATHER_TIMEZONE
from platform_utils import (
    IS_LINUX,
    consume_slideshow_commands,
    get_default_font_path,
    get_pygame_display_flags,
    get_pygame_display_size,
    get_status_file,
    get_pi_model as get_platform_pi_model,
)

# Minimal helper for extracting translations (PyBabel).
def _(text, **kwargs):
    try:
        return text % kwargs if kwargs else text
    except (KeyError, TypeError, ValueError):
        return text

# Define paths.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PREPARED_BASE_DIR = Path(BASE_DIR) / 'static' / 'prepared'
STATUS_FILE = str(get_status_file("pictureframe_slideshow_status.json"))
SOUNDS_DIR = Path(BASE_DIR) / 'static' / 'sounds'
CUSTOM_PLAYLIST_FILE = str(get_status_file("pictureframe_custom_playlist.json"))
ICONS_DIR = Path(BASE_DIR) / 'static' / 'icons'
CURRENT_PHOTO_FILE = str(get_status_file("pictureframe_current_photo.txt"))
CONFIG_PATH = os.path.join(BASE_DIR, 'config', 'config.json')
FAVORITES_PATH = os.path.join(BASE_DIR, 'config', 'favorites.json')
FILTER_STATES_PATH = os.path.join(BASE_DIR, 'config', 'filter_states.json')
TIDES_CACHE_FILE = Path(BASE_DIR) / 'cache' / 'tides.json'
MPV_LOG_FILE = get_status_file("mpv_pictureframe.log")
_icon_cache = {} # Cache for loaded weather icons.

# --- Global variables for slideshow control ---
paused = False
next_photo_requested = False
previous_photo_requested = False

# Internal state for the status file.
_current_status = {"paused": False, "is_custom": False}

_current_background_music = None # Resume after a video.
# Paths and cache for ISO 3166 country codes (flags).
COUNTRY_CODES_PATH = Path(BASE_DIR) / 'static' / 'flags' / 'country_codes.json'
_country_codes_cache = None  # Loaded once and cached.

LOGS_DIR = Path(__file__).resolve().parent / "logs"
LOGS_DIR.mkdir(exist_ok=True)

class EmojiFormatter(logging.Formatter):
    """Format log records with an emoji based on their severity."""
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

config = load_config()

file_handler = RotatingFileHandler(
    LOGS_DIR / "pictureframe.log",
    maxBytes=10 * 1024 * 1024,
    backupCount=3,
    encoding="utf-8"
)
level_name = config.get("level_log", "INFO")
level = getattr(logging, level_name.upper(), logging.INFO)

file_handler.setLevel(level)

file_formatter = EmojiFormatter(
    '%(emoji)s🟦%(asctime)s %(message)s',
    datefmt='%d-%m %H:%M:%S'
)
file_handler.setFormatter(file_formatter)

logging.basicConfig(
    level=level,  # niveau global
    handlers=[file_handler, logging.StreamHandler()],
    force=True
)

logger = logging.getLogger(__name__)

def button_callback(channel):
    """Callback run when the button is pressed."""
    logger.info(f"Physical button pressed (GPIO {channel}). Toggling sleep...")
    try:
        # Call the web application API to toggle the slideshow state.
        requests.post("http://127.0.0.1:7090/api/slideshow/toggle_sleep", timeout=5)
    except requests.RequestException as e:
        logger.error(f"Unable to contact the API to enter sleep mode: {e}")


# Startup messages.
logger.debug("----------------Initialisation local_Slideshow  ----------------")



def load_country_codes():
    """Load the ISO-to-country-name mapping for reverse lookups."""
    global _country_codes_cache
    if _country_codes_cache is None:
        try:
            with open(COUNTRY_CODES_PATH, 'r', encoding='utf-8') as f:
                codes = json.load(f)
                # Reverse mapping: country name → ISO code (e.g. "France" → "fr").
                _country_codes_cache = {name.lower(): iso for iso, name in codes.items()}
        except FileNotFoundError:
            logger.info(f"⚠️  country_codes.json manquant dans config/")
            _country_codes_cache = {}
        except Exception as e:
            logger.info(f"❌ Error loading country_codes.json: {e}")
            _country_codes_cache = {}
    return _country_codes_cache

def update_status_file(new_fields):
    """Update the JSON status file while preserving other fields."""
    global _current_status
    _current_status.update(new_fields)
    try:
        with open(STATUS_FILE, "w") as f:
            json.dump(_current_status, f)
    except IOError as e:
        logger.info(f"Error writing status file: {e}")

def signal_handler_next(signum, frame):
    global next_photo_requested, previous_photo_requested
    next_photo_requested = True
    previous_photo_requested = False

def signal_handler_previous(signum, frame):
    global next_photo_requested, previous_photo_requested
    previous_photo_requested = True
    next_photo_requested = False

def signal_handler_pause_toggle(signum, frame):
    global paused
    paused = not paused
    update_status_file({"paused": paused})

def handle_platform_commands():
    """Apply queued controls on platforms that do not support POSIX signals."""
    global next_photo_requested, previous_photo_requested
    for command in consume_slideshow_commands():
        if command == "next":
            signal_handler_next(None, None)
        elif command == "previous":
            signal_handler_previous(None, None)
        elif command == "toggle_pause":
            signal_handler_pause_toggle(None, None)

# NEW FUNCTION TO HANDLE EVENTS (QUIT, TOUCH)
def handle_slideshow_events(screen_width):
    """Handle window, keyboard and touch controls."""
    global paused, next_photo_requested, previous_photo_requested
    if not IS_LINUX:
        handle_platform_commands()
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            pygame.quit()
            sys.exit()
        elif event.type == pygame.KEYDOWN:
            from utils import slideshow_controls
            if event.key in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_SPACE):
                slideshow_controls.reveal()
                if event.key == pygame.K_LEFT:
                    signal_handler_previous(None, None)
                elif event.key == pygame.K_RIGHT:
                    signal_handler_next(None, None)
                elif not getattr(event, "repeat", False):
                    signal_handler_pause_toggle(None, None)
        # --- NEW: Handle touch controls ---
        elif event.type in (pygame.MOUSEBUTTONDOWN, pygame.FINGERDOWN):
            from utils import slideshow_controls
            surface = pygame.display.get_surface()
            if surface is None:
                continue
            height = surface.get_height()
            if event.type == pygame.FINGERDOWN:
                pos = (event.x * screen_width, event.y * height)
            elif event.button == 1 and not getattr(event, "touch", False):
                pos = event.pos
            else:
                continue
            action = slideshow_controls.click(pos, screen_width, height)
            if action == "previous":
                signal_handler_previous(None, None)
            elif action == "next":
                signal_handler_next(None, None)
            elif action == "pause":
                signal_handler_pause_toggle(None, None)

def play_background_music(filename):
    """Load and play background music in a loop."""
    if not filename: return
    music_path = Path(BASE_DIR) / 'static' / 'music' / filename
    if music_path.exists():
        try:
            if not pygame.mixer.get_init(): pygame.mixer.init()
            pygame.mixer.music.load(str(music_path))
            pygame.mixer.music.play(-1) # -1 loops indefinitely.
            logger.info(f"🎵 Background music started: {filename}")
        except Exception as e:
            logger.error(f"❌ Error reading music: {e}")

VIDEO_EXTENSIONS = ('.mp4', '.mov', '.avi', '.mkv')

def reinit_pygame():
    """Completely quit and reset Pygame and its associated resources."""
    logger.debug("📸 Fully resetting Pygame...")
    pygame.quit()
    pygame.display.init()
    pygame.font.init()
    clear_font_cache()

    global _icon_cache
    _icon_cache = {}
    logger.debug("📸 Weather icon cache cleared.")

    info = pygame.display.Info()
    width, height = info.current_w, info.current_h
    if not IS_LINUX:
        width, height = get_pygame_display_size()
    screen = pygame.display.set_mode((width, height), get_pygame_display_flags())
    pygame.mouse.set_visible(False)
    logger.debug(f"📸 Pygame fully reset to {width}x{height}.")
    return screen, width, height

def load_filter_states():
    """Load filter states from a JSON file."""
    if not os.path.exists(FILTER_STATES_PATH):
        return {}
    try:
        with open(FILTER_STATES_PATH, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        logger.info(f"Warning: Unable to read filter state file '{FILTER_STATES_PATH}'.")
        return {}

def load_favorites():
    """Load the favorites list and return it as a set for fast lookups."""
    if not os.path.exists(FAVORITES_PATH):
        return set()
    try:
        with open(FAVORITES_PATH, 'r') as f:
            # Expect a list of paths in the JSON.
            favorites_list = json.load(f)
            if isinstance(favorites_list, list):
                return set(favorites_list)
            else:
                logger.info(f"Warning: Favorites file '{FAVORITES_PATH}' does not contain a list. It will be ignored.")
                return set()
    except (json.JSONDecodeError, IOError):
        logger.info(f"Warning: Unable to read favorites file '{FAVORITES_PATH}'.")
        return set()

def get_local_ip():
    """Robustly retrieve the machine's local IP address."""
    # Method 1: Use `hostname -I` (more reliable on Linux/RPi).
    try:
        result = subprocess.run(
            ['hostname', '-I'],
            capture_output=True, text=True, check=True, timeout=2
        )
        # Take the first IP address in the list.
        ip = result.stdout.strip().split()[0]
        if ip:
            return ip
    except (FileNotFoundError, subprocess.CalledProcessError, IndexError, subprocess.TimeoutExpired):
        pass # The command failed; try the next method.

    # Method 2: Socket method (fallback).
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # This IP does not need to be reachable.
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "xxx.xxx.xxx.xxx" # Fallback
    finally:
        s.close()
    return ip

# NEW FUNCTION
def get_pi_model():
    """Detect the Raspberry Pi model for optimal video decoding."""
    return get_platform_pi_model()

# Helper function to parse hex colors (including alpha)
def parse_color(hex_color):
    hex_color = str(hex_color).lstrip('#')
    if len(hex_color) == 6: # RRGGBB
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    elif len(hex_color) == 8: # RRGGBBAA
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4, 6))
    else:
        return (255, 255, 255) # Default to white if invalid

def fit_photo_to_screen(pil_image, screen_width, screen_height):
    """Fit a photo onto a centered screen-sized canvas without distortion."""
    fitted_image = pil_image.convert('RGB')
    fitted_image.thumbnail((screen_width, screen_height), Image.Resampling.LANCZOS)
    canvas = Image.new('RGB', (screen_width, screen_height), (0, 0, 0))
    canvas.paste(fitted_image, (
        (screen_width - fitted_image.width) // 2,
        (screen_height - fitted_image.height) // 2,
    ))
    return canvas


def prepare_pan_zoom(pil_image, screen_width, screen_height, config):
    start_zoom = max(0.01, float(config.get("pan_zoom_start_factor", 1.0)))
    zoom_factor = max(1.0, float(config.get("pan_zoom_factor", 1.15)))

    def edge_point():
        edge = random.choice(("top", "bottom", "left", "right"))
        if edge == "top":
            return random.random(), 0.0
        if edge == "bottom":
            return random.random(), 1.0
        if edge == "left":
            return 0.0, random.random()
        return 1.0, random.random()

    start = edge_point()
    end = edge_point()
    if end == start:
        end = (1.0 - start[0], 1.0 - start[1])
    return pil_image, start, end, start_zoom, zoom_factor


def render_pan_zoom_frame(base_surface, screen_width, screen_height, start_offset, end_offset, start_zoom, end_zoom, progress):
    zoom = start_zoom + (end_zoom - start_zoom) * progress
    width = max(1, int(screen_width * zoom))
    height = max(1, int(screen_height * zoom))
    scaled = pygame.transform.smoothscale(base_surface, (width, height))
    if width < screen_width or height < screen_height:
        frame = pygame.Surface((screen_width, screen_height)).convert()
        frame.fill((0, 0, 0))
        frame.blit(scaled, ((screen_width - width) // 2, (screen_height - height) // 2))
        return frame
    x_fraction = start_offset[0] + (end_offset[0] - start_offset[0]) * progress
    y_fraction = start_offset[1] + (end_offset[1] - start_offset[1]) * progress
    x = int(x_fraction * (width - screen_width))
    y = int(y_fraction * (height - screen_height))
    return scaled.subsurface((x, y, screen_width, screen_height))


def read_slideshow_photo(photo_path, screen_width, screen_height):
    with Image.open(photo_path) as image:
        return fit_photo_to_screen(image, screen_width, screen_height)


def load_slideshow_photo(screen, photo_path, screen_width, screen_height, loader):
    """Keep processing navigation while the worker decodes and resizes a photo."""
    future = loader.submit(read_slideshow_photo, photo_path, screen_width, screen_height)
    background = screen.copy()
    clock = pygame.time.Clock()
    try:
        while True:
            handle_slideshow_events(screen_width)
            if next_photo_requested or previous_photo_requested:
                return None
            if future.done():
                return future.result()
            screen.blit(background, (0, 0))
            draw_pause_icon(screen, screen_width, screen_height)
            pygame.display.flip()
            clock.tick(60)
    finally:
        if not future.cancel() and (next_photo_requested or previous_photo_requested):
            def report_discarded_load(completed):
                error = completed.exception()
                if error is not None:
                    logger.error("Skipped photo failed to load: %s", photo_path,
                                 exc_info=(type(error), error, error.__traceback__))
            future.add_done_callback(report_discarded_load)


# New function to perform a transition between two images
def perform_transition(screen, old_image_surface, new_image_path, duration, screen_width, screen_height, main_font, config, transition_type, initial_image=None, prepared_image=None):
    if transition_type == "random":
        transition_type = random.choice(("fade", "slide_left", "slide_right", "slide_up", "slide_down"))
    clock = pygame.time.Clock()
    fps_config = config.get("transition_fps", "auto")
    if fps_config == "30":
        fps = 30
    elif fps_config == "60":
        fps = 60
    else: # "auto"
        fps = 30 if get_pi_model() in [1, 2, 3] else 60
    num_frames = int(duration * fps)
    if num_frames == 0: # Avoid division by zero if duration is too small
        num_frames = 1

    # Load and prepare new image
    try:
        new_pil_image = (prepared_image if prepared_image is not None
                         else read_slideshow_photo(new_image_path, screen_width, screen_height))
    except (FileNotFoundError, Image.UnidentifiedImageError) as e:
        logger.info(f"[Transition] ERREUR: Impossible de charger l'image '{new_image_path}': {e}")
        return None # Return None to indicate failure.
    transition_image = initial_image if initial_image is not None else new_pil_image
    new_surface_scaled = pygame.image.fromstring(
        transition_image.tobytes(), transition_image.size, transition_image.mode
    ).convert()

    # Get metadata for the image currently being transitioned.
    photo_metadata = get_photo_metadata(new_image_path)

    # Pre-render the overlay instead of redrawing it each frame (performance optimization).
    overlay_surface = pygame.Surface((screen_width, screen_height), pygame.SRCALPHA)
    draw_overlay(overlay_surface, screen_width, screen_height, config, main_font, photo_metadata)

    # Pi 1, 2, 3 downscaling optimization for transitions
    is_low_end_pi = (get_pi_model() in [1, 2, 3])
    if is_low_end_pi:
        small_width, small_height = screen_width // 2, screen_height // 2
        old_image_small = pygame.transform.scale(old_image_surface, (small_width, small_height)).convert()
        new_surface_small = pygame.transform.scale(new_surface_scaled, (small_width, small_height)).convert()
        temp_surface_small = pygame.Surface((small_width, small_height)).convert()

    i = 0
    while i <= num_frames:
        handle_slideshow_events(screen_width)
        if next_photo_requested or previous_photo_requested:
            return new_pil_image
        progress = i / num_frames # 0.0 to 1.0

        if transition_type == "fade":
            alpha = int(255 * progress)
            if is_low_end_pi:
                new_surface_small.set_alpha(alpha)
                temp_surface_small.blit(old_image_small, (0, 0))
                temp_surface_small.blit(new_surface_small, (0, 0))
                pygame.transform.scale(temp_surface_small, (screen_width, screen_height), screen)
            else:
                # Major optimization: modify alpha directly on the original surface without making a costly copy.
                new_surface_scaled.set_alpha(alpha)
                screen.blit(old_image_surface, (0, 0))
                screen.blit(new_surface_scaled, (0, 0))
        elif transition_type.startswith("slide_"):
            # Determine slide direction
            direction = transition_type.split("_")[1]
            
            # Calculate offset for the new image
            offset_x, offset_y = 0, 0
            if direction == "left":
                offset_x = int(screen_width * (1 - progress)) # New image starts off-screen right, slides left
            elif direction == "right":
                offset_x = int(-screen_width * (1 - progress)) # New image starts off-screen left, slides right
            elif direction == "up":
                offset_y = int(screen_height * (1 - progress)) # New image starts off-screen bottom, slides up
            elif direction == "down":
                offset_y = int(-screen_height * (1 - progress)) # New image starts off-screen top, slides down
            
            screen.blit(old_image_surface, (0, 0)) # Draw old image first
            screen.blit(new_surface_scaled, (offset_x, offset_y)) # Draw new image sliding in
        else: # Fallback to fade if unknown type
            screen.blit(old_image_surface, (0, 0))
            screen.blit(new_surface_scaled, (0, 0)) # Just blit new image directly
        
        # Draw overlay during transition
        screen.blit(overlay_surface, (0, 0))
        draw_pause_icon(screen, screen_width, screen_height)

        pygame.display.flip()
        clock.tick(fps)
        if not paused:
            i += 1

    # Ensure the new image is fully blitted at the end of the transition
    screen.blit(new_surface_scaled, (0, 0))
    draw_overlay(screen, screen_width, screen_height, config, main_font, photo_metadata)
    draw_pause_icon(screen, screen_width, screen_height)
    pygame.display.flip()

    return new_pil_image

# Check whether the current time is within the active hours.
def is_within_active_hours(config):
    now = datetime.now()
    try:
        if now.weekday() in (4, 5):
            start = config.get("active_start_weekend", config.get("active_start", "07:00"))
            end = config.get("active_end_weekend", config.get("active_end", "22:00"))
        else:
            start = config.get("active_start_weekday", config.get("active_start", "07:00"))
            end = config.get("active_end_weekday", config.get("active_end", "22:00"))
            
        start_time = datetime.strptime(start, "%H:%M").time()
        end_time = datetime.strptime(end, "%H:%M").time()
        now_time = now.time()
    except Exception as e:
        logger.info(f"Schedule format error: {e}")
        return True

    if start_time <= end_time:
        return start_time <= now_time <= end_time
    else:
        return now_time >= start_time or now_time <= end_time

# --- Weather handling ---
_weather_and_forecast_data = None
_last_weather_and_forecast_fetch = None
_weather_warning_printed = False
_last_weather_city = None
_last_weather_units = None

WMO_ICON_MAP = {
    0: "01", 1: "02", 2: "03", 3: "04",
    45: "50", 48: "50",
    51: "09", 53: "09", 55: "09", 56: "09", 57: "09",
    61: "10", 63: "10", 65: "10", 66: "10", 67: "10",
    71: "13", 73: "13", 75: "13", 77: "13",
    80: "09", 81: "09", 82: "09", 85: "13", 86: "13",
    95: "11", 96: "11", 99: "11",
}

WMO_DESCRIPTIONS = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Rime fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Dense drizzle",
    56: "Freezing drizzle", 57: "Dense freezing drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain",
    66: "Freezing rain", 67: "Heavy freezing rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Light showers", 81: "Showers", 82: "Violent showers",
    85: "Snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with hail",
    99: "Thunderstorm with heavy hail",
}


def _wmo_icon(code, is_day=True):
    """Map a WMO weather code to an existing weather icon filename."""
    return WMO_ICON_MAP.get(code, "01") + ("d" if is_day else "n")


def get_weather_and_forecast(config):
    """Fetch current weather and a five-day forecast from Open-Meteo."""
    global _weather_and_forecast_data, _last_weather_and_forecast_fetch
    global _weather_warning_printed, _last_weather_city, _last_weather_units

    city_name = config.get("weather_city")
    city = get_city(city_name)
    units = config.get("weather_units", "metric")
    try:
        interval_minutes = int(config.get("weather_update_interval_minutes", 30))
    except (ValueError, TypeError):
        interval_minutes = 30

    if not city:
        if not _weather_warning_printed:
            logger.info("[Weather] Unknown or missing city '%s'. Weather is disabled.", city_name)
            _weather_warning_printed = True
        return None

    now = datetime.now()
    if (
        city_name == _last_weather_city
        and units == _last_weather_units
        and _last_weather_and_forecast_fetch
        and (now - _last_weather_and_forecast_fetch).total_seconds() < interval_minutes * 60
    ):
        return _weather_and_forecast_data

    if city_name != _last_weather_city or units != _last_weather_units:
        _weather_and_forecast_data = None
    logger.info("[Weather] Fetching weather forecast...")
    _last_weather_and_forecast_fetch = now
    _last_weather_city = city_name
    _last_weather_units = units

    try:
        params = {
            "latitude": city["lat"],
            "longitude": city["lon"],
            "current": "temperature_2m,wind_speed_10m,precipitation,weather_code,is_day",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weather_code",
            "timezone": WEATHER_TIMEZONE,
            "forecast_days": 5,
        }
        imperial = units == "imperial"
        if imperial:
            params["temperature_unit"] = "fahrenheit"
            params["wind_speed_unit"] = "mph"
        response = requests.get(
            "https://api.open-meteo.com/v1/forecast", params=params, timeout=10)
        response.raise_for_status()
        api_data = response.json()

        current = api_data["current"]
        current_code = current.get("weather_code", 0)
        current_weather = {
            "city": city_name,
            "weather": [{
                "icon": _wmo_icon(current_code, bool(current.get("is_day", 1))),
                "description": WMO_DESCRIPTIONS.get(current_code, "Unknown"),
            }],
            "main": {"temp": current.get("temperature_2m")},
            "wind_speed": current.get("wind_speed_10m"),
            "precipitation": current.get("precipitation"),
            "units": {
                "temperature": "°F" if imperial else "°C",
                "wind_speed": "mph" if imperial else "km/h",
            },
        }

        # Show the five daily entries returned by Open-Meteo.
        processed_forecast = []
        daily = api_data["daily"]
        weekdays = (
            "Monday", "Tuesday", "Wednesday", "Thursday",
            "Friday", "Saturday", "Sunday",
        )
        for index, (date, maximum, minimum, precipitation, code) in enumerate(zip(
            daily["time"],
            daily["temperature_2m_max"],
            daily["temperature_2m_min"],
            daily["precipitation_sum"],
            daily["weather_code"],
        )):
            if index == 5:
                break
            day_name = (
                "Today" if index == 0
                else "Tomorrow" if index == 1
                else weekdays[datetime.strptime(date, "%Y-%m-%d").weekday()]
            )
            processed_forecast.append({
                "day": day_name,
                "min_temp": round(minimum),
                "max_temp": round(maximum),
                "icon": _wmo_icon(code),
                "description": WMO_DESCRIPTIONS.get(code, "Unknown"),
                "precipitation": precipitation,
            })

        _weather_and_forecast_data = {
            "current": current_weather,
            "forecast": processed_forecast,
        }
        logger.info("[Weather] Weather and forecast updated for %s.", city_name)
        return _weather_and_forecast_data

    except requests.exceptions.RequestException as e:
        logger.info(f"[Weather] Network error retrieving forecast: {e}")
        return None
    except Exception as e:
        logger.info(f"[Weather] General error retrieving forecast: {e}")
        traceback.print_exc()
        return None

# --- Tide handling ---
_tides_data = None
_last_tides_fetch = None
_tides_warning_printed = False

def get_tides(config):
    """Get the next high and low tides using in-memory and persistent file caches."""
    global _tides_data, _last_tides_fetch, _tides_warning_printed
    api_key = config.get("stormglass_api_key")
    lat = config.get("tide_latitude")
    lon = config.get("tide_longitude")
    # Cache for 12 hours to limit API calls to at most two per day.
    cache_duration_seconds = 12 * 3600

    if not all([api_key, lat, lon]):
        if not _tides_warning_printed:
            logger.info("[Tides] StormGlass API key, latitude, or longitude missing. Tides are disabled.")
            _tides_warning_printed = True
        return None

    # 1. Check the in-memory cache first.
    now = datetime.now()
    if _last_tides_fetch and (now - _last_tides_fetch).total_seconds() < cache_duration_seconds:
        return _tides_data

    # 2. The in-memory cache has expired; check the file cache.
    TIDES_CACHE_FILE.parent.mkdir(exist_ok=True)
    if TIDES_CACHE_FILE.exists():
        try:
            with open(TIDES_CACHE_FILE, 'r') as f:
                cache_content = json.load(f)
            
            last_file_fetch_dt = datetime.fromisoformat(cache_content['timestamp'])
            
            if (now - last_file_fetch_dt).total_seconds() < cache_duration_seconds:
                # If this is a cooldown entry, do nothing and wait.
                if cache_content.get('cooldown'):
                    logger.info("[Tides] API cooldown active from file cache.")
                    _last_tides_fetch = now # Update the in-memory timer to respect the cooldown.
                    _tides_data = None
                    return None

                tide_data_from_cache = cache_content.get('data')

                # --- NEW: Check the cache format for backward compatibility ---
                if isinstance(tide_data_from_cache, list):
                    logger.info("[Tides] Valid tide data (list format) found in file cache.")
                    _tides_data = tide_data_from_cache
                    _last_tides_fetch = now
                    return tide_data_from_cache
                else:
                    logger.info("[Tides] Legacy cache format (dictionary) detected. Cache will be invalidated and recreated.")
                    # Continue execution so the API can be called.
        except Exception as e:
            logger.info(f"[Tides] Error reading file cache; fetching from API. Error: {e}")

    # 3. Both caches are invalid; call the API.
    logger.info("[Tides] Fetching tide data from the StormGlass API...")
    _last_tides_fetch = now # Update this to avoid repeated calls after a failure.

    try:
        start_time_utc = datetime.utcnow()
        end_time_utc = start_time_utc + timedelta(days=7) # --- CHANGE: Retrieve 7 days of data ---

        headers = {'Authorization': api_key}
        params = {'lat': lat, 'lng': lon, 'start': start_time_utc.isoformat(), 'end': end_time_utc.isoformat()}
        
        response = requests.get('https://api.stormglass.io/v2/tide/extremes/point', params=params, headers=headers, timeout=15)
        response.raise_for_status()
        extremes_data = response.json().get('data', [])

        # Keep only future tides.
        now_utc = datetime.utcnow().replace(tzinfo=None)
        future_extremes = [e for e in extremes_data if datetime.fromisoformat(e['time'].replace('Z', '+00:00')).replace(tzinfo=None) > now_utc]

        if not future_extremes:
            logger.info("[Tides] No future tides found in the API data for the next 24 hours.")
            return None

        # Save the full list of future tides to the cache.
        data_to_cache = {'data': future_extremes, 'timestamp': datetime.now().isoformat()}
        
        with open(TIDES_CACHE_FILE, 'w') as f:
            json.dump(data_to_cache, f, indent=2)
        
        logger.info("[Tides] Tide data updated and cache saved.")
        # --- FIX: Update the in-memory cache before returning ---
        _tides_data = future_extremes
        return _tides_data
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 402:
            logger.info("[Tides] ERROR: StormGlass API quota exceeded. Retrying in 12 hours.")
            # Write a cooldown timestamp to the cache to avoid retries after a restart.
            cooldown_data = {'data': {}, 'timestamp': datetime.now().isoformat(), 'cooldown': True}
            try:
                with open(TIDES_CACHE_FILE, 'w') as f:
                    json.dump(cooldown_data, f, indent=2)
                logger.info("[Tides] Cooldown timestamp written to file cache.")
            except Exception as write_e:
                logger.info(f"[Tides] Unable to write cooldown to file cache: {write_e}")
        else:
            logger.info(f"[Tides] HTTP error retrieving tides: {e}")
        _tides_data = None
        return None
    except Exception as e:
        logger.info(f"[Tides] General error retrieving tides: {e}")
        traceback.print_exc()
        _tides_data = None # Clear the in-memory cache to force another attempt.
        return None

def load_icon(icon_name, size, is_weather_icon=True):
    """
    Load an icon, cache it, and return it as a Pygame surface.
    Return a red square on failure for visual debugging.
    """
    if size <= 0:
        logger.info(f"[Display] WARNING: Invalid icon size ({size}px) for '{icon_name}'.")
        return None

    icon_key = f"{icon_name}_{size}"
    if icon_key in _icon_cache:
        return _icon_cache[icon_key]

    if is_weather_icon:
        icon_dir = PREPARED_BASE_DIR.parent / 'weather_icons'
    else:
        icon_dir = ICONS_DIR
    
    icon_path = icon_dir / f"{icon_name}.png"

    if icon_path.exists():
        try:
            loaded_surface = pygame.image.load(str(icon_path)).convert_alpha()
            icon_surface = pygame.transform.scale(loaded_surface, (size, size))
            _icon_cache[icon_key] = icon_surface
            return icon_surface
        except Exception as e:
            logger.info(f"[Display] Error loading icon '{icon_path}': {e}")
            # Fall through to return placeholder
    else:
        warning_key = f"warn_{icon_name}"
        if warning_key not in _icon_cache:
            logger.info(f"[Display] WARNING: Icon file not found: {icon_path}")
            _icon_cache[warning_key] = True
    
    # --- Return None on failure ---
    # This allows the display logic to skip the icon.
    return None

def draw_pause_icon(screen, screen_width, screen_height):
    from utils import slideshow_controls
    slideshow_controls.draw(screen, screen_width, screen_height, paused)

def get_path_to_display(photo_path_obj, source, filter_states):
    """
    Determine the correct file path to display based on the source and filters.
    """
    relative_path_str = f"{source}/{photo_path_obj.name}"
    active_filter = filter_states.get(relative_path_str, 'none')
    
    # Display the base image by default.
    path_to_display = str(photo_path_obj)

    # Priority 1: Explicit user filter.
    if active_filter == 'polaroid':
        polaroid_path = photo_path_obj.with_name(f"{photo_path_obj.stem}_polaroid.jpg")
        if polaroid_path.exists():
            path_to_display = str(polaroid_path)
    elif active_filter == 'postcard':
        postcard_path = photo_path_obj.with_name(f"{photo_path_obj.stem}_postcard.jpg")
        if postcard_path.exists():
            path_to_display = str(postcard_path)
            
    return path_to_display

def build_playlist(media_list, config, favorites):
    """
    Build the final playlist, applying boosts for favorites and recent photos.
    """
    favorite_boost = int(config.get("favorite_boost_factor", 2))
    anniversary_boost_enabled = config.get("anniversary_boost_enabled", False)
    anniversary_boost_factor = int(config.get("anniversary_boost_factor", 2))

    playlist = []
    for media_path in media_list:
        playlist.append(media_path)
        relative_path = str(Path(media_path).relative_to(PREPARED_BASE_DIR))
        normalized_relative_path = re.sub(r'(_polaroid|_postcard)\.jpg$', '.jpg', relative_path)

        if normalized_relative_path in favorites:
            for _ in range(favorite_boost): playlist.append(media_path)

        # --- Boost d'anniversaire ---
        if anniversary_boost_enabled:
            photo_metadata = get_photo_metadata(media_path)
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
                            logger.debug(f"📸 Anniversary boost for {Path(media_path).name} (taken on {photo_date.strftime('%d/%m')})")
                            for _ in range(anniversary_boost_factor): playlist.append(media_path)
                    except Exception as e:
                        logger.debug(f"Error reading the date for the anniversary boost: {e}")
    return playlist

try:
    import RPi.GPIO as GPIO
    GPIO.setmode(GPIO.BCM) # Use BCM pin numbering.
    GPIO_AVAILABLE = True
except ImportError:
    logger.debug("RPi.GPIO is unavailable. Fan control is disabled.")
    GPIO_AVAILABLE = False

def set_gpio_output(pin, state):
    """
    Set a GPIO pin's output state (HIGH/True or LOW/False).

    Args:
        pin (int): The GPIO pin number (BCM numbering).
        state (bool): True pour HIGH (3.3V), False pour LOW (0V).

    Returns:
        None
    """
    if GPIO_AVAILABLE:
        try:
            GPIO.setup(pin, GPIO.OUT)
            GPIO.output(pin, GPIO.HIGH if state else GPIO.LOW)
        except Exception as e:
            logger.info(f"Error handling GPIO pin {pin}: {e}")

def control_fan(temperature, threshold=55, pin=14):
    if temperature >= threshold:
        set_gpio_output(pin, True)
        # logger.info(f"Fan enabled (temperature: {temperature}°C, threshold: {threshold}°C)") # Commented out to reduce log noise
    else:
        set_gpio_output(pin, False)

class OverlayDataCache:
    """Keep weather/tide acquisition off the rendering thread.

    One worker and one pending job bound resource use. Existing getters retain
    their refresh intervals, persistent tide cache, and API cooldown behavior.
    """

    KEYS = (
        "show_weather", "show_clock", "show_tides",
        "weather_city", "weather_units", "weather_update_interval_minutes",
        "stormglass_api_key", "tide_latitude", "tide_longitude",
    )

    def __init__(self, weather_loader=None, tide_loader=None, clock=time.monotonic):
        self._weather_loader = weather_loader or get_weather_and_forecast
        self._tide_loader = tide_loader or get_tides
        self._clock = clock
        self._lock = threading.Lock()
        self._queue = queue.Queue(maxsize=1)
        self._worker = None
        self._pending = False
        self._key = None
        self._snapshot = (None, None)
        self._next_check = 0
        self._closed = False

    def get(self, config):
        """Return memory-only snapshots and schedule a background refresh."""
        selected = {name: config.get(name) for name in self.KEYS}
        key = tuple(selected.values())
        with self._lock:
            snapshot = self._snapshot if key == self._key else (None, None)
            if self._closed or self._pending:
                return snapshot
            if key == self._key and self._clock() < self._next_check:
                return snapshot
            self._pending = True
            self._queue.put_nowait((key, dict(config)))
            if self._worker is None:
                self._worker = threading.Thread(
                    target=self._run, name="overlay-data", daemon=True)
                self._worker.start()
            return snapshot

    def close(self):
        with self._lock:
            self._closed = True
            worker = self._worker
        if worker is not None:
            self._queue.join()
            self._queue.put(None)
            worker.join()
            self._worker = None

    def _run(self):
        while True:
            job = self._queue.get()
            try:
                if job is None:
                    return
                key, config = job
                weather, tides = None, None
                for enabled, loader, kind in (
                    (config.get("show_weather", False), self._weather_loader, "weather"),
                    (config.get("show_clock", False) and config.get("show_tides", False),
                     self._tide_loader, "tides"),
                ):
                    if enabled:
                        try:
                            value = loader(config)
                            if kind == "weather":
                                weather = value
                            else:
                                tides = value
                        except Exception:
                            logger.warning("Background %s overlay acquisition failed", kind)
                with self._lock:
                    self._key = key
                    self._snapshot = (weather, tides)
                    self._next_check = self._clock() + 1
            finally:
                with self._lock:
                    self._pending = False
                self._queue.task_done()


overlay_data = OverlayDataCache()


# New function to draw the overlay elements (clock, date, weather)
def draw_overlay(screen, screen_width, screen_height, config, main_font, photo_metadata=None):
    now = datetime.now()
    text_color = parse_color(config.get("clock_color", "#FFFFFF"))
    outline_color = parse_color(config.get("clock_outline_color", "#000000"))
    weather_and_forecast, tides_data = overlay_data.get(config)

    show_clock = config.get("show_clock", False)
    if show_clock or config.get("show_weather", False):
        separator = "  |  "
        icon_padding = 10

        # --- Prepare the items to display ---
        elements = []

        # Time
        if show_clock:
            time_str = now.strftime(config.get("clock_format", "%H:%M"))
            elements.append({'type': 'text', 'text': time_str})

        # Date
        if show_clock and config.get("show_date", False):
            date_str = now.strftime(config.get("date_format", "%A %d %B %Y"))
            elements.append({'type': 'text', 'text': separator + date_str})

        # --- Calculate the total size and position of the block ---
        total_width = 0
        max_height = 0
        for el in elements:
            if el['type'] == 'text':
                el['surface'] = main_font.render(el['text'], True, text_color)
            total_width += el['surface'].get_width()
            if el.get('padding'):
                total_width += el['padding']
            if el['surface'].get_height() > max_height:
                max_height = el['surface'].get_height()

        offset_x = int(config.get("clock_offset_x", 0))
        offset_y = int(config.get("clock_offset_y", 0))
        position = config.get("clock_position", "center")

        if position == "left":
            block_x = offset_x
        elif position == "right":
            block_x = screen_width - total_width + offset_x
        else: # center
            block_x = (screen_width - total_width) // 2 + offset_x
        
        # Place the block at the top of the display with 15px padding.
        block_y = 15 + offset_y
        clock_block_bottom = block_y + max_height

        # --- Draw the semi-transparent background ---
        if config.get("clock_background_enabled", False):
            bg_color_hex = config.get("clock_background_color", "#00000080")
            bg_color_rgba = parse_color(bg_color_hex)
            
            if len(bg_color_rgba) == 3:
                bg_color_rgba = bg_color_rgba + (128,) # Add semi-transparency by default.
            
            bg_surface = pygame.Surface((screen_width, max_height + 20), pygame.SRCALPHA)
            bg_surface.fill(bg_color_rgba)
            screen.blit(bg_surface, (0, block_y - 10))

        # --- Draw the elements in sequence ---
        current_x = block_x
        for el in elements:
            el_y = block_y + (max_height - el['surface'].get_height()) // 2
            
            if el.get('padding'):
                current_x += el['padding']

            # Draw the element only if it is visible (True by default).
            if el.get('visible', True):
                if el['type'] == 'text':
                    draw_text_with_outline(screen, el['text'], main_font, text_color, outline_color, (current_x, el_y), anchor="topleft")
                elif el['type'] == 'icon':
                    screen.blit(el['surface'], (current_x, el_y))
            
            current_x += el['surface'].get_width()

    # Draw current weather below the clock.
    if (
        config.get("show_weather", False) and weather_and_forecast
    ) or (show_clock and config.get("show_tides", False)):
        current_weather = (weather_and_forecast or {}).get("current") or {}
        units = current_weather.get("units", {})
        temperature_unit = units.get("temperature", "°C")
        weather_parts = []

        temperature = current_weather.get("main", {}).get("temp")
        conditions = (current_weather.get("weather") or [{}])[0].get("description")
        current_parts = []
        if current_weather.get("city"):
            current_parts.append(current_weather["city"])
        if temperature is not None:
            current_parts.append(f"{round(temperature)}{temperature_unit}")
        if conditions:
            current_parts.append(conditions.capitalize())
        if current_parts:
            weather_parts.append("  ".join(current_parts))

        if weather_parts:
            weather_font_size = max(16, min(30, int(main_font.get_height() * 0.4)))
            weather_font = load_font(
                config.get("clock_font_path", get_default_font_path()),
                weather_font_size,
            )
            max_line_width = max(1, screen_width - 30)
            weather_lines = []
            for text in weather_parts:
                words = text.split()
                line_words = []
                for word in words:
                    candidate = " ".join(line_words + [word])
                    if line_words and weather_font.size(candidate)[0] > max_line_width:
                        weather_lines.append(" ".join(line_words))
                        line_words = [word]
                    else:
                        line_words.append(word)
                if line_words:
                    weather_lines.append(" ".join(line_words))

            line_height = weather_font.get_linesize()
            weather_y = clock_block_bottom + 6
            for line in weather_lines:
                line_surface = weather_font.render(line, True, text_color)
                line_x = max(15, (screen_width - line_surface.get_width()) // 2)
                if config.get("clock_background_enabled", False):
                    bg_color = parse_color(config.get("clock_background_color", "#00000080"))
                    if len(bg_color) == 3:
                        bg_color += (128,)
                    bg_surface = pygame.Surface(
                        (screen_width, line_height + 8), pygame.SRCALPHA)
                    bg_surface.fill(bg_color)
                    screen.blit(bg_surface, (0, weather_y - 4))
                draw_text_with_outline(
                    screen, line, weather_font, text_color, outline_color,
                    (line_x, weather_y), anchor="topleft",
                )
                weather_y += line_height

        # --- Bottom block for tides ---
        if show_clock and config.get("show_tides", False):
            tide_text = None
            font_to_use = main_font

            if tides_data:
                tide_parts = []
                today = datetime.now().date()
                tomorrow = today + timedelta(days=1)
                day_map = {'Mon':'Lun', 'Tue':'Mar', 'Wed':'Mer', 'Thu':'Jeu', 'Fri':'Ven', 'Sat':'Sam', 'Sun':'Dim'}

                # Show the next four tides for a useful view of the coming days.
                for tide in tides_data[:4]:
                    tide_dt = datetime.fromisoformat(tide['time']).astimezone()
                    tide_date = tide_dt.date()

                    if tide_date == today: day_str = "Auj."
                    elif tide_date == tomorrow: day_str = "Dem."
                    else: day_str = day_map.get(tide_dt.strftime('%a'), tide_dt.strftime('%a'))

                    type_str = "PM" if tide['type'] == 'high' else "BM"
                    time_str = tide_dt.strftime('%H:%M')
                    
                    tide_parts.append(f"{day_str} {type_str}: {time_str}")
                
                if tide_parts:
                    tide_text = " | ".join(tide_parts)
            else:
                # Show a message if the feature is enabled but no data is available.
                tide_text = _("Données de marée non disponibles")
                try:
                    # Use a slightly smaller font for the error message.
                    font_path = config.get("clock_font_path", get_default_font_path())
                    font_size = int(main_font.get_height() * 0.8) # 80% de la taille de la police principale
                    font_to_use = load_font(font_path, font_size)
                except Exception as e:
                    logger.info(f"[Display] Error loading font for tide message: {e}")
                    font_to_use = main_font # Fallback

            if tide_text:
                tide_offset_x = int(config.get("tide_offset_x", 0))
                tide_offset_y = int(config.get("tide_offset_y", 0))

                tide_surface = font_to_use.render(tide_text, True, text_color)
                tide_rect = tide_surface.get_rect(centerx=(screen_width // 2) + tide_offset_x, bottom=(screen_height - 15) + tide_offset_y)

                # --- Add a background for tides ---
                if config.get("clock_background_enabled", False):
                    bg_color_hex = config.get("clock_background_color", "#00000080")
                    bg_color_rgba = parse_color(bg_color_hex)

                    if len(bg_color_rgba) == 3:
                        bg_color_rgba = bg_color_rgba + (128,)

                    # Create a background surface across the full display width.
                    bg_height = tide_rect.height + 10  # Ajouter 5px de padding en haut et en bas
                    bg_surface = pygame.Surface((screen_width, bg_height), pygame.SRCALPHA)
                    bg_surface.fill(bg_color_rgba)
                    # Position the background vertically to frame the text.
                    screen.blit(bg_surface, (0, tide_rect.top - 5))

                draw_text_with_outline(screen, tide_text, font_to_use, text_color, outline_color, tide_rect.topleft, anchor="topleft")


    # --- Sigalou change 2026-01-25: show photo metadata at the bottom of the display ---
    # This block displays the photo capture date and/or location
    # when this information is available in the photo metadata.
    has_any_date = False
    if photo_metadata is not None:
        has_any_date = any(photo_metadata.get(field) for field in [
            "SubSecDateTimeOriginal", "DateTimeOriginal", "SubSecCreateDate", 
            "CreateDate", "SubSecModifyDate", "MediaCreateDate", "DateTimeCreated", 
            "subSecDateTimeOriginal", "dateTimeOriginal", "subSecCreateDate", "createDate",
            "subSecModifyDate", "modifyDate", "mediaCreateDate", "dateTimeCreated",
            "fileModifiedAt", "fileCreatedAt"
        ])

    if photo_metadata and (has_any_date or config.get("show_photo_location", False)):
        # Get the custom font for metadata.
        metadata_font_path = config.get("photo_metadata_font_path", get_default_font_path())
        metadata_font_size = int(config.get("photo_metadata_font_size", 23))

        metadata_font = load_font(metadata_font_path, metadata_font_size)

        # Custom metadata colors.
        metadata_text_color = parse_color(config.get("photo_metadata_color", "#ffffff"))
        metadata_outline_color = parse_color(config.get("photo_metadata_outline_color", "#000000"))
        
        metadata_text = format_photo_metadata(photo_metadata, config, _)
        if metadata_text:
            metadata_surface = metadata_font.render(metadata_text, True, metadata_text_color)

            # Offsets optionnels
            metadata_offset_x = int(config.get("photo_metadata_offset_x", 0))
            metadata_offset_y = int(config.get("photo_metadata_offset_y", 0))

            # Position according to the configuration.
            position = config.get("photo_metadata_position", "bottom_left")

            if position == "bottom_left":
                metadata_rect = metadata_surface.get_rect(
                    left=15 + metadata_offset_x,
                    bottom=(screen_height - 15) + metadata_offset_y
                )
            elif position == "bottom_right":
                metadata_rect = metadata_surface.get_rect(
                    right=(screen_width - 15) + metadata_offset_x,
                    bottom=(screen_height - 15) + metadata_offset_y
                )
            elif position == "bottom_center":
                metadata_rect = metadata_surface.get_rect(
                    centerx=(screen_width // 2) + metadata_offset_x,
                    bottom=(screen_height - 15) + metadata_offset_y
                )
            elif position == "top_left":
                metadata_rect = metadata_surface.get_rect(
                    left=15 + metadata_offset_x,
                    top=15 + metadata_offset_y
                )
            elif position == "top_right":
                metadata_rect = metadata_surface.get_rect(
                    right=(screen_width - 15) + metadata_offset_x,
                    top=15 + metadata_offset_y
                )
            else:  # Fallback
                metadata_rect = metadata_surface.get_rect(
                    left=15 + metadata_offset_x,
                    bottom=(screen_height - 15) + metadata_offset_y
                )

            # Draw the background if enabled.
            if config.get("photo_metadata_background_enabled", True):
                bg_color_hex = config.get("photo_metadata_background_color", "#00000080")
                bg_color_rgba = parse_color(bg_color_hex)

                if len(bg_color_rgba) == 3:
                    bg_color_rgba = bg_color_rgba + (128,)

                bg_width = metadata_rect.width + 20
                bg_height = metadata_rect.height + 10
                bg_surface = pygame.Surface((bg_width, bg_height), pygame.SRCALPHA)
                bg_surface.fill(bg_color_rgba)
                screen.blit(bg_surface, (metadata_rect.left - 10, metadata_rect.top - 5))

            # Draw the text with an outline.
            draw_text_with_outline(
                screen, 
                metadata_text, 
                metadata_font, 
                metadata_text_color, 
                metadata_outline_color, 
                metadata_rect.topleft, 
                anchor="topleft"
            )
    # --- End of Sigalou change 2026-01-25 ---

    # Flag display is independent of the date/location text settings.
    if photo_metadata and config.get("show_country_flag", True):
        country = (photo_metadata.get("countryCode") or photo_metadata.get("country_code")
                   or photo_metadata.get("country", ""))
        flag_pil = country_flags.get(country, config.get("country_flag_size", "128x96"))
        if flag_pil is not None:
            opacity = config.get("country_flag_opacity", 0.7)
            r, g, b, a = flag_pil.split()
            a = a.point(lambda p: int(p * opacity))
            flag_pil = Image.merge('RGBA', (r, g, b, a))
            flag_surf = pygame.image.fromstring(
                flag_pil.tobytes(), flag_pil.size, flag_pil.mode
            )
            flag_position = config.get("country_flag_position", "top_right")
            flag_offset_x = int(config.get("country_flag_offset_x", 15))
            flag_offset_y = int(config.get("country_flag_offset_y", 15))

            if flag_position == "top_left":
                flag_rect = flag_surf.get_rect(topleft=(flag_offset_x, flag_offset_y))
            elif flag_position == "bottom_left":
                flag_rect = flag_surf.get_rect(bottomleft=(flag_offset_x, screen_height - flag_offset_y))
            elif flag_position == "bottom_right":
                flag_rect = flag_surf.get_rect(bottomright=(screen_width - flag_offset_x, screen_height - flag_offset_y))
            else:  # top_right (default)
                flag_rect = flag_surf.get_rect(topright=(screen_width - flag_offset_x, flag_offset_y))
            screen.blit(flag_surf, flag_rect)

def display_title_slide(screen, screen_width, screen_height, title, duration, config, photos_for_slide=None):
    """Display a title screen with the playlist name and a photo collage."""
    logger.info(f"📸 Displaying title screen: '{title}'")
 
    # --- NEW: Load the thumbtack images as PIL images ---
    thumbtack_pil_images = []
    try:
        icons_dir = Path(BASE_DIR) / 'static' / 'icons'
        # Look for thumbtacks in different colors.
        thumbtack_paths = list(icons_dir.glob('thumbtack_*.png'))
        if thumbtack_paths:
            for tack_path in thumbtack_paths:
                tack_img = Image.open(str(tack_path)).convert("RGBA")
                # Resize to a reasonable size (e.g. 40x40 pixels).
                tack_img.thumbnail((40, 40), Image.Resampling.LANCZOS)
                thumbtack_pil_images.append(tack_img)
        else:
            logger.info("[Title Slide] Warning: No thumbtack image (thumbtack_*.png) found in static/icons/.")
    except Exception as e:
        logger.info(f"[Title Slide] Warning: Unable to load thumbtacks: {e}")

    # Draw all elements to a temporary surface before displaying them.
    # This avoids refresh issues and ensures everything is drawn in the right order.
    temp_surface = pygame.Surface((screen_width, screen_height))

    try:
        cork_bg_path = Path(BASE_DIR) / 'static' / 'backgrounds' / 'cork_background.jpg'
        if cork_bg_path.exists():
            cork_bg_img = pygame.image.load(str(cork_bg_path)).convert()
            # --- NEW: Background resizing and centering logic ---
            screen_height_percent = int(config.get("screen_height_percent", "100"))
            
            # Calculate the usable background height.
            new_bg_height = int(screen_height * (screen_height_percent / 100.0))

            # Resize the background image to fill the usable area without distortion.
            original_bg_width, original_bg_height = cork_bg_img.get_size()
            bg_aspect_ratio = original_bg_width / original_bg_height
            
            # Scale the image so its width matches the display width.
            scaled_w = screen_width
            scaled_h = int(scaled_w / bg_aspect_ratio)
            
            # If the image is shorter than the usable area, scale it by height.
            if scaled_h < new_bg_height:
                scaled_h = new_bg_height
                scaled_w = int(scaled_h * bg_aspect_ratio)

            scaled_cork_bg = pygame.transform.smoothscale(cork_bg_img, (scaled_w, scaled_h))

            # Crop the background image if it is larger than the usable area.
            crop_area = pygame.Rect(
                (scaled_w - screen_width) // 2,
                (scaled_h - new_bg_height) // 2,
                screen_width,
                new_bg_height
            )

            # Position of the usable area on the final display.
            bg_y = (screen_height - new_bg_height) // 2
            
            temp_surface.fill((0, 0, 0)) # Fill the screen background with black (for the borders).
            temp_surface.blit(scaled_cork_bg, (0, bg_y), crop_area) # Draw the cropped and centered section.
        else:
            # Fall back to a solid color if the image is not found.
            logger.info(f"[Title Slide] Warning: Background image not found at {cork_bg_path}. Using a solid color.")
            temp_surface.fill((181, 136, 99)) # A cork-like color.
    except Exception as e:
        logger.info(f"[Title Slide] Error loading background: {e}. Using a solid color.")
        temp_surface.fill((181, 136, 99))

    # --- Photo collage ---
    if photos_for_slide:
        num_photos = min(len(photos_for_slide), 4)
        if num_photos > 0:
            selected_paths = random.sample(photos_for_slide, num_photos)

            photo_surfaces = []
            for path in selected_paths:
                try:
                    # Load the image with PIL.
                    img = Image.open(path)
                    # Create a thumbnail.
                    img.thumbnail((400, 400), Image.Resampling.LANCZOS)
                    # Add a white border for the Polaroid effect.
                    img_with_border = ImageOps.expand(img, border=20, fill='white')
                    
                    image_to_rotate = img_with_border.convert("RGBA")

                    # --- NEW: Add the thumbtack to a larger canvas BEFORE rotation ---
                    if thumbtack_pil_images:
                        tack_img = random.choice(thumbtack_pil_images)
                        
                        # Create a larger canvas to include the protruding thumbtack.
                        new_height = image_to_rotate.height + tack_img.height // 2
                        composite_canvas = Image.new('RGBA', (image_to_rotate.width, new_height), (0, 0, 0, 0))
                        
                        # Coller la photo sur la toile, en laissant de l'espace en haut
                        composite_canvas.paste(image_to_rotate, (0, tack_img.height // 2))
                        
                        # Coller la punaise en haut au centre
                        tack_x = (composite_canvas.width - tack_img.width) // 2
                        composite_canvas.paste(tack_img, (tack_x, 0), tack_img)
                        
                        image_to_rotate = composite_canvas
                        
                    # Random tilt.
                    angle = random.uniform(-15, 15)
                    rotated_img = image_to_rotate.rotate(angle, expand=True, resample=Image.Resampling.BICUBIC, fillcolor=(0, 0, 0, 0))
                    
                    py_surface = pygame.image.fromstring(rotated_img.tobytes(), rotated_img.size, rotated_img.mode).convert_alpha()
                    photo_surfaces.append(py_surface)
                except Exception as e:
                    logger.info(f"[Title Slide] Error preparing image {path}: {e}")

            # Debug line to check whether any photos were processed.
            logger.info(f"[Title Slide] DEBUG: Number of prepared photo surfaces: {len(photo_surfaces)}")

            # Position the photos randomly but evenly.
            base_positions = [
                (screen_width * 0.25, screen_height * 0.25),
                (screen_width * 0.75, screen_height * 0.35),
                (screen_width * 0.30, screen_height * 0.75),
                (screen_width * 0.70, screen_height * 0.80)
            ]
            random.shuffle(base_positions)

            for i, surface in enumerate(photo_surfaces):
                pos_x = base_positions[i][0] + random.randint(-50, 50)
                pos_y = base_positions[i][1] + random.randint(-50, 50)
                rect = surface.get_rect(center=(pos_x, pos_y))
                temp_surface.blit(surface, rect)

    # --- Titre de la playlist ---
    text_color = parse_color(config.get("clock_color", "#FFFFFF"))
    outline_color = parse_color(config.get("clock_outline_color", "#000000"))

    try:
        # Use a larger cursive font for the title.
        font_path = str(Path(BASE_DIR) / "static" / "fonts" / "Caveat-Regular.ttf")
        # Increase the font size for greater visual impact.
        title_font_size = int(config.get("clock_font_size", 72) * 2.5)
        title_font = load_font(font_path, title_font_size)
    except Exception as e:
        logger.info(f"Error loading font for title screen: {e}")
        title_font = pygame.font.SysFont("Arial", 150, bold=True)

    # Draw the title centered over the photos.
    draw_text_with_outline(temp_surface, title, title_font, text_color, outline_color, (screen_width // 2, screen_height // 2), anchor="center")

    # Display the final surface on the main screen.
    screen.blit(temp_surface, (0, 0))
    pygame.display.flip()

    # Wait in a loop to remain responsive to signals (e.g. QUIT).
    start_sleep = time.time()
    while time.time() - start_sleep < duration:
        handle_slideshow_events(screen_width)
        if next_photo_requested or previous_photo_requested:
            return
        screen.blit(temp_surface, (0, 0))
        draw_pause_icon(screen, screen_width, screen_height)
        pygame.display.flip()
        time.sleep(0.1)

# Function to display an image and the time.

def display_photo_with_pan_zoom(screen, pil_image, screen_width, screen_height, config, main_font, photo_path=None, pan_zoom_plan=None):
    """
    Display a prepared image with a pan/zoom effect and handle controls (pause, next, previous).
    """
    global paused, next_photo_requested, previous_photo_requested
    # Sigalou change 2026-01-25: retrieve the photo metadata.
    photo_metadata = get_photo_metadata(photo_path) if photo_path else None
    # End of Sigalou change 2026-01-25.

    # Prepare the image and metadata at the start to avoid definition errors (NameError).
    pil_image = fit_photo_to_screen(pil_image, screen_width, screen_height)
    pygame_image_base = pygame.image.fromstring(pil_image.tobytes(), pil_image.size, pil_image.mode)


    # Pause loop: wait here while the slideshow is paused.
    while paused:
        config = load_config() # Reload to respond immediately to notification changes.
        handle_slideshow_events(screen_width)
        if next_photo_requested or previous_photo_requested: return

        screen.blit(pygame_image_base, (0, 0))
        draw_overlay(screen, screen_width, screen_height, config, main_font, photo_metadata)
        draw_pause_icon(screen, screen_width, screen_height)

        pygame.display.flip()
        time.sleep(0.1) # Avoid overloading the CPU while paused.

    """Display a prepared image and the time on screen."""
    try:
        pan_zoom_enabled = config.get("pan_zoom_enabled", False)
        display_duration = config.get("display_duration", 10)
        logger.info(f"⏳ Pause de {display_duration} secondes.") # Debug print
        
        if not pan_zoom_enabled: # If pan/zoom is disabled, just show static image
            # Static display: blit once, then wait for the duration.
            screen.blit(pygame_image_base, (0, 0))
            draw_overlay(screen, screen_width, screen_height, config, main_font, photo_metadata)
            draw_pause_icon(screen, screen_width, screen_height)
            pygame.display.flip()
            # Wait in a loop to remain responsive to signals.
            start_sleep = time.time()
            while time.time() - start_sleep < display_duration:
                handle_slideshow_events(screen_width)

                if next_photo_requested or previous_photo_requested: return
                screen.blit(pygame_image_base, (0, 0))
                draw_overlay(screen, screen_width, screen_height, config, main_font, photo_metadata)
                draw_pause_icon(screen, screen_width, screen_height)
                pygame.display.flip()
                was_paused = False
                while paused:
                    config = load_config() # Reload to respond immediately to the button.
                    was_paused = True
                    handle_slideshow_events(screen_width)
                    if next_photo_requested or previous_photo_requested: return

                    # Redraw the background to clear the previous phase icon.
                    screen.blit(pygame_image_base, (0, 0))
                    draw_overlay(screen, screen_width, screen_height, config, main_font, photo_metadata)

                    draw_pause_icon(screen, screen_width, screen_height)

                    pygame.display.flip()
                    time.sleep(0.1)
                    start_sleep += 0.1

                time.sleep(0.1)
        else:
            if pan_zoom_plan is None:
                pan_zoom_plan = prepare_pan_zoom(pil_image, screen_width, screen_height, config)
            base_image, start_offset, end_offset, start_zoom, end_zoom = pan_zoom_plan
            base_surface = pygame.image.fromstring(base_image.tobytes(), base_image.size, base_image.mode)
            initial_frame = render_pan_zoom_frame(base_surface, screen_width, screen_height,
                                                 start_offset, end_offset, start_zoom, end_zoom, 0)
            overlay = pygame.Surface((screen_width, screen_height), pygame.SRCALPHA)
            draw_overlay(overlay, screen_width, screen_height, config, main_font, photo_metadata)
            overlay_updated = time.monotonic()
            screen.blit(initial_frame, (0, 0))
            screen.blit(overlay, (0, 0))
            draw_pause_icon(screen, screen_width, screen_height)
            pygame.display.flip()

            clock = pygame.time.Clock()
            start_animation_time = time.time()

            while time.time() - start_animation_time < display_duration:
                elapsed_animation_time = time.time() - start_animation_time

                handle_slideshow_events(screen_width)

                # Check for signals on every animation frame.
                if next_photo_requested or previous_photo_requested: return

                # Apply an ease-in-out function for smoother motion.
                raw_progress = min(1.0, elapsed_animation_time / display_duration)
                eased_progress = 0.5 * (1 - math.cos(raw_progress * math.pi))

                frame = render_pan_zoom_frame(base_surface, screen_width, screen_height,
                                              start_offset, end_offset, start_zoom, end_zoom, eased_progress)
                screen.blit(frame, (0, 0))

                # Refresh text once per second instead of rebuilding it for every animation frame.
                now = time.monotonic()
                if now - overlay_updated >= 1.0:
                    overlay.fill((0, 0, 0, 0))
                    draw_overlay(overlay, screen_width, screen_height, config, main_font, photo_metadata)
                    overlay_updated = now
                screen.blit(overlay, (0, 0))
                draw_pause_icon(screen, screen_width, screen_height)

                # Pause handling.
                if paused:
                    config = load_config() # Recharger pendant la pause de l'animation
                    overlay_updated = float("-inf")

                    pygame.display.flip()
                    time.sleep(0.1)
                    start_animation_time += 0.1 # Offset the time to avoid skipping the animation.
                    continue # On recommence la boucle sans avancer l'image

                pygame.display.flip()
                clock.tick(60) # Limit frame rate to 60 FPS for smoother animation
                
    except Exception as e:
        logger.info(f"Error displaying photo with pan/zoom: {e}")
        traceback.print_exc()

def fade_to_black(screen, previous_surface, duration, clock):
    """Fade the given surface to black."""
    num_frames = int(duration * 60)
    if num_frames == 0: num_frames = 1
    
    black_surface = pygame.Surface(screen.get_size()).convert()
    black_surface.fill((0, 0, 0))

    for i in range(num_frames + 1):
        progress = i / num_frames
        alpha = int(255 * progress)
        black_surface.set_alpha(alpha)
        
        screen.blit(previous_surface, (0, 0))
        screen.blit(black_surface, (0, 0))
        pygame.display.flip()
        clock.tick(60)

def draw_loading_banner(screen, text, width, height, font):
    """Display a black screen with a centered message for the user."""
    try:
        screen.fill((0, 0, 0))
        text_surface = font.render(text, True, (255, 255, 255))
        text_rect = text_surface.get_rect(center=(width // 2, height // 2))
        screen.blit(text_surface, text_rect)
        pygame.display.flip()
    except Exception as e:
        logger.warning(f"Error drawing banner: {e}")

def display_video(screen, video_path, screen_width, screen_height, config, main_font, previous_surface, clock):
    """Display a video full-screen using the external mpv player."""
    global _current_background_music
    audio_enabled = config.get("video_audio_enabled", False)
    audio_output = config.get("video_audio_output", "auto")
    audio_volume = int(config.get("video_audio_volume", 100))
    transition_duration = float(config.get("transition_duration", 1.0))
    hwdec_enabled = config.get("video_hwdec_enabled", True)
    pi_model = get_pi_model()

    # 1. Display a loading banner before starting (using a Unicode hourglass supported by the font).
    if main_font:
        draw_loading_banner(screen, "⌛ Loading video...", screen_width, screen_height, main_font)
        time.sleep(0.5)

    # To avoid graphics-surface conflicts (CMA and Wayland scanout) between Pygame and mpv,
    # shut down Pygame cleanly before launching mpv on every Raspberry Pi model (1/2/3/4/5).
    # Leaving Pygame open on these boards can cause an EGL resource conflict on the GPU and block mpv.
    # After shutdown, wait 0.8 seconds for the Wayland compositor to release the display surface.
    if pi_model in [1, 2, 3, 4, 5]:
        logger.info(f"📸 [Pi {pi_model}] Closing Pygame to release graphics overlay context for mpv.")
        pygame.quit()
        time.sleep(0.8)
    elif audio_enabled:
        if pygame.mixer.get_init(): pygame.mixer.quit()

    try:
        # 1. Fade to black before starting the video (only if Pygame is not already closed).
        if previous_surface and pi_model not in [1, 2, 3, 4, 5]:
            fade_to_black(screen, previous_surface, transition_duration / 2, clock)
        
        logger.info(f"📸 Starting video with mpv: {video_path}")
        # Show the cursor in case the user wants to interact with mpv (progress bar, etc.).
        if pi_model not in [1, 2, 3, 4, 5]:
            pygame.mouse.set_visible(True)
        
        # --- New approach: return to mpv with a robust configuration ---
        command = [
            'mpv',
            '--no-config',
            '--no-terminal',
            '--fs', '--no-osc', '--no-osd-bar', '--loop=no'
        ]
        
        # Do not use --ontop on Pi 3 (Wayland bug).
        # For other models (Pi 1/2 with Pygame underneath, or Pi 4/5), force --ontop.
        if pi_model != 3:
            command.append('--ontop')

        if hwdec_enabled:
            # Try high-performance DMABUF first on every Raspberry Pi model (1/2/3/4/5).
            # It is the only direct (zero-copy) hardware mode, avoiding bandwidth stutter and a 15s black screen.
            if pi_model in [1, 2, 3, 4, 5]:
                logger.info(f"[Video Playback] Raspberry Pi {pi_model} detected. High-performance DMABUF mode.")
                command.extend(['-v', '--hwdec=v4l2m2m', '--vo=dmabuf-wayland', '--wayland-app-id=mpv', f'--log-file={MPV_LOG_FILE}'])
            else:
                # Fall back on other systems or if detection fails.
                logger.info("[Video Playback] No specific Pi model detected. Using '--hwdec=auto'.")
                if IS_LINUX:
                    command.extend(['--hwdec=auto', '--vo=gpu'])
                else:
                    command.append('--hwdec=auto')
            # --- FIN MODIFICATION ---
        else:
            # Default software mode (more stable on some systems, but slower).
            logger.info("[Video Playback] Hardware decoding disabled. Using software mode.")
            # CHANGE: x11 is too slow on Pi 4/5; use gpu even in software mode.
            if not IS_LINUX:
                pass
            elif pi_model in [4, 5]:
                command.extend(['--hwdec=no', '--vo=gpu'])
            else:
                command.extend(['--hwdec=no', '--vo=x11'])

        command.append(video_path)

        if audio_enabled:
            # Set the system volume with amixer for better compatibility.
            try:
                subprocess.run(['amixer', 'sset', 'Master', f'{audio_volume}%', 'unmute'], check=False, capture_output=True, text=True)
                logger.info(f"[Audio] System volume set to {audio_volume}% via amixer.")
            except FileNotFoundError:
                logger.info("[Audio] WARNING: 'amixer' not found. Volume cannot be adjusted.")
                   # Also pass the volume to mpv.
            command.extend([f'--volume={audio_volume}', '--no-mute'])
        else:
             command.append('--no-audio')

        
        # On Raspberry Pi models 1/2/3/4/5, try high-performance DMABUF mode first.
        # If this fails, fall back to GPU compatibility mode (with shader caching).
        commands_to_try = [command]
        if hwdec_enabled and pi_model in [1, 2, 3, 4, 5]:
            shader_cache_dir = os.path.join(BASE_DIR, "cache", "mpv_shaders")
            os.makedirs(shader_cache_dir, exist_ok=True)
            cmd_fallback = [
                'mpv',
                '--no-config',
                '--no-terminal',
                '--fs', '--no-osc', '--no-osd-bar', '--loop=no',
                '-v',
                '--profile=fast',
                '--hwdec=v4l2m2m-copy',
                '--vo=gpu',
                '--gpu-context=wayland',
                '--gpu-shader-cache=yes',
                f'--gpu-shader-cache-dir={shader_cache_dir}',
                '--scale=bilinear',
                '--cscale=bilinear',
                '--dscale=bilinear',
                '--vd-lavc-dr=yes',
                '--wayland-app-id=mpv',
                f'--log-file={MPV_LOG_FILE}',
                video_path
            ]
            if pi_model != 3:
                cmd_fallback.append('--ontop')
            if audio_enabled:
                cmd_fallback.extend([f'--volume={audio_volume}', '--no-mute'])
            else:
                cmd_fallback.append('--no-audio')
            
            commands_to_try = [command, cmd_fallback]
        
        success = False
        last_error = None
        
        # Use a fixed 90-second watchdog timeout so a frozen mpv process cannot block the slideshow.
        # Avoid a dynamic ffprobe call to keep startup responsive.
        timeout_limit = 90.0

        for idx, cmd_to_run in enumerate(commands_to_try):
            logger.info(f"📸 Executing mpv command (try {idx+1}/{len(commands_to_try)}): {' '.join(cmd_to_run)}")
            # Briefly wait for the system to settle.
            time.sleep(0.1)
            
            try:
                result = subprocess.run(
                    cmd_to_run, 
                    check=True, 
                    env=os.environ.copy(), 
                    stdout=subprocess.PIPE, 
                    stderr=subprocess.STDOUT, 
                    text=True,
                    timeout=timeout_limit
                )
                success = True
                break
            except subprocess.TimeoutExpired:
                logger.warning(f"⏱️ mpv exceeded the safety timeout ({timeout_limit}s). Process terminated.")
                break
            except subprocess.CalledProcessError as e:
                last_error = e
                logger.info(f"⚠️ Display mode attempt {idx+1} failed. Trying the next mode...")
                
        if not success:
            logger.info(f"Error running mpv for video {video_path}. mpv returned an error code.")
            
            # Extract the actual diagnostic log.
            log_content = ""
            if MPV_LOG_FILE.exists():
                try:
                    with MPV_LOG_FILE.open("r", encoding="utf-8") as f:
                        # Keep only the last 50 lines to avoid flooding the PictureFrame log.
                        log_content = "".join(f.readlines()[-50:])
                except Exception: 
                    pass
            
            combined_output = last_error.stdout if (last_error and last_error.stdout and last_error.stdout.strip()) else (log_content if log_content.strip() else "No error message captured.")
            logger.info(f"mpv error details:\n{combined_output}")
    except Exception as e:
        logger.info(f"Unexpected error playing video {video_path}: {e}")
    finally:
        # --- Reinitialize the Pygame mixer after video playback ---
        # This is essential so Pygame can play audio later,
        # and maintain a consistent state.
        if audio_enabled and pi_model not in [1, 2, 3, 4, 5]:
            logger.info(f"📸 Re-initializing pygame.mixer.")
            try:
                pygame.mixer.init()
            except pygame.error as e:
                logger.info(f"WARNING: Unable to reset pygame.mixer: {e}")
        
        # Restart the playlist background music if needed.
        if _current_background_music and pi_model not in [1, 2, 3, 4, 5]:
            play_background_music(_current_background_music)


# Main slideshow loop.
def start_slideshow():
    pi_model = get_pi_model()
    global _current_background_music
    photo_loader = ThreadPoolExecutor(max_workers=2, thread_name_prefix="slideshow-photo")
    try:
        logger.debug(f"📸 Starting slideshow initialization.")
        config = load_config()
        logger.debug(f"📸 Config loaded. show_clock: {config.get('show_clock')}, show_weather: {config.get('show_weather')}")
        
      
        
        time.sleep(2)
        logger.debug(f"📸 Attente de 2s pour stabilisation ")
        
        # ✅ NEW: Initialize only the display and font modules to save CPU (avoid initializing the mixer).
        pygame.display.init()
        pygame.font.init()
        logger.debug(f"📸 Pygame display and font modules initialized.")
        
        # ✅ FORCE initialization of the display module.
        pygame.display.init()
        logger.debug("📸 pygame.display.init() called explicitly")
        
        # Check environment information.
        logger.debug(f"📸 Environment check:")
        logger.debug(f"   DISPLAY={os.environ.get('DISPLAY', 'NOT SET')}")
        logger.debug(f"   WAYLAND_DISPLAY={os.environ.get('WAYLAND_DISPLAY', 'NOT SET')}")
        logger.debug(f"   XDG_RUNTIME_DIR={os.environ.get('XDG_RUNTIME_DIR', 'NOT SET')}")
        logger.debug(f"   SDL_VIDEODRIVER={os.environ.get('SDL_VIDEODRIVER', 'NOT SET')}")
        
        # ✅ NEW: Check that pygame.display.get_driver() works.
        try:
            driver = pygame.display.get_driver()
            logger.debug(f"📸 Video driver detected: {driver}")
        except Exception as e:
            logger.error(f"❌ Unable to detect the video driver: {e}")
        
        info = pygame.display.Info()
        if IS_LINUX:
            SCREEN_WIDTH, SCREEN_HEIGHT = info.current_w, info.current_h
        else:
            SCREEN_WIDTH, SCREEN_HEIGHT = get_pygame_display_size()
        logger.debug(f"📸 Screen resolution detected: {SCREEN_WIDTH}x{SCREEN_HEIGHT}")
        
        # Force 1920x1080 if the resolution is invalid.
        if SCREEN_WIDTH == 0 or SCREEN_HEIGHT == 0:
            logger.warning("❌ Invalid resolution detected (0x0); using the default 1920x1080")
            SCREEN_WIDTH, SCREEN_HEIGHT = 1920, 1080
        
        # Create the display.
        logger.debug(f"📸 Attempting to create display {SCREEN_WIDTH}x{SCREEN_HEIGHT}...")
        screen = pygame.display.set_mode(
            (SCREEN_WIDTH, SCREEN_HEIGHT),
            get_pygame_display_flags()
        )
        logger.info(f"✅ Display created successfully: {screen.get_size()}")
        
        pygame.mouse.set_visible(False)
        logger.debug(f"📸 Mouse cursor hidden.")       


        # --- Register signal handlers ---
        if all(hasattr(signal, name) for name in ("SIGUSR1", "SIGUSR2", "SIGTSTP")):
            signal.signal(signal.SIGUSR1, signal_handler_next)      # Pour "suivant"
            signal.signal(signal.SIGUSR2, signal_handler_previous) # For "previous".
            signal.signal(signal.SIGTSTP, signal_handler_pause_toggle) # Pour "pause/reprendre"
        logger.debug(f"📸 Signal handlers registered.")

        # Initialize the status file.
        update_status_file({"paused": False})

        try:
            import locale
            locale.setlocale(locale.LC_TIME, 'fr_FR.UTF-8')
            logger.debug(f"📸 Locale set to fr_FR.UTF-8.")
        except locale.Error:
            logger.warning("Warning: fr_FR.UTF-8 locale is unavailable. Dates will be in English.")

        # --- Physical button handling ---
        button_enabled = config.get("button_enabled", False)
        button_pin = int(config.get("button_pin", 23)) # GPIO 23 by default.

        if GPIO_AVAILABLE and button_enabled:
            try:
                # Clean up any previous pin configuration.
                GPIO.remove_event_detect(button_pin)
                # Configure the pin as input with an internal pull-up resistor.
                # The button must connect the pin to GND.
                GPIO.setup(button_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
                
                # Detect falling-edge events (button press).
                # bouncetime prevents multiple detections for one press.
                GPIO.add_event_detect(button_pin, GPIO.FALLING, callback=button_callback, bouncetime=500)
                logger.info(f"✅ Physical button enabled on GPIO pin {button_pin}.")
            except Exception as e:
                logger.error(f"❌ Error initializing GPIO button {button_pin}: {e}")
        # --- END: Physical button handling ---

        logger.debug(f"📸 Entering main slideshow loop.")
        
        # --- Initialize the previous surface for transitions ---
        previous_photo_surface = None

        # --- Check for and load a custom playlist (once) ---
        custom_playlist = None
        playlist_name = None
        is_custom_run = False # Drapeau pour indiquer un cycle de playlist unique
        if os.path.exists(CUSTOM_PLAYLIST_FILE):
            try:
                with open(CUSTOM_PLAYLIST_FILE, 'r') as f:
                    playlist_data = json.load(f)
                
                if isinstance(playlist_data, dict) and 'name' in playlist_data and 'photos' in playlist_data:
                    playlist_name = playlist_data['name']
                    custom_playlist_paths = playlist_data['photos']
                else:
                    # Fallback for the old structure (a simple list of paths).
                    custom_playlist_paths = playlist_data
                
                # Convert relative paths to absolute paths.
                custom_playlist = [str(Path(BASE_DIR) / 'static' / 'prepared' / p) for p in custom_playlist_paths]
                
                # Music handling.
                _current_background_music = playlist_data.get('music_file')
                if _current_background_music:
                    play_background_music(_current_background_music)

                logger.info(f"📸 Custom playlist '{playlist_name or 'Untitled'}' loaded with {len(custom_playlist)} photos.")
                is_custom_run = True # On active le drapeau pour le premier passage
                update_status_file({"is_custom": True})
                os.remove(CUSTOM_PLAYLIST_FILE) # Remove it to prevent reuse on the next startup.
            except Exception as e:
                logger.info(f"📸 Error loading custom playlist: {e}. Using the default playlist.")

        # Show the title screen when a custom playlist starts.
        if playlist_name:
            # Use a configurable duration for information screens.
            info_duration = int(config.get("info_display_duration", 5))
            display_title_slide(screen, SCREEN_WIDTH, SCREEN_HEIGHT, playlist_name, info_duration, config, photos_for_slide=custom_playlist)
            previous_photo_surface = screen.copy() # Capture the title screen for the first transition.

        while True:
            config = load_config() # Reload the config on every iteration.

            # --- FIX: Load transition settings here so they are always defined ---
            # Previously, they were only set when no custom playlist was used.
            transition_type = config.get("transition_type", "fade")
            transition_enabled = config.get("transition_enabled", True)
            transition_duration = float(config.get("transition_duration", 1.0))

            # --- Build the playlist ---
            if is_custom_run:
                playlist = custom_playlist
            else:
                # Build the default playlist.
                filter_states = load_filter_states()
                favorites = load_favorites()
                display_sources = config.get("display_sources", ["usb", "smartphone", "invités"])
                slideshow_video_enabled = config.get("slideshow_video_enabled", True)
                
                all_media = []
                for source in display_sources:
                    source_dir = PREPARED_BASE_DIR / source
                    if source_dir.is_dir():
                        base_photos = [f for f in source_dir.iterdir() if f.is_file() and (f.suffix.lower() in ('.jpg', '.jpeg', '.png') or f.suffix.lower() in VIDEO_EXTENSIONS) and not f.name.endswith(('_polaroid.jpg', '_thumbnail.jpg', '_postcard.jpg'))]
                        for photo_path_obj in base_photos:
                            # Filter out videos if the option is disabled.
                            if photo_path_obj.suffix.lower() in VIDEO_EXTENSIONS and not slideshow_video_enabled:
                                continue
                                
                            path_to_display = get_path_to_display(photo_path_obj, source, filter_states)
                            all_media.append(path_to_display)
                
                playlist = build_playlist(all_media, config, favorites)
                random.shuffle(playlist)
            
            # --- Load the font on every iteration ---
            # This is more robust, especially after a display reset.
            font_path_config = config.get("clock_font_path", get_default_font_path())
            clock_font_size_config = int(config.get("clock_font_size", 72))
            main_font_loaded = load_font(font_path_config, clock_font_size_config)
            # --- Font loading complete ---
            
            if not playlist:
                logger.info("No photos found in enabled sources. Checking again in 60 seconds.")
                
                screen.fill((0, 0, 0))
                
                text_color = parse_color(config.get("clock_color", "#FFFFFF"))
                outline_color = parse_color(config.get("clock_outline_color", "#000000"))
                
                try:
                    font_path = config.get("clock_font_path", get_default_font_path())
                    font_size = int(config.get("clock_font_size", 72) * 0.6) # Increased from 0.5.
                    message_font = load_font(font_path, font_size)
                    ip_font_size = int(config.get("clock_font_size", 72) * 0.8) # Increased from 0.65.
                    ip_font = load_font(font_path, ip_font_size)
                    small_font_size = int(config.get("clock_font_size", 72) * 0.4) # Increased from 0.35.
                    small_font = load_font(font_path, small_font_size)
                except Exception:
                    message_font = pygame.font.SysFont("Arial", 48)
                    ip_font = pygame.font.SysFont("Arial", 64)
                    small_font = pygame.font.SysFont("Arial", 32)

                # --- Logo ---
                logo_surface = message_font.render("PictureFrame", True, (67, 165, 214))
                if logo_surface.get_width() > SCREEN_WIDTH - 40:
                    width = max(1, SCREEN_WIDTH - 40)
                    height = max(1, int(logo_surface.get_height() * width / logo_surface.get_width()))
                    logo_surface = pygame.transform.smoothscale(logo_surface, (width, height))
                logo_height, logo_spacing = logo_surface.get_height(), 30

                # --- Generate the QR code ---
                qr_surface, qr_height, qr_spacing = None, 0, 30
                try:
                    ip_address_for_qr = get_local_ip()
                    url = f"http://{ip_address_for_qr}:7090"
                    qr_img_pil = qrcode.make(url, box_size=8).convert('RGB')
                    qr_surface = pygame.image.fromstring(qr_img_pil.tobytes(), qr_img_pil.size, qr_img_pil.mode)
                    qr_height = qr_surface.get_height()
                except Exception as e:
                    logger.info(f"Error generating QR code: {e}")

                ip_address = get_local_ip()
                messages = [
                    (message_font, _("Aucune photo trouvée.")),
                    (ip_font, _("Configurez sur : http://%(ip)s", ip=f"{ip_address}:7090")),
                    (small_font, _("(Identifiants dans credentials.json à la racine de la SD)")),
                    (message_font, _("Résolution de l'écran : [%(w)s x %(h)s]", w=SCREEN_WIDTH, h=SCREEN_HEIGHT)),
                    (message_font, _("Nouvelle tentative dans 60 secondes..."))
                ]
                
                line_spacing = 20
                text_block_height = sum(font.get_height() for font, _ in messages) + (len(messages) - 1) * line_spacing
                
                # Calculate the total height for perfect centering.
                total_height = text_block_height
                if logo_surface: total_height += logo_height + logo_spacing
                if qr_surface: total_height += qr_height + qr_spacing + small_font.get_height() + 10
                current_y = (SCREEN_HEIGHT - total_height) // 2

                if logo_surface:
                    logo_rect = logo_surface.get_rect(centerx=SCREEN_WIDTH // 2, top=current_y)
                    screen.blit(logo_surface, logo_rect)
                    current_y += logo_height + logo_spacing

                for font, txt in messages:
                    text_surface = font.render(txt, True, text_color)
                    text_rect = text_surface.get_rect(centerx=SCREEN_WIDTH // 2, top=current_y)
                    draw_text_with_outline(screen, txt, font, text_color, outline_color, text_rect.topleft, anchor="topleft")
                    current_y += font.get_height() + line_spacing

                # Display the QR code.
                if qr_surface:
                    current_y += qr_spacing - line_spacing # Ajuster l'espacement avant le QR
                    qr_title_text = _("Scannez pour configurer")
                    qr_title_surface = small_font.render(qr_title_text, True, text_color)
                    qr_title_rect = qr_title_surface.get_rect(centerx=SCREEN_WIDTH // 2, top=current_y)
                    draw_text_with_outline(screen, qr_title_text, small_font, text_color, outline_color, qr_title_rect.topleft, anchor="topleft")
                    current_y += qr_title_surface.get_height() + 10
                    qr_rect = qr_surface.get_rect(centerx=SCREEN_WIDTH // 2, top=current_y)
                    screen.blit(qr_surface, qr_rect)
                
                pygame.display.flip()

                retry_deadline = time.monotonic() + 60
                while time.monotonic() < retry_deadline:
                    handle_slideshow_events(SCREEN_WIDTH)
                    time.sleep(0.05)
                continue

            playlist_index = 0
            while 0 <= playlist_index < len(playlist):
                photo_path = playlist[playlist_index]
                
                # Reset photo-change requests.
                global next_photo_requested, previous_photo_requested
                next_photo_requested = False
                previous_photo_requested = False

                logger.info(f"🖼️ Affichage de la photo: {photo_path}")
                
                # --- Fan control ---
                if GPIO_AVAILABLE:
                    try:
                        temp = psutil.sensors_temperatures()['cpu_thermal'][0].current
                        control_fan(temp)
                    except Exception as e:
                        logger.debug(f"Error reading temperature or controlling the fan: {e}")

                # --- FIX: Check that the file exists before attempting to display it ---
                if not os.path.exists(photo_path):
                    logger.warning(f"🖼️ File not found (probably deleted): {photo_path}. Skipping to the next.")
                    playlist_index += 1
                    continue

                # Check whether the file is a video or an image.
                is_video = any(photo_path.lower().endswith(ext) for ext in VIDEO_EXTENSIONS)

                # Write the current photo path to the status file.
                try:
                    with open(CURRENT_PHOTO_FILE, "w") as f:
                        path_to_write = Path(photo_path)
                        if is_video:
                            # For a video, write the thumbnail path for the live preview.
                            thumbnail_path = path_to_write.with_name(f"{path_to_write.stem}_thumbnail.jpg")
                            if thumbnail_path.exists():
                                path_to_write = thumbnail_path

                        # Convert the absolute path to a path relative to the 'static' directory.
                        relative_path = path_to_write.relative_to(Path(BASE_DIR) / 'static')
                        f.write(str(relative_path))
                except Exception as e:
                    logger.info(f"Error writing current photo file: {e}")

                if is_video:
                    display_video(screen, photo_path, SCREEN_WIDTH, SCREEN_HEIGHT, config, main_font_loaded, previous_photo_surface, pygame.time.Clock())
                    
                    # If Pygame was closed for video playback (on all Raspberry Pi models), reinitialize the display.
                    # Wait 0.8 seconds for Wayland to destroy the mpv surface before restarting Pygame.
                    if pi_model in [1, 2, 3, 4, 5]:
                        logger.info("📸 Waiting 0.8s for stabilization before resetting the display...")
                        time.sleep(0.8)
                        screen, SCREEN_WIDTH, SCREEN_HEIGHT = reinit_pygame()
                        # Reload the font because pygame.quit() invalidated it.
                        font_path_config = config.get("clock_font_path", get_default_font_path())
                        clock_font_size_config = int(config.get("clock_font_size", 72))
                        main_font_loaded = load_font(font_path_config, clock_font_size_config)
                        # Restart the music if it was playing.
                        if _current_background_music:
                            play_background_music(_current_background_music)
                    else:
                        # General case (desktop computer).
                        screen = pygame.display.set_mode(
                            (SCREEN_WIDTH, SCREEN_HEIGHT),
                            get_pygame_display_flags()
                        )
                        pygame.mouse.set_visible(False)
                        
                    # Show the resume banner after video playback (with a supported Unicode refresh symbol).
                    if main_font_loaded:
                        draw_loading_banner(screen, "↻ Reprise du diaporama...", SCREEN_WIDTH, SCREEN_HEIGHT, main_font_loaded)
                        time.sleep(0.5)
                else: # C'est une image
                    current_pil_image = None # Initialize to None to ensure it's always defined
                    pan_zoom_plan = None
                    try:
                        current_pil_image = load_slideshow_photo(
                            screen, photo_path, SCREEN_WIDTH, SCREEN_HEIGHT, photo_loader)
                        initial_image = None
                        if current_pil_image is not None and config.get("pan_zoom_enabled", False):
                            pan_zoom_plan = prepare_pan_zoom(current_pil_image, SCREEN_WIDTH, SCREEN_HEIGHT, config)
                            base_image, start_offset, end_offset, start_zoom, end_zoom = pan_zoom_plan
                            base_surface = pygame.image.fromstring(base_image.tobytes(), base_image.size, base_image.mode)
                            initial_frame = render_pan_zoom_frame(base_surface, SCREEN_WIDTH, SCREEN_HEIGHT,
                                                                  start_offset, end_offset, start_zoom, end_zoom, 0)
                            initial_image = Image.frombytes("RGB", (SCREEN_WIDTH, SCREEN_HEIGHT),
                                                            pygame.image.tostring(initial_frame, "RGB"))
                        # Perform transition if it's not the first photo and transition is enabled
                        handle_slideshow_events(SCREEN_WIDTH)
                        if current_pil_image is not None and not (next_photo_requested or previous_photo_requested) and previous_photo_surface is not None and transition_enabled and transition_duration > 0 and transition_type != "none":
                            current_pil_image = perform_transition(screen, previous_photo_surface, photo_path, transition_duration, SCREEN_WIDTH, SCREEN_HEIGHT, main_font_loaded, config, transition_type, initial_image=initial_image, prepared_image=current_pil_image)
                            # If the transition failed (e.g. file not found), move to the next item.
                            if current_pil_image is None:
                                previous_photo_surface = None # Avoid transitioning from an empty surface.
                                playlist_index += 1
                                continue
                    except Exception as e:
                        logger.info(f"🖼️ Error loading or transitioning to photo {photo_path}: {e}")
                        traceback.print_exc()
                        current_pil_image = None # Explicitly set to None on error
                        playlist_index += 1
                        continue

                    if next_photo_requested or previous_photo_requested:
                        previous_photo_surface = screen.copy()
                    elif current_pil_image: # Only proceed if image was successfully loaded
                        display_photo_with_pan_zoom(screen, current_pil_image, SCREEN_WIDTH, SCREEN_HEIGHT, config, main_font_loaded, photo_path, pan_zoom_plan=pan_zoom_plan)
                        previous_photo_surface = screen.copy()
                    else:
                        logger.info(f"🖼️ Skipping photo {photo_path} due to loading error.")

                # --- Navigation logic ---
                if next_photo_requested:
                    playlist_index += 1
                elif previous_photo_requested:
                    playlist_index -= 1
                else: # Comportement normal
                    playlist_index += 1

                # Handle playlist looping.
                if playlist_index >= len(playlist): playlist_index = 0
                if playlist_index < 0: playlist_index = len(playlist) - 1

            # --- Custom playlist completion logic ---
            if is_custom_run:
                logger.info("🖼️ Custom playlist finished. Returning to the standard slideshow.")
                if pygame.mixer.get_init() and pygame.mixer.music.get_busy():
                    pygame.mixer.music.fadeout(2000)
                _current_background_music = None
                is_custom_run = False # The next while-loop iteration will build the default playlist.
                update_status_file({"is_custom": False})
                playlist = [] # Vider la playlist pour forcer la reconstruction.
    except KeyboardInterrupt:
        logger.info("Slideshow stopped manually.")
    except Exception as e:
        logger.info(f"FATAL ERROR IN SLIDESHOW: {e}")
        traceback.print_exc() # Print full traceback for any unhandled error
    finally:
        photo_loader.shutdown(wait=False, cancel_futures=True)
        # --- MODIFICATION SIGALOU 30/01/2026 ---
        # Display power is now managed centrally by `slideshow_manager`.
        # Remove the call here to avoid duplicate calls and race conditions
        # that could prevent the smart plug from turning off correctly.
        # from utils.display_manager import set_display_power
        # set_display_power(False)
        # Clean up the status file on exit.
        if os.path.exists(CURRENT_PHOTO_FILE):
            os.remove(CURRENT_PHOTO_FILE)
        if os.path.exists(STATUS_FILE):
            os.remove(STATUS_FILE)
        pygame.quit()
        if GPIO_AVAILABLE:
            GPIO.cleanup()
        logger.info(f"🖼️ Pygame exited cleanly.")

if __name__ == "__main__":
    start_slideshow()
