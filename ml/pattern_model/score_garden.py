"""Score one garden session folder with the trained pattern model.

Runs in the project's Python 3.14 environment (it needs torch), not the backend's.
Prints one JSON object on stdout. From the repository root:

    .venv/bin/python -m ml.pattern_model.score_garden data/<session folder>
"""
import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np
import torch

from ml.pattern_model.checkpoint import load_checkpoint
from ml.pattern_model.config import SCORE_MEANING, SCORES, Segment
from ml.pattern_model.recording import Recording, RecordingError
from ml.pattern_model.score import score_recording

ROOT = Path(__file__).resolve().parents[2]


def score_session(folder: Path, checkpoint: Path) -> dict:
    meta = json.loads((folder / "session.json").read_text(encoding="utf-8"))
    device = torch.device("cpu")
    model, blob = load_checkpoint(checkpoint, device)
    mean = np.asarray(blob["norm_mean"], dtype=np.float32)
    std = np.asarray(blob["norm_std"], dtype=np.float32)

    levels = []
    for item in meta.get("levels", []):
        csv_path = folder / item["folder"] / "controller_data.csv"
        entry = {"level": item["level"], "completed": item.get("completed", False)}
        try:
            with csv_path.open(newline="", encoding="utf-8-sig") as stream:
                recording = Recording.from_rows(list(csv.DictReader(stream)), item["level"])
            result = score_recording(
                model, recording, mean, std,
                sample_hz=int(blob["sample_hz"]), segment=Segment(**blob["segment"]),
                hand_scores=list(blob["hand_scores"]), device=device,
            )
            entry.update(scores=result["scores"], stretches=result["stretches"], duration_s=result["duration_s"])
        except (OSError, RecordingError) as error:
            entry.update(scores={name: None for name in SCORES}, error=str(error))
        levels.append(entry)

    # Session score: average of the levels that could be scored, weighted by how many
    # moving stretches each level contributed.
    session = {}
    for name in SCORES:
        pairs = [(lv["scores"][name], sum(lv.get("stretches", {}).values()) or 1)
                 for lv in levels if lv["scores"].get(name) is not None]
        weight = sum(w for _, w in pairs)
        session[name] = round(sum(v * w for v, w in pairs) / weight, 1) if pairs else None

    return {
        "scores": session,
        "levels": levels,
        "meaning": SCORE_MEANING,
        "checkpoint": str(checkpoint.relative_to(ROOT)) if checkpoint.is_relative_to(ROOT) else str(checkpoint),
        "schema_version": blob.get("schema_version"),
        "is_synthetic": bool(meta.get("is_synthetic")),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("folder", type=Path)
    parser.add_argument("--checkpoint", type=Path, default=ROOT / "ml" / "runs" / "pattern_model" / "model.pt")
    args = parser.parse_args()
    json.dump(score_session(args.folder.resolve(), args.checkpoint.resolve()), sys.stdout)


if __name__ == "__main__":
    main()
