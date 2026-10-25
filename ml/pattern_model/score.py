"""Turn per-hand stretch scores into the three recording scores."""

import numpy as np
import torch

from ml.pattern_model.config import SCORES, Segment
from ml.pattern_model.prepare import prepare
from ml.pattern_model.recording import Recording
from ml.pattern_model.stretch import build_stretches


def score_recording(
    model: torch.nn.Module,
    recording: Recording,
    mean: np.ndarray,
    std: np.ndarray,
    sample_hz: int,
    segment: Segment,
    hand_scores: list[str],
    device: torch.device,
) -> dict:
    prepared = prepare(recording, sample_hz=sample_hz)
    stretches = build_stretches(prepared, recording.cue_s, segment, recording.task_spans)
    counts = {"left": 0, "right": 0}
    if not stretches:
        return _result(recording.name, prepared.duration_s, counts, {name: None for name in SCORES})

    values = np.stack([(item.values - mean[:, None]) / std[:, None] for item in stretches])
    inputs = torch.from_numpy(np.ascontiguousarray(values)).to(device)
    with torch.no_grad():
        predicted = model(inputs).detach().cpu().numpy()

    bags = {name: {"left": [], "right": []} for name in hand_scores}
    for stretch, row in zip(stretches, predicted, strict=True):
        counts[stretch.hand] += 1
        for name in hand_scores:
            bags[name][stretch.hand].append(float(row[hand_scores.index(name)]))
    return _result(
        recording.name,
        prepared.duration_s,
        counts,
        _aggregate(bags.get("tremor", {}), bags.get("impairment", {})),
    )


def fuse(apple: dict, path: dict) -> dict[str, float | None]:
    """Combine one apple recording with one butterfly or water recording.

    Parkinson and essential tremor are averaged across the two files. A null
    is left out of that average. Stroke stays with the apple file.
    """

    def average(left: float | None, right: float | None) -> float | None:
        values = [value for value in (left, right) if value is not None]
        if not values:
            return None
        return round(float(sum(values) / len(values)), 1)

    def keep(value: float | None) -> float | None:
        return None if value is None else round(float(value), 1)

    return {
        "parkinson": average(apple.get("parkinson"), path.get("parkinson")),
        "stroke": keep(apple.get("stroke")),
        "essential_tremor": average(apple.get("essential_tremor"), path.get("essential_tremor")),
    }


def _aggregate(
    tremor: dict[str, list[float]],
    impairment: dict[str, list[float]],
) -> dict[str, float | None]:
    """Parkinson is the impairment shared by both hands. Stroke is the gap.

    One hand moving leaves stroke null; the hands do not have to move at the same time.
    """
    tremor_means = _means(tremor)
    impairment_means = _means(impairment)
    scores: dict[str, float | None] = {name: None for name in SCORES}
    if not tremor_means:
        return scores
    scores["essential_tremor"] = max(tremor_means.values())
    if "left" in impairment_means and "right" in impairment_means:
        scores["parkinson"] = min(impairment_means["left"], impairment_means["right"])
        scores["stroke"] = abs(impairment_means["left"] - impairment_means["right"])
    else:
        scores["parkinson"] = next(iter(impairment_means.values()))
        scores["stroke"] = None
    return scores


def _means(groups: dict[str, list[float]] | None) -> dict[str, float]:
    if not groups:
        return {}
    return {hand: float(np.mean(values)) for hand, values in groups.items() if values}


def _result(name: str, duration_s: float, counts: dict[str, int], scores: dict[str, float | None]) -> dict:
    return {
        "recording": name,
        "duration_s": round(duration_s, 3),
        "stretches": counts,
        "scores": {name: None if value is None else round(float(value), 1) for name, value in scores.items()},
    }
