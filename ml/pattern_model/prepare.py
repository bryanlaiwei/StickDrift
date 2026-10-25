"""Resample a Recording onto a uniform grid."""

from dataclasses import dataclass

import numpy as np

from ml.pattern_model.config import MIN_DURATION_S, SAMPLE_HZ, STICK_CENTER
from ml.pattern_model.recording import Recording, RecordingError


@dataclass(frozen=True)
class Prepared:
    """One recording after resampling.

    `values` has shape (channels, time). Each channel has had its own median
    removed, which takes out stick-center offset, gyro bias, and gravity.
    `time_s` is the uniform grid those columns sit on.
    """

    values: np.ndarray
    time_s: np.ndarray
    duration_s: float
    sample_hz: int
    name: str
    aim: np.ndarray | None = None
    cursor: np.ndarray | None = None
    bounds: np.ndarray | None = None


def prepare(recording: Recording, sample_hz: int = SAMPLE_HZ) -> Prepared:
    """Resample one recording onto a uniform `sample_hz` grid."""
    timestamps = recording.time_s
    samples = recording.values
    order = np.argsort(timestamps, kind="stable")
    timestamps = timestamps[order]
    samples = samples[order]
    targets = None if recording.targets is None else recording.targets[order]
    cursors = None if recording.cursors is None else recording.cursors[order]
    bounds = None if recording.bounds is None else recording.bounds[order]
    keep = np.ones(len(timestamps), dtype=bool)
    keep[:-1] = np.diff(timestamps) > 0
    timestamps = timestamps[keep]
    samples = samples[keep]
    if targets is not None:
        targets = targets[keep]
    if cursors is not None:
        cursors = cursors[keep]
    if bounds is not None:
        bounds = bounds[keep]
    if len(timestamps) < 2:
        raise RecordingError(f"{recording.name or 'recording'} has no increasing timestamps.")

    duration = float(timestamps[-1] - timestamps[0])
    if duration < MIN_DURATION_S:
        raise RecordingError(
            f"{recording.name or 'recording'} is {duration:.2f}s. "
            f"Recordings need at least {MIN_DURATION_S:.0f}s."
        )

    grid = _grid(float(timestamps[0]), float(timestamps[-1]), sample_hz)
    resampled = np.empty((len(grid), samples.shape[1]), dtype=np.float64)
    for index in range(samples.shape[1]):
        resampled[:, index] = np.interp(grid, timestamps, samples[:, index])
    centered = resampled - np.median(resampled, axis=0, keepdims=True)
    aim = None
    cursor = None
    bound_rows = None
    if targets is not None:
        aim = np.ascontiguousarray(_resample_with_gaps(timestamps, targets, grid).T)
        stick_cursor = _cursor_from_sticks(resampled[:, :4])
        if cursors is None:
            cursor_rows = stick_cursor
        else:
            cursor_rows = _resample_with_gaps(timestamps, cursors, grid)
            missing = ~np.isfinite(cursor_rows)
            if missing.any():
                cursor_rows = np.where(missing, stick_cursor, cursor_rows)
        cursor = np.ascontiguousarray(cursor_rows.T)
    if bounds is not None:
        bound_rows = np.column_stack(
            [np.interp(grid, timestamps, bounds[:, index]) for index in range(bounds.shape[1])]
        )
    return Prepared(
        values=np.ascontiguousarray(centered.T, dtype=np.float64),
        time_s=grid,
        duration_s=duration,
        sample_hz=sample_hz,
        name=recording.name,
        aim=aim,
        cursor=cursor,
        bounds=None if bound_rows is None else np.ascontiguousarray(bound_rows.T),
    )


def _cursor_from_sticks(sticks: np.ndarray) -> np.ndarray:
    """Lobby sticks are already -1..1. Older files still store raw bytes."""
    typical = float(np.nanpercentile(np.abs(sticks), 95)) if sticks.size else 0.0
    if typical > 3.0:
        return scale_stick(sticks)
    return np.array(sticks, dtype=np.float64, copy=True)


def scale_stick(raw: np.ndarray, center: float = STICK_CENTER) -> np.ndarray:
    """Map raw stick bytes into the game's -1..1 cursor space.

    Matches garden.norm_axis: the positive side is divided by (255 - center)
    and the negative side by the center. Files that already logged cursor_*
    do not come through here.
    """
    delta = np.asarray(raw, dtype=np.float64) - center
    scaled = np.where(delta > 0.0, delta / (255.0 - center), delta / center)
    return np.clip(scaled, -1.0, 1.0)


def _resample_with_gaps(times: np.ndarray, values: np.ndarray, grid: np.ndarray) -> np.ndarray:
    """Resample columns that may be blank. A blank stays blank on the grid."""
    out = np.empty((len(grid), values.shape[1]), dtype=np.float64)
    nearest = _nearest_index(times, grid)
    for index in range(values.shape[1]):
        column = values[:, index]
        finite = np.isfinite(column)
        if int(finite.sum()) == 0:
            out[:, index] = np.nan
            continue
        out[:, index] = np.interp(grid, times[finite], column[finite])
        out[~finite[nearest], index] = np.nan
    return out


def _nearest_index(times: np.ndarray, grid: np.ndarray) -> np.ndarray:
    right = np.clip(np.searchsorted(times, grid, side="left"), 0, len(times) - 1)
    left = np.clip(right - 1, 0, len(times) - 1)
    choose_left = np.abs(grid - times[left]) <= np.abs(times[right] - grid)
    return np.where(choose_left, left, right)


def _grid(start: float, end: float, sample_hz: int) -> np.ndarray:
    steps = int(round((end - start) * sample_hz)) + 1
    return np.linspace(start, end, steps)
