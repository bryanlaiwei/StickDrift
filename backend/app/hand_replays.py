"""Reconstructed-hands GIFs for lobby visits: one per visit, drawn by ml/hand_replay/ when the visit ends."""
from typing import Optional
from uuid import UUID

from .db import pool


def meta_sql(session_id_column: str) -> str:
    """SQL for one visit's replay details as JSON (NULL when there is none). Never selects the GIF itself."""
    return f"""(SELECT jsonb_build_object('game', r.game, 'window_start_s', r.window_start_s,
                                          'duration_s', r.duration_s, 'has_motion', r.has_motion)
                FROM session_hand_replays r WHERE r.session_id = {session_id_column})"""


def store(session_id: UUID, gif: bytes, meta: dict) -> None:
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
        row = conn.execute("SELECT gif FROM session_hand_replays WHERE session_id = %s", (session_id,)).fetchone()
    return None if row is None else bytes(row["gif"])
