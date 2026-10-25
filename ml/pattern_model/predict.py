"""Score a Recording with a trained checkpoint.

    from ml.pattern_model import score
    score("ml/runs/pattern_model/model.pt", recording)
"""

from pathlib import Path

import numpy as np
import torch

from ml.pattern_model.checkpoint import load_checkpoint
from ml.pattern_model.config import Segment
from ml.pattern_model.recording import Recording
from ml.pattern_model.score import score_recording
from ml.pattern_model.train import _device


def score(checkpoint: str | Path, recording: Recording, device: str = "auto") -> dict:
    """Return the three pattern scores (parkinson, stroke, essential_tremor) for one recording.

    Stroke is null when only one hand moves, because the gap between hands
    cannot be read. Parkinson and tremor are null when neither hand moves.
    """
    torch_device = _device(device)
    model, blob = load_checkpoint(Path(checkpoint), torch_device)
    return score_recording(
        model,
        recording,
        np.asarray(blob["norm_mean"], dtype=np.float32),
        np.asarray(blob["norm_std"], dtype=np.float32),
        sample_hz=int(blob["sample_hz"]),
        segment=Segment(**blob["segment"]),
        hand_scores=list(blob["hand_scores"]),
        device=torch_device,
    )
