"""Train the shared per-hand pattern model.

    from ml.pattern_model import Example, fit, load_examples

    fit(load_examples("data"))
"""

from pathlib import Path

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader

from ml.pattern_model.checkpoint import save_checkpoint
from ml.pattern_model.config import (
    DEFAULT_SEGMENT,
    DROPOUT,
    HAND_CHANNELS,
    HAND_SCORES,
    HIDDEN,
    KERNEL,
    LEVELS,
    SAMPLE_HZ,
    SCORE_MEANING,
    SCORES,
    Segment,
)
from ml.pattern_model.dataset import StretchDataset, load_stretches, normalization, split_items
from ml.pattern_model.network import PatternTCN
from ml.pattern_model.recording import Example, RecordingError


def fit(
    examples: list[Example],
    out: str | Path = "ml/runs/pattern_model/model.pt",
    epochs: int = 30,
    batch_size: int = 16,
    lr: float = 1e-3,
    val_ratio: float = 0.2,
    seed: int = 7,
    device: str = "auto",
    sample_hz: int = SAMPLE_HZ,
    segment: Segment = DEFAULT_SEGMENT,
    hidden: int = HIDDEN,
    levels: int = LEVELS,
    kernel: int = KERNEL,
    dropout: float = DROPOUT,
) -> Path:
    """Train on labeled recordings and save a checkpoint. Returns its path."""
    if not examples:
        raise RecordingError("fit needs at least one labeled recording.")
    seed_everything(seed)
    torch_device = _device(device)
    items = load_stretches(examples, sample_hz=sample_hz, segment=segment)
    train_items, val_items = split_items(items, val_ratio, seed)
    mean, std = normalization(train_items)
    train_loader = _loader(train_items, mean, std, batch_size, shuffle=True)
    val_loader = _loader(val_items, mean, std, batch_size, shuffle=False) if val_items else None

    model = PatternTCN(
        in_channels=len(HAND_CHANNELS),
        hidden=hidden,
        levels=levels,
        kernel=kernel,
        dropout=dropout,
        n_scores=len(HAND_SCORES),
    ).to(torch_device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)

    recordings = len({item.recording for item in items})
    print(
        f"Pattern TCN  recordings={recordings}  train_stretches={len(train_items)}  "
        f"val_stretches={len(val_items)}  device={torch_device}"
    )
    print(SCORE_MEANING)
    if not val_items and val_ratio > 0:
        print("No validation split. Add at least two recordings to hold one out.")

    best_mae = None
    best_state = None
    destination = Path(out)
    for epoch in range(1, epochs + 1):
        train_mae = _epoch(model, train_loader, optimizer, torch_device)
        if val_loader is None:
            print(f"epoch {epoch:03d}  train_mae={train_mae:.2f}", flush=True)
            best_state = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}
            _write_best(model, best_state, destination, mean, std, sample_hz, segment)
            continue
        val_mae = _epoch(model, val_loader, None, torch_device)
        print(f"epoch {epoch:03d}  train_mae={train_mae:.2f}  val_mae={val_mae:.2f}", flush=True)
        if best_mae is None or val_mae < best_mae:
            best_mae = val_mae
            best_state = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}
            _write_best(model, best_state, destination, mean, std, sample_hz, segment)

    if best_state is None:
        raise RecordingError("Training produced no checkpoint.")
    model.load_state_dict(best_state)
    save_checkpoint(
        destination,
        model,
        mean,
        std,
        sample_hz=sample_hz,
        segment=segment,
        channels=HAND_CHANNELS,
        hand_scores=HAND_SCORES,
        scores=SCORES,
    )
    held = f"  best_val_mae={best_mae:.2f}" if best_mae is not None else ""
    print(f"Saved {destination}{held}")
    return destination


def _write_best(model, state, destination, mean, std, sample_hz, segment) -> None:
    """Keep the best weights on disk so a stopped run still leaves a checkpoint."""
    current = {key: value.detach().clone() for key, value in model.state_dict().items()}
    model.load_state_dict(state)
    save_checkpoint(
        destination,
        model,
        mean,
        std,
        sample_hz=sample_hz,
        segment=segment,
        channels=HAND_CHANNELS,
        hand_scores=HAND_SCORES,
        scores=SCORES,
    )
    model.load_state_dict(current)


def _epoch(
    model: PatternTCN,
    loader: DataLoader,
    optimizer: torch.optim.Optimizer | None,
    device: torch.device,
) -> float:
    training = optimizer is not None
    model.train(training)
    absolute = 0.0
    count = 0
    for inputs, target in loader:
        inputs = inputs.to(device)
        target = target.to(device)
        if training:
            optimizer.zero_grad(set_to_none=True)
        predicted = model(inputs)
        loss = masked_loss(predicted, target)
        if training:
            loss.backward()
            optimizer.step()
        valid = torch.isfinite(target)
        if bool(valid.any()):
            absolute += (predicted[valid] - target[valid]).abs().sum().item()
            count += int(valid.sum().item())
    return absolute / max(count, 1)


def masked_loss(predicted: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
    """MSE on scores that have a label. NaN targets are skipped, not treated as 0."""
    mask = torch.isfinite(target)
    if not bool(mask.any()):
        return predicted.sum() * 0.0
    return nn.functional.mse_loss(predicted[mask] / 100.0, target[mask] / 100.0)


def _loader(items, mean, std, batch_size: int, shuffle: bool) -> DataLoader:
    return DataLoader(
        StretchDataset(items, mean, std),
        batch_size=min(batch_size, len(items)),
        shuffle=shuffle,
    )


def _device(name: str) -> torch.device:
    if name != "auto":
        return torch.device(name)
    if torch.cuda.is_available():
        return torch.device("cuda")
    mps = getattr(torch.backends, "mps", None)
    if mps is not None and mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def seed_everything(seed: int) -> None:
    np.random.seed(seed)
    torch.manual_seed(seed)
