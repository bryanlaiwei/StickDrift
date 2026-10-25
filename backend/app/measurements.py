"""Per-hand movement measurements for a web lobby visit.

Fed one live sample at a time while the visit is played. A sample is a list in
SAMPLE_KEYS order, produced by web/lobby/measure.js: stick, target and in-game
hand positions, all normalized to -1..1. The games move an in-game hand with the
stick, so distance from a target uses that hand while shake is read from the
stick itself. Reaches arrive as finished `trial` events measured by the game,
because only the game knows when a target appeared.

Measurements:
  * reaches (Apple Picking, Rat Catching): reaction time, time to reach, peak
    speed, reach size, and how speed changes from the first attempts to the last;
  * tracking (Harbour Fishing): distance from the lane, time on the lane, and
    leftover shake once the slow path is removed;
  * left-right difference for every measurement both hands produce.
These describe movement only. They are not a diagnosis.

This module is the only definition of shake, tracking error and the per-hand
reach numbers. The end-of-visit report (ml/visit_report/report.py) imports `shake`,
`track`, `hand_summary` and SAMPLE_KEYS from here rather than keeping its own copies.
The running state round-trips through `to_state`/`from_state` (plain JSON), so
any API process can pick a session up where another left it.
"""
import math
from collections import deque
from statistics import mean, median
from typing import Dict, List, Optional

# The live sample columns, in order. Producer: web/lobby/measure.js (frame). Keep in step with
# LiveSample in web/src/api.ts. A 23-value sample adds MOTION_KEYS when the pad reports them.
SAMPLE_KEYS = (
    "t", "trial", "phase", "lx", "ly", "rx", "ry",
    "target_lx", "target_ly", "target_rx", "target_ry",
    "on_l", "on_r",
    "cursor_lx", "cursor_ly", "cursor_rx", "cursor_ry",
)
MOTION_KEYS = ("gyro_x", "gyro_y", "gyro_z", "acc_x", "acc_y", "acc_z")

SHAKE_WINDOW = 25       # samples in the slow path, as in ml/pattern_model/stretch.py
SHAKE_DEADBAND = 0.002  # ignore sign flips smaller than sensor noise
HANDS = ("left", "right")


def _r(x, y):
    return math.hypot(x, y)


class _Shake:
    """Leftover shake: how far each point sits from the SHAKE_WINDOW-sample average centred on it."""

    def __init__(self):
        self.window = deque(maxlen=SHAKE_WINDOW)
        self.n = 0
        self.sq = [0.0, 0.0]
        self.flips = [0, 0]
        self.last_sign = [0, 0]

    def add(self, x, y):
        self.window.append((x, y))
        if len(self.window) < SHAKE_WINDOW:
            return
        cx, cy = self.window[SHAKE_WINDOW // 2]
        mx = sum(p[0] for p in self.window) / SHAKE_WINDOW
        my = sum(p[1] for p in self.window) / SHAKE_WINDOW
        self.n += 1
        for axis, res in enumerate((cx - mx, cy - my)):
            self.sq[axis] += res * res
            if abs(res) > SHAKE_DEADBAND:
                sign = 1 if res > 0 else -1
                if self.last_sign[axis] and sign != self.last_sign[axis]:
                    self.flips[axis] += 1
                self.last_sign[axis] = sign

    def rms(self) -> Optional[float]:
        return math.sqrt(sum(self.sq) / self.n) if self.n else None

    def hz(self, span: float) -> Optional[float]:
        shake = self.rms()
        if span <= 1 or not shake or shake < 0.004:
            return None
        axis = 0 if self.sq[0] >= self.sq[1] else 1
        return round(self.flips[axis] / 2 / span, 1)

    def to_state(self) -> dict:
        return {"window": [list(p) for p in self.window], "n": self.n, "sq": self.sq,
                "flips": self.flips, "last_sign": self.last_sign}

    @classmethod
    def from_state(cls, st: dict) -> "_Shake":
        out = cls()
        out.window.extend(tuple(p) for p in st["window"])
        out.n, out.sq, out.flips, out.last_sign = st["n"], list(st["sq"]), list(st["flips"]), list(st["last_sign"])
        return out


class _Tracker:
    """Distance from a moving target plus leftover shake, for one hand."""

    def __init__(self):
        self.n = 0
        self.err_sum = 0.0
        self.on = 0
        self.shake = _Shake()
        self.t_first = None
        self.t_last = None

    def update(self, t, x, y, tx, ty, shake_xy=None, on=False):
        """(x, y) is compared with the target; shake is read from `shake_xy` (default the same point).
        `on` is the game's own call on whether the hand is on target."""
        self.t_first = t if self.t_first is None else self.t_first
        self.t_last = t
        err = _r(x - tx, y - ty)
        self.n += 1
        self.err_sum += err
        self.on += bool(on)
        self.shake.add(*(shake_xy or (x, y)))

    def result(self):
        if self.n == 0:
            return None
        shake = self.shake.rms()
        span = (self.t_last - self.t_first) if self.t_first is not None else 0
        return {"tracking_error": round(self.err_sum / self.n, 4), "on_target": round(self.on / self.n, 3),
                "shake": None if shake is None else round(shake, 4),
                "shake_hz": self.shake.hz(span),
                "samples": self.n}

    def to_state(self) -> dict:
        return {"n": self.n, "err_sum": self.err_sum, "on": self.on, "shake": self.shake.to_state(),
                "t_first": self.t_first, "t_last": self.t_last}

    @classmethod
    def from_state(cls, st: dict) -> "_Tracker":
        out = cls()
        out.n, out.err_sum, out.on = st["n"], st["err_sum"], st["on"]
        out.shake = _Shake.from_state(st["shake"])
        out.t_first, out.t_last = st["t_first"], st["t_last"]
        return out


def shake(points) -> Optional[float]:
    """Leftover shake of a run of (x, y) points; None entries are skipped."""
    s = _Shake()
    for point in points:
        if point is not None:
            s.add(*point)
    value = s.rms()
    return None if value is None else round(value, 4)


def track(samples) -> Optional[dict]:
    """Tracker result for a run of (t, (x, y), (tx, ty), shake_xy, on) samples; ones missing a point are skipped."""
    tracker = _Tracker()
    for t, xy, target, shake_xy, on in samples:
        if xy is not None and target is not None:
            tracker.update(t, *xy, *target, shake_xy=shake_xy, on=on)
    return tracker.result()


class SessionMetrics:
    def __init__(self):
        self.level: Optional[str] = None
        self.reach_trials: List[dict] = []
        self.trackers: Dict[str, Dict[str, _Tracker]] = {}

    def to_state(self) -> dict:
        return {"level": self.level, "reach_trials": self.reach_trials,
                "trackers": {lv: {h: tr.to_state() for h, tr in by_hand.items()}
                             for lv, by_hand in self.trackers.items()}}

    @classmethod
    def from_state(cls, st: Optional[dict]) -> "SessionMetrics":
        out = cls()
        if not st:
            return out
        out.level = st.get("level")
        out.reach_trials = list(st.get("reach_trials") or [])
        out.trackers = {lv: {h: _Tracker.from_state(tr) for h, tr in by_hand.items()}
                        for lv, by_hand in (st.get("trackers") or {}).items()}
        return out

    def start_level(self, level):
        self.level = level

    def add_trial(self, e: dict):
        """A finished reach measured by the game: {trial, hand, reaction_s, reach_s, ...}."""
        hand = e.get("hand")
        if hand not in HANDS:
            return
        num = lambda k: e[k] if isinstance(e.get(k), (int, float)) and not isinstance(e.get(k), bool) else None
        self.reach_trials.append({"trial": e.get("trial"), "game": self.level, hand: {
            "reaction_s": num("reaction_s"), "reach_s": num("reach_s"), "peak_speed": num("peak_speed"),
            "reach_size": num("reach_size"), "reached": bool(e.get("reached"))}})

    def add(self, sample):
        """One sample in SAMPLE_KEYS order. Only tracking phases are measured here."""
        f = dict(zip(SAMPLE_KEYS, sample))
        if f["phase"] != "track" or not self.level:
            return
        level = self.trackers.setdefault(self.level, {})
        for side, h in (("l", "left"), ("r", "right")):
            target = (f[f"target_{side}x"], f[f"target_{side}y"])
            cursor = (f[f"cursor_{side}x"], f[f"cursor_{side}y"])
            if target[0] is not None and cursor[0] is not None:
                stick = (f[f"{side}x"], f[f"{side}y"])
                level.setdefault(h, _Tracker()).update(f["t"], *cursor, *target, shake_xy=stick, on=f[f"on_{side}"])

    # ---- summaries -----------------------------------------------------------

    def summary(self) -> dict:
        trials = self.reach_trials
        hands = {h: self._hand_summary(h, trials) for h in HANDS}
        diff = {}
        for key in ("reaction_s", "reach_s", "peak_speed", "reach_size", "tracking_error", "shake"):
            a, b = hands["left"].get(key), hands["right"].get(key)
            if a is not None and b is not None and (a + b) > 0:
                diff[key] = round((a - b) / ((a + b) / 2) * 100, 1)
        tracking = {lv: {h: tr.result() for h, tr in by_hand.items()} for lv, by_hand in self.trackers.items()}
        return {"hands": hands, "left_right_difference_pct": diff, "reach_trials": trials, "tracking": tracking}

    def _hand_summary(self, hand, trials) -> dict:
        tracks = [tr.result() for by_hand in self.trackers.values() for h, tr in by_hand.items() if h == hand]
        return hand_summary(hand, trials, [x for x in tracks if x])


def hand_summary(hand: str, trials: List[dict], tracks: List[dict]) -> dict:
    """One hand's measurements from reach trials and tracker results (both plain dicts)."""
    rows = [t[hand] for t in trials if hand in t]
    out: Dict[str, Optional[float]] = {}

    def med(key, src=rows):
        vals = [r[key] for r in src if r.get(key) is not None]
        return round(median(vals), 3) if vals else None

    out["reaction_s"] = med("reaction_s")
    out["reach_s"] = med("reach_s")
    out["peak_speed"] = med("peak_speed")
    out["reach_size"] = med("reach_size")
    out["apples_reached"] = sum(r["reached"] for r in rows) if rows else None
    out["apples_total"] = len(rows) if rows else None
    speeds = [r["peak_speed"] for r in rows if r.get("peak_speed")]
    if len(speeds) >= 4:
        half = len(speeds) // 2
        first, last = mean(speeds[:half]), mean(speeds[-half:])
        out["speed_change_pct"] = round((last - first) / first * 100, 1) if first else None
    else:
        out["speed_change_pct"] = None

    out.update(combine_tracks(tracks))
    return out


def combine_tracks(tracks: List[dict]) -> dict:
    """Several tracker results as one: sample-weighted error, time on target and shake; median shake Hz."""
    total = sum(x["samples"] for x in tracks)
    if not total:
        return {"tracking_error": None, "on_target": None, "shake": None, "shake_hz": None}
    shakes = [x for x in tracks if x["shake"] is not None]
    hz = [x["shake_hz"] for x in tracks if x["shake_hz"]]
    return {
        "tracking_error": round(sum(x["tracking_error"] * x["samples"] for x in tracks) / total, 4),
        "on_target": round(sum(x["on_target"] * x["samples"] for x in tracks) / total, 3),
        "shake": (round(sum(x["shake"] * x["samples"] for x in shakes) / sum(x["samples"] for x in shakes), 4)
                  if shakes else None),
        "shake_hz": round(median(hz), 1) if hz else None,
    }


def game_summary(summary: dict, game: str) -> dict:
    """Measurements for one web lobby game, cut from a whole-visit `SessionMetrics.summary()`."""
    trials = [t for t in summary.get("reach_trials", []) if t.get("game") == game]
    by_hand = (summary.get("tracking") or {}).get(game) or {}
    hands = {h: hand_summary(h, trials, [by_hand[h]] if by_hand.get(h) else []) for h in HANDS}
    diff = {}
    for key in ("reaction_s", "reach_s", "peak_speed", "tracking_error", "shake"):
        a, b = hands["left"].get(key), hands["right"].get(key)
        if a is not None and b is not None and (a + b) > 0:
            diff[key] = round((a - b) / ((a + b) / 2) * 100, 1)
    return {"hands": hands, "left_right_difference_pct": diff, "attempts": len(trials)}
