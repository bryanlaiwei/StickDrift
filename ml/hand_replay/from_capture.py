"""Render a lobby visit's one reconstructed-hands GIF from the API's in-memory capture.

    python -m ml.hand_replay.from_capture --out hands.gif < capture.json

stdin is the capture `ml.visit_report` gets: {"apple": {"frames": [...], "events": [...]}, "fish": ..., "rat": ...}.
Writes the GIF and prints one JSON line:
    {"game", "window_start_s", "duration_s", "frames", "has_motion", "bytes", "renderer_version"}
Exits 2 when stdin is not a capture and 3 when no game has enough frames.
"""

from __future__ import annotations

import os

os.environ.setdefault("MPLBACKEND", "Agg")

import argparse
import json
import sys
from pathlib import Path

from ml.hand_replay.reconstruct import MIN_FRAMES_S, motion_from_capture
from ml.hand_replay.render import RENDERER_VERSION, render_scene_gif


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", required=True, type=Path, help="Where to write the GIF.")
    parser.add_argument("--seconds", type=float, default=6.0)
    parser.add_argument("--fps", type=int, default=25)
    parser.add_argument("--gain", type=float, default=10.0, help="How much the shake is exaggerated on screen.")
    args = parser.parse_args(argv)

    try:
        capture = json.load(sys.stdin)
    except ValueError as error:
        print(f"hand replay: stdin is not capture JSON ({error})", file=sys.stderr)
        return 2
    if not isinstance(capture, dict):
        print("hand replay: stdin is not a capture object", file=sys.stderr)
        return 2

    picked = motion_from_capture(capture, args.seconds, args.fps, args.gain)
    if picked is None:
        print(f"hand replay: no usable frames (no game has {MIN_FRAMES_S:g} s of play)", file=sys.stderr)
        return 3
    game, motion = picked
    frames = render_scene_gif(motion, args.out, args.fps)
    print(json.dumps({
        "game": game,
        "window_start_s": round(float(motion.time_s[0]), 2),
        "duration_s": round(frames / args.fps, 2),
        "frames": frames,
        "has_motion": motion.has_motion,
        "bytes": args.out.stat().st_size,
        "renderer_version": RENDERER_VERSION,
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
