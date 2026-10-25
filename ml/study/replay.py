"""Replay the dot and the real pen of one subject per group, side by side.

    uv run --group study python -m ml.study.replay
    uv run --group study python -m ml.study.replay --stim 4 --start 20 --seconds 15 --save ml/runs/study_figures/replay.gif
    uv run --group study python -m ml.study.replay --subjects 104 331 22
"""

import argparse
from pathlib import Path

import matplotlib
import numpy as np

from ml.study.load import DEFAULT_ROOT, GROUP_COLORS, GROUP_NAMES, HZ, load_study, local_frequency, tracking_lag_s

TAIL_S = 0.5
STRIP_S = 4.0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", default=str(DEFAULT_ROOT))
    parser.add_argument("--stim", type=int, default=4, help="Stimulus 1-11.")
    parser.add_argument("--start", type=float, default=20.0, help="Start time in seconds.")
    parser.add_argument("--seconds", type=float, default=20.0)
    parser.add_argument("--speed", type=float, default=1.0, help="Playback speed multiplier.")
    parser.add_argument("--fps", type=int, default=25)
    parser.add_argument("--subjects", nargs="+", help="Subject IDs, one lane each. Defaults to a typical subject per group.")
    parser.add_argument("--save", help="Write a .gif instead of opening a window.")
    args = parser.parse_args()

    if args.save:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.animation import FuncAnimation, PillowWriter

    study = load_study(args.data)
    subjects = args.subjects or [study.representative(group) for group in (1, 2, 3)]
    stim = args.stim
    dot = study.dots[stim]
    freq = local_frequency(dot)
    first = int(args.start * HZ)
    last = min(len(dot), first + int(args.seconds * HZ))
    step = max(1, int(round(HZ * args.speed / args.fps)))
    frames = range(first, last, step)
    tail = int(TAIL_S * HZ)
    strip = int(STRIP_S * HZ)

    lanes = len(subjects)
    fig = plt.figure(figsize=(11, 2.0 * lanes + 3.2))
    grid = fig.add_gridspec(lanes + 1, 1, height_ratios=[1] * lanes + [1.8], hspace=0.55)
    lane_axes = [fig.add_subplot(grid[row, 0]) for row in range(lanes)]
    strip_axis = fig.add_subplot(grid[lanes, 0])

    pens = [study.pen(stim, subject) for subject in subjects]
    colors = [GROUP_COLORS.get(study.group_of(subject), "grey") for subject in subjects]
    artists = []
    for axis, subject, color in zip(lane_axes, subjects, colors):
        group = study.group_of(subject)
        lag = tracking_lag_s(dot, study.pen(stim, subject))
        axis.set_xlim(-0.7, 0.7)
        axis.set_ylim(-1, 1)
        axis.set_yticks([])
        axis.set_xticks([])
        axis.axhline(0, color="#dddddd", lw=8, zorder=0)
        axis.set_title(
            f"{GROUP_NAMES.get(group, 'Unknown')}  |  subject {subject}, age {study.age_of(subject)}  |  "
            f"trial lag {lag * 1000:.0f} ms",
            loc="left",
            fontsize=10,
            color=color,
        )
        target = axis.scatter([0], [0], s=420, color="black", zorder=3, label="dot")
        trail = axis.scatter(np.zeros(tail), np.zeros(tail), s=np.linspace(4, 60, tail), color=color, alpha=0.0, zorder=2)
        (pen_marker,) = axis.plot([0], [0], marker="X", ms=16, color=color, mec="black", zorder=4, label="pen")
        readout = axis.text(0.99, 0.08, "", transform=axis.transAxes, ha="right", fontsize=9, family="monospace")
        artists.append((target, trail, pen_marker, readout, matplotlib.colors.to_rgba(color)))
    lane_axes[0].legend(loc="upper left", fontsize=8, ncol=2, markerscale=0.5)

    (dot_line,) = strip_axis.plot([], [], color="black", lw=2, label="dot")
    pen_lines = [
        strip_axis.plot([], [], color=color, lw=1.4, label=f"{subject}")[0] for subject, color in zip(subjects, colors)
    ]
    strip_axis.set_ylim(-0.7, 0.7)
    strip_axis.set_xlabel("time (s)")
    strip_axis.set_ylabel("x")
    strip_axis.legend(loc="upper left", fontsize=8, ncol=lanes + 1)
    strip_axis.grid(alpha=0.3)
    header = fig.suptitle("", x=0.01, ha="left")

    def draw(sample: int):
        changed = [dot_line, header, *pen_lines]
        lo = max(0, sample - tail)
        alphas = np.linspace(0.05, 0.6, sample - lo) if sample > lo else np.zeros(0)
        for (target, trail, pen_marker, readout, rgba), pen in zip(artists, pens):
            target.set_offsets([[dot[sample], 0]])
            history = pen[lo:sample]
            keep = np.isfinite(history)
            points = np.column_stack([history[keep], np.zeros(int(keep.sum()))])
            trail.set_offsets(points if len(points) else np.zeros((0, 2)))
            trail.set_alpha(None)
            colors_rgba = np.tile(rgba, (len(points), 1))
            colors_rgba[:, 3] = alphas[keep]
            trail.set_facecolors(colors_rgba)
            trail.set_edgecolors("none")
            trail.set_sizes(np.linspace(4, 60, len(history))[keep])
            now = pen[sample]
            if np.isfinite(now):
                pen_marker.set_data([now], [0])
                readout.set_text(f"error {now - dot[sample]:+.3f}")
            else:
                pen_marker.set_data([], [])
                readout.set_text("pen lifted")
            changed += [target, trail, pen_marker, readout]
        window = slice(max(first, sample - strip), sample + 1)
        times = study.time_s[window]
        dot_line.set_data(times, dot[window])
        for line, pen in zip(pen_lines, pens):
            line.set_data(times, pen[window])
        strip_axis.set_xlim(study.time_s[sample] - STRIP_S, study.time_s[sample] + 0.2)
        header.set_text(
            f"Mirror game replay, trial dot{stim}  |  t = {study.time_s[sample]:5.2f} s  |  "
            f"dot speed {freq[sample]:g} Hz  |  playback x{args.speed:g}"
        )
        return changed

    animation = FuncAnimation(fig, draw, frames=frames, interval=1000 / args.fps, blit=False, repeat=True)
    if args.save:
        out = Path(args.save)
        out.parent.mkdir(parents=True, exist_ok=True)
        animation.save(out, writer=PillowWriter(fps=args.fps), dpi=80)
        print(f"Wrote {out} ({len(frames)} frames)")
    else:
        plt.show()


if __name__ == "__main__":
    main()
