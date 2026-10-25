"""One DualSense recording, independent of how it was stored.

A recording is a sequence of samples. Each sample has a timestamp in seconds,
both stick positions, and the motion sensor inside the controller body:

    t, lx, ly, rx, ry, gyro_x, gyro_y, gyro_z, acc_x, acc_y, acc_z

Stick columns may also be named raw_x, raw_y, raw_rx, raw_ry. When a garden
file includes target_* and cursor_*, those are kept so the miss can be scored.
`phase` marks cue and track, which is when that miss counts. The return to
center is not a cue. A file with no target columns simply has no miss to score.
"""

import math
from collections.abc import Mapping, Sequence

import numpy as np

from ml.pattern_model.config import CHANNELS, COLUMN_ALIASES, CUE_PHASES, SCORES

_TARGET_COLUMNS = ("target_lx", "target_ly", "target_rx", "target_ry")
_CURSOR_COLUMNS = ("cursor_lx", "cursor_ly", "cursor_rx", "cursor_ry")
_IMU = ("gyro_x", "gyro_y", "gyro_z", "acc_x", "acc_y", "acc_z")
_ACTIVITIES = ("apples", "butterfly", "water", "fish", "rat")


class RecordingError(ValueError):
    """A recording does not contain the expected sample pattern."""


class Recording:
    """Raw samples before resampling.

    `time_s` has shape (samples,). `values` has shape (samples, channels) in
    `CHANNELS` order. `cue_s` holds the times a movement was requested.
    """

    def __init__(
        self,
        time_s: np.ndarray,
        values: np.ndarray,
        name: str = "",
        cues: np.ndarray | None = None,
        task_spans: np.ndarray | None = None,
        targets: np.ndarray | None = None,
        cursors: np.ndarray | None = None,
        bounds: np.ndarray | None = None,
        activity: str | None = None,
    ):
        time_s = np.asarray(time_s, dtype=np.float64).reshape(-1)
        values = np.asarray(values, dtype=np.float64)
        if values.ndim != 2 or values.shape[1] != len(CHANNELS):
            raise RecordingError(
                f"{_label(name)} values must have shape (samples, {len(CHANNELS)}), "
                f"in this order: {', '.join(CHANNELS)}."
            )
        if len(time_s) != len(values):
            raise RecordingError(
                f"{_label(name)} has {len(time_s)} timestamps and {len(values)} samples."
            )
        if len(time_s) < 2:
            raise RecordingError(f"{_label(name)} needs at least 2 samples.")
        if not np.isfinite(time_s).all() or not np.isfinite(values).all():
            raise RecordingError(f"{_label(name)} contains a blank or non-numeric sample.")
        cue_s = np.zeros(0, dtype=np.float64) if cues is None else np.asarray(cues, dtype=np.float64).reshape(-1)
        if cue_s.size and not np.isfinite(cue_s).all():
            raise RecordingError(f"{_label(name)} contains a blank cue time.")
        if task_spans is None:
            spans = np.zeros((0, 2), dtype=np.float64)
        else:
            spans = np.asarray(task_spans, dtype=np.float64).reshape(-1, 2)
        if spans.size and not np.isfinite(spans).all():
            raise RecordingError(f"{_label(name)} contains a blank task time.")
        self.targets = _frame(targets, len(time_s), name, "targets")
        self.cursors = _frame(cursors, len(time_s), name, "cursors")
        self.bounds = _bounds(bounds, len(time_s), name)
        self.has_targets = self.targets is not None and bool(np.isfinite(self.targets).any())
        self.time_s = time_s
        self.values = values
        self.cue_s = np.sort(cue_s)
        self.task_spans = spans
        self.name = name
        self.activity = _checked_activity(activity if activity is not None else activity_from_name(name), name)

    @classmethod
    def from_columns(
        cls,
        time_s: Sequence[float],
        name: str = "",
        cues: Sequence[float] | None = None,
        **columns: Sequence[float],
    ) -> "Recording":
        """Build a recording from one array per channel."""
        resolved = _resolve_columns(columns, name)
        width = len(np.asarray(time_s).reshape(-1))
        rows = np.column_stack([_match_length(resolved[channel], width, channel, name) for channel in CHANNELS])
        return cls(time_s, rows, name, cues=None if cues is None else np.asarray(cues, dtype=np.float64))

    @classmethod
    def from_rows(cls, rows: Sequence[Mapping[str, object]], name: str = "") -> "Recording":
        """Build a recording from an ordered sequence of sample mappings."""
        samples = list(rows)
        if not samples:
            raise RecordingError(f"{_label(name)} has no samples.")
        header: set[str] = set()
        for sample in samples:
            header.update(str(key) for key in sample.keys())
        chosen = _choose(header, ("t", "lx", "ly", "rx", "ry"), name)
        for channel in _IMU:
            chosen[channel] = next((item for item in COLUMN_ALIASES[channel] if item in header), None)
        target_names = _aliases(header, _TARGET_COLUMNS)
        cursor_names = _aliases(header, _CURSOR_COLUMNS)
        reached_names = _aliases(header, ("reached_l", "reached_r"))
        times: list[float] = []
        values: list[list[float]] = []
        targets: list[list[float]] = []
        cursors: list[list[float]] = []
        bounds: list[list[float]] = []
        for sample in samples:
            parsed = _parse_sample(sample, chosen)
            if parsed is None:
                continue
            stamp, row = parsed
            times.append(stamp)
            values.append(row)
            if target_names is not None:
                targets.append([_blank_float(sample.get(column)) for column in target_names])
            if cursor_names is not None:
                cursors.append([_blank_float(sample.get(column)) for column in cursor_names])
            if reached_names is not None and str(sample.get("phase") or "") == "track":
                bounds.append([_flag(sample.get(column)) for column in reached_names])
            elif reached_names is not None:
                bounds.append([0.0, 0.0])
        if not values:
            raise RecordingError(f"{_label(name)} has no complete samples.")
        cues, spans = _task_times(samples, chosen["t"])
        activity = activity_from_name(name) or _activity_from_level(samples)
        return cls(
            times,
            values,
            name,
            cues=cues,
            task_spans=spans,
            targets=None if not targets else targets,
            cursors=None if not cursors else cursors,
            bounds=None if not bounds else bounds,
            activity=activity,
        )


class Example:
    """A recording plus the pattern it should match.

    `parkinson`, `stroke`, and `essential_tremor` are from 0 to 100.
    The weak hand is trained on the shared Parkinson score plus the stroke gap.
    The other hand is trained on the shared score. `tremor_hand` limits the
    tremor target to one hand.
    """

    def __init__(
        self,
        recording: Recording,
        parkinson: float,
        stroke: float,
        essential_tremor: float,
        weak_hand: str | None = None,
        tremor_hand: str | None = None,
        activity: str | None = None,
    ):
        target = np.asarray([parkinson, stroke, essential_tremor], dtype=np.float32)
        for score_name, value in zip(SCORES, target, strict=True):
            if not 0.0 <= float(value) <= 100.0:
                raise RecordingError(f"{score_name} must be from 0 to 100.")
        if weak_hand not in (None, "left", "right"):
            raise RecordingError("weak_hand must be left, right, or empty.")
        if float(stroke) > 0.0 and weak_hand is None:
            raise RecordingError("A stroke target needs weak_hand set to left or right.")
        if weak_hand is not None and float(stroke) <= 0.0:
            raise RecordingError("weak_hand is set, but the stroke target is 0.")
        if tremor_hand not in (None, "both", "left", "right"):
            raise RecordingError("tremor_hand must be both, left, right, or empty.")
        self.recording = recording
        self.target = target
        self.weak_hand = weak_hand
        self.tremor_hand = "both" if tremor_hand is None else tremor_hand
        self.activity = _checked_activity(
            recording.activity if activity is None else activity,
            recording.name,
        )


def _resolve_columns(columns: Mapping[str, Sequence[float]], name: str) -> dict[str, np.ndarray]:
    chosen = _choose(set(columns), CHANNELS, name)
    resolved = {}
    for channel in CHANNELS:
        resolved[channel] = np.asarray(columns[chosen[channel]], dtype=np.float64).reshape(-1)
    return resolved


def _choose(header: set[str], fields: tuple[str, ...], name: str) -> dict[str, str]:
    chosen = {}
    missing = []
    for logical in fields:
        alias = next((item for item in COLUMN_ALIASES[logical] if item in header), None)
        if alias is None:
            missing.append(logical)
        else:
            chosen[logical] = alias
    if missing:
        raise RecordingError(
            f"{_label(name)} is missing {', '.join(missing)}. "
            "Each sample needs t, lx, ly, rx, ry, gyro_x, gyro_y, gyro_z, acc_x, acc_y, acc_z. "
            "Stick fields may also be named raw_x, raw_y, raw_rx, raw_ry."
        )
    return chosen


def _parse_sample(sample: Mapping[str, object], chosen: dict[str, str | None]) -> tuple[float, list[float]] | None:
    cells: list[float] = []
    for logical in ("t", *CHANNELS):
        key = chosen.get(logical)
        if not key:
            if logical in _IMU:
                cells.append(0.0)
                continue
            return None
        text = sample.get(key)
        if text is None or text == "":
            if logical in _IMU:
                cells.append(0.0)
                continue
            return None
        try:
            cells.append(float(text))
        except (TypeError, ValueError):
            return None
    return cells[0], cells[1:]


def _task_times(
    samples: Sequence[Mapping[str, object]],
    time_key: str,
) -> tuple[np.ndarray, np.ndarray]:
    """Cue times and the [start, end] spans where the task asked for a reach."""
    cues: list[float] = []
    spans: list[tuple[float, float]] = []
    active = False
    start = 0.0
    stamp = 0.0
    saw_phase = False
    for sample in samples:
        phase = sample.get("phase")
        if phase is None or str(phase) == "":
            if active:
                spans.append((start, stamp))
                active = False
            continue
        saw_phase = True
        try:
            stamp = float(sample.get(time_key))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if not np.isfinite(stamp):
            continue
        in_task = str(phase) in CUE_PHASES
        if in_task and not active:
            active = True
            start = stamp
            cues.append(stamp)
        elif not in_task and active:
            spans.append((start, stamp))
            active = False
    if active:
        spans.append((start, stamp))
    if not saw_phase:
        return np.zeros(0, dtype=np.float64), np.zeros((0, 2), dtype=np.float64)
    return np.asarray(cues, dtype=np.float64), np.asarray(spans, dtype=np.float64).reshape(-1, 2)


def _match_length(values: np.ndarray, width: int, channel: str, name: str) -> np.ndarray:
    if len(values) != width:
        raise RecordingError(
            f"{_label(name)} channel {channel} has {len(values)} samples, expected {width}."
        )
    return values


def activity_from_name(name: str) -> str | None:
    """Apple, butterfly, or water, when the file path says which task it is."""
    for part in str(name).replace("\\", "/").split("/"):
        found = _activity_token(part.lower())
        if found is not None:
            return found
    return None


def _activity_token(token: str) -> str | None:
    if _word(token, "butterfly"):
        return "butterfly"
    if _word(token, "fish"):
        return "fish"
    if _word(token, "rat"):
        return "rat"
    if _word(token, "apple") or _word(token, "apples"):
        return "apples"
    if _word(token, "water"):
        return "water"
    return None


def _word(token: str, word: str) -> bool:
    """Match a game name as a whole word, so 'rat' inside a longer folder name is not the rat game."""
    return token == word or token.startswith(word + "_") or token.endswith("_" + word) or f"_{word}_" in token


def _activity_from_level(samples: Sequence[Mapping[str, object]]) -> str | None:
    for sample in samples:
        level = sample.get("level")
        if level is None or str(level) == "":
            continue
        found = _activity_token(str(level).lower())
        if found is not None:
            return found
    return None


def _checked_activity(activity: str | None, name: str) -> str | None:
    if activity is None:
        return None
    if activity not in _ACTIVITIES:
        raise RecordingError(f"{_label(name)} activity must be apples, fish, butterfly, water, or rat.")
    return activity


def _aliases(header: set[str], logicals: tuple[str, ...]) -> list[str] | None:
    names = []
    for logical in logicals:
        alias = next((item for item in COLUMN_ALIASES[logical] if item in header), None)
        if alias is None:
            return None
        names.append(alias)
    return names


def _flag(value: object) -> float:
    number = _blank_float(value)
    if not math.isfinite(number):
        return 0.0
    return 1.0 if number else 0.0


def _bounds(frame: np.ndarray | None, width: int, name: str) -> np.ndarray | None:
    if frame is None:
        return None
    array = np.asarray(frame, dtype=np.float64)
    if array.shape != (width, 2):
        raise RecordingError(f"{_label(name)} bounds must have shape ({width}, 2).")
    return array


def _frame(frame: np.ndarray | None, width: int, name: str, label: str) -> np.ndarray | None:
    if frame is None:
        return None
    array = np.asarray(frame, dtype=np.float64)
    if array.shape != (width, 4):
        raise RecordingError(f"{_label(name)} {label} must have shape ({width}, 4).")
    return array


def _blank_float(value: object) -> float:
    if value is None or value == "":
        return math.nan
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return math.nan
    if not math.isfinite(number):
        return math.nan
    return number


def _label(name: str) -> str:
    return name or "recording"
