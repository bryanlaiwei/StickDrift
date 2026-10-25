"""Save and load a trained per-hand pattern model."""

from dataclasses import asdict
from pathlib import Path

import numpy as np
import torch

from ml.pattern_model.config import SCHEMA_VERSION, SCORE_MEANING, Segment
from ml.pattern_model.network import PatternTCN


def save_checkpoint(
    path: Path,
    model: PatternTCN,
    mean: np.ndarray,
    std: np.ndarray,
    sample_hz: int,
    segment: Segment,
    channels: tuple[str, ...],
    hand_scores: tuple[str, ...],
    scores: tuple[str, ...],
) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "schema_version": SCHEMA_VERSION,
            "model": model.state_dict(),
            "in_channels": model.in_channels,
            "hidden": model.hidden,
            "levels": model.levels,
            "kernel": model.kernel,
            "dropout": model.dropout,
            "sample_hz": sample_hz,
            "segment": asdict(segment),
            "channels": list(channels),
            "hand_scores": list(hand_scores),
            "scores": list(scores),
            "norm_mean": mean.astype(np.float32),
            "norm_std": std.astype(np.float32),
            "score_meaning": SCORE_MEANING,
        },
        path,
    )


def load_checkpoint(path: Path, device: torch.device) -> tuple[PatternTCN, dict]:
    blob = torch.load(Path(path), map_location=device, weights_only=False)
    version = blob.get("schema_version")
    if version != SCHEMA_VERSION:
        raise ValueError(f"Checkpoint schema {version} does not match this code ({SCHEMA_VERSION}).")
    model = PatternTCN(
        in_channels=int(blob["in_channels"]),
        hidden=int(blob["hidden"]),
        levels=int(blob["levels"]),
        kernel=int(blob["kernel"]),
        dropout=float(blob["dropout"]),
        n_scores=len(blob["hand_scores"]),
    )
    model.load_state_dict(blob["model"])
    model.to(device)
    model.eval()
    return model, blob
