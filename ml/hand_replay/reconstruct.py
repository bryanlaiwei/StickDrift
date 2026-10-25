"""Turn one lobby level recording into per-frame controller pose and per-hand shake.

Two inputs share one path: a recorded level folder (`controller_data.csv`) and the frame dicts the API keeps
in memory during a live lobby visit (the capture `ml.visit_report` gets).

Body frame used everywhere: x to the player's right, y away from the player, z up (centimetres, radians).
"""

from __future__ import annotations

import csv
import json
import math
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy import signal

GYRO_COUNTS_PER_RAD_S = 16.4 * 180.0 / np.pi
SAMPLE_HZ = 60.0
TREMOR_BAND_HZ = (3.0, 12.0)
SLOW_CUTOFF_HZ = 2.0
YAW_HIGHPASS_HZ = 0.3
MAX_TILT_RAD = np.radians(30)
GRIPS_CM = np.array([[-8.0, -5.0, 0.0], [8.0, -5.0, 0.0]])
GRIP_SPAN_CM = 16.0
JITTER_WINDOW_S = 1.0
SHARE_LIMITS = (0.25, 1.75)
SHAKE_CAP_CM = 2.0

NUMERIC = (
    "t", "lx", "ly", "rx", "ry", "tgt_lx", "tgt_ly", "tgt_rx", "tgt_ry",
    "gyro_x", "gyro_y", "gyro_z", "acc_x", "acc_y", "acc_z", "l2_value", "r2_value",
    "l1_pressed", "r1_pressed", "cross_pressed", "circle_pressed", "square_pressed", "triangle_pressed",
)
HELD = ("tgt_lx", "tgt_ly", "tgt_rx", "tgt_ry", "l1_pressed", "r1_pressed",
        "cross_pressed", "circle_pressed", "square_pressed", "triangle_pressed")
FACE_BUTTONS = ("cross", "circle", "square", "triangle")
# Triggers and buttons the source did not report are released, not unknown (the live lobby sends none).
ZERO_WHEN_MISSING = ("l2_value", "r2_value", "l1_pressed", "r1_pressed",
                     "cross_pressed", "circle_pressed", "square_pressed", "triangle_pressed")
CAPTURE_NAMES = {"tgt_lx": "target_lx", "tgt_ly": "target_ly", "tgt_rx": "target_rx", "tgt_ry": "target_ry"}
CAPTURE_GAMES = ("apple", "fish", "rat")
PREFERRED_S = 3.0
MIN_FRAMES_S = 1.5
RUN_GAP_S = 1.0
MOTION_SHARE = 0.5


@dataclass
class Motion:
    """Everything the renderer needs, one row per output frame."""

    time_s: np.ndarray
    sticks: np.ndarray
    targets: np.ndarray
    triggers: np.ndarray
    bumpers: np.ndarray
    face: np.ndarray
    tilt: np.ndarray
    grip_shift: np.ndarray
    shares: np.ndarray
    shake_cm: np.ndarray
    peak_hz: float
    gain: float
    label: str
    has_motion: bool = True


def _columns(rows: Iterable[dict], names: dict[str, str] | None = None) -> dict[str, np.ndarray]:
    """One float array per NUMERIC column. Blank or missing cells are NaN (0 for ZERO_WHEN_MISSING)."""
    names = names or {}
    rows = list(rows)

    def cell(row: dict, key: str) -> float:
        value = row.get(names.get(key, key))
        if value is None or value == "":
            return 0.0 if key in ZERO_WHEN_MISSING else np.nan
        return float(value)

    return {key: np.array([cell(row, key) for row in rows], dtype=float) for key in NUMERIC}


def read_level(csv_path: Path) -> dict[str, np.ndarray]:
    with open(csv_path, newline="") as handle:
        return _columns(csv.DictReader(handle))


def _resample(raw: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    order = np.argsort(raw["t"], kind="stable")
    t = raw["t"][order]
    keep = np.concatenate([[True], np.diff(t) > 0])
    t = t[keep]
    grid = np.arange(t[0], t[-1], 1.0 / SAMPLE_HZ)
    out = {"t": grid}
    nearest = np.clip(np.searchsorted(t, grid), 0, len(t) - 1)
    out["gyro_ok"] = np.isfinite(raw["gyro_x"][order][keep])[nearest].astype(float)
    for key in NUMERIC[1:]:
        values = raw[key][order][keep]
        if key in HELD:
            out[key] = values[nearest]
            continue
        finite = np.isfinite(values)
        out[key] = np.interp(grid, t[finite], values[finite]) if finite.any() else np.zeros_like(grid)
    return out


def _body(x: np.ndarray, y: np.ndarray, z: np.ndarray) -> np.ndarray:
    return np.stack([x, -z, y], axis=1)


def _filter(kind: str, cutoff, data: np.ndarray) -> np.ndarray:
    sos = signal.butter(2, cutoff, btype=kind, fs=SAMPLE_HZ, output="sos")
    return signal.sosfiltfilt(sos, data, axis=0)


def _rolling_rms(data: np.ndarray, window: int) -> np.ndarray:
    kernel = np.ones(window) / window
    return np.sqrt(np.convolve(data**2, kernel, mode="same"))


def _hand_shares(s: dict[str, np.ndarray]) -> np.ndarray:
    """How much of the measured shake each hand carries, from each stick's own fast jitter."""
    window = int(JITTER_WINDOW_S * SAMPLE_HZ)
    jitter = []
    for x, y in (("lx", "ly"), ("rx", "ry")):
        fast = _filter("highpass", TREMOR_BAND_HZ[0], np.stack([s[x], s[y]], axis=1))
        jitter.append(_rolling_rms(np.linalg.norm(fast, axis=1), window))
    jitter = np.stack(jitter, axis=1)
    floor = 0.15 * max(float(np.median(jitter)), 1e-3)
    shares = 2 * (jitter + floor) / (jitter.sum(axis=1, keepdims=True) + 2 * floor)
    return np.clip(shares, *SHARE_LIMITS)


def reconstruct(csv_path: Path, gain: float = 10.0) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray]]:
    return reconstruct_columns(read_level(csv_path), gain)


def reconstruct_columns(raw: dict[str, np.ndarray], gain: float = 10.0) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray]]:
    """Full-length signals at SAMPLE_HZ: the resampled columns plus derived pose."""
    s = _resample(raw)
    gyro = _body(s["gyro_x"], s["gyro_y"], s["gyro_z"]) / GYRO_COUNTS_PER_RAD_S
    gyro -= np.median(gyro, axis=0)
    acc = _filter("lowpass", SLOW_CUTOFF_HZ, _body(s["acc_x"], s["acc_y"], s["acc_z"]))

    pitch = np.arctan2(-acc[:, 1], acc[:, 2])
    roll = np.arctan2(acc[:, 0], acc[:, 2])
    yaw = _filter("highpass", YAW_HIGHPASS_HZ, np.cumsum(gyro[:, 2]) / SAMPLE_HZ)
    tilt = np.stack([pitch - np.median(pitch), roll - np.median(roll), yaw], axis=1)
    tilt = np.clip(_filter("lowpass", SLOW_CUTOFF_HZ, tilt), -MAX_TILT_RAD, MAX_TILT_RAD)

    tremor_rate = _filter("bandpass", TREMOR_BAND_HZ, gyro)
    tremor_angle = _filter("bandpass", TREMOR_BAND_HZ, np.cumsum(tremor_rate, axis=0) / SAMPLE_HZ)
    shares = _hand_shares(s)
    real_shift = np.stack([shares[:, [hand]] * np.cross(tremor_angle, GRIPS_CM[hand]) for hand in (0, 1)], axis=1)
    size = np.linalg.norm(real_shift, axis=2, keepdims=True)
    shown = SHAKE_CAP_CM * np.tanh(gain * size / SHAKE_CAP_CM)
    derived = {
        "tilt": tilt,
        "grip_shift": real_shift * shown / np.maximum(size, 1e-9),
        "shares": shares,
        "tremor_rate": tremor_rate,
        "shake_cm": size[..., 0],
    }
    return s, derived


def busiest_window(derived: dict[str, np.ndarray], s: dict[str, np.ndarray], seconds: float, skip_s: float = 1.5) -> int:
    """Start sample of the stretch with the most shake plus stick movement."""
    width = int(seconds * SAMPLE_HZ)
    sticks = np.stack([s[k] for k in ("lx", "ly", "rx", "ry")], axis=1)
    speed = np.linalg.norm(np.diff(sticks, axis=0, prepend=sticks[:1]), axis=1)
    shake = np.linalg.norm(derived["tremor_rate"], axis=1)
    score = shake / (shake.mean() + 1e-9) + speed / (speed.mean() + 1e-9)
    totals = np.convolve(score, np.ones(width), mode="valid")
    first = min(int(skip_s * SAMPLE_HZ), max(0, len(totals) - 1))
    return first + int(np.argmax(totals[first:])) if len(totals) > first else 0


def peak_frequency(rate: np.ndarray) -> float:
    freqs, power = signal.welch(rate, fs=SAMPLE_HZ, nperseg=min(len(rate), 256), axis=0)
    power = power.sum(axis=1)
    band = (freqs >= TREMOR_BAND_HZ[0]) & (freqs <= TREMOR_BAND_HZ[1])
    return float(freqs[band][np.argmax(power[band])])


def load_motion(level_dir: Path, label: str, seconds: float = 8.0, fps: int = 25, gain: float = 10.0) -> Motion:
    s, derived = reconstruct(level_dir / "controller_data.csv", gain)
    return _window_motion(s, derived, label, seconds, fps, gain)


def _window_motion(s: dict[str, np.ndarray], derived: dict[str, np.ndarray], label: str,
                   seconds: float, fps: int, gain: float) -> Motion:
    """The busiest `seconds` (all of it when the recording is shorter), sampled at `fps`."""
    seconds = min(seconds, len(s["t"]) / SAMPLE_HZ)
    start = busiest_window(derived, s, seconds)
    stop = min(len(s["t"]), start + int(seconds * SAMPLE_HZ))
    frames = np.round(np.arange(start, stop, SAMPLE_HZ / fps)).astype(int)
    frames = frames[frames < stop]

    def take(*keys: str) -> np.ndarray:
        return np.stack([s[k][frames] for k in keys], axis=1)

    return Motion(
        time_s=s["t"][frames],
        sticks=take("lx", "ly", "rx", "ry"),
        targets=take("tgt_lx", "tgt_ly", "tgt_rx", "tgt_ry"),
        triggers=take("l2_value", "r2_value"),
        bumpers=take("l1_pressed", "r1_pressed"),
        face=take(*(f"{name}_pressed" for name in FACE_BUTTONS)),
        tilt=derived["tilt"][frames],
        grip_shift=derived["grip_shift"][frames],
        shares=derived["shares"][frames],
        shake_cm=derived["shake_cm"][frames],
        peak_hz=peak_frequency(derived["tremor_rate"][start:stop]),
        gain=gain,
        label=label,
        has_motion=bool(s["gyro_ok"][start:stop].mean() >= MOTION_SHARE),
    )


def _longest_run(frames: Iterable) -> list[dict]:
    """The longest stretch of frames without a pause; the live clock runs across the whole visit."""
    timed = sorted(
        (f for f in frames or [] if isinstance(f, dict) and isinstance(f.get("t"), (int, float)) and math.isfinite(f["t"])),
        key=lambda f: f["t"],
    )
    runs, current = [], []
    for frame in timed:
        if current and frame["t"] - current[-1]["t"] > RUN_GAP_S:
            runs.append(current)
            current = []
        current.append(frame)
    if current:
        runs.append(current)
    return max(runs, key=_span, default=[])


def _span(frames: list[dict]) -> float:
    return float(frames[-1]["t"] - frames[0]["t"]) if len(frames) > 1 else 0.0


def motion_from_frames(frames: Iterable, label: str, seconds: float = 6.0, fps: int = 25, gain: float = 10.0) -> Motion:
    """Motion from live-capture frame dicts (t, lx..ry, target_*, optional gyro_*/acc_*).

    Without gyro and accelerometer values the controller holds still and only the thumbs move.
    """
    run = _longest_run(frames)
    if _span(run) < MIN_FRAMES_S:
        raise ValueError(f"need at least {MIN_FRAMES_S:g} s of frames, got {_span(run):.1f} s")
    raw = _columns(run, CAPTURE_NAMES)
    raw["t"] -= raw["t"][0]
    s, derived = reconstruct_columns(raw, gain)
    return _window_motion(s, derived, label, seconds, fps, gain)


def pick_game(capture: dict) -> str | None:
    """Apple if it has PREFERRED_S of frames, else fish, else rat; failing that, the longest game with MIN_FRAMES_S."""
    spans = {game: _span(_longest_run((capture.get(game) or {}).get("frames"))) for game in CAPTURE_GAMES}
    for game in CAPTURE_GAMES:
        if spans[game] >= PREFERRED_S:
            return game
    longest = max(CAPTURE_GAMES, key=spans.__getitem__)
    return longest if spans[longest] >= MIN_FRAMES_S else None


def motion_from_capture(capture: dict, seconds: float = 6.0, fps: int = 25,
                        gain: float = 10.0) -> tuple[str, Motion] | None:
    """The one window shown for a lobby visit, or None when no game has enough frames."""
    game = pick_game(capture or {})
    if game is None:
        return None
    return game, motion_from_frames(capture[game]["frames"], game, seconds, fps, gain)


def level_folder(session_dir: Path, level: str) -> Path | None:
    meta = json.loads((session_dir / "session.json").read_text())
    for entry in meta.get("levels", []):
        if entry.get("level") == level and (session_dir / entry["folder"] / "controller_data.csv").exists():
            return session_dir / entry["folder"]
    return None
