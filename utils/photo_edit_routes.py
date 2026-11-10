"""Authenticated photo-edit details, comparison and manual location APIs."""

from pathlib import Path

from flask import jsonify, request, send_file

from utils.auth import login_required
from utils.metadata_utils import get_photo_metadata, format_preview_location, _preview_country_codes
from utils.photo_edits import load_edits, update_edit, validate_date


def register_photo_edit_routes(app, prepared_root, translate):
    root = Path(prepared_root).resolve()

    def prepared_photo(photo):
        if not isinstance(photo, str) or "\\" in photo or len(photo.split("/")) != 2:
            raise ValueError("Invalid photo path.")
        path = (root / photo).resolve()
        if not path.is_relative_to(root) or not path.is_file() or path.suffix.lower() != ".jpg":
            raise ValueError("Prepared photo not found.")
        return path

    @app.route("/api/photo_edits", methods=["GET", "POST"])
    @login_required
    def photo_edits():
        try:
            data = request.get_json() if request.method == "POST" else request.args
            if not isinstance(data, dict) and request.method == "POST":
                raise ValueError("Provide photo edit data.")
            photo = data.get("photo")
            path = prepared_photo(photo)
            if request.method == "POST":
                changes = {}
                if "location" in data:
                    location = data.get("location")
                    if location is not None:
                        if not isinstance(location, dict) or set(location) != {"city", "country"}:
                            raise ValueError("Provide city and country.")
                        if any(not isinstance(value, str) or len(value) > 160 for value in location.values()):
                            raise ValueError("Location fields must be text of at most 160 characters.")
                        location = {key: value.strip() for key, value in location.items()}
                        codes = _preview_country_codes()
                        country = location["country"]
                        if country and country.lower() not in codes and country.casefold() not in {
                                name.casefold() for name in codes.values()}:
                            raise ValueError("Choose a country from the list.")
                        if country.lower() in codes:
                            location["country"] = codes[country.lower()]
                    changes["location"] = location
                if "date" in data:
                    date = data.get("date")
                    if date is not None:
                        date = validate_date(date)
                    changes["date"] = date
                if changes:
                    update_edit(photo, changes)
            metadata = get_photo_metadata(path)
            edit = load_edits().get(photo, {})
            if request.method == "GET" and request.args.get("before") == "1":
                backup = root.parent / ".backups" / photo
                response = send_file(backup if backup.is_file() else path, mimetype="image/jpeg")
                response.headers["Cache-Control"] = "no-store"
                return response
            return jsonify(success=True, strength=edit.get("strength", 1.0),
                           city=metadata.get("city") or "", country=metadata.get("country") or "",
                           manual_location="location" in edit,
                           date=metadata.get("dateTimeOriginal") or "",
                           manual_date="date" in edit,
                           location_text=format_preview_location(metadata, translate),
                           countries=sorted(_preview_country_codes().values()))
        except ValueError as error:
            app.logger.warning("Photo edits rejected: %s", error)
            return jsonify(success=False, message=str(error)), 400
        except (OSError, TypeError) as error:
            app.logger.exception("Photo edit settings failed")
            return jsonify(success=False, message=str(error)), 500
