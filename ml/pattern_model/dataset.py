"""Labeled moving stretches. Input is Example objects, not files."""

from dataclasses import dataclass

import numpy as np
import torch
from torch.utils.data import Dataset

from ml.pattern_model.config import HAND_SCORES, SAMPLE_HZ, SCORES, Segment
from ml.pattern_model.prepare import prepare
from ml.pattern_model.recording import Example, RecordingError
from ml.pattern_model.stretch import Stretch, build_stretches


@dataclass(frozen=True)
class StretchItem:
    recording: str
    hand: str
    values: np.ndarray
    target: np.ndarray


class StretchDataset(Dataset):
    def __init__(self, items: list[StretchItem], mean: np.ndarray, std: np.ndarray):
        self.items = items
        self.mean = mean.astype(np.float32)
        self.std = std.astype(np.float32)

    def __len__(self) -> int:
        return len(self.items)

    def __getitem__(self, index: int) -> tuple[torch.Tensor, torch.Tensor]:
        item = self.items[index]
        values = (item.values - self.mean[:, None]) / self.std[:, None]
        return (
            torch.from_numpy(np.ascontiguousarray(values)),
            torch.from_numpy(item.target.copy()),
        )


def load_stretches(
    examples: list[Example],
    sample_hz: int = SAMPLE_HZ,
    segment: Segment | None = None,
) -> list[StretchItem]:
    """Turn each labeled recording into the moving stretches of each hand."""
    items: list[StretchItem] = []
    seen: dict[str, int] = {}
    for index, example in enumerate(examples):
        name = example.recording.name or f"recording-{index}"
        seen[name] = seen.get(name, 0) + 1
        if seen[name] > 1:
            name = f"{name}-{seen[name]}"
        prepared = prepare(example.recording, sample_hz=sample_hz)
        for stretch in build_stretches(
            prepared,
            example.recording.cue_s,
            segment or Segment(),
            example.recording.task_spans,
        ):
            items.append(StretchItem(name, stretch.hand, stretch.values, _target(example, stretch)))
    if not items:
        raise RecordingError("No moving stretches. The sticks never left rest.")
    return items


def split_items(
    items: list[StretchItem],
    val_ratio: float,
    seed: int,
) -> tuple[list[StretchItem], list[StretchItem]]:
    """Hold out whole recordings so stretches from one play do not leak into validation."""
    names = sorted({item.recording for item in items})
    if val_ratio <= 0 or len(names) < 2:
        return items, []
    rng = np.random.default_rng(seed)
    order = list(names)
    rng.shuffle(order)
    val_count = int(round(len(order) * val_ratio))
    val_count = min(max(val_count, 1), len(order) - 1)
    held = set(order[:val_count])
    train = [item for item in items if item.recording not in held]
    valid = [item for item in items if item.recording in held]
    return train, valid


def normalization(items: list[StretchItem]) -> tuple[np.ndarray, np.ndarray]:
    """Per-channel mean and standard deviation across training stretches."""
    stacked = np.concatenate([item.values for item in items], axis=1)
    mean = stacked.mean(axis=1).astype(np.float32)
    std = stacked.std(axis=1).astype(np.float32)
    std = np.where(std < 1e-6, np.float32(1.0), std)
    return mean, std


def _target(example: Example, stretch: Stretch) -> np.ndarray:
    tremor_score = float(example.target[SCORES.index("essential_tremor")])
    tremor = tremor_score if example.tremor_hand in ("both", stretch.hand) else 0.0
    parkinson = float(example.target[SCORES.index("parkinson")])
    stroke = float(example.target[SCORES.index("stroke")])
    if example.weak_hand is None:
        impairment = parkinson
    elif stretch.hand == example.weak_hand:
        impairment = min(100.0, parkinson + stroke)
    else:
        impairment = parkinson
    target = np.asarray([tremor, impairment], dtype=np.float32)
    if len(target) != len(HAND_SCORES):
        raise RecordingError("Hand targets do not match the network outputs.")
    return target

