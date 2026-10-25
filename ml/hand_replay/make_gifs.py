"""Render hand + controller replays from data/ultimate_data.

    uv run python -m ml.hand_replay.make_gifs --all
    uv run python -m ml.hand_replay.make_gifs --all --style xray
    uv run python -m ml.hand_replay.make_gifs --session "data/ultimate_data/Tremor/2026-10-18_02-16-51_lobby"
    uv run python -m ml.hand_replay.make_gifs --session "<dir>" --level fish --seconds 6 --still
    uv run python -m ml.hand_replay.make_gifs --proposals
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from ml.hand_replay.reconstruct import level_folder, load_motion, reconstruct
from ml.hand_replay.render import render_gif, render_still
from ml.hand_replay.styles import STYLES, Style

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "ultimate_data"
OUT = Path(__file__).resolve().parent / "gifs"
PROPOSALS = Path(__file__).resolve().parent / "proposals"
PROPOSAL_SESSION = DATA / "Tremor" / "2026-10-18_02-38-26_lobby"
PROPOSAL_FRAME = 61
PER_CONDITION = 2
PER_STROKE_SIDE = 1
WEAK_HAND = {"Stroke / Left Hand Weak": 0, "Stroke / Right Hand Weak": 1}


def condition_of(session_dir: Path) -> str:
    return " / ".join(session_dir.parent.relative_to(DATA).parts)


def labelled_sessions() -> dict[str, list[Path]]:
    groups: dict[str, list[Path]] = {}
    for meta in sorted(DATA.rglob("session.json")):
        session = meta.parent
        if session.parent == DATA:
            continue
        groups.setdefault(condition_of(session), []).append(session)
    return groups


def usable_level(session: Path, level: str) -> Path | None:
    """The requested level, or the other one when that recording is missing on disk."""
    return level_folder(session, level) or level_folder(session, "fish" if level == "apple" else "apple")


def pick_sessions(condition: str, sessions: list[Path], level: str) -> list[tuple[Path, Path]]:
    usable = [(session, folder) for session in sessions if (folder := usable_level(session, level))]
    weak = WEAK_HAND.get(condition)
    if weak is None:
        return usable[:PER_CONDITION]

    def weak_share(item: tuple[Path, Path]) -> float:
        return float(reconstruct(item[1] / "controller_data.csv")[1]["shares"][:, weak].mean())

    return sorted(usable, key=weak_share)[:PER_STROKE_SIDE]


def session_motion(session: Path, folder: Path, seconds: float, fps: int, gain: float):
    level = folder.name.split("_")[-1]
    label = f"{condition_of(session)}  |  {session.name}  |  {level} level"
    return load_motion(folder, label, seconds=seconds, fps=fps, gain=gain), level


def render_session(session: Path, folder: Path, seconds: float, fps: int, gain: float, still: bool, style: Style) -> None:
    motion, level = session_motion(session, folder, seconds, fps, gain)
    out = OUT / condition_of(session).replace(" / ", "_").replace(" ", "_") / f"{session.name}_{level}"
    began = time.perf_counter()
    if still:
        render_still(motion, out.with_suffix(".png"), fps, len(motion.time_s) // 2, style)
        print(f"wrote {out.with_suffix('.png').relative_to(ROOT)}")
        return
    frames = render_gif(motion, out.with_suffix(".gif"), fps, style)
    size = out.with_suffix(".gif").stat().st_size / 1e6
    print(f"wrote {out.with_suffix('.gif').relative_to(ROOT)}  {frames} frames  {size:.1f} MB  {time.perf_counter() - began:.0f} s")


def render_proposals(seconds: float, fps: int, gain: float, only: str | None) -> None:
    """The same moment in every style (or just `only`), so they can be compared side by side."""
    folder = usable_level(PROPOSAL_SESSION, "apple")
    motion, _ = session_motion(PROPOSAL_SESSION, folder, seconds, fps, gain)
    for number, style in enumerate(STYLES.values(), start=1):
        if only and style.name != only:
            continue
        out = PROPOSALS / f"{number}_{style.name}.png"
        render_still(motion, out, fps, PROPOSAL_FRAME, style)
        print(f"wrote {out.relative_to(ROOT)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--all", action="store_true", help="Render a few sessions for every labelled condition.")
    parser.add_argument("--session", help="One session folder.")
    parser.add_argument("--proposals", action="store_true", help="One still per style into ml/hand_replay/proposals.")
    parser.add_argument("--style", choices=sorted(STYLES), help="Defaults to natural; with --proposals, defaults to all.")
    parser.add_argument("--level", default="apple", choices=("apple", "fish"))
    parser.add_argument("--seconds", type=float, default=8.0)
    parser.add_argument("--fps", type=int, default=25)
    parser.add_argument("--gain", type=float, default=10.0, help="How much the shake is exaggerated on screen.")
    parser.add_argument("--still", action="store_true", help="Write a single PNG frame instead of a GIF.")
    args = parser.parse_args()
    style = STYLES[args.style or "natural"]

    if args.proposals:
        render_proposals(args.seconds, args.fps, args.gain, args.style)
    elif args.session:
        session = Path(args.session).resolve()
        folder = usable_level(session, args.level)
        if folder is None:
            parser.error(f"{session} has no level recordings")
        render_session(session, folder, args.seconds, args.fps, args.gain, args.still, style)
    elif args.all:
        for condition, sessions in labelled_sessions().items():
            for session, folder in pick_sessions(condition, sessions, args.level):
                render_session(session, folder, args.seconds, args.fps, args.gain, args.still, style)
    else:
        parser.error("pass --all, --session or --proposals")


if __name__ == "__main__":
    main()
