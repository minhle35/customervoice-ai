"""Generate a cryptographically secure database password."""

import secrets
import string
import argparse

SETTINGS_DIR = "settings"


def generate_password(length: int = 32, file_name: str = "db_password.txt") -> str:
    # RDS requires: uppercase, lowercase, digits, special chars
    # Exclude characters that cause issues in connection strings: @ / : ? # [ ] @
    safe_special = "!$^&*()-_=+[]{}|;,.<>"
    alphabet = string.ascii_letters + string.digits + safe_special

    while True:
        password = "".join(secrets.choice(alphabet) for _ in range(length))
        # Ensure all character classes are present
        has_upper = any(c in string.ascii_uppercase for c in password)
        has_lower = any(c in string.ascii_lowercase for c in password)
        has_digit = any(c in string.digits for c in password)
        has_special = any(c in safe_special for c in password)
        if has_upper and has_lower and has_digit and has_special:
            with open(f"{SETTINGS_DIR}/{file_name}", "w") as f:
                f.write(password)
            return password


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate a secure password. Saved into ./settings/"
    )
    parser.add_argument(
        "--length", type=int, default=32, help="Length of the password (default: 32)"
    )
    parser.add_argument(
        "--name",
        type=str,
        default="db_password.txt",
        help="Name of the output file (default: db_password.txt)",
    )
    args = parser.parse_args()

    password = generate_password(length=args.length, file_name=args.name)
    print(f"\nGenerated password:\n  {password}")
