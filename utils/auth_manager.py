import json
import subprocess
from werkzeug.security import generate_password_hash
from platform_utils import IS_RASPBERRY_PI, get_credentials_path

CREDENTIALS_PATH = get_credentials_path()

def change_password(new_password: str):
    """
    Updates the password in credentials.json and stores it as a hash.
    Requires sudo privileges on Raspberry Pi to write to /boot/firmware/.
    """
    if not new_password:
        raise ValueError("The new password cannot be empty.")

    try:
        with CREDENTIALS_PATH.open('r', encoding='utf-8') as f:
            credentials = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        # If the file is missing or corrupt, create a new one with the default 'admin' user.
        print(f"Warning: Unable to read {CREDENTIALS_PATH} ({e}). A new file will be created.")
        credentials = {'username': 'admin'}

    # Update the password using a secure hash.
    credentials['password_hash'] = generate_password_hash(new_password)
    # Remove the old plaintext password, if present.
    credentials.pop('password', None)

    # Prepare the content to write.
    new_content = json.dumps(credentials, indent=2)

    if not IS_RASPBERRY_PI:
        CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
        CREDENTIALS_PATH.write_text(new_content, encoding='utf-8')
        return

    try:
        subprocess.run(
            ['sudo', '-n', '/usr/bin/tee', str(CREDENTIALS_PATH)],
            input=new_content,
            text=True,
            check=True,
            timeout=10,
            stdout=subprocess.DEVNULL,  # Keep tee output out of the log.
            stderr=subprocess.PIPE
        )
        print(f"Password successfully updated in {CREDENTIALS_PATH}")
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as e:
        # With text=True, e.stderr is already a string.
        stderr_msg = e.stderr.strip() if hasattr(e, 'stderr') and e.stderr else str(e)
        error_message = (f"Unable to write to {CREDENTIALS_PATH}. "
                         f"Check that the pi user has sudo NOPASSWD privileges. "
                         f"Details: {stderr_msg}")
        print(error_message)
        raise Exception(error_message)