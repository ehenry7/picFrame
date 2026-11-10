import json
import secrets
from werkzeug.security import generate_password_hash
import argparse
import sys

def generate_random_password(length=12):
    """Generate a secure, easy-to-type random password."""
    # Exclude ambiguous characters (I, l, 1, O, 0) and punctuation for easier typing.
    alphabet = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    password = ''.join(secrets.choice(alphabet) for i in range(length))
    return password

def create_credentials_file(output_path, username="admin"):
    """Generate a password, hash it, and create credentials.json."""
    password = generate_random_password()
    flask_secret_key = secrets.token_hex(24) # Generate a secure 24-byte key for Flask.
    
    # Hash the password using a secure method.
    # Werkzeug handles salting automatically.
    password_hash = generate_password_hash(password)
    
    credentials = {
        "username": username,
        "password_hash": password_hash,
        "flask_secret_key": flask_secret_key
    }
    
    try:
        with open(output_path, 'w') as f:
            json.dump(credentials, f, indent=2)
        
        # Display the credentials so the user can record them.
        # This is the only time the plaintext password is shown.
        print("\n" + "="*60, file=sys.stderr)
        print("✅ Secure credentials file created.", file=sys.stderr)
        print("\n" + "-"*60, file=sys.stderr)
        print("⚠️  SAVE THESE CREDENTIALS; THEY WILL NOT BE SHOWN AGAIN  ⚠️", file=sys.stderr)
        print(f"   Username: {username}", file=sys.stderr)
        print(f"   Password: {password}", file=sys.stderr)
        print("="*60 + "\n", file=sys.stderr)

    except Exception as e:
        print(f"ERROR: Unable to create credentials file at '{output_path}'.", file=sys.stderr)
        print(f"Details: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create a secure credentials.json file with a random password.")
    parser.add_argument(
        '--output',
        required=True,
        help="Full path of the credentials.json file to create."
    )
    parser.add_argument(
        '--username',
        default='admin',
        help="Username to create (default: admin)."
    )
    
    args = parser.parse_args()
    
    create_credentials_file(args.output, args.username)