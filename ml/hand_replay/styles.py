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
