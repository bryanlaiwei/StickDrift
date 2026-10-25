"""What caregivers read about live sessions: a short brief, the full state, and samples.

These read Tiger Data only, so a caregiver on any computer can watch any resident. The HTTP
routes (routes.py) and the WebSocket (stream.py) both use them.
"""
from typing import List, Optional
from uuid import UUID

from .. import hand_replays
from ..db import pool
from ..measurements import SessionMetrics
from .session import ACTIVE, STALE_S, WATCH_COLUMNS
from .visit import REPLAY_TIMEOUT_S

RECENT_H = 6             # finished sessions listed under "Just finished"

BRIEF_COLUMNS = """live_id, participant_id, name, status, level, levels, levels_done, synthetic,
                   started_at, ended_at, updated_at, db_session_id, error, host,
                   result->'scores' AS tcn_scores,
                   result->'rat' AS rat,
                   EXTRACT(EPOCH FROM (COALESCE(ended_at, now()) - started_at)) AS elapsed_s,
                   updated_at < now() - make_interval(secs => %s) AS stale"""


def brief(row: dict) -> dict:
    status = row["status"]
    error = row["error"]
    if status in ACTIVE and row["stale"]:
        status = "lost"
        error = error or ("The resident's lobby tab stopped sending updates, so it was probably closed or "
                          "went offline. The games played so far are saved.")
    return {
        "live_id": row["live_id"], "resident_id": row["participant_id"], "name": row["name"],
        "status": status, "level": row["level"], "levels": row["levels"], "levels_done": row["levels_done"],
        "synthetic": row["synthetic"], "started_at": row["started_at"],
        "elapsed_s": round(float(row["elapsed_s"]), 1), "tcn_scores": row["tcn_scores"],
        "rat": row["rat"],
        "db_session_id": row["db_session_id"], "error": error,
    }


def recent() -> List[dict]:
    """Sessions playing now or finished in the last RECENT_H hours, newest first."""
    with pool.connection() as conn:
        rows = conn.execute(
            f"""SELECT {BRIEF_COLUMNS} FROM live_sessions
                WHERE updated_at > now() - make_interval(hours => %s)
                ORDER BY started_at DESC LIMIT 20""",
            (STALE_S, RECENT_H),
        ).fetchall()
    return [brief(r) for r in rows]


def _replay_pending(row: dict) -> bool:
    """A finished visit whose hand GIF may still be drawing (it runs beside the report)."""
    if "lobby" not in (row["levels"] or []) or row["hand_replay"] is not None:
        return False
    if row["status"] == "scoring":
        return not row["stale"]
    ago = row["ended_ago_s"]
    return (row["status"] in ("finished", "ended") and row["db_session_id"] is not None
            and ago is not None and float(ago) < REPLAY_TIMEOUT_S + 15)


def state(live_id: UUID) -> Optional[dict]:
    """Everything about a live session except its samples, or None if it doesn't exist."""
    with pool.connection() as conn:
        row = conn.execute(
            f"""SELECT {BRIEF_COLUMNS}, trial, phase, seq, metrics, result,
                       EXTRACT(EPOCH FROM (now() - ended_at)) AS ended_ago_s,
                       {hand_replays.meta_sql("live_sessions.db_session_id")} AS hand_replay
                FROM live_sessions WHERE live_id = %s""",
            (STALE_S, live_id),
        ).fetchone()
    if row is None:
        return None
    return {**brief(row), "trial": row["trial"], "phase": row["phase"], "seq": row["seq"],
            "metrics": row["metrics"] or SessionMetrics().summary(), "result": row["result"],
            "hand_replay_ready": row["hand_replay"] is not None, "hand_replay": row["hand_replay"],
            "hand_replay_pending": _replay_pending(row)}


def samples_since(live_id: UUID, since: int, limit: int) -> List[list]:
    """The newest `limit` samples after `since`, oldest first."""
    with pool.connection() as conn:
        rows = conn.execute(
            f"""SELECT {", ".join(WATCH_COLUMNS)} FROM live_samples WHERE live_id = %s AND seq > %s
                ORDER BY seq DESC LIMIT %s""",
            (live_id, max(since, 0), limit),
        ).fetchall()
    return [list(r.values()) for r in reversed(rows)]
