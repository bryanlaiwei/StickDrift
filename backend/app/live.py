"""Live sessions: the resident's web lobby streamed to caregivers.

The lobby tab posts samples and game events to /live/ingest with a token. Everything about a running session lives in TigerData:
`live_sessions` holds its status, token hash and running measurements,
`live_samples` its samples and `live_events` the in-game events the visit report
needs. Each request loads the session row (locked), applies the batch and writes
it back in one transaction. So any API process can serve any request, the API can
run more than one worker, and restarting it does not lose a visit in progress:
the tab keeps posting and the next request picks up where the last one stopped.

Caregivers on any computer sharing the database watch through live_stream.py.
"""
import hashlib
import json
import logging
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from . import hand_replays
from .auth import current_caregiver, current_senior
from .db import pool
from .measurements import MOTION_KEYS, SAMPLE_KEYS, SessionMetrics, game_summary

log = logging.getLogger(__name__)
router = APIRouter(tags=["live"])

ROOT = Path(__file__).resolve().parents[2]
GAME_PYTHON = Path(os.environ.get("STICKDRIFT_GAME_PYTHON", ROOT / ".venv" / "bin" / "python"))
HOST = socket.gethostname()
CHANNEL = "stickdrift_live"  # NOTIFY channel; caregiver APIs LISTEN on it (see live_stream.py)
NOTIFY_MAX = 7000            # Postgres caps a payload at 8000 bytes; bigger batches send only a pointer

ACTIVE = {"ready", "playing", "scoring"}
OPEN = sorted(ACTIVE - {"scoring"})  # statuses that still accept samples
STATE_EVERY_S = 0.5      # how often the caregiver-facing measurements are rewritten and announced
STALE_S = 20             # an active row older than this lost its game or tab
RECENT_H = 6             # finished sessions listed under "Just finished"
LOBBY_GAMES = ("apple", "fish", "rat")
KEEP_EVENTS = {"trial", "wrong", "basket", "expired", "result", "trace", "slam", "miss", "card_rat"}
MAX_FRAMES = 24000       # a visit is a few minutes at 60 Hz; the report stops reading there
# live_samples column for each SAMPLE_KEYS entry; the table keeps its older short names.
LIVE_COLUMNS = tuple({"target_lx": "tgt_lx", "target_ly": "tgt_ly", "target_rx": "tgt_rx", "target_ry": "tgt_ry",
                      "on_l": "reached_l", "on_r": "reached_r", "cursor_lx": "cur_lx", "cursor_ly": "cur_ly",
                      "cursor_rx": "cur_rx", "cursor_ry": "cur_ry"}.get(k, k) for k in SAMPLE_KEYS)
# What watchers get for each sample (samples_since and the NOTIFY payload): seq, level, then the sample.
WATCH_COLUMNS = ("seq", "level", *LIVE_COLUMNS)

# Applied at startup (and kept in backend/sql/schema.sql), so a database set up before
# sessions moved out of the API's memory needs no manual step.
SCHEMA_SQL = """
ALTER TABLE live_sessions ADD COLUMN IF NOT EXISTS token_hash TEXT;
ALTER TABLE live_sessions ADD COLUMN IF NOT EXISTS keyboard BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE live_sessions ADD COLUMN IF NOT EXISTS running JSONB;
CREATE UNIQUE INDEX IF NOT EXISTS live_sessions_token_idx ON live_sessions (token_hash);
ALTER TABLE live_samples ADD COLUMN IF NOT EXISTS gyro_x REAL;
ALTER TABLE live_samples ADD COLUMN IF NOT EXISTS gyro_y REAL;
ALTER TABLE live_samples ADD COLUMN IF NOT EXISTS gyro_z REAL;
ALTER TABLE live_samples ADD COLUMN IF NOT EXISTS acc_x REAL;
ALTER TABLE live_samples ADD COLUMN IF NOT EXISTS acc_y REAL;
ALTER TABLE live_samples ADD COLUMN IF NOT EXISTS acc_z REAL;
CREATE TABLE IF NOT EXISTS live_events (
    id BIGSERIAL PRIMARY KEY,
    live_id UUID NOT NULL REFERENCES live_sessions (live_id) ON DELETE CASCADE,
    level TEXT NOT NULL,
    event JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS live_events_live_idx ON live_events (live_id, id);
"""


def ensure_schema():
    try:
        with pool.connection() as conn:
            conn.execute(SCHEMA_SQL)
    except Exception:
        log.exception("Could not add the live-session columns; apply backend/sql/schema.sql by hand")


def _now():
    return datetime.now(timezone.utc)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _num(v) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


class LiveSession:
    """One live session's state, loaded from live_sessions for each request and written back after it."""

    def __init__(self, participant_id: UUID, name: str, keyboard: bool, live_id: Optional[UUID] = None):
        self.id = live_id or uuid4()
        self.participant_id = participant_id
        self.name = name
        self.keyboard = keyboard
        self.lock = threading.Lock()
        self.created_at = _now()
        self.ended_at: Optional[datetime] = None
        self.status = "ready"
        self.level: Optional[str] = None
        self.levels: List[str] = ["lobby", *LOBBY_GAMES]
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
                    if item.get("type") in KEEP_EVENTS and self.level in LOBBY_GAMES:
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
        elif kind == "result" and self.level in LOBBY_GAMES:
            # A game only sends its result when it was played through; leaving early sends none.
            if self.level not in self.levels_done:
                self.levels_done.append(self.level)
            self.needs_save = True
        elif kind == "level_end":
            self.needs_save = self.needs_save or self.level in LOBBY_GAMES  # also when left early
            self.status, self.level, self.trial, self.phase = "ready", None, None, None
        elif kind == "input":  # the lobby saw a controller after starting as "keyboard"
            if e.get("source") == "gamepad":
                self.synthetic = self.keyboard = False
        elif kind == "trial" and self.level:
            self.metrics.add_trial(e)
        else:
            return False
        return True


# ---- TigerData persistence ----------------------------------------------------

SESSION_COLUMNS = """live_id, participant_id, name, status, level, levels, levels_done, trial, phase, synthetic,
                     keyboard, seq, running, result, db_session_id, error, started_at, ended_at"""


def _create(s: LiveSession) -> str:
    """Store a new session and return its token. Only the token's hash is kept."""
    token = secrets.token_urlsafe(32)
    with pool.connection() as conn:
        conn.execute(
            """INSERT INTO live_sessions
               (live_id, participant_id, name, status, levels, token_hash, keyboard, synthetic, host,
                running, started_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())""",
            (s.id, s.participant_id, s.name, s.status, Jsonb(s.levels), _token_hash(token), s.keyboard, s.synthetic, HOST,
             Jsonb(s.metrics.to_state()), s.created_at),
        )
        conn.execute("SELECT pg_notify(%s, %s)", (CHANNEL, json.dumps({"i": str(s.id), "st": 1})))
    return token


def _write(conn, s: LiveSession, announce: bool = True):
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


def _persist(s: LiveSession):
    try:
        with pool.connection() as conn:
            _write(conn, s)
    except Exception:
        log.exception("Could not write live session %s to TigerData", s.id)


def _load(live_id: UUID) -> Optional[LiveSession]:
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


def _apply(conn, token: str, items: List[Any]) -> Optional[LiveSession]:
    """Lock the open session behind `token`, apply a batch and write it back. None if no such open session."""
    row = conn.execute(
        f"""SELECT {SESSION_COLUMNS}, EXTRACT(EPOCH FROM (now() - updated_at)) AS quiet_s
            FROM live_sessions WHERE token_hash = %s AND status = ANY(%s) FOR UPDATE""",
        (_token_hash(token), OPEN),
    ).fetchone()
    if row is None:
        return None
    s = LiveSession.from_row(row)
    samples, events, changed = s.ingest(items)
    _store_samples(conn, samples)
    _store_events(conn, events)
    _write(conn, s, announce=changed or float(row["quiet_s"]) >= STATE_EVERY_S)
    return s


def _prune_db():
    try:
        save_unsaved_lobbies()  # never drop a finished lobby visit that hasn't reached the history yet
        with pool.connection() as conn:
            conn.execute("DELETE FROM live_sessions WHERE updated_at < now() - interval '1 day'")
    except Exception:
        log.exception("Pruning old live sessions failed")


# ---- browser lobby ------------------------------------------------------------
# The 3D lobby (web/lobby.html) runs in the resident's own browser tab. It opens a
# live session here with their login cookie and streams its stick samples to
# /live/ingest. When the tab closes, the visit's in-game
# samples and events are read back from live_samples/live_events, ml.visit_report
# scores Apple Picking and Harbour Fishing and counts Rat Catching, and that
# document is stored with the visit.

LOBBY_IDLE_S = 60        # a lobby tab that stopped posting this long ago is ended
REPORT_TIMEOUT_S = 180
REPLAY_TIMEOUT_S = 120   # drawing the reconstructed-hands GIF (ml.hand_replay.from_capture)
REPLAY_WAIT_S = 600      # how long a drawn GIF waits for the visit's session_id before it is dropped
REPORT_RETRY_S = REPORT_TIMEOUT_S + 120  # a visit still "scoring" after this lost its API mid-report


def _holds_frames(value) -> bool:
    if isinstance(value, dict):
        if "frames" in value or "cursor_lx" in value:
            return True
        return any(_holds_frames(item) for item in value.values())
    if isinstance(value, list):
        return any(_holds_frames(item) for item in value)
    return False


def _run_report(capture: dict) -> dict:
    python = str(GAME_PYTHON) if GAME_PYTHON.is_file() else sys.executable
    out = subprocess.run(
        [python, "-m", "ml.visit_report.report"],
        input=json.dumps(capture),
        text=True,
        capture_output=True,
        cwd=ROOT,
        timeout=REPORT_TIMEOUT_S,
    )
    if out.returncode != 0:
        detail = out.stderr.strip().splitlines()
        raise RuntimeError(detail[-1] if detail else "visit report failed")
    report = json.loads(out.stdout)
    if _holds_frames(report):
        raise RuntimeError("visit report still held the raw frames")
    return report


def _run_hand_replay(capture: dict) -> Tuple[bytes, dict]:
    """Draw the visit's reconstructed-hands GIF; returns its bytes and the details from_capture printed."""
    python = str(GAME_PYTHON) if GAME_PYTHON.is_file() else sys.executable
    with tempfile.TemporaryDirectory(prefix="stickdrift-hands-") as tmp:
        gif_path = Path(tmp) / "hands.gif"
        out = subprocess.run(
            [python, "-m", "ml.hand_replay.from_capture", "--out", str(gif_path)],
            input=json.dumps(capture),
            text=True,
            capture_output=True,
            cwd=ROOT,
            timeout=REPLAY_TIMEOUT_S,
            env={**os.environ, "MPLBACKEND": "Agg"},
        )
        if out.returncode != 0:
            detail = out.stderr.strip().splitlines()
            raise RuntimeError(detail[-1] if detail else "hand replay failed")
        return gif_path.read_bytes(), json.loads(out.stdout.strip().splitlines()[-1])


class _HandReplay:
    """Draws the GIF beside the visit report, then stores it once the visit's session_id is known.

    Every failure stays in here and is only logged: the visit, its status and its scores never wait on it.
    """

    def __init__(self, live_id: UUID, capture: dict):
        self.live_id = live_id
        # own frame lists, so nothing that clears the capture can empty them under this thread
        self.capture = {name: {"frames": list(bucket.get("frames") or [])} for name, bucket in capture.items()}
        self.session_id: Optional[UUID] = None
        self.known = threading.Event()
        self.thread = threading.Thread(target=self._run, name=f"hand-replay-{live_id}", daemon=True)
        self.thread.start()

    def deliver(self, session_id: Optional[UUID]):
        self.session_id = session_id
        self.known.set()

    def _run(self):
        try:
            gif, meta = _run_hand_replay(self.capture)
        except Exception as error:
            log.warning("No hand replay for live session %s: %s", self.live_id, error)
            return
        finally:
            self.capture = None
        if not self.known.wait(REPLAY_WAIT_S) or self.session_id is None:
            log.warning("Dropping the hand replay for live session %s: the visit was not saved", self.live_id)
            return
        try:
            hand_replays.store(self.session_id, gif, meta)
            with pool.connection() as conn:
                conn.execute("SELECT pg_notify(%s, %s)", (CHANNEL, json.dumps({"i": str(self.live_id), "st": 1})))
        except Exception:
            log.exception("Storing the hand replay for visit %s failed", self.session_id)


def _start_hand_replay(s: LiveSession, capture: dict) -> Optional[_HandReplay]:
    try:
        return _HandReplay(s.id, capture)
    except Exception:
        log.exception("Could not start the hand replay for live session %s", s.id)
        return None


def _store_visit(s: LiveSession, report: dict) -> UUID:
    session_id = uuid4()
    metrics = _report_metrics(report)
    finished = metrics["levels_completed"]
    with s.lock:
        synthetic = s.synthetic
        participant_id = s.participant_id
        started = s.created_at
    with pool.connection() as conn:
        conn.execute(
            """INSERT INTO sessions
               (session_id, participant_id, mode, protocol_version, connection, placement,
                status, quality, is_synthetic, started_at, completed_at)
               VALUES (%s, %s, 'free_play', 'lobby-v1', %s, 'other', %s, 'good', %s, %s, now())""",
            (session_id, participant_id, "simulated" if synthetic else "unknown",
             "completed" if finished else "abandoned", synthetic, started),
        )
        conn.execute(
            """INSERT INTO session_summaries (session_id, metrics, code_version)
               VALUES (%s, %s, 'lobby-report-v1')""",
            (session_id, Jsonb(metrics)),
        )
    return session_id


def _report_metrics(report: dict) -> dict:
    model = report.get("model") or {}
    dashboard = report.get("dashboard") or {}
    return {
        "levels_completed": int(report.get("levels_completed") or 0),
        "tcn": {
            "scores": dashboard.get("scores") if "scores" in dashboard else model.get("scores"),
            "levels": dashboard.get("levels") or [],
            "by_game": model.get("by_game") or {},
            "meaning": model.get("meaning"),
            "schema_version": report.get("schema_version"),
        },
        "visit": report,
    }


def _model_error(view: dict) -> Optional[str]:
    """Say why the pattern bars are missing. A visit that did score stays quiet."""
    if view.get("scores"):
        return None
    errors = [level["error"] for level in view.get("levels") or [] if isinstance(level, dict) and level.get("error")]
    if not errors:
        return None
    return "The pattern model could not score this visit (" + "; ".join(errors) + ")."


def _attach_report(session_id: UUID, report: dict):
    """Add the pattern-model report to a visit save_lobby already stored (its own keys don't overlap)."""
    with pool.connection() as conn:
        conn.execute(
            "UPDATE session_summaries SET metrics = metrics || %s WHERE session_id = %s",
            (Jsonb(_report_metrics(report)), session_id),
        )


def _finish_visit(s: LiveSession, capture: dict, session_id: Optional[UUID] = None):
    replay = _start_hand_replay(s, capture)
    try:
        report = _run_report(capture)
        if session_id is not None:
            _attach_report(session_id, report)
        else:  # nothing in-game reached the live buffer, so store the report as the visit
            session_id = _store_visit(s, report)
        view = report.get("dashboard") or {}
        scored = bool(view.get("scores")) or view.get("rat") is not None
        with s.lock:
            s.result = view if scored else None
            s.db_session_id = session_id
            s.status = "finished" if scored else "ended"
            s.ended_at = _now()
            s.error = _model_error(view)
    except Exception as error:
        log.exception("Lobby visit report failed")
        with s.lock:
            # The visit itself is already in the history when session_id is set; only the scores are missing.
            s.status = "ended" if session_id is not None else "failed"
            s.ended_at = _now()
            s.error = str(error)
    finally:
        capture.clear()
        _persist(s)
        if replay is not None:
            replay.deliver(session_id)

def _load_capture(live_id: UUID) -> dict:
    """The visit's in-game frames and events, per game, in the shape ml.visit_report reads."""
    capture = {name: {"frames": [], "events": []} for name in LOBBY_GAMES}
    columns = ", ".join((*LIVE_COLUMNS, *MOTION_KEYS))
    with pool.connection() as conn:
        for name in LOBBY_GAMES:
            rows = conn.execute(
                f"SELECT {columns} FROM live_samples WHERE live_id = %s AND level = %s ORDER BY seq LIMIT %s",
                (live_id, name, MAX_FRAMES + 1),
            ).fetchall()
            bucket = capture[name]
            if len(rows) > MAX_FRAMES:
                rows, bucket["truncated"] = rows[:MAX_FRAMES], True
            for r in rows:
                frame = {key: r[col] for key, col in zip(SAMPLE_KEYS, LIVE_COLUMNS)}
                if r["gyro_x"] is not None:
                    frame.update({key: r[key] for key in MOTION_KEYS})
                bucket["frames"].append(frame)
        for r in conn.execute("SELECT level, event FROM live_events WHERE live_id = %s ORDER BY id",
                              (live_id,)).fetchall():
            if r["level"] in capture:
                capture[r["level"]]["events"].append(r["event"])
    return capture


def _played(conn, live_id: UUID) -> bool:
    return conn.execute(
        """SELECT EXISTS (SELECT 1 FROM live_samples WHERE live_id = %s AND level = ANY(%s))
               OR EXISTS (SELECT 1 FROM live_events WHERE live_id = %s) AS played""",
        (live_id, list(LOBBY_GAMES), live_id),
    ).fetchone()["played"]


def _end_lobby(live_id: Optional[UUID] = None, status: str = "ended", token: Optional[str] = None,
               items: Optional[List[Any]] = None):
    """Close an open lobby session (by id or by its token), save the visit, then score it in the background.

    The row is locked while it closes, so when two processes try to end the same visit only one does.
    """
    with pool.connection() as conn, conn.transaction():
        if token is not None:
            s = _apply(conn, token, items or [])
        else:
            row = conn.execute(
                f"""SELECT {SESSION_COLUMNS} FROM live_sessions
                    WHERE live_id = %s AND levels ? 'lobby' AND status = ANY(%s) FOR UPDATE SKIP LOCKED""",
                (live_id, OPEN),
            ).fetchone()
            s = None if row is None else LiveSession.from_row(row)
        if s is None:
            return
        played = _played(conn, s.id)
        with s.lock:
            s.level = None
            if played:
                s.status = "scoring"
            else:
                s.status, s.ended_at = status, _now()
        _write(conn, s)
    # Save the visit first (measurements + in-game samples), then add the pattern-model report to it.
    session_id = None
    try:
        session_id = save_lobby(s.id)
    except Exception:
        log.exception("Saving lobby visit %s failed; a later sweep will retry", s.id)
    if played:
        _score_visit(s, session_id)


def _score_visit(s: LiveSession, session_id: Optional[UUID]):
    def run():
        try:
            capture = _load_capture(s.id)
        except Exception as error:
            log.exception("Could not read lobby visit %s back for its report", s.id)
            with s.lock:
                s.status = "ended" if session_id is not None else "failed"
                s.ended_at, s.error = _now(), str(error)
            _persist(s)
            return
        _finish_visit(s, capture, session_id)

    threading.Thread(target=run, name=f"visit-report-{s.id}", daemon=True).start()


# ---- saving lobby visits to the resident's history ---------------------------------
# A visit becomes one `sessions` row (protocol lobby-v1, mode free_play) with per-game results in
# session_summaries.metrics. Only in-game samples are copied to raw_samples, so walking around the
# lobby, menus and countdowns are left out.

LOBBY_PROTOCOL = "lobby-v1"


def _save_so_far(live_id: UUID):
    try:
        save_lobby(live_id, final=False)
    except Exception:
        log.exception("Saving lobby visit %s so far failed; it will be saved when the visit ends", live_id)


def save_lobby(live_id: UUID, final: bool = True) -> Optional[UUID]:
    """Save a lobby visit to the resident's history and return its session_id (None if no game was played).

    Safe to call again: the same visit is updated and only new in-game samples are copied. While the visit
    is still open (`final=False`) it is `in_progress`, so a caregiver sees each game's results as soon as
    that game ends, even if the resident then leaves without playing the others.
    """
    with pool.connection() as conn, conn.transaction():
        row = conn.execute(
            """SELECT participant_id, synthetic, status, levels, levels_done, metrics, db_session_id,
                      started_at, COALESCE(ended_at, updated_at) AS ended_at
               FROM live_sessions WHERE live_id = %s FOR UPDATE""",
            (live_id,),
        ).fetchone()
        if row is None or "lobby" not in (row["levels"] or []):
            return None
        played = conn.execute(
            """SELECT level, count(*) AS n, max(t) - min(t) AS span
               FROM live_samples WHERE live_id = %s AND level <> 'lobby' AND phase IS NOT NULL
               GROUP BY level""",
            (live_id,),
        ).fetchall()
        if not played:
            return row["db_session_id"]
        metrics = row["metrics"] or SessionMetrics().summary()
        done = list(dict.fromkeys(g for g in row["levels_done"] if g in LOBBY_GAMES))
        # The page only knows about a controller once a button is pressed, so "keyboard" at the start can be
        # wrong. Keys give exactly -1, 0 or 1; a real stick gives values in between.
        synthetic = row["synthetic"] and _keyboard_only(conn, live_id)
        games = {p["level"]: {**game_summary(metrics, p["level"]), "samples": p["n"],
                              "play_s": round(float(p["span"] or 0), 1), "finished": p["level"] in done}
                 for p in played if p["level"] in LOBBY_GAMES}
        status = "in_progress" if not final else ("completed" if done else "abandoned")
        summary = {"games": games, "games_finished": done, "reach_trials": metrics.get("reach_trials", [])}
        connection = "simulated" if synthetic else "unknown"
        session_id = row["db_session_id"]
        if session_id is None:
            session_id = conn.execute(
                """INSERT INTO sessions (participant_id, mode, protocol_version, connection, status, quality,
                                       is_synthetic, started_at, completed_at)
                   VALUES (%s, 'free_play', %s, %s, %s, NULL, %s, %s, %s) RETURNING session_id""",
                (row["participant_id"], LOBBY_PROTOCOL, connection, status, synthetic, row["started_at"],
                 row["ended_at"] if final else None),
            ).fetchone()["session_id"]
            conn.execute(
                "INSERT INTO session_summaries (session_id, metrics, code_version) VALUES (%s, %s, %s)",
                (session_id, Jsonb(summary), LOBBY_PROTOCOL),
            )
            conn.execute("UPDATE live_sessions SET db_session_id = %s WHERE live_id = %s", (session_id, live_id))
        else:
            # `||` only replaces these keys, so a pattern-model report attached later is kept
            conn.execute(
                """UPDATE sessions SET status = %s, connection = %s, is_synthetic = %s,
                          completed_at = %s WHERE session_id = %s""",
                (status, connection, synthetic, row["ended_at"] if final else None, session_id),
            )
            conn.execute(
                "UPDATE session_summaries SET metrics = metrics || %s WHERE session_id = %s",
                (Jsonb(summary), session_id),
            )
        last = conn.execute("SELECT COALESCE(max(seq), 0) AS m FROM raw_samples WHERE session_id = %s",
                            (session_id,)).fetchone()["m"]
        conn.execute(
            """INSERT INTO raw_samples (time, session_id, seq, t_ms, lx, ly, rx, ry, connected, activity, game,
                                      trial_id, target_lx, target_ly, target_rx, target_ry,
                                      cursor_lx, cursor_ly, cursor_rx, cursor_ry)
               SELECT %s + make_interval(secs => t), %s, seq, t * 1000.0, lx, ly, rx, ry, true,
                      CASE level WHEN 'fish' THEN 'target_tracking' ELSE 'target_reach' END, level,
                      trial, tgt_lx, tgt_ly, tgt_rx, tgt_ry, cur_lx, cur_ly, cur_rx, cur_ry
               FROM live_samples
               WHERE live_id = %s AND level <> 'lobby' AND phase IS NOT NULL AND lx IS NOT NULL AND seq > %s""",
            (row["started_at"], session_id, live_id, last),
        )
        return session_id


def _keyboard_only(conn, live_id: UUID) -> bool:
    analog = conn.execute(
        """SELECT EXISTS (SELECT 1 FROM live_samples WHERE live_id = %s AND level <> 'lobby' AND
                  (abs(lx) NOT IN (0, 1) OR abs(ly) NOT IN (0, 1) OR abs(rx) NOT IN (0, 1) OR abs(ry) NOT IN (0, 1)))
                  AS analog""",
        (live_id,),
    ).fetchone()["analog"]
    return not analog

_last_sweep = 0.0


def save_unsaved_lobbies(min_gap_s: float = 30.0) -> int:
    """Save lobby visits that ended without being saved (a closed laptop, an older API), and re-run reports
    that an API lost mid-way. Cheap to call often."""
    global _last_sweep
    if time.monotonic() - _last_sweep < min_gap_s:
        return 0
    _last_sweep = time.monotonic()
    with pool.connection() as conn:
        ids = [r["live_id"] for r in conn.execute(
            """SELECT l.live_id FROM live_sessions l LEFT JOIN sessions s ON s.session_id = l.db_session_id
               WHERE l.levels ? 'lobby' AND (l.db_session_id IS NULL OR s.status = 'in_progress')
                 AND (l.status <> ALL(%s) OR l.updated_at < now() - make_interval(secs => %s))""",
            (sorted(ACTIVE), STALE_S),
        ).fetchall()]
        # Claim a stuck report by touching the row, so only one process re-runs it.
        stuck = [r["live_id"] for r in conn.execute(
            """UPDATE live_sessions SET updated_at = now()
               WHERE levels ? 'lobby' AND status = 'scoring' AND updated_at < now() - make_interval(secs => %s)
               RETURNING live_id""",
            (REPORT_RETRY_S,),
        ).fetchall()]
    saved = 0
    for live_id in ids:
        try:
            saved += save_lobby(live_id) is not None
        except Exception:
            log.exception("Saving lobby visit %s failed", live_id)
    for live_id in stuck:
        s = _load(live_id)
        if s is not None:
            log.warning("Re-running the visit report for lobby session %s", live_id)
            _score_visit(s, s.db_session_id)
    return saved


def _prune_lobby():
    with pool.connection() as conn:
        ids = [r["live_id"] for r in conn.execute(
            """SELECT live_id FROM live_sessions
               WHERE levels ? 'lobby' AND status = ANY(%s) AND updated_at < now() - make_interval(secs => %s)""",
            (OPEN, LOBBY_IDLE_S),
        ).fetchall()]
    for live_id in ids:
        _end_lobby(live_id, "lost")


class LobbyStart(BaseModel):
    keyboard: bool = False


@router.post("/me/lobby/start", status_code=201)
def lobby_start(body: LobbyStart, me: dict = Depends(current_senior)):
    _prune_lobby()
    with pool.connection() as conn:
        old = [r["live_id"] for r in conn.execute(
            "SELECT live_id FROM live_sessions WHERE levels ? 'lobby' AND participant_id = %s AND status = ANY(%s)",
            (me["account_id"], OPEN),
        ).fetchall()]
    for live_id in old:
        _end_lobby(live_id)  # one open lobby per resident; a reload replaces the old tab
    s = LiveSession(me["account_id"], me["display_name"], body.keyboard)
    token = _create(s)
    _prune_db()
    return {"live_id": s.id, "token": token}


class LiveEnd(BaseModel):
    """The last samples ride with the close, so they are scored before the session is closed."""
    items: List[Union[List[Any], Dict[str, Any]]] = Field(default_factory=list, max_length=5000)


@router.post("/live/end", status_code=204)
def lobby_end(x_live_token: str = Header(...), body: Optional[LiveEnd] = None):
    _end_lobby(token=x_live_token, items=body.items if body is not None else [])


# ---- game -------------------------------------------------------------------

class IngestIn(BaseModel):
    items: List[Union[List[Any], Dict[str, Any]]] = Field(max_length=5000)


@router.post("/live/ingest")
def ingest(body: IngestIn, x_live_token: str = Header(...)):
    with pool.connection() as conn, conn.transaction():
        s = _apply(conn, x_live_token, body.items)
    if s is None:
        raise HTTPException(410, "This live session is no longer open.")
    if s.needs_save:
        threading.Thread(target=_save_so_far, args=(s.id,), daemon=True).start()
    return {"ok": True}


# ---- caregiver (reads TigerData, so any computer can watch) ----------------------

BRIEF_COLUMNS = """live_id, participant_id, name, status, level, levels, levels_done, synthetic,
                   started_at, ended_at, updated_at, db_session_id, error, host,
                   result->'scores' AS tcn_scores,
                   result->'rat' AS rat,
                   EXTRACT(EPOCH FROM (COALESCE(ended_at, now()) - started_at)) AS elapsed_s,
                   updated_at < now() - make_interval(secs => %s) AS stale"""


def _brief(row: dict) -> dict:
    status = row["status"]
    error = row["error"]
    if status in ACTIVE and row["stale"]:
        status = "lost"
        error = error or ("The resident's lobby tab stopped sending updates, so it was probably closed or "
                          "went offline. The games played so far are saved.")
    return {
        "live_id": row["live_id"], "participant_id": row["participant_id"], "name": row["name"],
        "status": status, "level": row["level"], "levels": row["levels"], "levels_done": row["levels_done"],
        "synthetic": row["synthetic"], "started_at": row["started_at"],
        "elapsed_s": round(float(row["elapsed_s"]), 1), "tcn_scores": row["tcn_scores"],
        "rat": row["rat"],
        "db_session_id": row["db_session_id"], "error": error,
    }


@router.get("/caregiver/live")
def live_list(_: dict = Depends(current_caregiver)):
    with pool.connection() as conn:
        rows = conn.execute(
            f"""SELECT {BRIEF_COLUMNS} FROM live_sessions
                WHERE updated_at > now() - make_interval(hours => %s)
                ORDER BY started_at DESC LIMIT 20""",
            (STALE_S, RECENT_H),
        ).fetchall()
    return [_brief(r) for r in rows]


def _replay_pending(row: dict) -> bool:
    """A finished lobby visit whose hand GIF may still be drawing (it runs beside the report)."""
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
        replay = hand_replays.meta_sql("live_sessions.db_session_id") if hand_replays.exists(conn) else "NULL::jsonb"
        row = conn.execute(
            f"""SELECT {BRIEF_COLUMNS}, trial, phase, seq, metrics, result,
                       EXTRACT(EPOCH FROM (now() - ended_at)) AS ended_ago_s, {replay} AS hand_replay
                FROM live_sessions WHERE live_id = %s""",
            (STALE_S, live_id),
        ).fetchone()
    if row is None:
        return None
    return {**_brief(row), "trial": row["trial"], "phase": row["phase"], "seq": row["seq"],
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


@router.get("/caregiver/live/{live_id}")
def live_snapshot(live_id: UUID, since: int = 0, limit: int = 2000, _: dict = Depends(current_caregiver)):
    limit = max(1, min(limit, 4000))
    st = state(live_id)
    if st is None:
        raise HTTPException(404, "That live session was not found.")
    return {**st, "samples": samples_since(live_id, since, limit)}
