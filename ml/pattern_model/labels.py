"""Read recordings whose folder is the pattern label.

Played recordings under data/new_game_data:

- Baseline Data: every score 0
- Parkinsons Data: parkinson 100, everything else 0
- Tremor Data: essential tremor 100, everything else 0
- Stroke Data/Left Weak or Right Weak: stroke 100 on that hand, everything else 0

Synthetic mixes use the folder names in `ml.pattern_model.synthetic.CONDITIONS`.
Older recordings of patterns the model no longer scores are skipped, not labelled.
"""

import csv
from dataclasses import dataclass
from pathlib import Path

from ml.pattern_model.recording import Example, Recording, RecordingError
from ml.pattern_model.synthetic import CONDITIONS

_BASELINE = frozenset({"Baseline Data", "Baseline"})
_PARKINSON = frozenset({"Parkinsons Data", "Parkinsons"})
_TREMOR = frozenset({"Tremor Data", "Tremor"})
_LEFT = frozenset({"Left Weak", "Left Hand Weak"})
_RIGHT = frozenset({"Right Weak", "Right Hand Weak"})


def load_examples(root: str | Path) -> list[Example]:
    """Load every `controller_data.csv` under `root` and label it from its folder."""
    folder = Path(root)
    paths = sorted(folder.rglob("controller_data.csv"))
    if not paths:
        raise RecordingError(f"{folder} has no controller_data.csv recordings.")
    return [_example(folder, path) for path in paths if not _retired(path)]


def _retired(path: Path) -> bool:
    """Recordings kept on disk for patterns the model no longer scores (old diabetes and ataxia folders)."""
    return any("diabet" in part.lower() or "ataxia" in part.lower() for part in path.parts)


def _example(root: Path, path: Path) -> Example:
    label = _targets(path)
    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    name = str(path.relative_to(root))
    return Example(
        Recording.from_rows(rows, name),
        label.parkinson,
        label.stroke,
        label.tremor,
        weak_hand=label.weak_hand,
        tremor_hand=label.tremor_hand,
    )


@dataclass(frozen=True)
class _FolderLabel:
    parkinson: float
    stroke: float
    tremor: float
    weak_hand: str | None = None
    tremor_hand: str | None = None


def _targets(path: Path) -> _FolderLabel:
    parts = set(path.parts)
    for condition in CONDITIONS:
        if condition.folder in parts:
            return _FolderLabel(
                condition.parkinson,
                condition.stroke,
                condition.tremor,
                weak_hand=condition.weak_hand,
                tremor_hand=condition.tremor_hand,
            )
    if parts & _LEFT:
        return _played(0.0, 100.0, 0.0, weak_hand="left")
    if parts & _RIGHT:
        return _played(0.0, 100.0, 0.0, weak_hand="right")
    if parts & _PARKINSON:
        return _played(100.0, 0.0, 0.0)
    if parts & _TREMOR:
        return _played(0.0, 0.0, 100.0)
    if parts & _BASELINE:
        return _played(0.0, 0.0, 0.0)
    raise RecordingError(
        f"{path} is not under Baseline, Parkinsons, Tremor, "
        "Stroke/Left Hand Weak or Right Hand Weak, or a Synthetic condition folder."
    )


def _played(
    parkinson: float,
    stroke: float,
    tremor: float,
    weak_hand: str | None = None,
) -> _FolderLabel:
    """One recorded condition at full strength, and none of the others."""
    return _FolderLabel(parkinson, stroke, tremor, weak_hand=weak_hand)


def load_training_examples(root: str | Path = "data") -> list[Example]:
    """Apple and fishing recordings in data/ultimate_data. Rat files are left out."""
    folder = Path(root) / "ultimate_data"
    if not folder.is_dir() or not any(folder.rglob("controller_data.csv")):
        raise RecordingError(f"{folder} has no recorded controller files.")
    examples = [example for example in load_examples(folder) if example.activity != "rat"]
    if not examples:
        raise RecordingError(f"{folder} has no apple or fishing recordings.")
    return examples
