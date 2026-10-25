"""Synthetic apple and fishing recordings for the pattern model.

Each condition is one person. The apple file and the fishing file share the
same scores. Three traits are kept apart so a mix can carry more than one:

- Parkinson slows, weakens, and breaks both hands into small steps. The
  gyroscope stays still.
- Essential tremor is a gyroscope oscillation. The hands keep a normal speed.
- Stroke slows one hand and leaves the other at a normal speed.

The fishing lane has no stored border: reached_l / reached_r is 1 while the
cursor is inside the lane and 0 while it is outside. The cursor is always written.

Folder names are the labels.
"""

import csv
import math
import shutil
from dataclasses import dataclass
from pathlib import Path

import numpy as np

HZ = 60
LANE_HALF = 0.10

APPLES_LEFT = (
    (0.42, -0.28),
    (-0.36, 0.18),
    (0.18, 0.40),
    (-0.48, -0.16),
    (0.52, 0.08),
    (0.02, -0.42),
)
APPLES_RIGHT = tuple((-x, y + 0.05) for x, y in APPLES_LEFT)

COLUMNS = (
    "t", "level", "phase",
    "lx", "ly", "rx", "ry",
    "gyro_x", "gyro_y", "gyro_z",
    "tgt_lx", "tgt_ly", "tgt_rx", "tgt_ry",
    "reached_l", "reached_r",
    "cur_lx", "cur_ly", "cur_rx", "cur_ry",
)


@dataclass(frozen=True)
class Condition:
    folder: str
    parkinson: float
    stroke: float
    tremor: float
    weak_hand: str | None = None
    tremor_hand: str | None = None
    latency_s: float = 0.08
    move_s_left: float = 0.35
    move_s_right: float = 0.35
    gain_left: float = 1.0
    gain_right: float = 1.0
    gyro_shake: float = 0.0
    tremor_hz: float = 5.5
    levels: tuple[str, ...] = ("apple", "fish")


def _person(
    folder: str,
    parkinson: float = 0.0,
    stroke: float = 0.0,
    tremor: float = 0.0,
    weak_hand: str | None = None,
) -> Condition:
    shared = parkinson / 100.0
    sided = stroke / 100.0
    shake = tremor / 100.0
    # Parkinson weakens both hands a little. A moderate slowdown is already the
    # full pattern, so the score rises before the reach is extremely slow.
    # Stroke changes speed on one hand only. Mild tremor is a small gyroscope
    # wobble; the shake has to be strong before it matches a high score.
    gain_left = 1.0 - 0.22 * shared
    gain_right = 1.0 - 0.22 * shared
    move_left = 0.35 + 0.62 * shared
    move_right = 0.35 + 0.62 * shared
    if weak_hand == "left":
        move_left += 0.72 * sided
    elif weak_hand == "right":
        move_right += 0.72 * sided
    return Condition(
        folder,
        parkinson,
        stroke,
        tremor,
        weak_hand=weak_hand,
        latency_s=0.08 + 0.22 * shared,
        move_s_left=move_left,
        move_s_right=move_right,
        gain_left=gain_left,
        gain_right=gain_right,
        # Mild tremor already shakes hard. A small wobble stays well below a score of 25.
        gyro_shake=0.0 if shake <= 0.0 else 220.0 * (shake ** 0.55),
    )


_SEVERITIES = (25.0, 50.0, 75.0, 100.0)
_DISEASES = (
    ("Parkinson", "parkinson", None),
    ("Tremor", "tremor", None),
    ("Stroke Left", "stroke", "left"),
    ("Stroke Right", "stroke", "right"),
)


def _conditions() -> tuple[Condition, ...]:
    """Baseline, each disease at 25/50/75/100, and every pair at every strength pair."""
    found: list[Condition] = [_person("Baseline")]
    for name, kind, side in _DISEASES:
        for amount in _SEVERITIES:
            found.append(_person(f"{name} {int(amount)}", weak_hand=side, **{kind: amount}))
    for index, left in enumerate(_DISEASES):
        for right in _DISEASES[index + 1:]:
            if left[1] == "stroke" and right[1] == "stroke":
                continue
            side = left[2] or right[2]
            for left_amount in _SEVERITIES:
                for right_amount in _SEVERITIES:
                    folder = f"{left[0]} {int(left_amount)} + {right[0]} {int(right_amount)}"
                    scores = {left[1]: left_amount, right[1]: right_amount}
                    found.append(_person(folder, weak_hand=side, **scores))
    return tuple(found)


CONDITIONS = _conditions()


def write_synthetic(root: str | Path, seeds: int = 3) -> int:
    """Write several apple and fishing takes per condition. Returns the file count."""
    destination = Path(root)
    if destination.exists():
        shutil.rmtree(destination)
    count = 0
    for condition in CONDITIONS:
        for level in condition.levels:
            for seed in range(1, seeds + 1):
                folder = destination / condition.folder / f"{level}_s{seed}"
                folder.mkdir(parents=True)
                rows = _apple(condition, seed) if level == "apple" else _fish(condition, seed)
                _write(folder / "controller_data.csv", rows)
                count += 1
    return count


def _apple(condition: Condition, seed: int) -> list[list]:
    rng = np.random.default_rng(_seed(condition, seed))
    rows: list[list] = []
    clock = 0.0
    clock = _hold(rows, clock, 0.45, "apple", "", (0.0, 0.0), (0.0, 0.0), (0.0, 0.0), (0.0, 0.0), condition)
    for index, (left_goal, right_goal) in enumerate(zip(APPLES_LEFT, APPLES_RIGHT, strict=True)):
        clock = _reach(rows, clock, rng, condition, index, "apple", "cue", left_goal, right_goal)
        clock = _reach(
            rows, clock, rng, condition, index, "apple", "carry",
            (0.0, 0.15), (0.0, 0.15), origin=(left_goal, right_goal),
        )
        clock = _hold(rows, clock, 0.30, "apple", "", (0.0, 0.0), (0.0, 0.0), (0.0, 0.0), (0.0, 0.0), condition)
    return rows


def _fish(condition: Condition, seed: int) -> list[list]:
    rows: list[list] = []
    clock = 0.0
    for hand, sign in (("left", 1.0), ("right", -1.0)):
        clock = _hold(rows, clock, 0.40, "fish", "", (0.0, 0.0), (0.0, 0.0), (0.0, 0.0), (0.0, 0.0), condition)
        duration = 8.0
        count = int(round(duration * HZ))
        followed = (0.0, 0.0)
        move_s = condition.move_s_left if hand == "left" else condition.move_s_right
        for step in range(count):
            time_s = clock + step / HZ
            along = -0.75 + 1.50 * (step / max(count - 1, 1))
            sway = 0.22 * math.sin(2.0 * math.pi * (0.55 + 0.04 * seed) * time_s)
            center = (sign * along * (1.0 + 0.02 * (seed - 2)), sway)
            followed = _follow(followed, center, move_s)
            cursor = _fish_cursor(condition, hand, followed, time_s, seed)
            other = (0.0, 0.0)
            left_cur, right_cur = (cursor, other) if hand == "left" else (other, cursor)
            left_tgt, right_tgt = (center, None) if hand == "left" else (None, center)
            reached_l = _inside(left_cur, left_tgt)
            reached_r = _inside(right_cur, right_tgt)
            stick_l = _stick_command("left", left_cur, moving=hand == "left")
            stick_r = _stick_command("right", right_cur, moving=hand == "right")
            rows.append(_row(time_s, "fish", "track", stick_l, stick_r, left_tgt, right_tgt, left_cur, right_cur, reached_l, reached_r, condition))
        clock += duration
    return rows


def _reach(rows, clock, rng, condition, index, level, phase, left_goal, right_goal, origin=None):
    del rng
    start_left, start_right = ((0.0, 0.0), (0.0, 0.0)) if origin is None else origin
    longest = max(condition.move_s_left, condition.move_s_right)
    duration = condition.latency_s + longest + 0.20
    count = max(2, int(round(duration * HZ)))
    for step in range(count):
        elapsed = step / HZ
        time_s = clock + elapsed
        left = _aimed(condition, "left", start_left, left_goal, elapsed, index)
        right = _aimed(condition, "right", start_right, right_goal, elapsed, index)
        moving = elapsed > condition.latency_s
        stick_l = _stick_command("left", left, moving=moving)
        stick_r = _stick_command("right", right, moving=moving)
        rows.append(_row(
            time_s, level, phase, stick_l, stick_r, left_goal, right_goal, left, right, 0, 0, condition,
        ))
    return clock + duration


def _aimed(condition, hand, start, goal, elapsed, index):
    gain = condition.gain_left if hand == "left" else condition.gain_right
    move_s = condition.move_s_left if hand == "left" else condition.move_s_right
    # Later reaches get smaller. That is the parkinson decrement, shared by both hands.
    if condition.parkinson > 0.0:
        gain *= max(0.72, 1.0 - 0.28 * (condition.parkinson / 100.0) * (index / 5.0))
    if elapsed < condition.latency_s:
        scale = 0.0
    else:
        moved = elapsed - condition.latency_s
        unit = moved / move_s
        scale = _progress(moved, unit, condition.parkinson / 100.0)
    return (
        start[0] + (goal[0] - start[0]) * gain * scale,
        start[1] + (goal[1] - start[1]) * gain * scale,
    )


def _follow(previous, target, move_s):
    """Lag the lane. A long reach time is a slow hand, still fast enough to score."""
    tau = 0.04 + 0.16 * max(0.0, move_s - 0.35)
    alpha = (1.0 / HZ) / ((1.0 / HZ) + tau)
    return (
        previous[0] + alpha * (target[0] - previous[0]),
        previous[1] + alpha * (target[1] - previous[1]),
    )


def _fish_cursor(condition, hand, center, time_s, seed: int):
    gain = condition.gain_left if hand == "left" else condition.gain_right
    point = (center[0] * gain, center[1] * gain)
    return _steps(point, condition.parkinson / 100.0, seed)


def _stick_command(hand, cursor, moving: bool):
    del hand
    if not moving:
        return (0.0, 0.0)
    return (max(-1.0, min(1.0, cursor[0])), max(-1.0, min(1.0, cursor[1] * 0.5)))


def _inside(cursor, target) -> int:
    if target is None:
        return 0
    return 1 if math.dist(cursor, target) <= LANE_HALF else 0


def _hold(rows, clock, duration, level, phase, left_tgt, right_tgt, left_cur, right_cur, condition: Condition | None = None) -> float:
    count = max(2, int(round(duration * HZ)))
    for step in range(count):
        time_s = clock + step / HZ
        rows.append(_row(
            time_s, level, phase, (0.0, 0.0), (0.0, 0.0), left_tgt, right_tgt, left_cur, right_cur, 0, 0, condition,
        ))
    return clock + duration


def _row(time_s, level, phase, stick_l, stick_r, left_tgt, right_tgt, left_cur, right_cur, reached_l, reached_r, condition=None):
    gyro = _gyro(condition, time_s)
    return [
        round(time_s, 4),
        level,
        phase,
        _num(stick_l[0]), _num(stick_l[1]), _num(stick_r[0]), _num(stick_r[1]),
        _num(gyro[0]), _num(gyro[1]), _num(gyro[2]),
        *_point(left_tgt),
        *_point(right_tgt),
        reached_l,
        reached_r,
        _num(left_cur[0]), _num(left_cur[1]), _num(right_cur[0]), _num(right_cur[1]),
    ]


def _gyro(condition, time_s) -> tuple[float, float, float]:
    """Controller shake. Parkinson and stroke leave this at rest."""
    if condition is None or condition.gyro_shake <= 0.0:
        return (0.0, 0.0, 0.0)
    cycle = 2.0 * math.pi * condition.tremor_hz * time_s
    amp = condition.gyro_shake
    return (
        amp * math.sin(cycle),
        amp * 0.70 * math.cos(cycle),
        amp * 0.35 * math.sin(cycle * 1.07),
    )


def _progress(moved: float, unit: float, incremental: float) -> float:
    """A smooth reach, or short steps with brief pauses when parkinson is present.

    Each step is quick enough to be detected. The pauses make the whole reach
    slow without breaking it into pieces the scorer would drop.
    """
    unit = min(max(unit, 0.0), 1.0)
    if incremental <= 0.0:
        return _ease(unit)
    hop_s = 0.12
    pause_s = 0.10 * incremental
    cycle = hop_s + pause_s
    steps = 4
    if moved >= steps * cycle:
        return 1.0
    whole = math.floor(moved / cycle)
    frac_s = moved - whole * cycle
    if frac_s < pause_s:
        hop = 0.0
    else:
        hop = min((frac_s - pause_s) / hop_s, 1.0)
    return min((whole + hop) / steps, 1.0)


def _steps(point, incremental: float, seed: int):
    """Snap a fishing cursor onto a coarse grid. Zero leaves the point alone."""
    if incremental <= 0.0:
        return point
    grid = 0.055 + 0.01 * (seed % 3)
    return (round(point[0] / grid) * grid, round(point[1] / grid) * grid)


def _point(point) -> tuple[str, str]:
    if point is None:
        return "", ""
    return _num(point[0]), _num(point[1])


def _num(value: float) -> str:
    return f"{value:.4f}"


def _ease(unit: float) -> float:
    unit = min(max(unit, 0.0), 1.0)
    return 0.5 - 0.5 * math.cos(math.pi * unit)


def _seed(condition: Condition, seed: int) -> int:
    return seed + sum(ord(char) for char in condition.folder)


def _write(path: Path, rows: list[list]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(COLUMNS)
        writer.writerows(rows)


def main() -> None:
    count = write_synthetic(Path("data/Synthetic"), seeds=3)
    print(f"Wrote {count} synthetic recordings to data/Synthetic")


if __name__ == "__main__":
    main()
