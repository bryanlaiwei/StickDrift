"""Ending a visit: save it to the resident's history, then score it in the background.

When the lobby tab closes (or goes quiet), the visit is saved as one `sessions` row with its
in-game samples copied to raw_samples. Its in-game samples and events are then read back from
live_samples/live_events: ml.visit_report scores Apple Picking and Harbour Fishing with the
pattern model and counts Rat Catching, and ml.hand_replay draws the reconstructed-hands GIF.
Both run in the root uv environment (Python 3.14) as subprocesses.
"""
import json
import logging
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, List, Optional, Tuple
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from .. import hand_replays
from ..db import pool
from ..measurements import MOTION_KEYS, SAMPLE_KEYS, SessionMetrics, game_summary
from .session import (ACTIVE, CHANNEL, GAMES, LIVE_COLUMNS, OPEN, SESSION_COLUMNS, STALE_S, LiveSession,
                      apply_batch, load, now, persist, write)

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[3]
# Python of the root uv environment, which has torch and matplotlib.
ML_PYTHON = Path(os.environ.get("STICKDRIFT_ML_PYTHON", ROOT / ".venv" / "bin" / "python"))
MAX_FRAMES = 24000       # a visit is a few minutes at 60 Hz; the report stops reading there
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
    python = str(ML_PYTHON) if ML_PYTHON.is_file() else sys.executable
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
    python = str(ML_PYTHON) if ML_PYTHON.is_file() else sys.executable
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
        resident_id = s.resident_id
        started = s.created_at
    with pool.connection() as conn:
        conn.execute(
            """INSERT INTO sessions
               (session_id, participant_id, mode, protocol_version, connection, placement,
                status, quality, is_synthetic, started_at, completed_at)
               VALUES (%s, %s, 'free_play', 'lobby-v1', %s, 'other', %s, 'good', %s, %s, now())""",
            (session_id, resident_id, "simulated" if synthetic else "unknown",
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
    """Add the pattern-model report to a visit save_visit already stored (its own keys don't overlap)."""
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
            s.ended_at = now()
            s.error = _model_error(view)
    except Exception as error:
        log.exception("Lobby visit report failed")
        with s.lock:
            # The visit itself is already in the history when session_id is set; only the scores are missing.
            s.status = "ended" if session_id is not None else "failed"
            s.ended_at = now()
            s.error = str(error)
    finally:
        capture.clear()
        persist(s)
        if replay is not None:
            replay.deliver(session_id)

def _load_capture(live_id: UUID) -> dict:
    """The visit's in-game frames and events, per game, in the shape ml.visit_report reads."""
    capture = {name: {"frames": [], "events": []} for name in GAMES}
    columns = ", ".join((*LIVE_COLUMNS, *MOTION_KEYS))
    with pool.connection() as conn:
        for name in GAMES:
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
        (live_id, list(GAMES), live_id),
    ).fetchone()["played"]


def end_visit(live_id: Optional[UUID] = None, status: str = "ended", token: Optional[str] = None,
               items: Optional[List[Any]] = None):
    """Close an open lobby session (by id or by its token), save the visit, then score it in the background.

    The row is locked while it closes, so when two processes try to end the same visit only one does.
    """
    with pool.connection() as conn, conn.transaction():
        if token is not None:
            s = apply_batch(conn, token, items or [])
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
                s.status, s.ended_at = status, now()
        write(conn, s)
    # Save the visit first (measurements + in-game samples), then add the pattern-model report to it.
    session_id = None
    try:
        session_id = save_visit(s.id)
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
                s.ended_at, s.error = now(), str(error)
            persist(s)
            return
        _finish_visit(s, capture, session_id)

    threading.Thread(target=run, name=f"visit-report-{s.id}", daemon=True).start()


# ---- saving lobby visits to the resident's history ---------------------------------
# A visit becomes one `sessions` row (protocol lobby-v1, mode free_play) with per-game results in
# session_summaries.metrics. Only in-game samples are copied to raw_samples, so walking around the
# lobby, menus and countdowns are left out.

LOBBY_PROTOCOL = "lobby-v1"


def save_so_far(live_id: UUID):
    try:
        save_visit(live_id, final=False)
    except Exception:
        log.exception("Saving lobby visit %s so far failed; it will be saved when the visit ends", live_id)


def save_visit(live_id: UUID, final: bool = True) -> Optional[UUID]:
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
        done = list(dict.fromkeys(g for g in row["levels_done"] if g in GAMES))
        # The page only knows about a controller once a button is pressed, so "keyboard" at the start can be
        # wrong. Keys give exactly -1, 0 or 1; a real stick gives values in between.
        synthetic = row["synthetic"] and _keyboard_only(conn, live_id)
        games = {p["level"]: {**game_summary(metrics, p["level"]), "samples": p["n"],
                              "play_s": round(float(p["span"] or 0), 1), "finished": p["level"] in done}
                 for p in played if p["level"] in GAMES}
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


def save_unsaved_visits(min_gap_s: float = 30.0) -> int:
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
            saved += save_visit(live_id) is not None
        except Exception:
            log.exception("Saving lobby visit %s failed", live_id)
    for live_id in stuck:
        s = load(live_id)
        if s is not None:
            log.warning("Re-running the visit report for lobby session %s", live_id)
            _score_visit(s, s.db_session_id)
    return saved


def end_idle_visits():
    with pool.connection() as conn:
        ids = [r["live_id"] for r in conn.execute(
            """SELECT live_id FROM live_sessions
               WHERE levels ? 'lobby' AND status = ANY(%s) AND updated_at < now() - make_interval(secs => %s)""",
            (OPEN, LOBBY_IDLE_S),
        ).fetchall()]
    for live_id in ids:
        end_visit(live_id, "lost")


def prune():
    try:
        save_unsaved_visits()  # never drop a finished lobby visit that hasn't reached the history yet
        with pool.connection() as conn:
            conn.execute("DELETE FROM live_sessions WHERE updated_at < now() - interval '1 day'")
    except Exception:
        log.exception("Pruning old live sessions failed")
