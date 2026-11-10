import os
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PLAYLISTS_PATH = BASE_DIR / 'config' / 'playlists.json'

def load_playlists():
    """Load the playlist list from the JSON file."""
    if not PLAYLISTS_PATH.exists():
        return []
    try:
        with open(PLAYLISTS_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []

def save_playlists(playlists_data):
    """Save the complete playlist list to the JSON file."""
    with open(PLAYLISTS_PATH, 'w', encoding='utf-8') as f:
        json.dump(playlists_data, f, indent=2)