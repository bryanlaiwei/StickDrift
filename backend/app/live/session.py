"""A live session's state and how it is stored.

The lobby tab posts samples and game events to /live/ingest with a token. Everything about a
running session lives in Tiger Data: `live_sessions` holds its status, token hash and running
measurements, `live_samples` its samples and `live_events` the in-game events the visit report
needs. Each request loads the session row (locked), applies the batch and writes it back in one
transaction (`apply_batch`). So any API process can serve any request, the API can run more than
one worker, and restarting it does not lose a visit in progress.
"""
import hashlib
import json
import logging
import secrets
import socket
import threading
from datetime import datetime, timezone
from typing import Any, List, Optional, Tuple
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from ..db import pool
from ..measurements import MOTION_KEYS, SAMPLE_KEYS, SessionMetrics

log = logging.getLogger(__name__)

HOST = socket.gethostname()
CHANNEL = "stickdrift_live"  # NOTIFY channel; caregiver APIs LISTEN on it (see stream.py)
NOTIFY_MAX = 7000            # Postgres caps a payload at 8000 bytes; bigger batches send only a pointer

ACTIVE = {"ready", "playing", "scoring"}
OPEN = sorted(ACTIVE - {"scoring"})  # statuses that still accept samples
STATE_EVERY_S = 0.5      # how often the caregiver-facing measurements are rewritten and announced
STALE_S = 20             # an active row older than this lost its game or tab
GAMES = ("apple", "fish", "rat")
KEEP_EVENTS = {"trial", "wrong", "basket", "expired", "result", "trace", "slam", "miss", "card_rat"}
# live_samples column for each SAMPLE_KEYS entry; the table keeps its older short names.
LIVE_COLUMNS = tuple({"target_lx": "tgt_lx", "target_ly": "tgt_ly", "target_rx": "tgt_rx", "target_ry": "tgt_ry",
                      "on_l": "reached_l", "on_r": "reached_r", "cursor_lx": "cur_lx", "cursor_ly": "cur_ly",
                      "cursor_rx": "cur_rx", "cursor_ry": "cur_ry"}.get(k, k) for k in SAMPLE_KEYS)
# What watchers get for each sample (samples_since and the NOTIFY payload): seq, level, then the sample.
WATCH_COLUMNS = ("seq", "level", *LIVE_COLUMNS)

def now():
    return datetime.now(timezone.utc)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _num(v) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


class LiveSession:
    """One live session's state, loaded from live_sessions for each request and written back after it."""

    def __init__(self, resident_id: UUID, name: str, keyboard: bool, live_id: Optional[UUID] = None):
        self.id = live_id or uuid4()
        self.resident_id = resident_id
        self.name = name
        self.keyboard = keyboard
        self.lock = threading.Lock()
        self.created_at = now()
        self.ended_at: Optional[datetime] = None
        self.status = "ready"
        self.level: Optional[str] = None
        self.levels: List[str] = ["lobby", *GAMES]
        self.levels_done: List[str] = []
        self.trial: Optional[int] = None
        self.phase: Optional[str] = None
        self.synthetic = keyboard
        self.seq = 0
        self.metrics = SessionMetrics()
        self.result: Optional[dict] = None
        self.db_session_id: Optional[UUID] = None
        self.error: Optional[str] = None
        self.needs_save = False  # a lobby game just ended: copy the visit so far into the resident's history

    @classmethod
    def from_row(cls, row: dict) -> "LiveSession":
        s = cls(row["participant_id"], row["name"], row["keyboard"], live_id=row["live_id"])
        s.created_at, s.ended_at = row["started_at"], row["ended_at"]
        s.status, s.level = row["status"], row["level"]
        s.levels, s.levels_done = list(row["levels"] or []), list(row["levels_done"] or [])
        s.trial, s.phase, s.synthetic = row["trial"], row["phase"], row["synthetic"]
        s.seq = row["seq"]
        s.metrics = SessionMetrics.from_state(row["running"])
        s.result, s.db_session_id, s.error = row["result"], row["db_session_id"], row["error"]
        return s

    def ingest(self, items: List[Any]) -> Tuple[List[tuple], List[tuple], bool]:
        """Apply events and samples; returns (sample rows, event rows, whether status changed)."""
        rows: List[tuple] = []
        events: List[tuple] = []
        changed = False
        with self.lock:
            for item in items:
                if isinstance(item, dict):
                    if item.get("type") in KEEP_EVENTS and self.level in GAMES:
                        events.append((self.id, self.level, Jsonb(item)))
                    changed |= self._event(item)
                elif isinstance(item, list) and len(item) in (17, 23) and self.level:
                    # SAMPLE_KEYS, plus MOTION_KEYS when the pad reports them
                    core = item[:17]
                    motion = [_num(v) for v in item[17:23]] if len(item) == 23 else [None] * 6
                    self.seq += 1
                    self.metrics.add(core)
                    self.trial, self.phase = core[1], core[2]
                    rows.append((self.id, self.seq, self.level, *core, *motion))
        return rows, events, changed

    def _event(self, e: dict) -> bool:
        kind = e.get("type")
        if kind == "session_start":
            self.synthetic = bool(e.get("synthetic")) or self.keyboard
            self.levels = [str(x) for x in e.get("levels", [])][:8]
        elif kind == "level_start":
            self.level = str(e.get("level"))
            self.metrics.start_level(self.level)
            self.status = "playing"
        elif kind == "result" and self.level in GAMES:
            # A game only sends its result when it was played through; leaving early sends none.
            if self.level not in self.levels_done:
                self.levels_done.append(self.level)
            self.needs_save = True
        elif kind == "level_end":
            self.needs_save = self.needs_save or self.level in GAMES  # also when left early
            self.status, self.level, self.trial, self.phase = "ready", None, None, None
        elif kind == "input":  # the lobby saw a controller after starting as "keyboard"
            if e.get("source") == "gamepad":
                self.synthetic = self.keyboard = False
        elif kind == "trial" and self.level:
            self.metrics.add_trial(e)
        else:
            return False
        return True


# ---- Tiger Data -------------------------------------------------------------------

SESSION_COLUMNS = """live_id, participant_id, name, status, level, levels, levels_done, trial, phase, synthetic,
                     keyboard, seq, running, result, db_session_id, error, started_at, ended_at"""


def create(s: LiveSession) -> str:
    """Store a new session and return its token. Only the token's hash is kept."""
    token = secrets.token_urlsafe(32)
    with pool.connection() as conn:
        conn.execute(
            """INSERT INTO live_sessions
               (live_id, participant_id, name, status, levels, token_hash, keyboard, synthetic, host,
                running, started_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())""",
            (s.id, s.resident_id, s.name, s.status, Jsonb(s.levels), token_hash(token), s.keyboard, s.synthetic, HOST,
             Jsonb(s.metrics.to_state()), s.created_at),
        )
        conn.execute("SELECT pg_notify(%s, %s)", (CHANNEL, json.dumps({"i": str(s.id), "st": 1})))
    return token


def write(conn, s: LiveSession, announce: bool = True):
    """Write the session back. `announce` also refreshes the caregiver-facing measurements and tells watchers."""
    with s.lock:
        metrics = s.metrics.summary() if announce else None
        values = (s.status, s.level, Jsonb(s.levels), Jsonb(s.levels_done), s.trial, s.phase, s.synthetic,
                  s.keyboard, s.seq, Jsonb(s.metrics.to_state()),
                  None if metrics is None else Jsonb(metrics), None if s.result is None else Jsonb(s.result),
                  s.db_session_id, s.error, s.ended_at, announce, s.id)
    conn.execute(
        """UPDATE live_sessions SET
             status = %s, level = %s, levels = %s, levels_done = %s, trial = %s, phase = %s, synthetic = %s,
             keyboard = %s, seq = %s, running = %s,
             metrics = COALESCE(%s, metrics),
             result = %s,
             db_session_id = COALESCE(%s, db_session_id),
             error = %s, ended_at = %s,
             updated_at = CASE WHEN %s THEN now() ELSE updated_at END
           WHERE live_id = %s""",
        values,
    )
    if announce:
        # Same transaction, so watchers are only told once the row is committed.
        conn.execute("SELECT pg_notify(%s, %s)", (CHANNEL, json.dumps({"i": str(s.id), "st": 1})))


def persist(s: LiveSession):
    try:
        with pool.connection() as conn:
            write(conn, s)
    except Exception:
        log.exception("Could not write live session %s to TigerData", s.id)


def load(live_id: UUID) -> Optional[LiveSession]:
    with pool.connection() as conn:
        row = conn.execute(f"SELECT {SESSION_COLUMNS} FROM live_sessions WHERE live_id = %s", (live_id,)).fetchone()
    return None if row is None else LiveSession.from_row(row)


def _store_samples(conn, rows: List[tuple]):
    if not rows:
        return
    columns = ("live_id", *WATCH_COLUMNS, *MOTION_KEYS)
    with conn.cursor() as cur:
        cur.executemany(
            f"""INSERT INTO live_samples ({", ".join(columns)})
                VALUES ({", ".join(["%s"] * len(columns))}) ON CONFLICT DO NOTHING""",
            rows,
        )
        # Small batches ride in the notification itself, so watchers don't need to read the table.
        live_id = str(rows[0][0])
        watched = slice(1, 1 + len(WATCH_COLUMNS))
        payload = json.dumps({"i": live_id, "s": [list(r[watched]) for r in rows]}, separators=(",", ":"))
        if len(payload) > NOTIFY_MAX:
            payload = json.dumps({"i": live_id, "q": rows[-1][1]})
        cur.execute("SELECT pg_notify(%s, %s)", (CHANNEL, payload))


def _store_events(conn, rows: List[tuple]):
    if rows:
        with conn.cursor() as cur:
            cur.executemany("INSERT INTO live_events (live_id, level, event) VALUES (%s, %s, %s)", rows)


def apply_batch(conn, token: str, items: List[Any]) -> Optional[LiveSession]:
    """Lock the open session behind `token`, apply a batch and write it back. None if no such open session."""
    row = conn.execute(
        f"""SELECT {SESSION_COLUMNS}, EXTRACT(EPOCH FROM (now() - updated_at)) AS quiet_s
            FROM live_sessions WHERE token_hash = %s AND status = ANY(%s) FOR UPDATE""",
        (token_hash(token), OPEN),
    ).fetchone()
    if row is None:
        return None
    s = LiveSession.from_row(row)
    samples, events, changed = s.ingest(items)
    _store_samples(conn, samples)
    _store_events(conn, events)
    write(conn, s, announce=changed or float(row["quiet_s"]) >= STATE_EVERY_S)
    return s
