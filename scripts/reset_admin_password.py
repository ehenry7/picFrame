"""Interactively set the web login password for admin."""

import json
import secrets
import sys
from getpass import getpass
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from werkzeug.security import generate_password_hash

from platform_utils import get_credentials_path


def main():
    path = get_credentials_path()
    print(f"Credentials file: {path}")
    try:
        try:
            with path.open(encoding="utf-8") as file:
                credentials = json.load(file)
        except FileNotFoundError:
            credentials = {}
        if not isinstance(credentials, dict):
            raise ValueError("The credentials file must contain a JSON object.")

        password = getpass("New admin password: ")
        if not password.strip():
            raise ValueError("The password must not be empty or whitespace.")
        if password != getpass("Confirm admin password: "):
            raise ValueError("Passwords do not match. No changes were made.")

        credentials["username"] = "admin"
        credentials["password_hash"] = generate_password_hash(password)
        credentials.pop("password", None)
        if not credentials.get("flask_secret_key"):
            credentials["flask_secret_key"] = secrets.token_hex(24)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as file:
            json.dump(credentials, file, indent=2)
            file.write("\n")
    except PermissionError:
        print(
            "Permission denied. On Raspberry Pi, run: sudo python3 scripts/reset_admin_password.py",
            file=sys.stderr,
        )
        return 1
    except (OSError, ValueError, EOFError) as error:
        print(f"Could not update admin credentials: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nPassword update cancelled.", file=sys.stderr)
        return 1

    print("Admin password updated. Log in as admin with your new password.")
    print("No app restart is required.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
