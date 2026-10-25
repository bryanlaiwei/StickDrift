"""Static figures of what the mirror-game study measured.

    uv run --group study python -m ml.study.figures [--stim 4] [--out ml/runs/study_figures]
"""

import argparse
import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.signal import find_peaks, welch

from ml.study.load import (
    DEFAULT_ROOT,
    GROUP_COLORS,
    GROUP_NAMES,
    HZ,
    STUDY_FREQS,
    Study,
    fill_gaps,
    load_study,
    local_frequency,
    tracking_lag_s,
)

GROUPS = (1, 2, 3)
FREQ_COLUMNS = ("0_25", "0_3215", "0_375", "0_4375", "0_5", "0_5625")
DX_COLUMNS = ("0_2500", "0_3215", "0_3750", "0_4375", "0_5000", "0_5625")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default=str(DEFAULT_ROOT))
    parser.add_argument("--out", default="ml/runs/study_figures")
    parser.add_argument("--stim", type=int, default=4, help="Stimulus 1-11 used for the example traces.")
    parser.add_argument("--start", type=float, default=15.0, help="Start of the example window in seconds.")
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    study = load_study(args.data)
    picks = {group: study.representative(group) for group in GROUPS}

    plot_stimuli(study, out / "01_stimuli.png")
    plot_tracking(study, picks, args.stim, args.start, 20.0, out / "02_tracking_by_group.png")
    plot_submovements(study, picks, args.stim, args.start + 4.0, 4.0, out / "03_submovements_zoom.png")
    plot_group_measures(Path(args.data) / "csv" / "combined.csv", out / "04_group_measures.png")
    plot_error_signal(study, args.stim, out / "05_error_signal.png")
    print(f"Wrote 5 figures to {out}")
    for group, subject in picks.items():
        print(f"  {GROUP_NAMES[group]:14s} example: subject {subject}, age {study.age_of(subject)}")


def plot_stimuli(study: Study, path: Path) -> None:
    fig, axes = plt.subplots(len(study.dots), 1, figsize=(13, 14), sharex=True)
    cmap = plt.get_cmap("viridis")
    lo, hi = min(STUDY_FREQS), max(STUDY_FREQS)
    for axis, (stim, dot) in zip(axes, study.dots.items()):
        freq = local_frequency(dot)
        axis.scatter(study.time_s, dot, c=(freq - lo) / (hi - lo), cmap=cmap, s=0.6, linewidths=0)
        axis.set_ylabel(f"dot{stim}", rotation=0, ha="right", va="center")
        axis.set_yticks([])
        axis.set_ylim(-0.65, 0.65)
    axes[-1].set_xlabel("time (s)")
    handles = [
        plt.Line2D([], [], marker="o", ls="", color=cmap((value - lo) / (hi - lo)), label=f"{value:g} Hz")
        for value in STUDY_FREQS
    ]
    fig.legend(handles=handles, loc="upper right", ncol=6, frameon=False)
    fig.suptitle("What participants followed: dot x position for each of the 11 trials (color = speed)", x=0.01, ha="left")
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    fig.savefig(path, dpi=130)
    plt.close(fig)


def plot_tracking(study: Study, picks: dict[int, str], stim: int, start: float, seconds: float, path: Path) -> None:
    window = _window(study, start, seconds)
    t = study.time_s[window]
    dot = study.dots[stim][window]
    fig, axes = plt.subplots(3, 1, figsize=(13, 8.5), sharex=True, sharey=True)
    for axis, group in zip(axes, GROUPS):
        subject = picks[group]
        pen = study.pen(stim, subject)[window]
        color = GROUP_COLORS[group]
        axis.plot(t, dot, color="black", lw=1.6, label="dot (target)")
        axis.plot(t, pen, color=color, lw=1.4, label="pen (hand)")
        axis.fill_between(t, dot, pen, color=color, alpha=0.18, label="error")
        lag = tracking_lag_s(study.dots[stim], study.pen(stim, subject))
        rms = np.sqrt(np.nanmean((pen - dot) ** 2))
        axis.set_title(
            f"{GROUP_NAMES[group]}  |  subject {subject}, age {study.age_of(subject)}  |  "
            f"lag {lag * 1000:.0f} ms, RMS error {rms:.3f}",
            loc="left",
            fontsize=10,
        )
        axis.set_ylabel("x (screen widths / 2)")
        axis.legend(loc="upper right", fontsize=8, ncol=3)
    axes[-1].set_xlabel("time (s)")
    fig.suptitle(f"Tracking the same dot (trial dot{stim}): typical subject from each group", x=0.01, ha="left")
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    fig.savefig(path, dpi=130)
    plt.close(fig)


def plot_submovements(study: Study, picks: dict[int, str], stim: int, start: float, seconds: float, path: Path) -> None:
    window = _window(study, start, seconds)
    t = study.time_s[window]
    dot_v = np.gradient(study.dots[stim])[window] * HZ
    fig, axes = plt.subplots(3, 1, figsize=(13, 8.5), sharex=True, sharey=True)
    for axis, group in zip(axes, GROUPS):
        subject = picks[group]
        pen_v = np.gradient(fill_gaps(study.pen(stim, subject)))[window] * HZ
        speed = np.abs(pen_v)
        peaks, _ = find_peaks(speed, prominence=0.04, distance=int(0.08 * HZ))
        color = GROUP_COLORS[group]
        axis.plot(t, dot_v, color="black", lw=1.5, label="dot velocity")
        axis.plot(t, pen_v, color=color, lw=1.3, label="pen velocity")
        axis.plot(t[peaks], pen_v[peaks], "v", color=color, ms=7, mec="black", label="speed peak (submovement)")
        axis.axhline(0, color="grey", lw=0.6)
        axis.set_title(
            f"{GROUP_NAMES[group]}  |  subject {subject}  |  {len(peaks)} speed peaks in {seconds:g} s "
            f"({len(peaks) / seconds:.1f}/s)",
            loc="left",
            fontsize=10,
        )
        axis.set_ylabel("velocity (units/s)")
        axis.legend(loc="upper right", fontsize=8, ncol=3)
    axes[-1].set_xlabel("time (s)")
    fig.suptitle(
        "Zoomed in: a smooth hand has one speed peak per sweep, a corrective hand breaks it into several submovements",
        x=0.01,
        ha="left",
    )
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    fig.savefig(path, dpi=130)
    plt.close(fig)


def plot_group_measures(combined: Path, path: Path) -> None:
    with combined.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    panels = (
        ("dT", DX_COLUMNS, "Timing error dT (s)"),
        ("dX", DX_COLUMNS, "Position error dX"),
        ("submovementRateType3", FREQ_COLUMNS, "Type 3 submovements per second"),
        ("submovementRate", FREQ_COLUMNS, "All submovements per second"),
    )
    fig, axes = plt.subplots(1, 4, figsize=(17, 4.6))
    for axis, (prefix, suffixes, title) in zip(axes, panels):
        for group in GROUPS:
            members = [row for row in rows if int(row["Group"]) == group]
            values = np.array(
                [[_float(row[f"{prefix}_{suffix}"]) for suffix in suffixes] for row in members]
            )
            mean = np.nanmean(values, axis=0)
            sem = np.nanstd(values, axis=0) / np.sqrt(np.isfinite(values).sum(axis=0))
            color = GROUP_COLORS[group]
            axis.errorbar(STUDY_FREQS, mean, yerr=sem, color=color, marker="o", capsize=3, label=f"{GROUP_NAMES[group]} (n={len(members)})")
        axis.set_title(title, fontsize=10)
        axis.set_xlabel("dot frequency (Hz)")
        axis.grid(alpha=0.3)
    axes[0].legend(fontsize=8)
    fig.suptitle("Published study measures by group (mean +/- standard error, from combined.csv)", x=0.01, ha="left")
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(path, dpi=130)
    plt.close(fig)


def plot_error_signal(study: Study, stim: int, path: Path) -> None:
    fig = plt.figure(figsize=(15, 9))
    grid = fig.add_gridspec(2, 3, height_ratios=(1.3, 1))
    trace_axes = [fig.add_subplot(grid[0, column]) for column in range(3)]
    spectrum_axis = fig.add_subplot(grid[1, 0:2])
    lag_axis = fig.add_subplot(grid[1, 2])
    window = _window(study, 10.0, 10.0)
    t = study.time_s[window]
    bins = np.linspace(-0.1, 0.45, 23)
    for axis, group in zip(trace_axes, GROUPS):
        color = GROUP_COLORS[group]
        spectra = []
        lags = []
        for subject in study.members(group):
            error = study.error(stim, subject)
            if np.isfinite(error).mean() < 0.5:
                continue
            axis.plot(t, error[window], color=color, alpha=0.25, lw=0.8)
            freqs, power = welch(fill_gaps(error), fs=HZ, nperseg=512)
            spectra.append(power)
            per_trial = [tracking_lag_s(study.dots[k], study.pen(k, subject)) for k in study.dots]
            lags.append(np.nanmedian(per_trial))
        axis.axhline(0, color="black", lw=0.8)
        axis.set_ylim(-0.35, 0.35)
        axis.set_title(f"{GROUP_NAMES[group]}: pen minus dot, every subject (dot{stim})", fontsize=10)
        axis.set_xlabel("time (s)")
        spectrum_axis.semilogy(freqs, np.mean(spectra, axis=0), color=color, lw=2, label=GROUP_NAMES[group])
        lag_axis.hist(lags, bins=bins, color=color, alpha=0.45, label=f"{GROUP_NAMES[group]} (mean {np.nanmean(lags) * 1000:.0f} ms)")
    trace_axes[0].set_ylabel("error (units)")
    spectrum_axis.set_xlim(0, 12)
    spectrum_axis.set_xlabel("frequency (Hz)")
    spectrum_axis.set_ylabel("error power")
    spectrum_axis.set_title("Average error spectrum: where the extra error energy sits", fontsize=10)
    spectrum_axis.legend(fontsize=8)
    spectrum_axis.grid(alpha=0.3, which="both")
    lag_axis.set_xlabel("lag behind dot (s), median over 11 trials")
    lag_axis.set_ylabel("subjects")
    lag_axis.set_title("Lag from velocity cross-correlation", fontsize=10)
    lag_axis.legend(fontsize=8)
    fig.suptitle(
        "The error signal: what a real hand adds on top of the target path (this is what we would transplant into controller runs)",
        x=0.01,
        ha="left",
    )
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig(path, dpi=130)
    plt.close(fig)


def _window(study: Study, start: float, seconds: float) -> slice:
    first = int(start * HZ)
    return slice(first, min(len(study.time_s), first + int(seconds * HZ)))


def _float(text: str) -> float:
    try:
        return float(text)
    except (TypeError, ValueError):
        return float("nan")


if __name__ == "__main__":
    main()
