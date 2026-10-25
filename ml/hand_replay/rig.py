"""3D DualSense and two arms that hold it, posed from one frame of Motion.

Geometry is authored for the right hand in the controller frame (cm) and mirrored for the left.
The controller is carried by the two grips: each hand's shake moves its grip, and the controller
pose is whatever rigid placement fits both grips, so motion visibly starts in the hands.

Primitives carry a role ("skin", "body", "cap", ...) instead of a colour; styles.py decides the look.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ml.hand_replay.reconstruct import GRIP_SPAN_CM

TOP_Z = 1.2
BOTTOM_Z = -1.8
STICK_BASES = np.array([[-3.1, -1.9, TOP_Z], [3.1, -1.9, TOP_Z]])
STICK_THROW = 0.9
CAP_HEIGHT = 1.1
FACE_CENTER = np.array([5.6, 1.3])
FACE_OFFSETS = {"triangle": (0, 1.0), "cross": (0, -1.0), "square": (-1.0, 0), "circle": (1.0, 0)}
ELBOWS = np.array([[-23.0, -30.0, -20.0], [23.0, -30.0, -20.0]])

RIGHT_HALF_OUTLINE = [
    (0, 4.0), (3.0, 4.3), (5.5, 4.4), (7.2, 3.6), (8.1, 1.5), (8.4, -1.5), (8.2, -4.5),
    (7.6, -7.0), (6.4, -8.3), (5.0, -8.0), (4.2, -6.2), (3.2, -4.6), (1.5, -4.2), (0, -4.2),
]

WRIST = np.array([9.6, -11.5, -2.2])
PALM_THICKNESS = 2.6
PALM = {
    "thumb": (7.6, -9.0, -0.4),
    "index": (9.0, -2.0, -0.3),
    "middle": (9.7, -3.9, -1.0),
    "ring": (9.7, -5.7, -1.5),
    "little": (9.2, -7.3, -1.9),
    "wrist_outer": (10.8, -11.0, -2.8),
    "wrist_inner": (8.2, -11.8, -1.6),
}
FOREARM_RADII = (1.8, 2.2)
SLEEVE_START = 0.67
SLEEVE_RADIUS = 2.6
CUFF_SPAN = (0.04, 0.12)
CUFF_THICKNESS = 0.12


@dataclass(frozen=True)
class Finger:
    name: str
    lengths: tuple[float, ...]
    pole: tuple[float, float, float]
    width: float
    curl_tip: tuple[float, float, float] | None = None


FINGERS = (
    Finger("thumb", (4.0, 3.4, 2.8), (0.5, -0.3, 1.0), 2.1),
    Finger("index", (4.0, 2.4, 1.9), (0.6, 0.0, 1.0), 1.7),
    Finger("middle", (3.8, 2.3, 1.8), (0.7, 0.0, -1.0), 1.8, (6.4, -3.4, -2.5)),
    Finger("ring", (3.6, 2.2, 1.7), (0.7, 0.0, -1.0), 1.7, (6.5, -5.4, -2.6)),
    Finger("little", (3.0, 1.9, 1.5), (0.7, 0.0, -1.0), 1.5, (6.3, -7.0, -2.4)),
)


@dataclass
class Poly:
    points: np.ndarray
    role: str
    layer: int
    cull: bool = True
    hand: int | None = None


@dataclass
class Chain:
    """A finger, forearm or stick shaft: one continuous tapered tube through its joints."""

    joints: np.ndarray
    radii: np.ndarray
    role: str
    layer: int
    hand: int | None = None
    nail: bool = False


@dataclass
class Pose:
    prims: list = field(default_factory=list)
    bones: list = field(default_factory=list)
    thumb_tips: np.ndarray = field(default_factory=lambda: np.zeros((2, 3)))
    wrists: np.ndarray = field(default_factory=lambda: np.zeros((2, 3)))


def rotation(pitch: float, roll: float, yaw: float) -> np.ndarray:
    cx, sx = np.cos(pitch), np.sin(pitch)
    cy, sy = np.cos(roll), np.sin(roll)
    cz, sz = np.cos(yaw), np.sin(yaw)
    rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return rz @ ry @ rx


def solve_chain(root: np.ndarray, target: np.ndarray, lengths, pole: np.ndarray, rounds: int = 12) -> np.ndarray:
    """FABRIK, seeded with an arc bulging toward `pole` so the bend stays on the natural side."""
    lengths = np.asarray(lengths, dtype=float)
    total = lengths.sum()
    reach = target - root
    dist = np.linalg.norm(reach)
    direction = reach / max(dist, 1e-9)
    if dist >= total * 0.999:
        return root + np.outer(np.concatenate([[0], np.cumsum(lengths)]), direction)
    side = pole - direction * (pole @ direction)
    side /= max(np.linalg.norm(side), 1e-9)
    frac = np.concatenate([[0], np.cumsum(lengths)]) / total
    bulge = np.sqrt(total**2 - dist**2) / 2
    joints = root + np.outer(frac, reach) + np.outer(np.sin(np.pi * frac), side * bulge)
    for _ in range(rounds):
        joints[-1] = target
        for i in range(len(lengths) - 1, -1, -1):
            step = joints[i] - joints[i + 1]
            joints[i] = joints[i + 1] + step / max(np.linalg.norm(step), 1e-9) * lengths[i]
        joints[0] = root
        for i in range(len(lengths)):
            step = joints[i + 1] - joints[i]
            joints[i + 1] = joints[i] + step / max(np.linalg.norm(step), 1e-9) * lengths[i]
    return joints


def _outline() -> np.ndarray:
    right = np.array(RIGHT_HALF_OUTLINE, dtype=float)
    left = right[-2:0:-1] * [-1, 1]
    ring = np.vstack([right, left])
    x, y = ring[:, 0], ring[:, 1]
    if 0.5 * np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y) < 0:
        ring = ring[::-1]
    return ring


OUTLINE = _outline()


def _disc(center, radius: float, n: int = 14) -> np.ndarray:
    angle = np.linspace(0, 2 * np.pi, n, endpoint=False)
    return np.column_stack([center[0] + radius * np.cos(angle), center[1] + radius * np.sin(angle), np.full(n, center[2])])


def _slab(outline: np.ndarray, thickness: float) -> list[np.ndarray]:
    """Closed prism around a roughly planar outline, faces wound outward."""
    centered = outline - outline.mean(axis=0)
    normal = np.sum(np.cross(centered, np.roll(centered, -1, axis=0)), axis=0)
    normal /= np.linalg.norm(normal)
    top, bottom = outline + normal * thickness / 2, outline - normal * thickness / 2
    faces = [top, bottom[::-1]]
    for i in range(len(outline)):
        j = (i + 1) % len(outline)
        faces.append(np.array([bottom[i], bottom[j], top[j], top[i]]))
    return faces


def _box(lo, hi) -> list[np.ndarray]:
    (x0, y0, z0), (x1, y1, z1) = np.minimum(lo, hi), np.maximum(lo, hi)
    c = np.array([[x, y, z] for z in (z0, z1) for y in (y0, y1) for x in (x0, x1)])
    faces = [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)]
    return [c[list(f)] for f in faces]


def _controller(frame, stick_xy: np.ndarray, triggers, bumpers, face) -> list:
    prims = []
    top = np.column_stack([OUTLINE, np.full(len(OUTLINE), TOP_Z)])
    bottom = np.column_stack([OUTLINE, np.full(len(OUTLINE), BOTTOM_Z)])
    prims.append(Poly(frame(top), "body", 1))
    prims.append(Poly(frame(bottom[::-1]), "body", 1))
    for i in range(len(OUTLINE)):
        j = (i + 1) % len(OUTLINE)
        prims.append(Poly(frame(np.array([bottom[i], bottom[j], top[j], top[i]])), "body", 1))

    lift = TOP_Z + 0.05
    pad = np.array([[-2.6, 0.4, lift], [2.6, 0.4, lift], [2.4, 3.9, lift], [-2.4, 3.9, lift]])
    prims.append(Poly(frame(pad), "touchpad", 2, cull=False))
    strip = np.array([[-2.2, -4.0, lift], [2.2, -4.0, lift], [2.0, 0.2, lift], [-2.0, 0.2, lift]])
    prims.append(Poly(frame(strip), "panel", 2, cull=False))
    for dx, dy in ((0, 0.75), (0, -0.75), (0.75, 0), (-0.75, 0)):
        prims.append(Poly(frame(_disc((-5.6 + dx, 1.3 + dy, lift), 0.42, 4)), "button", 2, cull=False))
    for (name, (dx, dy)), pressed in zip(FACE_OFFSETS.items(), face):
        role = f"press_{name}" if pressed else "button"
        prims.append(Poly(frame(_disc((FACE_CENTER[0] + dx, FACE_CENTER[1] + dy, lift), 0.45)), role, 2, cull=False))

    for hand in (0, 1):
        base = STICK_BASES[hand]
        prims.append(Poly(frame(_disc(base + [0, 0, 0.05], 1.35)), "well", 2, cull=False))
        cap = base + np.array([stick_xy[hand, 0] * STICK_THROW, -stick_xy[hand, 1] * STICK_THROW, CAP_HEIGHT])
        prims.append(Chain(frame(np.array([base, cap])), np.array([0.35, 0.35]), "cap", 2))
        prims.append(Poly(frame(_disc(cap, 0.95)), "cap", 3, cull=False))

        sign = 1 if hand else -1
        drop = 0.9 * float(triggers[hand])
        for face_pts in _box((sign * 4.6, 4.2, -0.7 - drop), (sign * 6.6, 5.6, 0.8 - drop)):
            prims.append(Poly(frame(face_pts), "trigger", 0))
        bump_z = 1.0 - (0.25 if bumpers[hand] else 0.0)
        for face_pts in _box((sign * 4.4, 4.3, bump_z), (sign * 6.9, 4.9, bump_z + 0.5)):
            prims.append(Poly(frame(face_pts), "trigger", 0))
    return prims


def _mirror(point, hand: int) -> np.ndarray:
    p = np.array(point, dtype=float)
    if hand == 0:
        p[0] = -p[0]
    return p


def _finger_target(finger: Finger, hand: int, stick_xy, triggers, bumpers, face) -> np.ndarray:
    if finger.name == "thumb":
        if hand == 1 and any(face):
            name = list(FACE_OFFSETS)[int(np.argmax(face))]
            dx, dy = FACE_OFFSETS[name]
            return np.array([FACE_CENTER[0] + dx, FACE_CENTER[1] + dy, TOP_Z + 0.9])
        base = STICK_BASES[hand]
        return base + np.array([stick_xy[hand, 0] * STICK_THROW, -stick_xy[hand, 1] * STICK_THROW - 0.2, CAP_HEIGHT + 0.75])
    if finger.name == "index":
        if bumpers[hand]:
            return _mirror((5.6, 4.7, 1.5), hand)
        return _mirror((5.6, 4.5, 0.9 - 1.0 * float(triggers[hand])), hand)
    return _mirror(finger.curl_tip, hand)


def _hand(frame, hand: int, stick_xy, triggers, bumpers, face, elbow: np.ndarray) -> tuple[list, list, np.ndarray, np.ndarray]:
    prims, bones = [], []
    palm_ids = ("thumb", "index", "middle", "ring", "little", "wrist_outer", "wrist_inner")
    palm_pts = np.array([_mirror(PALM[k], hand) for k in palm_ids])
    for face_pts in _slab(palm_pts, PALM_THICKNESS):
        prims.append(Poly(frame(face_pts), "skin", 4, hand=hand))

    wrist = frame(_mirror(WRIST, hand)[None])[0]
    stops = np.array([0.0, *CUFF_SPAN, SLEEVE_START])
    points = wrist + np.outer(stops, elbow - wrist)
    radii = np.interp(stops, [0.0, SLEEVE_START], FOREARM_RADII)
    for k, role in enumerate(("skin", "cuff", "skin")):
        prims.append(Chain(points[k : k + 2], radii[k : k + 2] + (CUFF_THICKNESS if role == "cuff" else 0), role, 4, hand))
    prims.append(Chain(np.array([points[-1], elbow]), np.array([SLEEVE_RADIUS, SLEEVE_RADIUS]), "sleeve", 4, hand))
    bones.append((hand, np.array([wrist, elbow])))

    thumb_tip = None
    for finger in FINGERS:
        root = _mirror(PALM[finger.name], hand)
        target = _finger_target(finger, hand, stick_xy, triggers, bumpers, face)
        joints = frame(solve_chain(root, target, finger.lengths, _mirror(finger.pole, hand)))
        radii = finger.width / 2 * (1 - 0.12 * np.arange(len(joints)))
        if finger.curl_tip is None:
            prims.append(Chain(joints, radii, "skin", 4, hand, nail=True))
        else:
            prims.append(Chain(joints[:2], radii[:2], "skin", 4, hand))
            prims.append(Chain(joints[1:], radii[1:], "skin", 0, hand))
        bones.append((hand, np.vstack([wrist, joints])))
        if finger.name == "thumb":
            thumb_tip = joints[-1]
    return prims, bones, thumb_tip, wrist


def pose_frame(motion, i: int) -> Pose:
    pitch, roll, yaw = motion.tilt[i]
    shift = motion.grip_shift[i]
    delta = shift[1] - shift[0]
    roll -= delta[2] / GRIP_SPAN_CM
    yaw += delta[1] / GRIP_SPAN_CM
    rot = rotation(pitch, roll, yaw)
    offset = shift.mean(axis=0)

    def frame(points: np.ndarray) -> np.ndarray:
        return points @ rot.T + offset

    stick_xy = motion.sticks[i].reshape(2, 2)
    pose = Pose()
    pose.prims += _controller(frame, stick_xy, motion.triggers[i], motion.bumpers[i], motion.face[i])
    for hand in (0, 1):
        prims, bones, tip, wrist = _hand(frame, hand, stick_xy, motion.triggers[i], motion.bumpers[i], motion.face[i], ELBOWS[hand])
        pose.prims += prims
        pose.bones += bones
        pose.thumb_tips[hand] = tip
        pose.wrists[hand] = wrist
    return pose
