"""Cut each hand into moving stretches and remove the slow path.

The slow path is a centered average of the stick. A reach takes a large
fraction of a second, so it survives the average. A shake flips direction
several times a second, so it cancels out. The network sees the difference,
plus how fast the slow path moved for its size.

The miss is separate from that leftover. It is the stick, in the game's
-1..1 space, minus that hand's target, rotated so the target direction is
the along axis. Positive along means the hand went past the target. Across
means it left the line of the target. A 6 Hz wobble stays in the residual.
A slow departure from a moving path stays in the miss.
"""

from dataclasses import dataclass, replace

import numpy as np

from ml.pattern_model.config import CHANNELS, DEFAULT_SEGMENT, HAND_CHANNELS, Segment
from ml.pattern_model.prepare import Prepared

_LEFT = (CHANNELS.index("lx"), CHANNELS.index("ly"))
_RIGHT = (CHANNELS.index("rx"), CHANNELS.index("ry"))
_GYRO = (CHANNELS.index("gyro_x"), CHANNELS.index("gyro_y"), CHANNELS.index("gyro_z"))
_HANDS = (("left", _LEFT, (0, 1)), ("right", _RIGHT, (2, 3)))
_MIN_TARGET_RADIUS = 0.05


@dataclass(frozen=True)
class Stretch:
    """One moving stretch for one hand, already shaped for the shared network."""

    hand: str
    values: np.ndarray
    start_s: float
    end_s: float
    speed_ratio: float
    amplitude: float


def build_stretches(
    prepared: Prepared,
    cues: np.ndarray,
    segment: Segment = DEFAULT_SEGMENT,
    task_spans: np.ndarray | None = None,
) -> list[Stretch]:
    """Return the moving stretches of both hands, in time order."""
    smooth_w = _odd_window(segment.smooth_s, prepared.sample_hz, prepared.values.shape[1])
    gyro = prepared.values[list(_GYRO)]
    gyro_resid = gyro - moving_average(gyro, smooth_w)
    in_task = _in_task(prepared.time_s, task_spans)
    found: list[tuple[float, Stretch]] = []
    for hand, sticks, aim_pair in _HANDS:
        found.extend(
            _hand_stretches(
                prepared, cues, segment, hand, sticks, aim_pair, gyro_resid, smooth_w, task_spans, in_task
            )
        )
    found.sort(key=lambda item: (item[0], item[1].hand))
    ordered = _with_shrink([item[1] for item in found], segment.shrink_clip)
    return ordered


def moving_average(values: np.ndarray, window: int) -> np.ndarray:
    """Centered moving average along the last axis. `values` is (channels, time)."""
    if window <= 1:
        return np.array(values, dtype=np.float64, copy=True)
    pad = window // 2
    padded = np.pad(values, ((0, 0), (pad, pad)), mode="edge")
    kernel = np.ones(window, dtype=np.float64) / window
    return np.vstack([np.convolve(padded[index], kernel, mode="valid") for index in range(values.shape[0])])


def _hand_stretches(
    prepared: Prepared,
    cues: np.ndarray,
    segment: Segment,
    hand: str,
    sticks: tuple[int, int],
    aim_pair: tuple[int, int],
    gyro_resid: np.ndarray,
    smooth_w: int,
    task_spans: np.ndarray | None,
    in_task: np.ndarray,
) -> list[tuple[float, Stretch]]:
    position = _hand_motion(prepared, aim_pair, sticks)
    motion = replace(segment, **_motion_limits(position, segment))
    slow = moving_average(position, smooth_w)
    residual = prepared.values[list(sticks)] - moving_average(prepared.values[list(sticks)], smooth_w)
    runs = _runs(position, prepared.sample_hz, motion)
    stretches: list[tuple[float, Stretch]] = []
    matched = _matched_runs(runs, prepared.time_s, cues, task_spans, segment.max_latency_s)
    for start, end, latency_s, has_cue, span in matched:
        override = None if span is None else _span_amplitude(position, prepared.time_s, span[0], span[1])
        piece = _stretch(
            prepared,
            motion,
            hand,
            position,
            slow,
            residual,
            gyro_resid,
            start,
            end,
            latency_s,
            has_cue,
            override,
            aim_pair,
            in_task,
        )
        if piece is not None:
            stretches.append((piece.start_s, piece))
    return stretches


def _matched_runs(
    runs: list[tuple[int, int]],
    time_s: np.ndarray,
    cues: np.ndarray,
    task_spans: np.ndarray | None,
    max_latency_s: float,
) -> list[tuple[int, int, float, float, tuple[float, float] | None]]:
    """Keep reaches inside a task. With only cue times, keep the next reach. With neither, keep every stretch."""
    if task_spans is not None and len(task_spans):
        chosen: list[tuple[int, int, float, float, tuple[float, float] | None]] = []
        for start, end in runs:
            start_s = float(time_s[start])
            hits = np.where((start_s >= task_spans[:, 0] - 0.05) & (start_s <= task_spans[:, 1] + 0.05))[0]
            if len(hits) == 0:
                continue
            span = (float(task_spans[hits[0], 0]), float(task_spans[hits[0], 1]))
            delay = max(0.0, start_s - span[0])
            chosen.append((start, end, delay, 1.0, span))
        return chosen
    if cues.size == 0:
        return [(start, end, 0.0, 0.0, None) for start, end in runs]
    chosen = []
    used: set[int] = set()
    cue_times = [float(item) for item in cues]
    for index, cue in enumerate(cue_times):
        window_end = cue_times[index + 1] if index + 1 < len(cue_times) else cue + max_latency_s
        match = None
        for run_index, (start, end) in enumerate(runs):
            if run_index in used:
                continue
            start_s = float(time_s[start])
            if start_s < cue - 0.05:
                continue
            if start_s >= window_end:
                break
            delay = start_s - cue
            if delay <= max_latency_s:
                match = run_index
                break
        if match is None:
            continue
        used.add(match)
        start, end = runs[match]
        delay = max(0.0, float(time_s[start]) - cue)
        chosen.append((start, end, delay, 1.0, None))
    return chosen


def _span_amplitude(position: np.ndarray, time_s: np.ndarray, start_s: float, end_s: float) -> float | None:
    mask = (time_s >= start_s) & (time_s <= end_s)
    if int(mask.sum()) < 2:
        return None
    return float(np.percentile(np.hypot(position[0, mask], position[1, mask]), 95))


def _stretch(
    prepared: Prepared,
    segment: Segment,
    hand: str,
    position: np.ndarray,
    slow: np.ndarray,
    residual: np.ndarray,
    gyro_resid: np.ndarray,
    start: int,
    end: int,
    latency_s: float,
    has_cue: float,
    amplitude_override: float | None,
    aim_pair: tuple[int, int],
    in_task: np.ndarray,
) -> Stretch | None:
    raw_x = position[0, start:end]
    raw_y = position[1, start:end]
    slow_x = slow[0, start:end]
    slow_y = slow[1, start:end]
    travel = float(np.max(np.hypot(raw_x - raw_x[0], raw_y - raw_y[0])))
    if travel < segment.min_amplitude:
        return None
    duration = (end - start) / prepared.sample_hz
    path = float(np.hypot(np.diff(slow_x), np.diff(slow_y)).sum())
    speed_ratio = path / duration / travel
    amplitude = travel if amplitude_override is None else amplitude_override
    move_speed = travel / max(duration, 1e-3)
    gyro_slice = gyro_resid[:, start:end]
    gyro_level = float(np.sqrt(np.mean(gyro_slice * gyro_slice))) if gyro_slice.size else 0.0
    along, across, has_target = _miss(prepared, aim_pair, start, end, in_task)
    series = np.vstack(
        [
            residual[0, start:end],
            residual[1, start:end],
            gyro_resid[0, start:end],
            gyro_resid[1, start:end],
            gyro_resid[2, start:end],
            along,
            across,
            has_target,
            _bounds_slice(prepared, aim_pair[0] // 2, start, end),
        ]
    )
    fixed = _fixed(series, segment.stretch_steps)
    constants = np.asarray(
        [speed_ratio, amplitude, latency_s, has_cue, 1.0, gyro_level, move_speed],
        dtype=np.float32,
    )
    constant_rows = np.repeat(constants[:, None], segment.stretch_steps, axis=1)
    values = np.vstack([fixed, constant_rows])
    if values.shape[0] != len(HAND_CHANNELS):
        raise RuntimeError("Hand channels and stretch features do not match.")
    return Stretch(
        hand=hand,
        values=np.ascontiguousarray(values, dtype=np.float32),
        start_s=float(prepared.time_s[start]),
        end_s=float(prepared.time_s[end - 1]),
        speed_ratio=float(speed_ratio),
        amplitude=amplitude,
    )


def _hand_motion(prepared: Prepared, aim_pair: tuple[int, int], sticks: tuple[int, int]) -> np.ndarray:
    """The in-game hand when the file logged it. Otherwise the stick itself."""
    if prepared.cursor is not None:
        cursor = prepared.cursor[list(aim_pair)]
        finite = np.isfinite(cursor)
        if float(finite.mean()) > 0.15:
            return np.where(finite, cursor, 0.0)
    return prepared.values[list(sticks)]


def _motion_limits(position: np.ndarray, segment: Segment) -> dict[str, float]:
    """Lobby sticks and cursors live in -1..1. Older recordings are raw bytes."""
    typical = float(np.percentile(np.abs(position), 95)) if position.size else 0.0
    if typical > 3.0:
        return {}
    return {"move_counts": 0.04, "min_amplitude": 0.08}


def _bounds_slice(prepared: Prepared, hand_index: int, start: int, end: int) -> np.ndarray:
    if prepared.bounds is None:
        return np.zeros(end - start, dtype=np.float64)
    return prepared.bounds[hand_index, start:end]


def _miss(
    prepared: Prepared,
    aim_pair: tuple[int, int],
    start: int,
    end: int,
    in_task: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Signed miss in the target frame. Zeros outside cue/track and with no target."""
    width = end - start
    zeros = np.zeros(width, dtype=np.float64)
    if prepared.aim is None or prepared.cursor is None:
        return zeros, zeros.copy(), zeros.copy()
    target = prepared.aim[list(aim_pair), start:end]
    cursor = prepared.cursor[list(aim_pair), start:end]
    tx, ty = target[0], target[1]
    radius = np.hypot(tx, ty)
    usable = in_task[start:end] & (radius > _MIN_TARGET_RADIUS)
    usable &= np.isfinite(target).all(axis=0) & np.isfinite(cursor).all(axis=0)
    safe = np.where(usable, radius, 1.0)
    ux = tx / safe
    uy = ty / safe
    miss_x = cursor[0] - tx
    miss_y = cursor[1] - ty
    along = miss_x * ux + miss_y * uy
    across = miss_x * (-uy) + miss_y * ux
    gate = usable.astype(np.float64)
    return np.where(usable, along, 0.0), np.where(usable, across, 0.0), gate


def _in_task(time_s: np.ndarray, task_spans: np.ndarray | None) -> np.ndarray:
    mask = np.zeros(len(time_s), dtype=bool)
    if task_spans is None or len(task_spans) == 0:
        return mask
    for start, end in task_spans:
        mask |= (time_s >= float(start)) & (time_s <= float(end))
    return mask


def _with_shrink(stretches: list[Stretch], clip: float) -> list[Stretch]:
    previous: dict[str, float] = {}
    shrink_index = HAND_CHANNELS.index("shrink_ratio")
    updated: list[Stretch] = []
    for stretch in stretches:
        prior = previous.get(stretch.hand)
        ratio = 1.0 if prior is None else float(np.clip(stretch.amplitude / prior, 0.0, clip))
        previous[stretch.hand] = stretch.amplitude
        values = stretch.values.copy()
        values[shrink_index] = np.float32(ratio)
        updated.append(
            Stretch(
                stretch.hand,
                values,
                stretch.start_s,
                stretch.end_s,
                stretch.speed_ratio,
                stretch.amplitude,
            )
        )
    return updated


def _runs(position: np.ndarray, sample_hz: int, segment: Segment) -> list[tuple[int, int]]:
    lag = max(1, int(round(segment.move_window_s * sample_hz)))
    smooth = moving_average(position, _odd_window(segment.move_window_s, sample_hz, position.shape[1]))
    displacement = np.hypot(smooth[0, lag:] - smooth[0, :-lag], smooth[1, lag:] - smooth[1, :-lag])
    moving = np.zeros(position.shape[1], dtype=bool)
    moving[lag:] = displacement >= segment.move_counts
    return _merge_runs(moving, sample_hz, segment.merge_gap_s, segment.min_stretch_s)


def _merge_runs(moving: np.ndarray, sample_hz: int, merge_gap_s: float, min_stretch_s: float) -> list[tuple[int, int]]:
    index = np.flatnonzero(moving)
    if len(index) == 0:
        return []
    gap_limit = int(round(merge_gap_s * sample_hz))
    min_len = int(round(min_stretch_s * sample_hz))
    splits = np.where(np.diff(index) > gap_limit + 1)[0]
    starts = np.concatenate([[index[0]], index[splits + 1]])
    ends = np.concatenate([index[splits], [index[-1]]]) + 1
    return [(int(start), int(end)) for start, end in zip(starts, ends, strict=True) if end - start >= min_len]


def _fixed(values: np.ndarray, steps: int) -> np.ndarray:
    width = values.shape[1]
    if width == steps:
        return values.astype(np.float32, copy=False)
    source = np.linspace(0.0, 1.0, width)
    grid = np.linspace(0.0, 1.0, steps)
    out = np.empty((values.shape[0], steps), dtype=np.float32)
    for index in range(values.shape[0]):
        out[index] = np.interp(grid, source, values[index])
    return out


def _odd_window(seconds: float, sample_hz: int, limit: int) -> int:
    width = max(1, int(round(seconds * sample_hz)))
    if width % 2 == 0:
        width += 1
    if width > limit:
        width = limit if limit % 2 == 1 else max(1, limit - 1)
    return max(1, width)
