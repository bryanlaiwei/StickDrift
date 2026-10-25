"""Turn one lobby visit into dashboard numbers and pattern scores.

Call `finish_visit` with the in-memory frames and the short event list from
Apple Picking, Harbour Fishing, and Rat Catching. Apple and Fishing are scored
by the pattern model. Rat Catching is counted from what the resident did. The
returned document is what gets stored. The frames are not part of it.

Shake, tracking error and the per-hand reach numbers come from
backend/app/measurements.py, the same code that measures the visit live, so
both places agree. This file only adds what the live view can't measure
(carry time, path length, overshoot, per-trace and rat details).
"""

import json
import math
import sys
from pathlib import Path

from backend.app.measurements import SAMPLE_KEYS, combine_tracks, hand_summary, shake, track

SCHEMA_VERSION = 1
MEANING = "0-100 pattern resemblance, not a disease probability"
GAMES = ("apple", "fish", "rat")
HANDS = ("left", "right")
SCORES = ("parkinson", "stroke", "essential_tremor")
# The trained model knows these two task names. Apple Picking and Harbour Fishing are
# scored for the same patterns. Rat Catching is not scored.
ACTIVITY = {"apple": "apples", "fish": "butterfly"}
DEFAULT_CHECKPOINT = Path(__file__).resolve().parents[1] / "runs" / "pattern_model" / "model.pt"

_CURSOR = {"left": ("cursor_lx", "cursor_ly"), "right": ("cursor_rx", "cursor_ry")}
_TARGET = {"left": ("target_lx", "target_ly"), "right": ("target_rx", "target_ry")}
_STICK = {"left": ("lx", "ly"), "right": ("rx", "ry")}
_ON = {"left": "on_l", "right": "on_r"}


def finish_visit(capture, score=None, checkpoint=None):
    """Build the stored document. `capture` maps a game name to frames and events."""
    capture = capture or {}
    path = Path(checkpoint) if checkpoint is not None else DEFAULT_CHECKPOINT
    if score is None:
        def score(game, frames, path=path):
            return score_with_model(game, frames, path)

    games = {name: _game(name, capture.get(name), score) for name in GAMES}
    by_game = {}
    for name in ("apple", "fish"):
        block = games[name]
        if block is None or not block.get("_scored"):
            continue
        by_game[name] = block["_model"]
    fused = _fuse(
        (by_game.get("apple") or {}).get("scores"),
        (by_game.get("fish") or {}).get("scores"),
    )
    for block in games.values():
        if block is not None:
            block.pop("_scored", None)
            block.pop("_model", None)
    model = {"scores": fused, "by_game": by_game, "meaning": MEANING}
    return {
        "schema_version": SCHEMA_VERSION,
        "levels_completed": sum(block is not None and block.get("finished") for block in games.values()),
        "games": games,
        "model": model,
        "dashboard": _dashboard(fused, by_game, games.get("rat")),
    }


def score_with_model(game, frames, checkpoint=DEFAULT_CHECKPOINT):
    """Score one game's frames. Apple is a reach task; fishing is a path task."""
    path = Path(checkpoint)
    if not path.is_file():
        raise FileNotFoundError(f"pattern model was not found at {path}")
    if game not in ACTIVITY:
        raise ValueError(f"the pattern model does not score {game}")

    import numpy as np
    import torch
    from ml.pattern_model.checkpoint import load_checkpoint
    from ml.pattern_model.config import Segment
    from ml.pattern_model.recording import Recording
    from ml.pattern_model.score import score_recording

    rows = [_model_row(frame, ACTIVITY[game]) for frame in frames]
    recording = Recording.from_rows(rows, ACTIVITY[game])
    device = torch.device("cpu")
    model, blob = load_checkpoint(path, device)
    mean = np.asarray(blob["norm_mean"], dtype=np.float32)
    std = np.asarray(blob["norm_std"], dtype=np.float32)
    return score_recording(
        model, recording, mean, std,
        sample_hz=int(blob["sample_hz"]),
        segment=Segment(**blob["segment"]),
        hand_scores=list(blob["hand_scores"]),
        device=device,
    )


def main():
    json.dump(finish_visit(json.load(sys.stdin)), sys.stdout)
    sys.stdout.write("\n")


def _game(name, bucket, score):
    if not bucket:
        return None
    frames = _frames(bucket.get("frames"))
    events = [event for event in bucket.get("events") or [] if isinstance(event, dict)]
    if not frames and not events:
        return None
    if name == "apple":
        block = _apple(frames, events)
    elif name == "fish":
        block = _fish(frames, events)
    elif name == "rat":
        block = _rat(frames, events)
    else:
        return None
    if bucket.get("truncated"):
        block["truncated"] = True
    block["finished"] = any(event.get("type") == "result" for event in events)
    if name in ACTIVITY and len(frames) >= 2:
        try:
            result = score(name, frames)
            block["_model"] = {
                "duration_s": result.get("duration_s"),
                "stretches": result.get("stretches"),
                "scores": result.get("scores"),
            }
        except Exception as error:
            block["_model"] = {"error": str(error)}
        block["_scored"] = True
    return block


def _apple(frames, events):
    trials = [_trial(event) for event in events if event.get("type") in ("trial", "grab")]
    trials = [trial for trial in trials if trial is not None]
    reaches = {hand: _reaches(frames, hand, phase_ok=lambda on: on == 0) for hand in HANDS}
    attempts = []
    for trial in trials:
        hand = trial["hand"]
        stats = _take_reach(reaches[hand], trial.get("t"))
        basket_t = _next_time(events, "basket", hand, trial.get("t"))
        delivered = basket_t is not None and trial.get("reached")
        attempts.append({
            **trial,
            "delivered": bool(delivered),
            "carry_s": None if not delivered else round(basket_t - trial["t"], 3),
            "path_length": None if stats is None else stats["path_length"],
            "reversals": None if stats is None else stats["reversals"],
            "overshoot": None if stats is None else stats["overshoot"],
        })
    result = _last(events, "result") or {}
    basket = _tally(events, "basket")
    if not any(basket.values()) and result:
        basket = {"left": int(result.get("red") or 0), "right": int(result.get("blue") or 0)}
    wrong = _tally(events, "wrong")
    expired = _tally(events, "expired")
    grabs = {hand: sum(1 for trial in trials if trial["hand"] == hand and trial["reached"]) for hand in HANDS}
    per_hand = {}
    for hand in HANDS:
        mine = [attempt for attempt in attempts if attempt["hand"] == hand]
        reached = [attempt for attempt in mine if attempt["reached"]]
        shared = hand_summary(hand, [{hand: attempt} for attempt in mine], [])
        per_hand[hand] = {
            "median_reaction_s": shared["reaction_s"],
            "median_reach_s": shared["reach_s"],
            "median_carry_s": _median(attempt["carry_s"] for attempt in reached),
            "median_peak_speed": shared["peak_speed"],
            "median_reach_size": shared["reach_size"],
            "median_path_length": _median(attempt["path_length"] for attempt in reached),
            "speed_change_pct": shared["speed_change_pct"],
            "idle_s": _idle(frames, hand),
            "shake": shake(_xy(frame, _STICK[hand]) for frame in frames),
        }
    return {
        "score": _int(result.get("score")),
        "stars": _int(result.get("stars")),
        "duration_s": _span(frames, events),
        "basket": basket,
        "wrong_touches": wrong,
        "expired": expired,
        "grabs": grabs,
        "undelivered": {hand: max(0, grabs[hand] - basket[hand]) for hand in HANDS},
        "attempts": attempts,
        "per_hand": per_hand,
        "left_right": _gap({
            "basket": (basket["left"], basket["right"]),
            "median_reach_s": (per_hand["left"]["median_reach_s"], per_hand["right"]["median_reach_s"]),
            "median_reaction_s": (per_hand["left"]["median_reaction_s"], per_hand["right"]["median_reaction_s"]),
        }),
    }


def _fish(frames, events):
    segments = _track_segments(frames)
    traces = []
    for event in events:
        if event.get("type") != "trace":
            continue
        hand = _hand(event)
        if hand is None:
            continue
        stats = dict(segments.pop(0) if segments else _empty_track())
        stats.pop("hand", None)
        stats.pop("trial", None)
        stats.pop("time_s", None)
        stats.pop("on_lane_pct", None)
        traces.append({
            "round": event.get("round"),
            "hand": hand,
            "shape": event.get("shape"),
            "time_s": _num(event.get("time_s", event.get("time"))),
            "on_lane_pct": _num(event.get("on_lane_pct", event.get("pct"))),
            "off_count": _int(event.get("off_count", event.get("off"))),
            "score": _int(event.get("score")),
            "completed": True,
            **stats,
        })
    for stats in segments:
        traces.append({"round": stats.pop("trial"), "hand": stats.pop("hand"), "shape": None,
                       "time_s": stats.pop("time_s"), "on_lane_pct": stats.pop("on_lane_pct"),
                       "off_count": None, "score": None, "completed": False, **stats})
    result = _last(events, "result") or {}
    per_hand = {}
    for hand in HANDS:
        mine = [trace for trace in traces if trace["hand"] == hand and trace["completed"]]
        tracked = combine_tracks([trace["_track"] for trace in traces if trace["hand"] == hand and trace["_track"]])
        per_hand[hand] = {
            "traces": len(mine),
            "mean_time_s": _mean(trace["time_s"] for trace in mine),
            "mean_on_lane_pct": _mean(trace["on_lane_pct"] for trace in mine),
            "mean_off_count": _mean(trace["off_count"] for trace in mine),
            "mean_lag": tracked["tracking_error"],
            "shake": tracked["shake"],
        }
    for trace in traces:
        trace.pop("_track", None)
    return {
        "score": _int(result.get("score")),
        "stars": _int(result.get("stars")),
        "caught": _int(result.get("caught")),
        "duration_s": _span(frames, events),
        "traces": traces,
        "per_hand": per_hand,
        "left_right": _gap({
            "mean_on_lane_pct": (per_hand["left"]["mean_on_lane_pct"], per_hand["right"]["mean_on_lane_pct"]),
            "mean_time_s": (per_hand["left"]["mean_time_s"], per_hand["right"]["mean_time_s"]),
        }),
    }


def _rat(frames, events):
    del frames  # a slam's timing comes from the game, which already decided the hit
    slams = []
    misses = []
    for event in events:
        kind = event.get("type")
        if kind == "slam":
            hand = _hand(event)
            outcome = event.get("outcome")
            if hand is None or outcome not in ("caught", "wrong", "empty"):
                continue
            slams.append({
                "hand": hand,
                "outcome": outcome,
                "round": event.get("round"),
                "reaction_s": _num(event.get("reaction_s")),
                "reach_s": _num(event.get("reach_s")),
                "flick_speed": _num(event.get("flick_speed")),
                "early": bool(event.get("early")) or outcome == "empty",
                "other_stick": bool(event.get("other_stick")),
                "t": _num(event.get("t")),
            })
        elif kind == "miss":
            misses.append({"round": event.get("round"), "t": _num(event.get("t"))})
    result = _last(events, "result") or {}
    caught = sum(slam["outcome"] == "caught" for slam in slams)
    wrong = sum(slam["outcome"] == "wrong" for slam in slams)
    empty = sum(slam["outcome"] == "empty" for slam in slams)
    missed = len(misses)
    if not slams and not misses and result:
        caught = _int(result.get("caught")) or 0
        wrong = _int(result.get("wrong")) or 0
        empty = _int(result.get("empty")) or 0
        missed = _int(result.get("missed")) or 0
    total = caught + wrong + empty + missed
    cards = [
        {"round": event.get("round"), "caught": bool(event.get("caught")), "reaction_s": _num(event.get("reaction_s"))}
        for event in events if event.get("type") == "card_rat"
    ]
    if cards:
        reactions = [card["reaction_s"] for card in cards if card["reaction_s"] is not None]
    else:
        reactions = [slam["reaction_s"] for slam in slams if slam["reaction_s"] is not None]
    correctness = _num(result.get("correctness_pct"))
    if correctness is None and cards:
        correctness = round(100 * sum(card["caught"] for card in cards) / len(cards), 1)
    per_hand = {}
    for hand in HANDS:
        mine = [slam for slam in slams if slam["hand"] == hand]
        per_hand[hand] = {
            "slams": len(mine),
            "caught": sum(slam["outcome"] == "caught" for slam in mine),
            "median_reaction_s": _median(slam["reaction_s"] for slam in mine),
            "median_flick_speed": _median(slam["flick_speed"] for slam in mine),
        }
    return {
        "score": _int(result.get("score")),
        "stars": _int(result.get("stars")),
        "duration_s": _span([], events),
        "caught": caught,
        "missed": missed,
        "wrong": wrong,
        "empty": empty,
        "accuracy": None if not total else round(caught / total, 3),
        "target_rats": len(cards) if cards else _int(result.get("target_rats")),
        "correctness_pct": correctness,
        "card_rats": cards,
        "median_reaction_s": _median(reactions),
        "reaction_spread_s": None if len(reactions) < 2 else round(max(reactions) - min(reactions), 3),
        "early_slams": sum(1 for slam in slams if slam["early"]),
        "slams": slams,
        "misses": misses,
        "rounds": _rounds(slams, misses),
        "per_hand": per_hand,
    }


def _frames(raw):
    frames = []
    for item in raw or []:
        if isinstance(item, dict) and item.get("t") is not None:
            frames.append(item)
        elif isinstance(item, list) and len(item) >= 17:
            frames.append(dict(zip(SAMPLE_KEYS, item)))
    frames.sort(key=lambda frame: float(frame["t"]))
    return frames


def _reaches(frames, hand, phase_ok):
    reaches = []
    current = None
    previous = None
    for frame in frames:
        target = _xy(frame, _TARGET[hand])
        cursor = _xy(frame, _CURSOR[hand])
        on = int(frame.get(_ON[hand]) or 0)
        active = target is not None and phase_ok(on)
        jumped = previous is not None and target is not None and _dist(previous, target) > 0.25
        if active and (current is None or jumped):
            if current is not None:
                reaches.append(current)
            current = {"t0": float(frame["t"]), "samples": []}
        if not active and current is not None:
            reaches.append(current)
            current = None
            previous = None
            continue
        if current is not None:
            current["samples"].append((float(frame["t"]), cursor, target, _xy(frame, _STICK[hand])))
            previous = target
    if current is not None:
        reaches.append(current)
    return [_reach_stats(reach) for reach in reaches]


def _reach_stats(reach):
    cursors = [sample[1] for sample in reach["samples"]]
    return {
        "t": reach["samples"][-1][0] if reach["samples"] else reach["t0"],
        "path_length": _path(cursors),
        "reversals": _reversals(cursors),
        "overshoot": _overshoot((sample[1], sample[2]) for sample in reach["samples"]),
    }


def _take_reach(reaches, when):
    if not reaches:
        return None
    if when is None:
        return reaches.pop(0)
    index = min(range(len(reaches)), key=lambda i: abs(reaches[i]["t"] - when))
    return reaches.pop(index)


def _track_segments(frames):
    groups = []
    current = None
    for frame in frames:
        if frame.get("phase") != "track":
            if current is not None:
                groups.append(current)
                current = None
            continue
        hand = next((name for name in HANDS if _xy(frame, _TARGET[name]) is not None), None)
        trial = frame.get("trial")
        if current is None or current["hand"] != hand or current["trial"] != trial:
            if current is not None:
                groups.append(current)
            current = {"hand": hand, "trial": trial, "samples": []}
        if hand is not None:
            current["samples"].append(frame)
    if current is not None:
        groups.append(current)
    return [_track_stats(group) for group in groups if group["samples"]]


def _track_stats(group):
    hand = group["hand"]
    samples = group["samples"]
    ons = []
    cursors = []
    times = []
    for frame in samples:
        cursors.append(_xy(frame, _CURSOR[hand]))
        times.append(float(frame["t"]))
        ons.append(int(frame.get(_ON[hand]) or 0))
    tracked = track((float(frame["t"]), _xy(frame, _CURSOR[hand]), _xy(frame, _TARGET[hand]),
                     _xy(frame, _STICK[hand]), int(frame.get(_ON[hand]) or 0)) for frame in samples)
    off_s, longest = _off_runs(times, ons)
    first = None
    for time, on in zip(times, ons):
        if on:
            first = round(time - times[0], 3)
            break
    on_pct = round(100 * sum(ons) / len(ons), 1) if ons else None
    return {
        "hand": hand,
        "trial": group["trial"],
        "time_s": None if len(times) < 2 else round(times[-1] - times[0], 3),
        "on_lane_pct": on_pct,
        "lag": None if tracked is None else tracked["tracking_error"],
        "path_length": _path(cursors),
        "reversals": _reversals(cursors),
        "off_s": off_s,
        "longest_off_s": longest,
        "first_contact_s": first,
        "shake": None if tracked is None else tracked["shake"],
        "_track": tracked,
    }


def _empty_track():
    return {
        "lag": None, "path_length": None, "reversals": None, "off_s": None,
        "longest_off_s": None, "first_contact_s": None, "shake": None, "_track": None,
    }


def _off_runs(times, ons):
    total = 0.0
    longest = 0.0
    run = 0.0
    for index in range(1, len(times)):
        step = times[index] - times[index - 1]
        if not ons[index]:
            total += step
            run += step
            longest = max(longest, run)
        else:
            run = 0.0
    return round(total, 3), round(longest, 3)


def _rounds(slams, misses):
    by_round = {}

    def slot(number):
        return by_round.setdefault(number, {"round": number, "caught": 0, "wrong": 0, "empty": 0, "missed": 0})

    for slam in slams:
        slot(slam.get("round"))[slam["outcome"]] += 1
    for miss in misses:
        slot(miss.get("round"))["missed"] += 1
    return [by_round[key] for key in sorted(by_round, key=lambda number: (number is None, number or 0))]


def _dashboard(scores, by_game, rat):
    """What the caregiver sees after the visit: fused pattern scores and the rat-game score."""
    scored = isinstance(scores, dict) and any(value is not None for value in scores.values())
    levels = []
    for name, block in by_game.items():
        if not isinstance(block, dict):
            continue
        levels.append({
            "level": name,
            "completed": "error" not in block,
            "scores": block.get("scores") or {key: None for key in SCORES},
            "stretches": block.get("stretches"),
            "duration_s": block.get("duration_s"),
            "error": block.get("error"),
        })
    shown = None
    if isinstance(rat, dict) and rat.get("score") is not None:
        shown = {
            "score": rat.get("score"),
            "stars": rat.get("stars"),
            "caught": rat.get("caught"),
            "missed": rat.get("missed"),
            "wrong": rat.get("wrong"),
            "empty": rat.get("empty"),
            "target_rats": rat.get("target_rats"),
            "correctness_pct": rat.get("correctness_pct"),
            "median_reaction_s": rat.get("median_reaction_s"),
        }
    return {
        "scores": scores if scored else None,
        "levels": levels,
        "meaning": MEANING,
        "rat": shown,
    }


def _fuse(apple, fish):
    if not apple or not fish:
        return apple or fish

    def average(left, right):
        values = [value for value in (left, right) if value is not None]
        if not values:
            return None
        return round(sum(values) / len(values), 1)

    def keep(value):
        return None if value is None else round(float(value), 1)

    return {
        "parkinson": average(apple.get("parkinson"), fish.get("parkinson")),
        "stroke": keep(apple.get("stroke")),
        "essential_tremor": average(apple.get("essential_tremor"), fish.get("essential_tremor")),
    }


def _trial(event):
    hand = _hand(event)
    if hand is None:
        return None
    return {
        "trial": event.get("trial"),
        "hand": hand,
        "t": _num(event.get("t")),
        "reaction_s": _num(event.get("reaction_s")),
        "reach_s": _num(event.get("reach_s")),
        "peak_speed": _num(event.get("peak_speed")),
        "reach_size": _num(event.get("reach_size")),
        "reached": bool(event.get("reached")),
    }


def _tally(events, kind):
    counts = {"left": 0, "right": 0}
    for event in events:
        if event.get("type") != kind:
            continue
        hand = _hand(event)
        if hand is not None:
            counts[hand] += int(event.get("count") or 1)
    return counts


def _next_time(events, kind, hand, after):
    if after is None:
        return None
    times = [_num(event.get("t")) for event in events
             if event.get("type") == kind and _hand(event) == hand and _num(event.get("t")) is not None
             and _num(event.get("t")) >= after]
    return min(times) if times else None


def _last(events, kind):
    found = [event for event in events if event.get("type") == kind]
    return found[-1] if found else None


def _hand(event):
    hand = event.get("hand") or event.get("side")
    return hand if hand in HANDS else None


def _gap(pairs):
    out = {}
    for key, (left, right) in pairs.items():
        if left is None or right is None:
            continue
        out[key] = round(left - right, 3)
    return out


def _idle(frames, hand):
    total = 0.0
    previous = None
    for frame in frames:
        stick = _xy(frame, _STICK[hand])
        waiting = _xy(frame, _TARGET[hand]) is not None and int(frame.get(_ON[hand]) or 0) == 0
        still = stick is not None and _dist(stick, (0.0, 0.0)) < 0.2
        now = (float(frame["t"]), waiting and still)
        if previous and previous[1] and now[1]:
            total += now[0] - previous[0]
        previous = now
    return round(total, 3)


def _path(points):
    total = 0.0
    previous = None
    seen = False
    for point in points:
        if point is None:
            continue
        if previous is not None:
            total += _dist(previous, point)
            seen = True
        previous = point
    return round(total, 3) if seen else None


def _reversals(points):
    flips = 0
    sign = [0, 0]
    previous = None
    for point in points:
        if point is None:
            continue
        if previous is not None:
            for axis in (0, 1):
                delta = point[axis] - previous[axis]
                if abs(delta) <= 0.002:
                    continue
                way = 1 if delta > 0 else -1
                if sign[axis] and way != sign[axis]:
                    flips += 1
                sign[axis] = way
        previous = point
    return flips


def _overshoot(samples):
    distances = []
    for cursor, target in samples:
        if cursor is None or target is None:
            continue
        distances.append(_dist(cursor, target))
    if not distances:
        return None
    closest = min(range(len(distances)), key=distances.__getitem__)
    if closest == len(distances) - 1:
        return 0.0
    return round(max(distances[closest:]) - distances[closest], 3)


def _span(frames, events):
    times = [float(frame["t"]) for frame in frames if frame.get("t") is not None]
    times += [value for value in (_num(event.get("t")) for event in events) if value is not None]
    if len(times) < 2:
        return 0.0
    return round(max(times) - min(times), 3)


def _xy(frame, keys):
    x, y = frame.get(keys[0]), frame.get(keys[1])
    if x is None or y is None or x == "" or y == "":
        return None
    return float(x), float(y)


def _dist(left, right):
    return math.hypot(left[0] - right[0], left[1] - right[1])


def _median(values):
    numbers = sorted(value for value in values if value is not None)
    if not numbers:
        return None
    mid = len(numbers) // 2
    if len(numbers) % 2:
        return round(numbers[mid], 3)
    return round((numbers[mid - 1] + numbers[mid]) / 2, 3)


def _mean(values):
    numbers = [value for value in values if value is not None]
    if not numbers:
        return None
    return round(sum(numbers) / len(numbers), 3)


def _num(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return number


def _int(value):
    number = _num(value)
    return None if number is None else int(number)


def _model_row(frame, activity):
    # Gyro and accelerometer ride along when the DualSense HID report was captured.
    # Missing motion channels stay at 0 so the stick, target, and in-game hand still score.
    row = {"level": activity, "phase": frame.get("phase") or ""}
    for key in ("t", "lx", "ly", "rx", "ry", "gyro_x", "gyro_y", "gyro_z", "acc_x", "acc_y", "acc_z"):
        row[key] = 0.0 if frame.get(key) is None else float(frame.get(key))
    for key in ("target_lx", "target_ly", "target_rx", "target_ry",
                "cursor_lx", "cursor_ly", "cursor_rx", "cursor_ry"):
        value = frame.get(key)
        row[key] = "" if value is None or value == "" else value
    return row


if __name__ == "__main__":
    main()
