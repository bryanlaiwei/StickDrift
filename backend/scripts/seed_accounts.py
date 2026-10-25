"""Give existing residents login accounts and create a caregiver account.

Idempotent and non-destructive: it only fills in missing usernames/passwords
and creates the caregiver if absent. It never deletes or overwrites game data.

Run from backend/:  .venv/bin/python -m scripts.seed_accounts
Every account created here gets its own random password, printed once. Keep
the output: the passwords are stored only as hashes.

`--reset-caregiver` gives the existing caregiver account a new random password
(accounts seeded before random passwords all shared one).
"""
import re
import secrets
import sys

from argon2 import PasswordHasher

from app.db import pool

CAREGIVER_USERNAME = "caregiver"
CAREGIVER_NAME = "Care Team"

hasher = PasswordHasher()


def slug(alias: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", alias.lower()).strip("-")
    return s[:24] or "resident"


def new_password() -> str:
    return secrets.token_urlsafe(12)


def main(reset_caregiver: bool = False):
    with pool.connection() as conn:
        # Seniors: backfill a username + password for any resident missing one.
        garden_imports_exist = conn.execute(
            "SELECT to_regclass('garden_imports') AS relation"
        ).fetchone()["relation"] is not None
        exclude_imports = (
            """WHERE NOT EXISTS (
                SELECT 1 FROM sessions s JOIN garden_imports i ON i.session_id = s.session_id
                WHERE s.participant_id = p.participant_id
            )""" if garden_imports_exist else ""
        )
        rows = conn.execute(
            f"SELECT p.participant_id, p.alias, p.username FROM participants p {exclude_imports} ORDER BY p.created_at"
        ).fetchall()
        taken = {r["username"].lower() for r in rows if r["username"]}
        for r in rows:
            if r["username"]:
                print(f"senior {r['alias']}: already has username '{r['username']}', left as is")
                continue
            base = slug(r["alias"])
            name, i = base, 2
            while name.lower() in taken:
                name = f"{base[:22]}-{i}"
                i += 1
            taken.add(name.lower())
            password = new_password()
            conn.execute(
                "UPDATE participants SET username = %s, password_hash = %s WHERE participant_id = %s",
                (name, hasher.hash(password), r["participant_id"]),
            )
            print(f"senior {r['alias']}: login '{name}' / '{password}'")

        # Caregiver: create once.
        exists = conn.execute(
            "SELECT 1 FROM caregivers WHERE lower(username) = lower(%s)", (CAREGIVER_USERNAME,)
        ).fetchone()
        if exists and reset_caregiver:
            password = new_password()
            conn.execute(
                "UPDATE caregivers SET password_hash = %s WHERE lower(username) = lower(%s)",
                (hasher.hash(password), CAREGIVER_USERNAME),
            )
            print(f"caregiver: login '{CAREGIVER_USERNAME}' / '{password}' (password reset)")
        elif exists:
            print(f"caregiver '{CAREGIVER_USERNAME}': already exists, left as is")
        else:
            password = new_password()
            conn.execute(
                "INSERT INTO caregivers (username, password_hash, display_name) VALUES (%s, %s, %s)",
                (CAREGIVER_USERNAME, hasher.hash(password), CAREGIVER_NAME),
            )
            print(f"caregiver: login '{CAREGIVER_USERNAME}' / '{password}'")


if __name__ == "__main__":
    pool.open()
    try:
        main(reset_caregiver="--reset-caregiver" in sys.argv[1:])
    finally:
        pool.close()
    print("done", file=sys.stderr)
