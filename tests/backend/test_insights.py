"""Resident insights: the game-visit baseline, the pattern model's concerns, and neutral wording."""

import os
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.app import insights  # noqa: E402

try:  # the assistant needs the backend packages (backend/requirements.txt)
    os.environ.setdefault("DATABASE_URL", "postgresql://unused.invalid/stickdrift")
    from backend.app import assistant
except ImportError:
    assistant = None

START = datetime(2026, 10, 20, 10, 0)


def visit(days_ago, left_reach=1.0, right_reach=1.0, lane=0.8, keyboard=False, scores=None):
    hands = {side: {"reaction_s": 0.4, "reach_s": reach} for side, reach in (("left", left_reach), ("right", right_reach))}
    return {
        "session_id": uuid4(), "started_at": START - timedelta(days=days_ago), "status": "completed",
        "is_synthetic": keyboard,
        "games": {"apple": {"hands": hands},
                  "fish": {"hands": {"left": {"tracking_error": 0.1, "on_target": lane},
                                     "right": {"tracking_error": 0.1, "on_target": lane}}}},
        "tcn": None if scores is None else {"scores": scores},
    }


class LobbyBaselineTest(unittest.TestCase):
    def test_needs_four_controller_visits(self):
        visits = [visit(i) for i in range(3)] + [visit(9, keyboard=True)]
        out = insights.analyze(visits)
        self.assertEqual(out["status"], "insufficient")
        self.assertEqual(out["usable_visits"], 3)
        self.assertIn("3 of 4", out["summary"])

    def test_steady_visits_raise_nothing(self):
        out = insights.analyze([visit(i) for i in range(6)])
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["risk"], "none")

    def test_one_slower_hand_is_a_one_sided_change(self):
        visits = [visit(0, left_reach=1.6), visit(1, left_reach=1.5)] + [visit(i) for i in range(2, 7)]
        out = insights.analyze(visits)
        self.assertEqual([c["id"] for c in out["concerns"]], ["one_sided_left"])
        self.assertEqual(out["concerns"][0]["level"], "check")  # persisted across both recent visits
        flagged = [f for f in out["findings"] if f["flagged"]]
        self.assertEqual([f["key"] for f in flagged], ["apple_reach_s_left"])
        self.assertEqual(flagged[0]["latest_text"], "1.60 s")

    def test_both_hands_worse_is_general(self):
        visits = [visit(0, left_reach=1.6, right_reach=1.6)] + [visit(i) for i in range(1, 6)]
        out = insights.analyze(visits)
        self.assertEqual([c["id"] for c in out["concerns"]], ["general_slowing"])

    def test_small_changes_do_not_count(self):
        visits = [visit(0, left_reach=1.1, lane=0.75)] + [visit(i) for i in range(1, 6)]
        self.assertEqual(insights.analyze(visits)["risk"], "none")


class ModelConcernTest(unittest.TestCase):
    def concerns(self, *scores):
        visits = [visit(i, scores={"parkinson": s, "stroke": 10, "essential_tremor": 10}) for i, s in enumerate(scores)]
        base = insights.analyze(visits)
        return insights.add_model_concerns(base, visits)["concerns"]

    def test_one_high_visit_is_only_watch(self):
        found = self.concerns(85, 20)
        self.assertEqual([(c["id"], c["level"]) for c in found], [("model_parkinson", "watch")])

    def test_two_high_visits_in_a_row_is_check(self):
        found = self.concerns(85, 75)
        self.assertEqual(found[0]["level"], "check")
        self.assertIn("and 75 the game visit before", found[0]["summary"])

    def test_wording_is_neutral(self):
        found = self.concerns(85, 75)
        text = " ".join([found[0]["title"], found[0]["summary"], *found[0]["evidence"]])
        self.assertTrue(found[0]["title"].startswith("Movement pattern: "))
        for word in ("parkinson", "stroke", "tremor"):
            self.assertNotIn(word, text.lower())
        for label in insights.PATTERN_LABELS.values():
            self.assertFalse(any(w in label.lower() for w in ("parkinson", "stroke", "tremor")))



@unittest.skipUnless(assistant, "needs the backend packages (backend/requirements.txt)")
class AssistantTest(unittest.TestCase):
    def profile(self, visits):
        ins = insights.add_model_concerns(insights.analyze(visits), visits)
        return {"display_name": "Ada", "dominant_hand": "right", "insights": ins,
                "game_sessions": visits, "review": insights.review_from(ins)}

    def test_every_condition_name_is_refused(self):
        for text in ("resembles Parkinson's", "a stroke pattern", "essential tremor", "possible PD"):
            self.assertTrue(assistant.names_condition(text), text)
        self.assertFalse(assistant.names_condition("slower, smaller movements in both hands"))

    def test_facts_describe_the_game_visit_baseline(self):
        visits = [visit(0, left_reach=1.6)] + [visit(i) for i in range(1, 6)]
        facts = assistant.build_facts([], self.profile(visits))
        self.assertIn("Baseline = median of 4 earlier game visits", facts)
        self.assertNotIn("reaction-test", facts)

    def test_rules_answer_works_from_game_visits(self):
        visits = [visit(0, left_reach=1.6)] + [visit(i) for i in range(1, 6)]
        answer = assistant._rules_answer("how is the left hand?", [], self.profile(visits))
        self.assertIn("latest game visit compared with their usual", answer)
        self.assertIn("Apple Picking time to reach, left hand: 1.60 s", answer)

    def test_rules_answer_describes_the_latest_visit_before_a_baseline(self):
        answer = assistant._rules_answer("how are they doing?", [], self.profile([visit(0)]))
        self.assertIn("Latest game visit", answer)
        self.assertIn("Apple Picking", answer)

if __name__ == "__main__":
    unittest.main()
