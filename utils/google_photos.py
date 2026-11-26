"""Google Photos import through the Google Photos Picker API.

Google removed third-party read access to user libraries from the Library API
on 2025-04-01, so photos are imported through the Picker API instead: the app
creates a picker session, the user selects photos in Google's picker UI, and
the app downloads the selected media items into ``static/photos/google``.

Credentials live outside the repository:

* ``secrets/google_client.json`` - OAuth client ("Desktop app" type) downloaded
  from Google Cloud Console.
* ``secrets/google_token.json`` - written after the first authorization.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import requests

from utils.photo_import import PHOTO_EXTENSIONS, photo_digest

logger = logging.getLogger(__name__)

SCOPE = "https://www.googleapis.com/auth/photospicker.mediaitems.readonly"
AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
PICKER_ENDPOINT = "https://photospicker.googleapis.com/v1"
DEFAULT_REDIRECT_URI = "http://localhost:8888/oauth2callback"
REQUEST_TIMEOUT = 60

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SECRETS_DIR = PROJECT_ROOT / "secrets"
CLIENT_FILE = SECRETS_DIR / "google_client.json"
TOKEN_FILE = SECRETS_DIR / "google_token.json"
GOOGLE_PHOTOS_DIR = PROJECT_ROOT / "static" / "photos" / "google"


class GooglePhotosError(Exception):
    """Raised for configuration, OAuth and API failures."""


# ---------------------------------------------------------------------------
# OAuth client / token handling
# ---------------------------------------------------------------------------

def _client_credentials() -> tuple[str, str]:
    if not CLIENT_FILE.exists():
        raise GooglePhotosError(
            "Google OAuth client is not configured. Save the client secret "
            f"JSON from Google Cloud Console as {CLIENT_FILE}."
        )
    try:
        data = json.loads(CLIENT_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise GooglePhotosError(f"Cannot read {CLIENT_FILE}: {exc}") from exc
    block = data.get("installed") or data.get("web") or data
    client_id = block.get("client_id")
    client_secret = block.get("client_secret")
    if not client_id or not client_secret:
        raise GooglePhotosError(
            f"{CLIENT_FILE} does not contain client_id/client_secret."
        )
    return client_id, client_secret


def client_configured() -> bool:
    try:
        _client_credentials()
    except GooglePhotosError:
        return False
    return True


def _load_token() -> dict:
    if not TOKEN_FILE.exists():
        raise GooglePhotosError("Google Photos is not connected yet.")
    try:
        return json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise GooglePhotosError(f"Cannot read {TOKEN_FILE}: {exc}") from exc


def _save_token(token: dict) -> None:
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(json.dumps(token, indent=2), encoding="utf-8")
    try:
        TOKEN_FILE.chmod(0o600)
    except OSError:
        pass


def connected() -> bool:
    try:
        token = _load_token()
    except GooglePhotosError:
        return False
    return bool(token.get("refresh_token") or token.get("access_token"))


def disconnect() -> None:
    if TOKEN_FILE.exists():
        TOKEN_FILE.unlink()


def build_authorization_url(redirect_uri: str = DEFAULT_REDIRECT_URI) -> str:
    client_id, _ = _client_credentials()
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
    }
    return f"{AUTH_ENDPOINT}?{urlencode(params)}"


def _token_request(payload: dict) -> dict:
    response = requests.post(TOKEN_ENDPOINT, data=payload, timeout=REQUEST_TIMEOUT)
    try:
        data = response.json()
    except ValueError:
        data = {}
    if response.status_code != 200:
        detail = data.get("error_description") or data.get("error") or response.text[:200]
        raise GooglePhotosError(f"Google token request failed: {detail}")
    return data


def exchange_code(code: str, redirect_uri: str = DEFAULT_REDIRECT_URI) -> dict:
    client_id, client_secret = _client_credentials()
    data = _token_request({
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    })
    token = {
        "access_token": data.get("access_token"),
        "refresh_token": data.get("refresh_token"),
        "expires_at": time.time() + int(data.get("expires_in", 3600)),
        "scope": data.get("scope", SCOPE),
    }
    if not token["access_token"]:
        raise GooglePhotosError("Google did not return an access token.")
    _save_token(token)
    logger.info("Google Photos: authorization completed")
    return token


def _refresh_access_token(token: dict) -> dict:
    client_id, client_secret = _client_credentials()
    refresh_token = token.get("refresh_token")
    if not refresh_token:
        raise GooglePhotosError(
            "No refresh token stored. Reconnect Google Photos from the settings page."
        )
    data = _token_request({
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
    })
    token["access_token"] = data.get("access_token")
    token["expires_at"] = time.time() + int(data.get("expires_in", 3600))
    if data.get("refresh_token"):
        token["refresh_token"] = data["refresh_token"]
    _save_token(token)
    return token


def get_access_token() -> str:
    token = _load_token()
    if not token.get("access_token") or token.get("expires_at", 0) <= time.time() + 60:
        token = _refresh_access_token(token)
    return token["access_token"]


def _api_request(method: str, path: str, **kwargs) -> dict:
    headers = {"Authorization": f"Bearer {get_access_token()}"}
    response = requests.request(
        method,
        f"{PICKER_ENDPOINT}{path}",
        headers=headers,
        timeout=REQUEST_TIMEOUT,
        **kwargs,
    )
    try:
        data = response.json()
    except ValueError:
        data = {}
    if response.status_code >= 400:
        message = (data.get("error") or {}).get("message") or response.text[:200]
        raise GooglePhotosError(f"Google Photos API error: {message}")
    return data


# ---------------------------------------------------------------------------
# Picker API
# ---------------------------------------------------------------------------

def create_session() -> dict:
    """Create a picker session. The returned pickerUri opens Google's picker."""
    return _api_request("POST", "/sessions", json={})


def get_session(session_id: str) -> dict:
    return _api_request("GET", f"/sessions/{session_id}")


def list_media_items(session_id: str) -> list[dict]:
    items: list[dict] = []
    page_token = None
    while True:
        params = {"sessionId": session_id, "pageSize": 100}
        if page_token:
            params["pageToken"] = page_token
        data = _api_request("GET", "/mediaItems", params=params)
        items.extend(data.get("mediaItems", []))
        page_token = data.get("nextPageToken")
        if not page_token:
            return items


def _unique_path(directory: Path, filename: str) -> Path:
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    stem, suffix = candidate.stem, candidate.suffix
    counter = 1
    while True:
        candidate = directory / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def download_item(item: dict, target_dir: Path = GOOGLE_PHOTOS_DIR) -> Path | None:
    """Download one selected media item; returns the written path or None."""
    media_file = item.get("mediaFile") or {}
    base_url = media_file.get("baseUrl")
    filename = media_file.get("filename") or f"{item.get('id', 'photo')}.jpg"
    mime_type = media_file.get("mimeType", "")
    if not base_url:
        return None
    if not mime_type.startswith("image/"):
        logger.info("Google Photos: skipping non-image item %s (%s)", filename, mime_type)
        return None

    suffix = Path(filename).suffix.lower()
    if suffix not in PHOTO_EXTENSIONS:
        filename = f"{Path(filename).stem}.jpg"

    target_dir.mkdir(parents=True, exist_ok=True)
    download_url = f"{base_url}=d"
    response = requests.get(
        download_url,
        headers={"Authorization": f"Bearer {get_access_token()}"},
        timeout=REQUEST_TIMEOUT,
        stream=True,
    )
    if response.status_code >= 400:
        raise GooglePhotosError(
            f"Cannot download {filename}: HTTP {response.status_code}"
        )

    destination = _unique_path(target_dir, filename)
    with open(destination, "wb") as handle:
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if chunk:
                handle.write(chunk)

    # Skip duplicates already present in the folder.
    digest = photo_digest(destination)
    for existing in target_dir.iterdir():
        if existing.is_file() and existing != destination and photo_digest(existing) == digest:
            destination.unlink()
            logger.info("Google Photos: %s already imported, skipped", filename)
            return None
    return destination


def import_session(session_id: str) -> dict:
    """Download all items selected in a picker session into the photo library."""
    items = list_media_items(session_id)
    imported = 0
    errors: list[str] = []
    for item in items:
        try:
            if download_item(item):
                imported += 1
        except Exception as exc:  # noqa: BLE001 - report per-item failures
            name = (item.get("mediaFile") or {}).get("filename", item.get("id", "?"))
            logger.warning("Google Photos: failed to download %s: %s", name, exc)
            errors.append(f"{name}: {exc}")
    logger.info("Google Photos: imported %s item(s), %s error(s)", imported, len(errors))
    return {"imported": imported, "total": len(items), "errors": errors, "source": "google"}


def normalize_code(value: str) -> str:
    """Accept a bare authorization code or the full redirect URL."""
    value = (value or "").strip()
    if "code=" in value:
        parsed = parse_qs(urlparse(value).query)
        return (parsed.get("code") or [value])[0]
    return value
