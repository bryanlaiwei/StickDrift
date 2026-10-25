"""Reconstructed-hands GIFs for lobby visits: one per visit, drawn by ml/hand_replay/ when the visit ends.

The table is created on first insert, so a database set up before it existed needs no manual step.
Reads treat a missing table as "no replay"; nothing here may stop a visit from being saved or shown.
"""
import logging
import threading
import time
from typing import Optional
from uuid import UUID

from .db import pool

log = logging.getLogger(__name__)

TABLE_SQL = """CREATE TABLE IF NOT EXISTS session_hand_replays (
    session_id uuid PRIMARY KEY REFERENCES sessions (session_id) ON DELETE CASCADE,
    gif bytea NOT NULL,
    game text,
    window_start_s real,
    duration_s real,
    frames int,
    has_motion boolean,
    renderer_version text,
    created_at timestamptz NOT NULL DEFAULT now()
)"""
RECHECK_S = 60  # how long a missing table (on read) or a refused CREATE (on insert) is remembered

_exists = False
_looked_at = float("-inf")
_create_failed_at = float("-inf")
_lock = threading.Lock()


def ensure_table() -> bool:
    """Create the table if needed (own connection). False when the database refuses; retried after RECHECK_S."""
    global _exists, _create_failed_at
    if _exists:
        return True
    with _lock:
        if _exists or time.monotonic() - _create_failed_at < RECHECK_S:
            return _exists
        try:
            with pool.connection() as conn:
                conn.execute(TABLE_SQL)
            _exists = True
        except Exception:
            _create_failed_at = time.monotonic()
            log.exception("Could not create session_hand_replays; hand replays are off until it exists")
    return _exists


def exists(conn) -> bool:
    """Whether reads may join the table, checked on the caller's connection without any DDL."""
    global _exists, _looked_at
    if _exists or time.monotonic() - _looked_at < RECHECK_S:
        return _exists
    _looked_at = time.monotonic()
    _exists = conn.execute("SELECT to_regclass('session_hand_replays') IS NOT NULL AS ok").fetchone()["ok"]
    return _exists


def meta_sql(session_id_column: str) -> str:
    """SQL for one visit's replay details as JSON (NULL when there is none). Never selects the GIF itself."""
    return f"""(SELECT jsonb_build_object('game', r.game, 'window_start_s', r.window_start_s,
                                          'duration_s', r.duration_s, 'has_motion', r.has_motion)
                FROM session_hand_replays r WHERE r.session_id = {session_id_column})"""


def store(session_id: UUID, gif: bytes, meta: dict) -> None:
    if not ensure_table():
        raise RuntimeError("the session_hand_replays table is not available")
    with pool.connection() as conn:
        conn.execute(
            """INSERT INTO session_hand_replays
               (session_id, gif, game, window_start_s, duration_s, frames, has_motion, renderer_version)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (session_id) DO UPDATE SET
                 gif = EXCLUDED.gif, game = EXCLUDED.game, window_start_s = EXCLUDED.window_start_s,
                 duration_s = EXCLUDED.duration_s, frames = EXCLUDED.frames, has_motion = EXCLUDED.has_motion,
                 renderer_version = EXCLUDED.renderer_version, created_at = now()""",
            (session_id, gif, meta.get("game"), meta.get("window_start_s"), meta.get("duration_s"),
             meta.get("frames"), meta.get("has_motion"), meta.get("renderer_version")),
        )


def fetch_gif(session_id: UUID) -> Optional[bytes]:
    with pool.connection() as conn:
        if not exists(conn):
            return None
        row = conn.execute("SELECT gif FROM session_hand_replays WHERE session_id = %s", (session_id,)).fetchone()
    return None if row is None else bytes(row["gif"])
