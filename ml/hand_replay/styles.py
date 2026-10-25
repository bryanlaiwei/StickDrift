"""Visual styles: how each rig role (skin, body, cap, ...) is filled, outlined and shaded."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from matplotlib.colors import to_rgb

PRESSED = {"press_cross": "#5b8def", "press_circle": "#e5484d", "press_square": "#e879c6", "press_triangle": "#3fbf7f"}


@dataclass(frozen=True)
class Style:
    name: str
    background: str
    ink: str
    muted: str
    grid: str
    fills: dict[str, str]
    edges: dict[str, str]
    trail_colors: tuple[str, str]
    hand_fills: tuple[str, str] | None = None
    hand_edges: tuple[str, str] | None = None
    fill_alpha: dict[str, float] = field(default_factory=dict)
    edge_alpha: dict[str, float] = field(default_factory=dict)
    edge_width: float = 0.7
    shading: float = 0.38
    highlight: float = 0.0
    nails: bool = False
    skeleton: str | None = None
    surface: str | None = None
    line: str | None = None

    def fill(self, role: str, hand: int | None) -> str:
        if role == "cuff":
            return self.trail_colors[hand]
        if role == "skin" and self.hand_fills and hand is not None:
            return self.hand_fills[hand]
        return PRESSED.get(role) or self.fills.get(role, self.fills["body"])

    def edge(self, role: str, hand: int | None) -> str:
        if role == "skin" and self.hand_edges and hand is not None:
            return self.hand_edges[hand]
        if role in self.edges:
            return self.edges[role]
        return tuple(np.array(to_rgb(self.fill(role, hand))) * 0.6)

    def alphas(self, role: str) -> tuple[float, float]:
        group = "skin" if role in ("skin", "sleeve", "cuff") else "controller"
        return (
            self.fill_alpha.get(role, self.fill_alpha.get(group, 1.0)),
            self.edge_alpha.get(role, self.edge_alpha.get(group, 1.0)),
        )


NATURAL = Style(
    name="natural",
    background="#f6f4ef",
    ink="#1b1f23",
    muted="#545b63",
    grid="#dad6cc",
    fills={
        "body": "#eef0f3", "touchpad": "#dfe2e7", "panel": "#1e2126", "button": "#3a3d44", "well": "#2a2d33",
        "cap": "#17191c", "trigger": "#3a3d44", "skin": "#e9b898", "sleeve": "#5b6472",
    },
    edges={"body": "#a7adb6", "touchpad": "#a7adb6", "skin": "#b88162", "sleeve": "#3c434e"},
    trail_colors=("#e02424", "#2a78d6"),
    edge_width=0.6,
    shading=0.35,
    highlight=0.3,
    nails=True,
    surface="#ffffff",
    line="#dad6cc",
)

XRAY = Style(
    name="xray",
    background="#0d1117",
    ink="#e6edf3",
    muted="#8b949e",
    grid="#30363d",
    fills={
        "body": "#16324a", "touchpad": "#1d4060", "panel": "#0f2233", "button": "#16324a", "well": "#0f2233",
        "cap": "#24567d", "trigger": "#16324a", "skin": "#7fd3ff", "sleeve": "#4a7a99",
    },
    edges={
        "body": "#6fb3e0", "touchpad": "#6fb3e0", "panel": "#6fb3e0", "button": "#6fb3e0", "well": "#6fb3e0",
        "cap": "#9fd2f2", "trigger": "#6fb3e0", "skin": "#a8e6ff", "sleeve": "#5d8fb0",
    },
    trail_colors=("#ff5c5c", "#4d94ec"),
    fill_alpha={"controller": 0.35, "skin": 0.14, "sleeve": 0.08},
    edge_alpha={"controller": 0.55, "skin": 0.9, "sleeve": 0.4},
    edge_width=0.9,
    shading=0.0,
    skeleton="#eaf7ff",
)

COLOUR_CODED = Style(
    name="colour_coded",
    background="#ffffff",
    ink="#1b1f23",
    muted="#545b63",
    grid="#dad6cc",
    fills={
        "body": "#2a2e35", "touchpad": "#353a42", "panel": "#1d2025", "button": "#4a4f58", "well": "#1a1c20",
        "cap": "#0f1012", "trigger": "#3a3f47", "skin": "#e9b898", "sleeve": "#d6d1c6",
    },
    edges={"body": "#121418", "sleeve": "#9a958a"},
    hand_fills=("#f6c3be", "#bcd5f3"),
    hand_edges=("#b3261e", "#1f5f8b"),
    trail_colors=("#e02424", "#2a78d6"),
    edge_width=0.9,
    shading=0.3,
    highlight=0.3,
)

STYLES = {style.name: style for style in (NATURAL, XRAY, COLOUR_CODED)}
