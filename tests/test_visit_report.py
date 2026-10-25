"""The end-of-visit report: dashboard numbers plus model scores, and no raw frames."""

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from visit.report import finish_visit  # noqa: E402


def _apple_frames():
    """Left glove travels out and back while an apple is the target. Right stick stays still."""
    frames = []
    xs = [0.0, 0.1, 0.2, 0.1, 0.0]
    for i, x in enumerate(xs):
        frames.append({
            "t": i * 0.5,
            "phase": "cue",
            "trial": 1,
            "lx": 0.0, "ly": 0.0, "rx": 0.0, "ry": 0.0,
            "cursor_lx": x, "cursor_ly": 0.0,
            "cursor_rx": None, "cursor_ry": None,
            "target_lx": 0.2, "target_ly": 0.0,
            "target_rx": None, "target_ry": None,
            "on_l": 0, "on_r": 0,
        })
    return frames


def _score(game, frames):
    assert frames and "cursor_lx" not in json.dumps(game)
    scores = {
        "parkinson": 10.0 if game == "apple" else 30.0,
        "stroke": 5.0 if game == "apple" else None,
        "essential_tremor": 8.0 if game == "apple" else 12.0,
    }
    return {"duration_s": 2.0, "stretches": {"left": 1, "right": 1}, "scores": scores}


class VisitReportTest(unittest.TestCase):
    def test_apple_numbers_and_no_leftover_frames(self):
        report = finish_visit({
            "apple": {
                "frames": _apple_frames(),
                "events": [
                    {"type": "trial", "t": 2.0, "trial": 1, "hand": "left",
                     "reaction_s": 0.4, "reach_s": 1.0, "peak_speed": 1.2, "reach_size": 0.8, "reached": True},
                    {"type": "wrong", "hand": "right", "t": 0.5},
                    {"type": "basket", "hand": "left", "t": 3.2},
                    {"type": "expired", "hand": "left", "t": 4.0},
                    {"type": "result", "score": 75, "stars": 1, "red": 1, "blue": 0, "wrong": 1},
                ],
            },
        }, score=_score)

        apple = report["games"]["apple"]
        self.assertEqual(apple["score"], 75)
        self.assertEqual(apple["stars"], 1)
        self.assertEqual(apple["basket"], {"left": 1, "right": 0})
        self.assertEqual(apple["wrong_touches"], {"left": 0, "right": 1})
        self.assertEqual(apple["expired"], {"left": 1, "right": 0})
        self.assertEqual(apple["undelivered"], {"left": 0, "right": 0})
        attempt = apple["attempts"][0]
        self.assertEqual(attempt["hand"], "left")
        self.assertEqual(attempt["reaction_s"], 0.4)
        self.assertEqual(attempt["carry_s"], 1.2)
        self.assertEqual(attempt["delivered"], True)
        self.assertAlmostEqual(attempt["path_length"], 0.4, places=3)
        self.assertEqual(attempt["reversals"], 1)
        self.assertIsNone(report["games"]["rat"])
        self.assertNotIn("frames", json.dumps(report))
        self.assertNotIn("cursor_lx", json.dumps(report))

    def test_fish_trace_and_rat_counts_skip_the_model(self):
        seen = []

        def score(game, frames):
            seen.append(game)
            return _score(game, frames)

        report = finish_visit({
            "fish": {
                "frames": [
                    {"t": 0.0, "phase": "track", "trial": 1, "lx": 0.0, "ly": 0.0, "rx": 0.0, "ry": 0.0,
                     "cursor_lx": 0.0, "cursor_ly": 0.0, "target_lx": 0.0, "target_ly": 0.0,
                     "cursor_rx": None, "cursor_ry": None, "target_rx": None, "target_ry": None,
                     "on_l": 1, "on_r": 0},
                    {"t": 0.5, "phase": "track", "trial": 1, "lx": 0.2, "ly": 0.0, "rx": 0.0, "ry": 0.0,
                     "cursor_lx": 0.4, "cursor_ly": 0.0, "target_lx": 0.2, "target_ly": 0.0,
                     "cursor_rx": None, "cursor_ry": None, "target_rx": None, "target_ry": None,
                     "on_l": 0, "on_r": 0},
                ],
                "events": [
                    {"type": "trace", "round": 1, "hand": "left", "shape": "wave",
                     "time_s": 8.0, "on_lane_pct": 80, "off_count": 2, "score": 500},
                    {"type": "result", "score": 500, "stars": 2, "caught": 1},
                ],
            },
            "rat": {
                "frames": [
                    {"t": 0.0, "lx": 0.0, "ly": 0.0, "rx": 0.0, "ry": -0.9, "phase": "run", "trial": 1,
                     "on_l": 0, "on_r": 0},
                ],
                "events": [
                    {"type": "slam", "hand": "right", "outcome": "caught", "round": 1,
                     "reaction_s": 0.3, "flick_speed": 4.0, "other_stick": False, "t": 0.3},
                    {"type": "slam", "hand": "left", "outcome": "empty", "round": 1,
                     "reaction_s": 0.1, "flick_speed": 3.0, "early": True, "other_stick": True, "t": 1.0},
                    {"type": "miss", "round": 2, "t": 2.0},
                    {"type": "result", "score": 250, "stars": 1, "caught": 1, "missed": 1, "wrong": 0, "empty": 1},
                ],
            },
        }, score=score)

        self.assertEqual(seen, ["fish"])
        fish = report["games"]["fish"]
        self.assertEqual(fish["traces"][0]["shape"], "wave")
        self.assertEqual(fish["traces"][0]["on_lane_pct"], 80)
        self.assertEqual(fish["traces"][0]["off_count"], 2)
        self.assertEqual(fish["traces"][0]["completed"], True)
        self.assertAlmostEqual(fish["traces"][0]["lag"], 0.1, places=3)
        self.assertEqual(fish["per_hand"]["left"]["mean_on_lane_pct"], 80)
        rat = report["games"]["rat"]
        self.assertEqual(rat["caught"], 1)
        self.assertEqual(rat["empty"], 1)
        self.assertEqual(rat["missed"], 1)
        self.assertEqual(rat["early_slams"], 1)
        self.assertEqual(rat["median_reaction_s"], 0.2)
        self.assertNotIn("rat", report["model"]["by_game"])
        self.assertEqual(report["model"]["scores"]["parkinson"], 30.0)
        self.assertEqual(set(report["model"]["scores"]), {"parkinson", "stroke", "essential_tremor"})
        self.assertEqual(report["dashboard"]["scores"]["parkinson"], 30.0)
        self.assertEqual(report["dashboard"]["rat"]["score"], 250)
        self.assertEqual(report["dashboard"]["rat"]["stars"], 1)
        self.assertEqual(report["dashboard"]["levels"][0]["level"], "fish")

    def test_fuses_apple_and_fishing_scores(self):
        capture = {
            "apple": {"frames": _apple_frames(), "events": [
                {"type": "result", "score": 100, "stars": 1, "red": 1, "blue": 0, "wrong": 0},
            ]},
            "fish": {"frames": _apple_frames(), "events": [
                {"type": "result", "score": 10, "stars": 0, "caught": 0},
            ]},
        }
        report = finish_visit(capture, score=_score)
        scores = report["model"]["scores"]
        self.assertEqual(scores["parkinson"], 20.0)
        self.assertEqual(scores["stroke"], 5.0)
        self.assertEqual(scores["essential_tremor"], 10.0)
        self.assertEqual(set(scores), {"parkinson", "stroke", "essential_tremor"})
        self.assertEqual(set(report["model"]["by_game"]), {"apple", "fish"})
        self.assertNotIn("live", report)  # the per-hand numbers live once, in the visit's live measurements

    def test_reach_comes_from_the_grab(self):
        report = finish_visit({
            "apple": {"frames": _apple_frames(), "events": [
                {"type": "trial", "t": 2.0, "trial": 1, "hand": "left",
                 "reaction_s": 0.4, "reach_s": 1.0, "peak_speed": 1.2, "reach_size": 0.8, "reached": True},
                {"type": "basket", "hand": "left", "t": 3.2},
            ]},
        }, score=_score)
        left = report["games"]["apple"]["per_hand"]["left"]
        self.assertEqual(left["median_reach_s"], 1.0)
        self.assertEqual(left["median_reaction_s"], 0.4)

    def test_missing_checkpoint_still_returns_the_counts(self):
        report = finish_visit({
            "apple": {"frames": _apple_frames(), "events": [
                {"type": "result", "score": 50, "stars": 0, "red": 1, "blue": 1, "wrong": 0},
            ]},
        }, checkpoint=Path("/no/such/model.pt"))
        self.assertEqual(report["games"]["apple"]["score"], 50)
        self.assertIn("error", report["model"]["by_game"]["apple"])
        self.assertIsNone(report["model"]["scores"])
        self.assertIsNone(report["dashboard"]["scores"])
        self.assertIn("error", report["dashboard"]["levels"][0])
        self.assertIsNone(report["dashboard"]["rat"])

    def test_card_rat_times_come_from_the_game(self):
        report = finish_visit({
            "rat": {"events": [
                {"type": "card_rat", "round": 1, "caught": True, "reaction_s": 0.42},
                {"type": "card_rat", "round": 1, "caught": False, "reaction_s": None},
                {"type": "result", "score": 300, "stars": 0, "caught": 1, "missed": 1, "wrong": 0, "empty": 0,
                 "target_rats": 2, "correctness_pct": 50.0, "median_reaction_s": 0.42},
            ]},
        }, score=_score)
        rat = report["games"]["rat"]
        self.assertEqual(rat["correctness_pct"], 50.0)
        self.assertEqual(rat["target_rats"], 2)
        self.assertEqual(rat["median_reaction_s"], 0.42)
        self.assertEqual(rat["card_rats"][0]["reaction_s"], 0.42)
        self.assertIsNone(rat["card_rats"][1]["reaction_s"])
        self.assertIsNone(report["model"]["scores"])
        self.assertEqual(report["dashboard"]["rat"]["score"], 300)
        self.assertIsNone(report["dashboard"]["scores"])

    def test_cli_prints_the_report_and_drops_frames(self):
        payload = {"rat": {"events": [
            {"type": "result", "score": 0, "stars": 0, "caught": 0, "missed": 0, "wrong": 0, "empty": 0},
        ]}}
        out = subprocess.run(
            [sys.executable, "-m", "visit.report"],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            cwd=ROOT,
            check=True,
        )
        report = json.loads(out.stdout)
        self.assertEqual(report["games"]["rat"]["score"], 0)
        self.assertNotIn("frames", out.stdout)



class SharedMeasurementsTest(unittest.TestCase):
    """The live view and the end-of-visit report measure shake and tracking with the same code."""

    def fish_frames(self):
        frames = []
        for i in range(120):
            wobble = 0.02 if i % 2 else -0.02
            frames.append({
                "t": i / 60, "phase": "track", "trial": 1,
                "lx": 0.3 + wobble, "ly": 0.1, "rx": 0.0, "ry": 0.0,
                "cursor_lx": 0.3 + wobble, "cursor_ly": 0.1, "cursor_rx": None, "cursor_ry": None,
                "target_lx": 0.25, "target_ly": 0.1, "target_rx": None, "target_ry": None,
                "on_l": 1 if i % 3 else 0, "on_r": 0,
            })
        return frames

    def test_fish_shake_and_tracking_match_the_live_numbers(self):
        from backend.app.live_metrics import SessionMetrics, game_summary

        frames = self.fish_frames()
        report = finish_visit({"fish": {"frames": frames, "events": [
            {"type": "trace", "round": 1, "hand": "left", "time_s": 2.0, "on_lane_pct": 66.7, "score": 10},
        ]}}, score=_score)
        report_left = report["games"]["fish"]["per_hand"]["left"]

        live = SessionMetrics()
        live.start_level("fish")
        keys = ("t", "trial", "phase", "lx", "ly", "rx", "ry", "target_lx", "target_ly", "target_rx", "target_ry",
                "on_l", "on_r", "cursor_lx", "cursor_ly", "cursor_rx", "cursor_ry")
        for frame in frames:
            live.add([frame[k] for k in keys])
        live_left = game_summary(live.summary(), "fish")["hands"]["left"]

        self.assertIsNotNone(live_left["shake"])
        self.assertEqual(report_left["shake"], live_left["shake"])
        self.assertEqual(report_left["mean_lag"], live_left["tracking_error"])

    def test_state_round_trip_keeps_measuring_the_same(self):
        import json

        from backend.app.live_metrics import SessionMetrics

        frames = self.fish_frames()
        keys = ("t", "trial", "phase", "lx", "ly", "rx", "ry", "target_lx", "target_ly", "target_rx", "target_ry",
                "on_l", "on_r", "cursor_lx", "cursor_ly", "cursor_rx", "cursor_ry")
        whole, split = SessionMetrics(), SessionMetrics()
        whole.start_level("fish")
        split.start_level("fish")
        for frame in frames:
            whole.add([frame[k] for k in keys])
        for frame in frames[:50]:
            split.add([frame[k] for k in keys])
        split = SessionMetrics.from_state(json.loads(json.dumps(split.to_state())))
        for frame in frames[50:]:
            split.add([frame[k] for k in keys])
        self.assertEqual(split.summary(), whole.summary())

if __name__ == "__main__":
    unittest.main()
