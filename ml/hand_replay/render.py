"""Draw posed frames from an over-the-shoulder camera and write them out as a GIF."""

from __future__ import annotations

import io
from collections.abc import Iterator
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.font_manager
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.collections import LineCollection
from matplotlib.colors import to_rgb, to_rgba
from matplotlib.lines import Line2D
from matplotlib.patches import Circle, FancyBboxPatch, Polygon
from PIL import Image

from ml.hand_replay.reconstruct import SHAKE_CAP_CM, Motion
from ml.hand_replay.rig import Chain, Poly, pose_frame
from ml.hand_replay.styles import NATURAL, Style

EYE = np.array([0.0, -44.0, 42.0])
LOOK_AT = np.array([0.0, -5.0, -2.0])
LIGHT = np.array([-0.4, -0.5, 1.0]) / np.linalg.norm([-0.4, -0.5, 1.0])
SCREEN_LIGHT = np.array([-0.6, 0.8])
VIEW_LIMITS = (-0.26, 0.26, -0.21, 0.19)
THUMB_TRAIL_S = 0.6
WRIST_TRAIL_S = 1.0
STICK_TRAIL_S = 1.0
STRIP_S = 4.0
SHAKE_AXIS_CM = 0.4
HAND_NAMES = ("left", "right")
NAIL = "#f4d6c8"
CARDS = {"scene": (0.012, 0.1, 0.6, 0.79), "sticks": (0.627, 0.53, 0.361, 0.36), "shake": (0.627, 0.1, 0.361, 0.4)}
CARD_TITLES = {"scene": "Reconstructed hands", "sticks": "Thumb sticks (recorded)", "shake": "Hand shake, 3-12 Hz (real size, cm)"}
AXES = {"scene": (0.02, 0.11, 0.585, 0.71), "sticks": (0.635, 0.545, 0.345, 0.27), "shake": (0.675, 0.19, 0.3, 0.23)}
FONTS = ("Atkinson Hyperlegible", "Segoe UI", "DejaVu Sans")
RENDERER_VERSION = "hands-natural-1"
SCENE_INCHES = 4.8  # figure width whose line widths match the scene card of the full replay
SCENE_SIZE = (400, 300)
GIF_BUDGET_BYTES = 1_500_000
GIF_COLOURS = (64, 48, 40)
GIF_MIN_SCALE = 0.6
GIF_BYTES_EXPONENT = 1.2  # measured: GIF bytes grow about with width**1.2 (the cost is in moving edges)

_installed = {font.name for font in matplotlib.font_manager.fontManager.ttflist}
matplotlib.rcParams["font.family"] = [name for name in FONTS if name in _installed] or ["DejaVu Sans"]


class Camera:
    def __init__(self, eye: np.ndarray, target: np.ndarray):
        forward = target - eye
        self.forward = forward / np.linalg.norm(forward)
        right = np.cross(self.forward, [0.0, 0.0, 1.0])
        self.right = right / np.linalg.norm(right)
        self.up = np.cross(self.right, self.forward)
        self.eye = eye

    def project(self, points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        rel = np.atleast_2d(points) - self.eye
        depth = rel @ self.forward
        xy = np.column_stack([rel @ self.right, rel @ self.up]) / depth[:, None]
        return xy, depth


def _shade(color, amount: float) -> tuple[float, float, float]:
    return tuple(np.clip(np.array(to_rgb(color)) * amount, 0, 1))


def _lighten(color, amount: float) -> tuple[float, float, float]:
    rgb = np.array(to_rgb(color))
    return tuple(rgb + (1 - rgb) * amount)


def _normal(points: np.ndarray) -> np.ndarray:
    nxt = np.roll(points, -1, axis=0)
    n = np.array([
        np.sum((points[:, 1] - nxt[:, 1]) * (points[:, 2] + nxt[:, 2])),
        np.sum((points[:, 2] - nxt[:, 2]) * (points[:, 0] + nxt[:, 0])),
        np.sum((points[:, 0] - nxt[:, 0]) * (points[:, 1] + nxt[:, 1])),
    ])
    return n / max(np.linalg.norm(n), 1e-9)


def tube_outline(xy: np.ndarray, radii: np.ndarray, cap_steps: int = 7) -> np.ndarray:
    """Closed 2D outline of a tapered tube through `xy` with round ends and no seams at the joints."""
    seg = np.diff(xy, axis=0)
    seg /= np.maximum(np.linalg.norm(seg, axis=1, keepdims=True), 1e-9)
    tangent = np.vstack([seg[:1], seg[:-1] + seg[1:], seg[-1:]])
    tangent /= np.maximum(np.linalg.norm(tangent, axis=1, keepdims=True), 1e-9)
    miter = np.ones(len(xy))
    if len(seg) > 1:
        miter[1:-1] = 1 / np.clip(np.sum(tangent[1:-1] * seg[1:], axis=1), 0.6, 1.0)
    normal = np.column_stack([-tangent[:, 1], tangent[:, 0]])
    offset = normal * (radii * miter)[:, None]
    left, right = xy + offset, xy - offset

    def arc(center, radius, start, stop):
        angles = np.linspace(start, stop, cap_steps)[1:-1]
        return center + radius * np.column_stack([np.cos(angles), np.sin(angles)])

    end_angle = np.arctan2(normal[-1, 1], normal[-1, 0])
    start_angle = np.arctan2(normal[0, 1], normal[0, 0])
    return np.vstack([
        left,
        arc(xy[-1], radii[-1], end_angle, end_angle - np.pi),
        right[::-1],
        arc(xy[0], radii[0], start_angle - np.pi, start_angle - 2 * np.pi),
    ])


class Scene:
    def __init__(self, ax, camera: Camera, style: Style, fps: int = 25):
        self.ax = ax
        self.camera = camera
        self.style = style
        self.artists: list = []
        self.thumb_trails: list[list[np.ndarray]] = [[], []]
        self.wrist_trails: list[list[np.ndarray]] = [[], []]
        self.thumb_keep = max(2, int(THUMB_TRAIL_S * fps))
        self.wrist_keep = max(2, int(WRIST_TRAIL_S * fps))
        ax.set_xlim(VIEW_LIMITS[0], VIEW_LIMITS[1])
        ax.set_ylim(VIEW_LIMITS[2], VIEW_LIMITS[3])
        ax.set_aspect("equal")
        ax.axis("off")

    def clear(self) -> None:
        for artist in self.artists:
            artist.remove()
        self.artists.clear()

    def _patch(self, xy, face, edge, lw: float, z: float):
        patch = Polygon(xy, closed=True, facecolor=face, edgecolor=edge, lw=lw, joinstyle="round", zorder=z)
        # add_artist, not add_patch: the view limits are fixed, and updating data limits per patch is most of the cost
        self.artists.append(self.ax.add_artist(patch))

    def draw(self, prims: list, bones: list) -> None:
        style = self.style
        queued = []
        for prim in prims:
            if isinstance(prim, Poly):
                center = prim.points.mean(axis=0)
                normal = _normal(prim.points)
                if prim.cull and normal @ (self.camera.eye - center) <= 0:
                    continue
                light = abs(normal @ LIGHT) if not prim.cull else max(0.0, normal @ LIGHT)
                xy, depth = self.camera.project(prim.points)
                queued.append((prim.layer, -depth.mean(), prim, xy, light))
            else:
                xy, depth = self.camera.project(prim.joints)
                queued.append((prim.layer, -depth.mean(), prim, (xy, prim.radii / depth), None))
        queued.sort(key=lambda item: (item[0], item[1]))

        for z, (_, _, prim, geometry, light) in enumerate(queued):
            fill = style.fill(prim.role, prim.hand)
            fill_a, edge_a = style.alphas(prim.role)
            edge = to_rgba(style.edge(prim.role, prim.hand), edge_a)
            if isinstance(prim, Poly):
                face = to_rgba(_shade(fill, 1 - style.shading + style.shading * light), fill_a)
                self._patch(geometry, face, edge, style.edge_width * 0.8, z)
                continue
            xy, radii = geometry
            face = to_rgba(_shade(fill, 1 - style.shading * 0.3), fill_a)
            self._patch(tube_outline(xy, radii), face, edge, style.edge_width, z)
            if style.highlight and prim.role in ("skin", "sleeve"):
                shift = SCREEN_LIGHT * radii.mean() * 0.35
                glow = to_rgba(_lighten(fill, 0.4), style.highlight)
                self._patch(tube_outline(xy + shift, radii * 0.42), glow, "none", 0, z + 0.2)
            if style.nails and prim.nail:
                tip = xy[-2] + 0.62 * (xy[-1] - xy[-2])
                self._patch(tube_outline(np.array([tip, xy[-1]]), radii[-2:] * 0.55), NAIL, _shade(NAIL, 0.75), 0.4, z + 0.3)

        if style.skeleton:
            top = len(queued) + 1
            for _, points in bones:
                xy, _ = self.camera.project(points)
                self.artists.append(self.ax.add_line(Line2D(xy[:, 0], xy[:, 1], color=style.skeleton, lw=1.3, alpha=0.85, zorder=top)))
                self.artists.append(self.ax.add_line(Line2D(xy[:, 0], xy[:, 1], ls="none", marker="o", ms=2.6, color=style.skeleton, zorder=top + 0.1)))

    def trail(self, history: list[np.ndarray], color: str, width: float) -> None:
        if len(history) < 2:
            return
        xy, _ = self.camera.project(np.array(history))
        segments = np.stack([xy[:-1], xy[1:]], axis=1)
        rgb = np.array(to_rgb(color))
        colors = np.column_stack([np.tile(rgb, (len(segments), 1)), np.linspace(0.05, 0.95, len(segments))])
        self.artists.append(self.ax.add_collection(
            LineCollection(segments, colors=colors, linewidths=width, zorder=10_000), autolim=False))

    def show(self, pose) -> None:
        """Draw one pose plus the thumb-tip and wrist trails built up over the frames before it."""
        self.clear()
        self.draw(pose.prims, pose.bones)
        for hand in (0, 1):
            self.thumb_trails[hand] = (self.thumb_trails[hand] + [pose.thumb_tips[hand]])[-self.thumb_keep:]
            self.wrist_trails[hand] = (self.wrist_trails[hand] + [pose.wrists[hand]])[-self.wrist_keep:]
            self.trail(self.thumb_trails[hand], self.style.trail_colors[hand], 1.6)
            self.trail(self.wrist_trails[hand], self.style.trail_colors[hand], 2.2)


def _card(fig, rect, style: Style, title: str) -> None:
    x, y, w, h = rect
    fig.patches.append(FancyBboxPatch(
        (x, y), w, h, boxstyle="round,pad=0,rounding_size=0.012", transform=fig.transFigure,
        facecolor=style.surface or style.background, edgecolor=style.line or style.grid, lw=1, zorder=-10,
    ))
    fig.text(x + 0.014, y + h - 0.052, title, fontsize=9.5, weight="bold", color=style.ink)


def _style_axis(ax, style: Style) -> None:
    ax.set_facecolor(style.surface or style.background)
    for spine in ax.spines.values():
        spine.set_color(style.grid)
    ax.tick_params(colors=style.muted, labelsize=7)
    ax.xaxis.label.set_color(style.muted)


def _stick_panel(ax, style: Style):
    ax.set_xlim(-2.4, 2.4)
    ax.set_ylim(-1.35, 1.35)
    ax.set_aspect("equal")
    ax.axis("off")
    artists = []
    for hand, cx in enumerate((-1.2, 1.2)):
        color = style.trail_colors[hand]
        ax.add_patch(Circle((cx, 0), 1.0, fill=False, color=style.muted, lw=1))
        ax.plot([cx - 1, cx + 1], [0, 0], color=style.grid, lw=0.6)
        ax.plot([cx, cx], [-1, 1], color=style.grid, lw=0.6)
        ax.text(cx, -1.3, HAND_NAMES[hand], ha="center", fontsize=8, color=color)
        (trail,) = ax.plot([], [], color=color, lw=1.2, alpha=0.6)
        (dot,) = ax.plot([], [], "o", color=color, ms=7, mec=style.ink, mew=0.6)
        (target,) = ax.plot([], [], "o", ms=11, mfc="none", mec=style.ink, mew=1.2)
        artists.append((cx, trail, dot, target))
    return artists


def _shake_panel(ax, style: Style):
    _style_axis(ax, style)
    ax.set_ylim(0, SHAKE_AXIS_CM)
    ax.set_xlabel("seconds", fontsize=8)
    ax.grid(color=style.grid, alpha=0.6)
    lines = [ax.plot([], [], color=style.trail_colors[hand], lw=1.4, label=HAND_NAMES[hand])[0] for hand in (0, 1)]
    legend = ax.legend(loc="upper left", fontsize=7, ncol=2, facecolor=style.surface or style.background, edgecolor=style.grid)
    for text in legend.get_texts():
        text.set_color(style.ink)
    return lines


def render_frames(motion: Motion, fps: int, style: Style = NATURAL, width_px: int = 840) -> Iterator[Image.Image]:
    """Yield each rendered frame; trails build up as frames advance."""
    fig = plt.figure(figsize=(width_px / 100, width_px / 100 * 0.56), dpi=100, facecolor=style.background)
    for name, rect in CARDS.items():
        _card(fig, rect, style, CARD_TITLES[name])
    scene = Scene(fig.add_axes(AXES["scene"]), Camera(EYE, LOOK_AT), style, fps)
    sticks = _stick_panel(fig.add_axes(AXES["sticks"]), style)
    strip_ax = fig.add_axes(AXES["shake"])
    shake_lines = _shake_panel(strip_ax, style)
    header = fig.text(0.01, 0.955, "", fontsize=11, weight="bold", color=style.ink)
    sub = fig.text(0.01, 0.915, "", fontsize=8.5, color=style.muted)
    footer = fig.text(0.01, 0.03, "", fontsize=8.5, color=style.muted)

    stick_keep = max(2, int(STICK_TRAIL_S * fps))
    strip_keep = int(STRIP_S * fps)
    try:
        for i in range(len(motion.time_s)):
            scene.show(pose_frame(motion, i))

            lo = max(0, i - stick_keep)
            for hand, (cx, trail, dot, target) in enumerate(sticks):
                xs = cx + motion.sticks[lo : i + 1, 2 * hand]
                ys = -motion.sticks[lo : i + 1, 2 * hand + 1]
                trail.set_data(xs, ys)
                dot.set_data([xs[-1]], [ys[-1]])
                tx, ty = motion.targets[i, 2 * hand], motion.targets[i, 2 * hand + 1]
                target.set_data(([cx + tx], [-ty]) if np.isfinite(tx) and np.isfinite(ty) else ([], []))

            lo = max(0, i - strip_keep)
            times = motion.time_s[lo : i + 1]
            for hand, line in enumerate(shake_lines):
                line.set_data(times, motion.shake_cm[lo : i + 1, hand])
            strip_ax.set_xlim(motion.time_s[i] - STRIP_S, motion.time_s[i] + 0.1)

            header.set_text(motion.label)
            sub.set_text(
                f"t = {motion.time_s[i]:5.1f} s   |   shake drawn x{motion.gain:g} (soft cap {SHAKE_CAP_CM:g} cm)   |   "
                f"dominant shake frequency {motion.peak_hz:.1f} Hz"
            )
            left, right = motion.shares[i]
            footer.set_text(
                f"Shake split by each thumb's own jitter:  left hand {left:.2f}   right hand {right:.2f}   "
                f"(1.00 = even).  Trails: thumb tips and wrists."
            )
            fig.canvas.draw()
            yield Image.fromarray(np.asarray(fig.canvas.buffer_rgba())[..., :3].copy())
    finally:
        plt.close(fig)


def render_gif(motion: Motion, out_path: Path, fps: int, style: Style = NATURAL) -> int:
    images = [
        frame.quantize(colors=96, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
        for frame in render_frames(motion, fps, style)
    ]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    images[0].save(out_path, save_all=True, append_images=images[1:], duration=int(round(1000 / fps)), loop=0, optimize=True)
    return len(images)


def render_scene_frames(motion: Motion, fps: int, style: Style = NATURAL,
                        size: tuple[int, int] = SCENE_SIZE) -> Iterator[Image.Image]:
    """Only the hands and controller with their trails, on the dashboard's surface colour: no cards or text.

    The figure is always SCENE_INCHES wide, so any `size` is the same picture with more or fewer pixels.
    """
    width, height = size
    fig = plt.figure(figsize=(SCENE_INCHES, SCENE_INCHES * height / width), dpi=width / SCENE_INCHES,
                     facecolor=style.surface or style.background)
    scene = Scene(fig.add_axes((0, 0, 1, 1)), Camera(EYE, LOOK_AT), style, fps)
    try:
        for i in range(len(motion.time_s)):
            scene.show(pose_frame(motion, i))
            fig.canvas.draw()
            yield Image.fromarray(np.asarray(fig.canvas.buffer_rgba())[..., :3].copy())
    finally:
        plt.close(fig)


def encode_gif(frames: list[Image.Image], fps: int, colours: int) -> bytes:
    """One palette for every frame, so pixels that did not change are written as transparent and compress away."""
    sample = frames[:: max(1, len(frames) // 8)]
    sheet = Image.new("RGB", (frames[0].width, frames[0].height * len(sample)))
    for k, frame in enumerate(sample):
        sheet.paste(frame, (0, k * frame.height))
    palette = sheet.quantize(colors=colours, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    indexed = [frame.quantize(palette=palette, dither=Image.Dither.NONE) for frame in frames]
    buffer = io.BytesIO()
    indexed[0].save(buffer, format="GIF", save_all=True, append_images=indexed[1:],
                    duration=int(round(1000 / fps)), loop=0, optimize=True)
    return buffer.getvalue()


def render_scene_gif(motion: Motion, out_path: Path, fps: int, style: Style = NATURAL,
                     size: tuple[int, int] = SCENE_SIZE, budget: int = GIF_BUDGET_BYTES) -> int:
    """Hands-only GIF. When it is over `budget` bytes even with fewer colours, it is drawn again, smaller."""
    scale, data, frames = 1.0, b"", []
    for _ in range(3):
        shown = (round(size[0] * scale), round(size[1] * scale))
        frames = list(render_scene_frames(motion, fps, style, shown))
        for colours in GIF_COLOURS:
            data = encode_gif(frames, fps, colours)
            if len(data) <= budget:
                break
        if len(data) <= budget or scale <= GIF_MIN_SCALE:
            break
        scale = max(GIF_MIN_SCALE, scale * 0.97 * (budget / len(data)) ** (1 / GIF_BYTES_EXPONENT))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)
    return len(frames)


def render_still(motion: Motion, out_path: Path, fps: int, frame: int, style: Style = NATURAL) -> None:
    """PNG of one frame, rendered after the frames before it so its trails are in place."""
    for i, image in enumerate(render_frames(motion, fps, style)):
        if i == frame:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            image.save(out_path)
            return
