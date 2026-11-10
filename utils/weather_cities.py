"""List Israeli cities available for Open-Meteo weather data."""

CITIES = [
    {"name": "Yokneam Illit",  "lat": 32.6600, "lon": 35.1100},
    {"name": "Tel Aviv",       "lat": 32.0853, "lon": 34.7818},
    {"name": "Jerusalem",      "lat": 31.7683, "lon": 35.2137},
    {"name": "Haifa",          "lat": 32.8192, "lon": 34.9992},
    {"name": "Rishon LeZion",  "lat": 31.9730, "lon": 34.7925},
    {"name": "Petah Tikva",    "lat": 32.0833, "lon": 34.8833},
    {"name": "Ashdod",         "lat": 31.8044, "lon": 34.6553},
    {"name": "Netanya",        "lat": 32.3286, "lon": 34.8567},
    {"name": "Be'er Sheva",    "lat": 31.2518, "lon": 34.7913},
    {"name": "Ashkelon",       "lat": 31.6658, "lon": 34.5664},
    {"name": "Rehovot",        "lat": 31.8914, "lon": 34.8078},
    {"name": "Nazareth",       "lat": 32.7021, "lon": 35.2978},
    {"name": "Tiberias",       "lat": 32.7897, "lon": 35.5247},
    {"name": "Eilat",          "lat": 29.5500, "lon": 34.9500},
]

WEATHER_TIMEZONE = "Asia/Jerusalem"
DEFAULT_WEATHER_CITY = "Yokneam Illit"


def get_city(name):
    """Return the matching city's dictionary, or None if it is unknown."""
    for city in CITIES:
        if city["name"] == name:
            return city
    return None
