"""The hand replay runs beside the visit report and never changes or delays it (backend/app/live/visit.py).

Needs the backend packages: run with the backend's Python, e.g.
`backend\\.venv\\Scripts\\python -m unittest tests.backend.test_live_hand_replay` from the repository root.
The database is never touched: every query is replaced with a mock.
"""

import os
import subprocess
import sys
import threading
import unittest
from importlib.util import find_spec
from pathlib import Path
from unittest import mock
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

HAS_DEPS = all(find_spec(name) for name in ("fastapi", "psycopg_pool", "pydantic", "dotenv", "argon2"))
if HAS_DEPS:
    os.environ.setdefault("DATABASE_URL", "postgresql://unused.invalid/stickdrift")
    from backend.app.live import visit, watch

REPORT = {
    "schema_version": 1,
    "levels_completed": 1,
    "games": {"apple": {"score": 10}},
    "model": {"scores": {"parkinson": 12.0}, "by_game": {}, "meaning": "x"},
    "dashboard": {"scores": {"parkinson": 12.0}, "levels": [{"level": "apple"}], "rat": None},
    "live": None,
}
GIF = (b"GIF89a-test", {"game": "apple", "window_start_s": 1.5, "duration_s": 6.0, "frames": 150,
                        "has_motion": True, "bytes": 11, "renderer_version": "test"})


def capture():
    frame = {"t": 0.0, "lx": 0.1, "ly": 0.0, "rx": 0.0, "ry": 0.0}
    return {"apple": {"frames": [dict(frame, t=i / 60) for i in range(240)], "events": [{"type": "result"}]},
            "fish": {"frames": [], "events": []}, "rat": {"frames": [], "events": []}}


@unittest.skipUnless(HAS_DEPS, "needs the backend packages (backend/requirements.txt)")
class FinishVisitWithReplayTest(unittest.TestCase):
    def setUp(self):
        self.session = visit.LiveSession(uuid4(), "Test resident", False)
        self.session_id = uuid4()
        self.replays = []
        real_start = visit._start_hand_replay

        def start(s, cap):
            replay = real_start(s, cap)
            self.replays.append(replay)
            return replay

        patches = [
            mock.patch.object(visit, "_start_hand_replay", side_effect=start),
            mock.patch.object(visit, "_run_report", return_value=REPORT),
            mock.patch.object(visit, "persist"),
            mock.patch.object(visit, "pool"),
        ]
        self.run_report, self.persist = patches[1].start(), patches[2].start()
        patches[0].start()
        patches[3].start()
        self.attach = mock.patch.object(visit, "_attach_report").start()
        self.store = mock.patch.object(visit.hand_replays, "store").start()
        self.addCleanup(mock.patch.stopall)

    def finish(self, cap=None, session_id="default"):
        cap = capture() if cap is None else cap
        visit._finish_visit(self.session, cap, self.session_id if session_id == "default" else session_id)
        return cap

    def join_replay(self):
        self.assertEqual(len(self.replays), 1)
        self.replays[0].thread.join(10)
        self.assertFalse(self.replays[0].thread.is_alive())

    def assert_visit_judged(self):
        self.attach.assert_called_once_with(self.session_id, REPORT)
        self.assertEqual(self.session.status, "finished")
        self.assertEqual(self.session.result, REPORT["dashboard"])
        self.assertEqual(self.session.db_session_id, self.session_id)
        self.assertIsNone(self.session.error)
        self.assertIsNotNone(self.session.ended_at)
        self.persist.assert_called_with(self.session)

    def test_replay_failure_leaves_the_visit_alone(self):
        with mock.patch.object(visit, "_run_hand_replay", side_effect=RuntimeError("renderer crashed")):
            cap = self.finish()
            self.join_replay()
        self.assert_visit_judged()
        self.assertEqual(cap, {})
        self.store.assert_not_called()

    def test_replay_timeout_leaves_the_visit_alone(self):
        timeout = subprocess.TimeoutExpired(["python", "-m", "ml.hand_replay.from_capture"], visit.REPLAY_TIMEOUT_S)
        with mock.patch.object(visit.subprocess, "run", side_effect=timeout) as run:
            self.finish()
            self.join_replay()
        self.assertEqual(run.call_args.kwargs["timeout"], visit.REPLAY_TIMEOUT_S)
        self.assertEqual(run.call_args.kwargs["env"]["MPLBACKEND"], "Agg")
        self.assert_visit_judged()
        self.store.assert_not_called()

    def test_slow_replay_does_not_delay_the_status_and_is_stored_after(self):
        release = threading.Event()

        def slow_replay(cap):
            self.assertEqual(len(cap["apple"]["frames"]), 240)  # its own copy survives capture.clear()
            release.wait(10)
            return GIF

        with mock.patch.object(visit, "_run_hand_replay", side_effect=slow_replay):
            self.finish()
            self.assert_visit_judged()
            self.assertTrue(self.replays[0].thread.is_alive())
            release.set()
            self.join_replay()
        self.store.assert_called_once_with(self.session_id, *GIF)

    def test_failed_store_is_only_logged(self):
        self.store.side_effect = RuntimeError("database refused")
        with mock.patch.object(visit, "_run_hand_replay", return_value=GIF):
            self.finish()
            self.join_replay()
        self.assert_visit_judged()

    def test_replay_follows_a_visit_stored_from_the_report(self):
        new_id = uuid4()
        with mock.patch.object(visit, "_store_visit", return_value=new_id), \
             mock.patch.object(visit, "_run_hand_replay", return_value=GIF):
            self.finish(session_id=None)
            self.join_replay()
        self.assertEqual(self.session.db_session_id, new_id)
        self.store.assert_called_once_with(new_id, *GIF)

    def test_unsaved_visit_drops_the_replay(self):
        self.run_report.side_effect = RuntimeError("visit report failed")
        with mock.patch.object(visit, "_run_hand_replay", return_value=GIF):
            self.finish(session_id=None)
            self.join_replay()
        self.assertEqual(self.session.status, "failed")
        self.assertEqual(self.session.error, "visit report failed")
        self.store.assert_not_called()


@unittest.skipUnless(HAS_DEPS, "needs the backend packages (backend/requirements.txt)")
class ReplayPendingTest(unittest.TestCase):
    def row(self, **over):
        base = {"levels": ["lobby"], "hand_replay": None, "status": "finished", "stale": False,
                "db_session_id": uuid4(), "ended_ago_s": 5.0}
        return {**base, **over}

    def test_pending_while_scoring_and_just_after(self):
        self.assertTrue(watch._replay_pending(self.row(status="scoring", ended_ago_s=None)))
        self.assertTrue(watch._replay_pending(self.row()))

    def test_not_pending(self):
        self.assertFalse(watch._replay_pending(self.row(hand_replay={"game": "apple"})))
        self.assertFalse(watch._replay_pending(self.row(levels=["apples"])))
        self.assertFalse(watch._replay_pending(self.row(ended_ago_s=visit.REPLAY_TIMEOUT_S + 60)))
        self.assertFalse(watch._replay_pending(self.row(db_session_id=None)))
        self.assertFalse(watch._replay_pending(self.row(status="scoring", stale=True)))
        self.assertFalse(watch._replay_pending(self.row(status="failed")))


if __name__ == "__main__":
    unittest.main()
