"""Shared constants for the per-hand pattern model.

Each hand is scored on what remains after its slow path is removed, and on how
far the stick sits from that hand's own target. Parkinson is the impairment
shared by both hands. Stroke is the gap between the hands. Essential tremor is
the leftover shake.
Scores are resemblance from 0 to 100, not disease probabilities, and more than
one may be high. They do not sum to 100.
"""

from dataclasses import dataclass

SAMPLE_HZ = 100
MIN_DURATION_S = 1.0

# Raw recording channels. Stick position, then the motion sensor.
CHANNELS = (
    "lx",
    "ly",
    "rx",
    "ry",
    "gyro_x",
    "gyro_y",
    "gyro_z",
    "acc_x",
    "acc_y",
    "acc_z",
)

# One shared network reads these, in this order, for whichever hand is moving.
# error_along / error_across are the miss in the target's own frame: along is
# past (positive) or short (negative) of the target, across is off to the side.
# The apple's direction is not a channel. has_target is 0 when this sample has
# no target, or when the phase is not cue or track. in_bounds is the fishing
# lane indicator (1 inside, 0 outside) and stays 0 on apple reaches.
HAND_CHANNELS = (
    "resid_x",
    "resid_y",
    "gyro_x",
    "gyro_y",
    "gyro_z",
    "error_along",
    "error_across",
    "has_target",
    "in_bounds",
    "speed_ratio",
    "amplitude",
    "latency_s",
    "has_cue",
    "shrink_ratio",
    # How hard the controller itself is shaking, and how fast this hand
    # actually moved. The tremor and impairment heads read these directly.
    "gyro_level",
    "move_speed",
)

# Network outputs for a single hand. Recording scores are derived from these.
HAND_SCORES = ("tremor", "impairment")

# Recording-level scores returned to callers.
SCORES = ("parkinson", "stroke", "essential_tremor")

# Midpoint of a 0..255 stick byte. Used only when a file has targets but no
# cursor columns. Played files already store cursor_* in the game's -1..1 space.
STICK_CENTER = 127.5

HIDDEN = 32
LEVELS = 6
KERNEL = 3
DROPOUT = 0.1

SCHEMA_VERSION = 9
SCORE_MEANING = "0-100 pattern resemblance, not a disease probability"


@dataclass(frozen=True)
class Segment:
    """How a recording is cut into moving stretches and how the slow path is removed."""

    smooth_s: float = 0.16
    move_window_s: float = 0.10
    move_counts: float = 3.0
    min_stretch_s: float = 0.25
    merge_gap_s: float = 0.15
    min_amplitude: float = 8.0
    stretch_steps: int = 80
    max_latency_s: float = 2.0
    shrink_clip: float = 3.0


DEFAULT_SEGMENT = Segment()

# Header aliases accepted from the HID recorder and from the pygame game logger.
COLUMN_ALIASES = {
    "t": ("t", "time"),
    "lx": ("lx", "raw_x"),
    "ly": ("ly", "raw_y"),
    "rx": ("rx", "raw_rx"),
    "ry": ("ry", "raw_ry"),
    "gyro_x": ("gyro_x",),
    "gyro_y": ("gyro_y",),
    "gyro_z": ("gyro_z",),
    "acc_x": ("acc_x",),
    "acc_y": ("acc_y",),
    "acc_z": ("acc_z",),
    "target_lx": ("target_lx", "tgt_lx"),
    "target_ly": ("target_ly", "tgt_ly"),
    "target_rx": ("target_rx", "tgt_rx"),
    "target_ry": ("target_ry", "tgt_ry"),
    "cursor_lx": ("cursor_lx", "cur_lx"),
    "cursor_ly": ("cursor_ly", "cur_ly"),
    "cursor_rx": ("cursor_rx", "cur_rx"),
    "cursor_ry": ("cursor_ry", "cur_ry"),
    "reached_l": ("reached_l",),
    "reached_r": ("reached_r",),
}

CUE_PHASES = frozenset({"cue", "track"})
