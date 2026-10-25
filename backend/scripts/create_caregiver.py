"""Create the shared caregiver login, or give it a new password.

Residents sign themselves up, and caregivers can register with CAREGIVER_INVITE_CODE;
this is the shortcut for a first caregiver account. The password is random and
printed once: it is stored only as a hash.

Run from backend/:  .venv/bin/python -m scripts.create_caregiver [--reset-password]
"""
import secrets
import sys

from argon2 import PasswordHasher

from app.db import pool

USERNAME = "caregiver"
DISPLAY_NAME = "Care Team"


def main(reset_password: bool = False):
    password = secrets.token_urlsafe(12)
    password_hash = PasswordHasher().hash(password)
    with pool.connection() as conn:
        exists = conn.execute("SELECT 1 FROM caregivers WHERE lower(username) = lower(%s)", (USERNAME,)).fetchone()
        if exists and not reset_password:
            print(f"caregiver '{USERNAME}' already exists; pass --reset-password to give it a new one")
            return
        if exists:
            conn.execute("UPDATE caregivers SET password_hash = %s WHERE lower(username) = lower(%s)",
                         (password_hash, USERNAME))
        else:
            conn.execute("INSERT INTO caregivers (username, password_hash, display_name) VALUES (%s, %s, %s)",
                         (USERNAME, password_hash, DISPLAY_NAME))
    print(f"caregiver login: '{USERNAME}' / '{password}'")


if __name__ == "__main__":
    pool.open()
    try:
        main(reset_password="--reset-password" in sys.argv[1:])
    finally:
        pool.close()
