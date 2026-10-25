"""Reconstructed-hands GIFs from the live lobby capture (hand_replay.reconstruct / render / from_capture).

Needs the root uv environment (numpy, scipy, matplotlib, pillow): `uv sync`, then
`uv run python -m unittest tests.ml.test_hand_replay`.
"""

import csv
import json
import math
import os
import subprocess
import sys
import tempfile
import unittest
from importlib.util import find_spec
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

HAS_DEPS = all(find_spec(name) for name in ("numpy", "scipy", "matplotlib", "PIL"))
if HAS_DEPS:
    import numpy as np
    from PIL import Image

    from ml.hand_replay.reconstruct import motion_from_capture, motion_from_frames, pick_game
    from ml.hand_replay.render import GIF_BUDGET_BYTES, RENDERER_VERSION

REAL_SESSION = ROOT / "data" / "ultimate_data" / "Tremor" / "2026-10-18_02-38-26_lobby"
CSV_TO_CAPTURE = {
    "tgt_lx": "target_lx", "tgt_ly": "target_ly", "tgt_rx": "target_rx", "tgt_ry": "target_ry",
    "reached_l": "on_l", "reached_r": "on_r",
    "cur_lx": "cursor_lx", "cur_ly": "cursor_ly", "cur_rx": "cursor_rx", "cur_ry": "cursor_ry",
}
CORE = ("t", "trial", "phase", "lx", "ly", "rx", "ry", "tgt_lx", "tgt_ly", "tgt_rx", "tgt_ry",
        "reached_l", "reached_r", "cur_lx", "cur_ly", "cur_rx", "cur_ry")
MOTION = ("gyro_x", "gyro_y", "gyro_z", "acc_x", "acc_y", "acc_z")


def frames(seconds, gyro=True, start=0.0, hz=60, tremor_hz=6.0):
    """Frames shaped like LiveSession._keep_frame: sticks circle, the left hand has a target, a 6 Hz tremor."""
    out = []
    for i in range(int(seconds * hz)):
        t = start + i / hz
        frame = {
            "t": round(t, 3), "trial": 1, "phase": "cue",
            "lx": 0.6 * math.sin(math.tau * 0.5 * t), "ly": 0.4 * math.cos(math.tau * 0.5 * t),
            "rx": 0.3 * math.sin(math.tau * 0.3 * t), "ry": 0.0,
            "target_lx": 0.5, "target_ly": 0.0, "target_rx": None, "target_ry": None,
            "on_l": 0, "on_r": 0,
            "cursor_lx": 0.1, "cursor_ly": 0.1, "cursor_rx": None, "cursor_ry": None,
        }
        if gyro:
            wobble = math.sin(math.tau * tremor_hz * t)
            frame.update(gyro_x=600 * wobble, gyro_y=300 * wobble, gyro_z=150 * wobble,
                         acc_x=200.0, acc_y=8192.0, acc_z=400.0)
        out.append(frame)
    return out


def _cell(key, value):
    if value in (None, ""):
        return None
    return value if key == "phase" else float(value)


def capture_from_session(session: Path) -> dict:
    """A recorded lobby session in the shape the API keeps in memory (tgt_* -> target_*, gyro only when measured)."""
    meta = json.loads((session / "session.json").read_text(encoding="utf-8"))
    capture = {game: {"frames": [], "events": []} for game in ("apple", "fish", "rat")}
    for level in meta["levels"]:
        path = session / level["folder"] / "controller_data.csv"
        if not path.is_file():
            continue
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                frame = {CSV_TO_CAPTURE.get(k, k): _cell(k, row.get(k)) for k in CORE}
                if row.get("gyro_x"):
                    frame.update({k: float(row[k]) for k in MOTION})
                capture[level["level"]]["frames"].append(frame)
    return capture


@unittest.skipUnless(HAS_DEPS, "needs numpy, scipy, matplotlib and pillow (uv sync)")
class MotionFromFramesTest(unittest.TestCase):
    def test_gyro_frames_tilt_and_shake(self):
        motion = motion_from_frames(frames(10), "apple")
        self.assertTrue(motion.has_motion)
        self.assertEqual(len(motion.time_s), 150)  # 6 s at 25 fps
        self.assertGreater(np.abs(motion.grip_shift).max(), 0.05)
        self.assertGreater(np.ptp(motion.sticks[:, 0]), 0.2)
        np.testing.assert_allclose(motion.targets[:, 0], 0.5)
        self.assertTrue(np.isnan(motion.targets[:, 2]).all())
        for released in (motion.triggers, motion.bumpers, motion.face):
            self.assertEqual(np.abs(released).max(), 0)

    def test_frames_without_gyro_still_move_the_thumbs(self):
        motion = motion_from_frames(frames(10, gyro=False), "apple")
        self.assertFalse(motion.has_motion)
        np.testing.assert_allclose(motion.tilt, 0, atol=1e-9)
        np.testing.assert_allclose(motion.grip_shift, 0, atol=1e-9)
        self.assertGreater(np.ptp(motion.sticks[:, 0]), 0.2)

    def test_window_is_relative_to_the_game_and_shorter_runs_play_whole(self):
        motion = motion_from_frames(frames(4, start=812.0), "fish")
        self.assertLess(motion.time_s[0], 1.0)
        self.assertLessEqual(len(motion.time_s), 100)

    def test_longest_run_is_used_when_a_game_is_played_twice(self):
        motion = motion_from_frames(frames(2, start=100.0) + frames(7, start=300.0), "apple")
        self.assertEqual(len(motion.time_s), 150)

    def test_too_few_frames_is_an_error(self):
        with self.assertRaises(ValueError):
            motion_from_frames(frames(1.0), "apple")


@unittest.skipUnless(HAS_DEPS, "needs numpy, scipy, matplotlib and pillow (uv sync)")
class PickGameTest(unittest.TestCase):
    def capture(self, **seconds):
        return {game: {"frames": frames(s), "events": []} for game, s in seconds.items()}

    def test_apple_first(self):
        self.assertEqual(pick_game(self.capture(apple=4, fish=10, rat=10)), "apple")

    def test_falls_back_to_fish_then_rat(self):
        self.assertEqual(pick_game(self.capture(apple=2, fish=4, rat=10)), "fish")
        self.assertEqual(pick_game(self.capture(apple=2, fish=1, rat=5)), "rat")

    def test_short_visit_uses_its_longest_game(self):
        self.assertEqual(pick_game(self.capture(apple=2.5, fish=1, rat=2)), "apple")

    def test_nothing_usable(self):
        self.assertIsNone(pick_game(self.capture(apple=1)))
        self.assertIsNone(pick_game({}))
        self.assertIsNone(motion_from_capture({"rat": {"events": [{"type": "result"}]}}))

    @unittest.skipUnless(REAL_SESSION.is_dir(), "recorded session not present")
    def test_recorded_session_through_the_capture_path(self):
        game, motion = motion_from_capture(capture_from_session(REAL_SESSION))
        self.assertEqual(game, "apple")
        self.assertTrue(motion.has_motion)
        self.assertEqual(len(motion.time_s), 150)
        self.assertGreater(motion.shake_cm.max(), 0.01)


@unittest.skipUnless(HAS_DEPS, "needs numpy, scipy, matplotlib and pillow (uv sync)")
class FromCaptureCliTest(unittest.TestCase):
    def run_cli(self, capture, out):
        return subprocess.run(
            [sys.executable, "-m", "ml.hand_replay.from_capture", "--out", str(out)],
            input=json.dumps(capture), text=True, capture_output=True, cwd=ROOT, timeout=180,
            env={**os.environ, "MPLBACKEND": "Agg"},
        )

    def test_writes_a_gif_under_the_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "hands.gif"
            done = self.run_cli({"apple": {"frames": frames(8), "events": []}}, out)
            self.assertEqual(done.returncode, 0, done.stderr)
            meta = json.loads(done.stdout.strip().splitlines()[-1])
            self.assertEqual(set(meta), {"game", "window_start_s", "duration_s", "frames", "has_motion", "bytes",
                                         "renderer_version"})
            self.assertEqual(meta["game"], "apple")
            self.assertEqual(meta["frames"], 150)
            self.assertEqual(meta["duration_s"], 6.0)
            self.assertTrue(meta["has_motion"])
            self.assertEqual(meta["renderer_version"], RENDERER_VERSION)
            self.assertEqual(meta["bytes"], out.stat().st_size)
            self.assertLessEqual(meta["bytes"], GIF_BUDGET_BYTES)
            with Image.open(out) as gif:
                self.assertEqual(gif.format, "GIF")
                self.assertEqual(gif.n_frames, 150)
                self.assertEqual(gif.info.get("duration"), 40)

    def test_no_usable_frames_exits_non_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "hands.gif"
            done = self.run_cli({"rat": {"frames": frames(0.5), "events": []}}, out)
            self.assertEqual(done.returncode, 3)
            self.assertIn("no usable frames", done.stderr)
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
