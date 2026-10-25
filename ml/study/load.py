"""Load the mirror-game study into normalized arrays.

`tablet_pixels.mat` holds the dot and pen x for every subject and stimulus,
already aligned on a 100 Hz grid in screen pixels. Positions here are scaled
to -1..1 across the screen width, with 0 at the center, the same convention
as a centered thumbstick.
"""

import csv
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy.io import loadmat

HZ = 100
SCREEN_PX = 2560
DEFAULT_ROOT = Path(__file__).resolve().parents[3] / "Parkinsons Data"  # beside the repository
GROUP_NAMES = {1: "Parkinson's", 2: "Older control", 3: "Young control"}
GROUP_COLORS = {1: "#d62728", 2: "#1f77b4", 3: "#2ca02c"}
STUDY_FREQS = (0.25, 0.3215, 0.375, 0.4375, 0.5, 0.5625)

# Spline resampling in the original analysis overshoots around pen lifts.
_PEN_LIMIT = 1.1


@dataclass
class Study:
    """Normalized study data.

    `dots[stim]` has shape (samples,). `pens[stim]` has shape (subjects, samples)
    and is NaN where the pen was lifted. Stimulus numbers run from 1 to 11 to
    match `stimuli/dotN.csv`.
    """

    time_s: np.ndarray
    dots: dict[int, np.ndarray]
    pens: dict[int, np.ndarray]
    subjects: list[str]
    groups: np.ndarray
    info: list[dict[str, str]] = field(default_factory=list)

    def index(self, subject: str | int) -> int:
        return self.subjects.index(str(subject))

    def group_of(self, subject: str | int) -> int:
        return int(self.groups[self.index(subject)])

    def age_of(self, subject: str | int) -> str:
        return self.info[self.index(subject)].get("Age", "?")

    def members(self, group: int) -> list[str]:
        return [subject for subject, g in zip(self.subjects, self.groups) if g == group]

    def representative(self, group: int, measure: str = "meandX") -> str:
        """The subject whose `measure` is the group median, so examples are typical."""
        scored = [
            (float(row[measure]), subject)
            for subject, row, g in zip(self.subjects, self.info, self.groups)
            if g == group and _is_number(row.get(measure, ""))
        ]
        scored.sort()
        return scored[len(scored) // 2][1]

    def pen(self, stim: int, subject: str | int) -> np.ndarray:
        return self.pens[stim][self.index(subject)]

    def error(self, stim: int, subject: str | int) -> np.ndarray:
        """Pen minus dot. Positive means the pen is to the right of the dot."""
        return self.pen(stim, subject) - self.dots[stim]


def load_study(root: str | Path = DEFAULT_ROOT, filtered: bool = True) -> Study:
    """Read `tablet_pixels.mat` and `csv/combined.csv` from the study folder."""
    folder = Path(root)
    mat = loadmat(folder / "tablet_pixels.mat")
    key = "xdata_filtered_pixels" if filtered else "xdata_pixels"
    subjects = [str(item[0]) for item in mat["dirnames"].ravel()]
    rows = _combined_rows(folder / "csv" / "combined.csv")
    info = [rows.get(subject, {}) for subject in subjects]
    groups = np.array([int(row.get("Group", 0) or 0) for row in info])
    dots: dict[int, np.ndarray] = {}
    pens: dict[int, np.ndarray] = {}
    for offset in range(mat[key].shape[1]):
        stim = offset + 1
        dots[stim] = _normalize(np.asarray(mat["stimuli_resampled"][0, offset], dtype=np.float64).ravel())
        pen = _normalize(np.asarray(mat[key][0, offset], dtype=np.float64))
        pen[np.abs(pen) > _PEN_LIMIT] = np.nan
        pens[stim] = pen
    samples = len(dots[1])
    time_s = np.arange(1, samples + 1) / HZ
    return Study(time_s, dots, pens, subjects, groups, info)


def local_frequency(dot: np.ndarray, hz: int = HZ) -> np.ndarray:
    """Dot frequency at each sample, snapped to the study's six frequencies.

    Each half cycle between zero crossings gives one frequency estimate.
    Samples before the first or after the last crossing take the nearest value.
    """
    centered = dot - np.median(dot)
    crossings = np.flatnonzero(np.diff(np.signbit(centered)))
    min_gap = int(hz / (2 * max(STUDY_FREQS) * 1.5))
    kept: list[int] = []
    for crossing in crossings:
        if not kept or crossing - kept[-1] >= min_gap:
            kept.append(int(crossing))
    out = np.full(len(dot), np.nan)
    if len(kept) < 2:
        return out
    for start, end in zip(kept, kept[1:]):
        freq = hz / (2.0 * (end - start))
        out[start:end] = min(STUDY_FREQS, key=lambda value: abs(value - freq))
    out[: kept[0]] = out[kept[0]]
    out[kept[-1]:] = out[kept[-1] - 1]
    return out


def fill_gaps(values: np.ndarray) -> np.ndarray:
    """Linearly bridge NaN gaps so derivatives and correlations work."""
    good = np.isfinite(values)
    if good.all() or not good.any():
        return np.array(values, copy=True)
    index = np.arange(len(values))
    return np.interp(index, index[good], values[good])


def tracking_lag_s(dot: np.ndarray, pen: np.ndarray, hz: int = HZ, max_lag_s: float = 0.6) -> float:
    """Delay of the pen behind the dot, from the peak velocity cross-correlation."""
    if np.isfinite(pen).mean() < 0.5:
        return float("nan")
    dot_v = np.gradient(dot)
    pen_v = np.gradient(fill_gaps(pen))
    max_lag = int(max_lag_s * hz)
    start, stop = max_lag, len(dot) - max_lag
    if stop - start < hz:
        return float("nan")
    reference = dot_v[start:stop]
    scores = [np.corrcoef(pen_v[start + lag : stop + lag], reference)[0, 1] for lag in range(-max_lag // 3, max_lag)]
    if not np.isfinite(scores).any():
        return float("nan")
    return (int(np.nanargmax(scores)) - max_lag // 3) / hz


def _normalize(pixels: np.ndarray) -> np.ndarray:
    half = SCREEN_PX / 2.0
    return (pixels - half) / half


def _combined_rows(path: Path) -> dict[str, dict[str, str]]:
    with path.open(newline="") as handle:
        return {row["Subject"]: row for row in csv.DictReader(handle)}


def _is_number(text: str) -> bool:
    try:
        return np.isfinite(float(text))
    except (TypeError, ValueError):
        return False
