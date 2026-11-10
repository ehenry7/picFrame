import json
import os
from platform_utils import get_default_font_path
from utils.weather_cities import DEFAULT_WEATHER_CITY, get_city

CONFIG_PATH = os.path.join(os.path.dirname(__file__), '..', 'config', 'config.json')

def create_default_config():
    """Create and return the default configuration dictionary, the single source of truth."""
    return {
        "level_log": "INFO",
        "display_duration": 10,
        "active_start": "07:00",
        "active_end": "22:00",
        "display_width": 1920,
        "display_height": 1080,
        "pan_zoom_factor": 1.15,
        "pan_zoom_start_factor": 1.0,
        "pan_zoom_enabled": False,
        "transition_enabled": True,
        "transition_type": "fade",
        "transition_duration": 1.0,
        "transition_fps": "auto",
        "video_audio_enabled": False,
        "video_audio_output": "auto",
        "video_audio_volume": 100,
        "display_sources": ["usb", "smartphone", "invités"],
        "show_clock": True,
        "clock_format": "%H:%M",
        "clock_color": "#FFFFFF",
        "clock_outline_color": "#000000",
        "clock_font_size": 72,
        "clock_font_path": get_default_font_path(),
        "clock_offset_x": 0,
        "clock_offset_y": 0,
        "clock_position": "center",
        "clock_background_enabled": False,
        "clock_background_color": "#00000080",
        "show_date": True,
        "date_format": "%A %d %B %Y",
        "show_weather": True,
        "weather_city": DEFAULT_WEATHER_CITY,
        "weather_units": "metric",
        "weather_update_interval_minutes": 60,
        "show_tides": False,
        "tide_latitude": "",
        "tide_longitude": "",
        "stormglass_api_key": "",
        "tide_offset_x": 0,
        "tide_offset_y": 0,
        # --- Smart plug settings ---
        "smart_plug_enabled": False,
        "smart_plug_on_url": "",
        "smart_plug_off_url": "",
        "smart_plug_on_delay": 5,
        "smart_plug_status_url": "",
        "home_assistant_token": "",
        "wifi_ssid": "",
        "wifi_country": "FR",
        "wifi_password": "",
        "timezone": "Europe/Paris",
        "info_display_duration": 5,
        "screen_height_percent": 100,
        "favorite_boost_factor": 2,
        "video_hwdec_enabled": False,
        
        # --- New photo metadata settings ---
        "show_photo_date": False,
        "photo_date_format": "%Y",
        "country_flag_size": "192x144",
        "country_flag_opacity": 1,
        "show_country_flag": True,        
        "show_photo_location": True,
        "photo_location_format": "city_country",
        "photo_metadata_color": "#ffffff",
        "photo_metadata_outline_color": "#000000",
        "photo_metadata_font_size": 23,
        "photo_metadata_font_path": get_default_font_path(),
        "photo_metadata_offset_x": 0,
        "photo_metadata_offset_y": 0,
        "photo_metadata_position": "bottom_left",
        "photo_metadata_background_enabled": True,
        "photo_metadata_background_color": "#00000080",
        
        "anniversary_boost_enabled": True,
        "anniversary_boost_factor": 2
    }

_config_cache = None
_last_config_load = 0

def _without_retired_settings(config):
    cleaned = {key: value for key, value in config.items()
               if not key.startswith(("voice_control_", "porcupine_", "smb_", "telegram_", "immich_"))
               and key not in {"notification_sound_volume", "album_name", "random_content_in_album",
                               "max_photos_to_download", "photo_source", "skip_initial_auto_import",
                               "weather_api_key"}}
    if "weather_city" in cleaned and not get_city(cleaned["weather_city"]):
        cleaned["weather_city"] = DEFAULT_WEATHER_CITY
    if "display_sources" in cleaned:
        cleaned["display_sources"] = [source for source in cleaned["display_sources"]
                                     if source != "samba"]
    return cleaned

def load_config():
    """Load configuration from file and merge it with the defaults."""
    global _config_cache, _last_config_load
    import time
    if _config_cache is not None and (time.time() - _last_config_load < 2.0):
        return _config_cache

    default_config = create_default_config()
    
    if not os.path.exists(CONFIG_PATH):
        # If the config file does not exist, create it with the default values.
        save_config(default_config)
        _config_cache = default_config
        _last_config_load = time.time()
        return default_config

    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            user_config = json.load(f)
        
        # Merge user configuration with the defaults.
        # This adds new configuration keys without overwriting existing user settings.
        merged_config = default_config.copy()
        merged_config.update(_without_retired_settings(user_config))
        _config_cache = merged_config
        _last_config_load = time.time()
        return merged_config
    except (json.JSONDecodeError, IOError) as e:
        # If the file is corrupt or unreadable, return the defaults to avoid an application crash.
        print(f"Warning: Unable to load {CONFIG_PATH} ({e}). Using the default configuration.")
        _config_cache = default_config
        _last_config_load = time.time()
        return default_config

def save_config(config):
    """Save the configuration to a JSON file."""
    global _config_cache, _last_config_load
    import time
    config = _without_retired_settings(config)
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4, ensure_ascii=False)
    _config_cache = config
    _last_config_load = time.time()
