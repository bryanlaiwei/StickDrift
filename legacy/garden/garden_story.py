"""Illustrated presentation for the garden recorder.

Screens advance with X (or Space/Enter). Stick holds are for play, pause, and leaving.

All task positions and raw recording remain owned by garden.Game/Recorder.
Artwork is drawn locally with Pygame; no downloaded assets or network needed.
"""
import math
import os
import statistics
import time

import pygame

import garden as core
from read_data import parse

CREAM = (255, 246, 221)
INK = (43, 61, 58)
TEAL = (37, 103, 104)
GOLD = (236, 184, 85)
PINK = (213, 117, 123)
BLUE = (75, 132, 166)
RUST = (184, 91, 64)


class HoldGesture:
    """A neutral-to-tilt hold fires once, and must return to neutral to rearm."""
    def __init__(self, seconds=0.8):
        self.seconds = seconds
        self.reset()

    def reset(self):
        self.armed = False
        self.since = None
        self.progress = 0.0

    def update(self, neutral, active, now):
        if neutral:
            self.armed = True
        if not active or not self.armed:
            self.since = None
            self.progress = 0.0
            return False
        if self.since is None:
            self.since = now
        self.progress = min(1.0, (now - self.since) / self.seconds)
        if self.progress >= 1:
            self.armed = False
            self.since = None
            return True
        return False


class DemoReader:
    """Explicit synthetic input for development; never impersonates HID data."""
    def __init__(self):
        packet = bytearray(64)
        packet[0] = 1
        packet[1:5] = bytes([128] * 4)
        packet[8] = 8
        self.state = parse(packet)
        self.status = "Synthetic keyboard input"

    def start(self):
        pass


class StoryGame(core.Game):
    def __init__(self, args):
        self.synthetic = args.demo or bool(args.preview)
        self.reduced_motion = args.reduced_motion
        self.break_hold = HoldGesture(1.4)
        self.leave_hold = HoldGesture(1.4)
        self.in_card = False
        self.chapter = "welcome"
        self.toast = ""
        self.toast_until = 0
        self.effects = []
        self.seen_blooms = set()
        super().__init__(args)
        pygame.display.set_caption("Mabel's Moonflower Garden")
        self.title_font = pygame.font.SysFont("Georgia", 58, bold=True)
        self.heading_font = pygame.font.SysFont("Georgia", 38)
        self.body_font = pygame.font.SysFont("Segoe UI", 27)
        self.label_font = pygame.font.SysFont("Segoe UI", 21, bold=True)
        self.small_font = pygame.font.SysFont("Segoe UI", 19)
        self.backdrops = {name: self.landscape(name) for name in ("day", "dusk")}
        self.meta.update({
            "presentation": "moonflower-garden-v1", "protocol": core.PROTOCOL,
            "is_synthetic": self.synthetic, "reduced_motion": self.reduced_motion,
            "controller": "synthetic keyboard (60 Hz render loop)" if self.synthetic else self.meta["controller"],
            "navigation": "press X (or Space/Enter) to continue between screens; both sticks outward 1.4s to pause; hold either stick down 1.4s from pause to finish",
        })

    def make_reader(self):
        return DemoReader() if self.synthetic else super().make_reader()

    def anim_time(self):
        return 0.0 if self.reduced_motion else time.perf_counter()

    def _events(self):
        s, pressed, pause = super()._events()
        if self.synthetic:
            keys = pygame.key.get_pressed()
            for axis, positive, negative in (
                ("lx", pygame.K_d, pygame.K_a), ("ly", pygame.K_s, pygame.K_w),
                ("rx", pygame.K_RIGHT, pygame.K_LEFT), ("ry", pygame.K_DOWN, pygame.K_UP),
            ):
                s[axis] = 128 + 110 * (int(keys[positive]) - int(keys[negative]))
            self.rec.sample(time.perf_counter(), s)
        if s is not None:
            centers = self.centers or dict.fromkeys(("lx", "ly", "rx", "ry"), 127.5)
            lx, ly, rx, ry = core.cursor(s, centers)
            neutral = max(abs(lx), abs(ly), abs(rx), abs(ry)) < 0.25
            outward = lx < -0.8 and rx > 0.8 and abs(ly) < 0.35 and abs(ry) < 0.35
            pause |= self.break_hold.update(neutral, outward, time.perf_counter())
        return s, pressed, pause

    def tick(self):
        self.clock.tick(core.FPS)
        s, self.pressed, pause = self._events()
        if pause or (s is None and self.centers is not None):
            self.pause_screen(lost=s is None)
            s, self.pressed = self.reader.state, False
        if s is not None and self.centers is not None:
            self.cur = core.cursor(s, self.centers)
        for hand in ("left", "right"):
            dx, dy = self.disp[hand]
            cx, cy = self.cur_of(hand)
            self.disp[hand] = (dx + core.DISPLAY_SMOOTHING * (cx - dx), dy + core.DISPLAY_SMOOTHING * (cy - dy))

    def navigation(self, s, gesture, direction=-1):
        if s is None:
            gesture.reset()
            return False
        centers = self.centers or dict.fromkeys(("lx", "ly", "rx", "ry"), 127.5)
        lx, ly, rx, ry = core.cursor(s, centers)
        # Either stick can navigate independently, including one-hand play.
        neutral = abs(ly) < 0.25 and abs(ry) < 0.25
        active = direction * ly > 0.6 or direction * ry > 0.6
        return gesture.update(neutral, active, time.perf_counter())

    def wrapped(self, text, font, color, x, y, width, gap=8):
        words, line = text.split(), ""
        for word in words + [None]:
            test = (line + " " + word).strip() if word else ""
            if line and (word is None or font.size(test)[0] > width):
                self.screen.blit(font.render(line, True, color), (x, y))
                y += font.get_linesize() + gap
                line = word or ""
            else:
                line = test
        return y

    def panel(self, rect, color=CREAM, radius=24):
        r = pygame.Rect(rect)
        pygame.draw.rect(self.screen, (66, 78, 63), r.move(0, 5), border_radius=radius)
        pygame.draw.rect(self.screen, color, r, border_radius=radius)

    def landscape(self, mood):
        """Cache the detailed static scenery so the live loop stays light."""
        s = pygame.Surface((core.W, core.H))
        dusk = mood == "dusk"
        top, bottom = ((86, 110, 138), (239, 190, 149)) if dusk else ((163, 209, 210), (244, 229, 190))
        for y in range(core.H):
            u = min(1, y / 590)
            pygame.draw.line(s, tuple(int(a + (b - a) * u) for a, b in zip(top, bottom)), (0, y), (core.W, y))
        pygame.draw.circle(s, (255, 230, 167), (1060, 154), 53)
        pygame.draw.ellipse(s, (116, 153, 143), (-280, 248, 1080, 470))
        pygame.draw.ellipse(s, (139, 169, 143), (520, 276, 1100, 440))
        pygame.draw.ellipse(s, (96, 139, 112), (-200, 360, 1500, 600))
        pygame.draw.ellipse(s, (125, 160, 115), (350, 430, 1200, 430))
        pygame.draw.polygon(s, (210, 187, 142), [(560, 720), (755, 720), (900, 450), (870, 448)])
        self.cottage(s)
        for x in range(0, 1280, 48):
            if 820 < x < 1120:
                continue
            pygame.draw.rect(s, (213, 206, 157), (x, 445, 10, 70), border_radius=4)
        pygame.draw.line(s, (213, 206, 157), (0, 469), (820, 469), 8)
        pygame.draw.line(s, (213, 206, 157), (1120, 469), (1280, 469), 8)
        # Deterministic little leaves, grass and flowers, outside the target field.
        for i in range(95):
            x, y = (i * 193 + 31) % 1280, 570 + (i * 47) % 150
            pygame.draw.line(s, (91, 134, 92), (x, y), (x - 3, y - 9), 2)
            if i % 3 == 0:
                pygame.draw.circle(s, (242, 221, 168) if i % 2 else (217, 156, 156), (x, y - 11), 4)
        # Curved string of pennants carries the picnic theme across the scene.
        pts = [(x, int(105 + 45 * math.sin(math.pi * x / 1280))) for x in range(0, 1281, 16)]
        pygame.draw.lines(s, (95, 107, 91), False, pts, 2)
        for i, x in enumerate(range(28, 1280, 72)):
            y = int(105 + 45 * math.sin(math.pi * x / 1280))
            pygame.draw.polygon(s, (CREAM, PINK, GOLD, TEAL)[i % 4], [(x, y), (x + 26, y + 3), (x + 13, y + 30)])
        return s

    def cottage(self, surface):
        pygame.draw.rect(surface, (242, 219, 174), (915, 292, 206, 155), border_radius=8)
        pygame.draw.polygon(surface, (137, 80, 66), [(892, 300), (1018, 211), (1144, 300)])
        pygame.draw.rect(surface, TEAL, (989, 354, 50, 93), border_radius=24)

    def background(self, dusk=False):
        self.screen.blit(self.backdrops["dusk" if dusk else "day"], (0, 0))
        t = self.anim_time()
        for k in range(4):
            x = int((k * 330 + t * 4) % 1560) - 140
            y = 195 + (k % 2) * 45
            for dx, dy, r in ((0, 0, 20), (25, -9, 28), (52, 1, 19)):
                pygame.draw.circle(self.screen, (246, 240, 217), (x + dx, y + dy), r)
        if dusk:
            for i in range(18):
                x = int(45 + i * 69 + 9 * math.sin(t * 0.8 + i))
                y = int(300 + (i * 73) % 290 + 8 * math.cos(t + i))
                pygame.draw.circle(self.screen, (255, 224, 132), (x, y), 3)

    def bird(self, pos, hand, scale=1, flying=True):
        x, y = map(int, pos)
        col = BLUE if hand == "left" else RUST
        direction = 1 if hand == "left" else -1
        r = max(1, int(19 * scale))
        flap = int(5 * math.sin(self.anim_time() * 8)) if flying else 0
        pygame.draw.ellipse(self.screen, (83, 110, 83), (x - r, y + r + 8, r * 2, max(3, r // 3)))
        pygame.draw.polygon(self.screen, col, [(x - direction * r, y), (x - direction * r * 2, y - r), (x - direction * r * 2, y + r // 2)])
        pygame.draw.circle(self.screen, col, (x, y), r)
        pygame.draw.circle(self.screen, CREAM, (x + direction * r // 3, y + r // 3), int(r * 0.65))
        pygame.draw.ellipse(self.screen, (53, 88, 100) if hand == "left" else (125, 63, 55), (x - r, y - r // 3 + flap, r, r))
        pygame.draw.circle(self.screen, INK, (x + direction * r // 2, y - r // 3), max(2, int(3 * scale)))
        pygame.draw.circle(self.screen, CREAM, (x + direction * r // 2, y - r // 3 - 1), max(1, int(scale)))
        pygame.draw.polygon(self.screen, GOLD, [(x + direction * r, y - r // 5), (x + direction * int(r * 1.5), y), (x + direction * r, y + r // 4)])
        # Different accessories supplement color: Pip's single crest, Poppy's flower.
        if hand == "left":
            pygame.draw.line(self.screen, col, (x, y - r + 3), (x - 7, y - r - 7), max(2, int(4 * scale)))
        else:
            pygame.draw.circle(self.screen, GOLD, (x - r // 2, y - r + 1), max(3, int(6 * scale)))

    def mabel(self, x, y, scale=1):
        """Warm, grown-up storybook gardener; anchor points at her feet."""
        s = pygame.Surface((180, 245), pygame.SRCALPHA)
        pygame.draw.ellipse(s, (51, 72, 61, 70), (23, 217, 136, 23))
        pygame.draw.ellipse(s, (77, 74, 61), (44, 213, 39, 18))
        pygame.draw.ellipse(s, (77, 74, 61), (96, 213, 39, 18))
        pygame.draw.polygon(s, (64, 112, 108), [(54, 106), (125, 106), (147, 216), (31, 216)])
        pygame.draw.rect(s, (227, 204, 157), (64, 133, 52, 70), border_radius=12)
        pygame.draw.rect(s, (191, 169, 123), (75, 162, 30, 20), border_radius=4)
        pygame.draw.line(s, (64, 112, 108), (58, 123), (27, 164), 21)
        pygame.draw.line(s, (64, 112, 108), (121, 123), (151, 147), 21)
        pygame.draw.circle(s, (226, 177, 141), (25, 166), 12)
        pygame.draw.circle(s, (226, 177, 141), (153, 145), 12)
        pygame.draw.circle(s, (221, 217, 202), (89, 76), 43)
        pygame.draw.ellipse(s, (237, 191, 152), (54, 48, 71, 76))
        for xx in (74, 106):
            pygame.draw.circle(s, (92, 92, 80), (xx, 81), 14, 2)
            pygame.draw.circle(s, INK, (xx, 82), 3)
        pygame.draw.line(s, (92, 92, 80), (88, 81), (92, 81), 2)
        pygame.draw.arc(s, (141, 85, 73), (79, 94, 22, 13), math.pi, 2 * math.pi, 2)
        pygame.draw.ellipse(s, (224, 184, 112), (15, 32, 149, 31))
        pygame.draw.rect(s, (236, 201, 133), (51, 3, 77, 45), border_radius=19)
        pygame.draw.rect(s, (178, 105, 88), (52, 28, 75, 13))
        pygame.draw.circle(s, CREAM, (118, 29), 9)
        pygame.draw.circle(s, GOLD, (118, 29), 4)
        s = pygame.transform.smoothscale(s, (int(180 * scale), int(245 * scale)))
        self.screen.blit(s, (int(x - 90 * scale), int(y - 245 * scale)))

    def tree(self, cx, cy):
        pygame.draw.ellipse(self.screen, (87, 123, 88), (cx - 205, cy + 165, 410, 60))
        pygame.draw.polygon(self.screen, (132, 98, 73), [(cx - 20, cy - 20), (cx + 15, cy - 20), (cx + 40, cy + 205), (cx - 42, cy + 205)])
        for sx in (-1, 1):
            pygame.draw.line(self.screen, (132, 98, 73), (cx, cy + 90), (cx + sx * 115, cy - 26), 18)
        for dx, dy, r, c in [(-125, -25, 107, (59, 108, 78)), (120, -38, 112, (63, 117, 81)),
                             (0, -108, 121, (78, 130, 84)), (-90, 65, 116, (82, 137, 89)),
                             (91, 68, 115, (93, 146, 92)), (0, 8, 149, (106, 156, 99))]:
            pygame.draw.circle(self.screen, c, (cx + dx, cy + dy), r)
        for i in range(24):
            a = i * 2.4
            radius = 52 + (i * 37) % 137
            x, y = int(cx + math.cos(a) * radius), int(cy + math.sin(a) * radius)
            pygame.draw.ellipse(self.screen, (130, 173, 109), (x, y, 14, 6))

    def hud(self, title, hint):
        self.panel((24, 21, 1232, 82), radius=18)
        self.screen.blit(self.heading_font.render(title, True, INK), (48, 26))
        self.screen.blit(self.small_font.render("Hold both sticks outward for a break", True, TEAL), (50, 76))
        names = ("Orchard", "Meadow", "Cottage", "Moonflowers")
        for i, name in enumerate(names):
            x = 767 + 119 * i
            done = core.LEVELS[i] in self.done
            current = core.LEVELS[i] == self.chapter
            pygame.draw.circle(self.screen, TEAL if done else GOLD if current else (221, 216, 193), (x, 46), 10)
            if done:
                pygame.draw.lines(self.screen, CREAM, False, [(x - 5, 46), (x - 1, 50), (x + 6, 42)], 2)
            self.text(name, self.small_font, (x, 77), INK)
        self.panel((24, 636, 1232, 62), radius=18)
        self.text(hint, self.body_font, (640, 667), INK)
        if self.synthetic:
            self.screen.blit(self.small_font.render("DEMO INPUT  |  WASD + arrows", True, INK), (28, 607))
        if self.break_hold.progress > 0:
            self.panel((460, 564, 360, 52), radius=16)
            self.text("Opening the garden bench...", self.small_font, (640, 582), INK)
            pygame.draw.rect(self.screen, TEAL, (478, 601, int(324 * self.break_hold.progress), 5), border_radius=2)

    def scene(self, title, hint, kind):
        self.background()
        if kind == "tree":
            for _, (cx, cy) in self.plots():
                self.tree(cx, cy - 15)
            title = "Apples for the picnic"
            hint = "Fly to an apple. Release the stick to bring it to the basket."
        elif kind == "meadow":
            title = "Follow a friend through the garden"
            hint = "LEFT stick guides Pip" if "left" in self.layout else "RIGHT stick guides Poppy"
            if len(self.layout) == 2:
                title, hint = "Meet Pip & Poppy", "Move the LEFT stick for Pip and the RIGHT stick for Poppy."
            for _, (cx, cy) in self.plots():
                pygame.draw.ellipse(self.screen, (148, 177, 119), (cx - 260, cy - 150, 520, 350))
                for i in range(13):
                    a = i * 2.4
                    self.flower_at(int(cx + 223 * math.cos(a)), int(cy + 168 * math.sin(a)), 0.7)
        else:
            title, hint = "Wake the moonflowers", "Guide both watering cans along the little rain clouds."
            for _, (cx, cy) in self.plots():
                pygame.draw.ellipse(self.screen, (101, 127, 88), (cx - 247, cy - 86, 494, 220))
                pygame.draw.ellipse(self.screen, (158, 123, 86), (cx - 235, cy - 80, 470, 200))
                pygame.draw.ellipse(self.screen, (185, 150, 107), (cx - 230, cy - 80, 460, 182), 5)
        self.mabel(640 if len(self.layout) == 2 else 1100, 627, 0.64)
        self.hud(title, hint)
        for h, (cx, cy) in self.plots():
            name = "PIP  /  LEFT STICK" if h == "left" else "POPPY  /  RIGHT STICK"
            self.panel((cx - 110, 567, 220, 34), radius=12)
            self.text(name, self.small_font, (cx, 584), INK)
        self.draw_effects()

    def draw_helper(self, hand, style):
        x, y = self.px(hand, self.disp[hand])
        if style == "can":
            col = BLUE if hand == "left" else RUST
            pygame.draw.rect(self.screen, col, (x - 19, y - 6, 38, 32), border_radius=7)
            pygame.draw.line(self.screen, col, (x + 17, y + 6), (x + 37, y - 8), 7)
            pygame.draw.arc(self.screen, col, (x - 31, y - 6, 25, 27), 1, 5, 4)
            self.bird((x - 5, y - 25), hand, 0.85)
            for i in range(3):
                dy = int((self.anim_time() * 75 + i * 12) % 35)
                pygame.draw.line(self.screen, (199, 230, 229), (x + 34 + i * 4, y + dy), (x + 33 + i * 4, y + dy + 6), 2)
        else:
            self.bird((x, y), hand)

    def apple_at(self, x, y, scale=1.0):
        r = int(23 * scale)
        pygame.draw.circle(self.screen, (121, 62, 53), (int(x), int(y + 4 * scale)), r + 2)
        pygame.draw.circle(self.screen, (198, 75, 61), (int(x - r * 0.3), int(y)), r)
        pygame.draw.circle(self.screen, (218, 91, 67), (int(x + r * 0.3), int(y)), r)
        pygame.draw.ellipse(self.screen, (249, 187, 126), (int(x - r * 0.65), int(y - r * 0.65), max(3, r // 3), max(4, r // 2)))
        pygame.draw.line(self.screen, (92, 72, 47), (int(x), int(y - r)), (int(x + 3), int(y - r - 10 * scale)), max(2, int(4 * scale)))
        pygame.draw.ellipse(self.screen, (59, 110, 69), (int(x + 3), int(y - r - 10 * scale), max(4, r), max(3, r // 2)))

    def draw_basket(self, hand, count):
        x, y = self.px(hand, (0, 0))
        pygame.draw.arc(self.screen, (108, 76, 49), (x - 38, y - 32, 76, 65), 0, math.pi, 5)
        for i in range(min(count, 6)):
            self.apple_at(x - 23 + (i % 3) * 23, y - 4 - (i // 3) * 15, 0.42)
        pygame.draw.polygon(self.screen, (192, 143, 83), [(x - 40, y - 3), (x + 40, y - 3), (x + 31, y + 35), (x - 31, y + 35)])
        for dy in (4, 14, 24):
            pygame.draw.line(self.screen, (144, 104, 62), (x - 34, y + dy), (x + 34, y + dy), 2)

    def flower_at(self, x, y, scale):
        for k in range(6):
            a = k * math.pi / 3
            pygame.draw.circle(self.screen, (250, 226, 193), (int(x + 12 * scale * math.cos(a)), int(y + 12 * scale * math.sin(a))), max(2, int(9 * scale)))
        pygame.draw.circle(self.screen, GOLD, (int(x), int(y)), max(2, int(7 * scale)))

    def draw_flower(self, hand, p, bloomed):
        super().draw_flower(hand, p, bloomed)
        key = (hand, p)
        if bloomed and key not in self.seen_blooms:
            self.seen_blooms.add(key)
            self.effects.append((*self.px(hand, p), time.perf_counter()))

    def draw_effects(self):
        now = time.perf_counter()
        self.effects = [e for e in self.effects if now - e[2] < 1.1]
        if not self.reduced_motion:
            for x, y, born in self.effects:
                age = now - born
                for k in range(7):
                    a = k * math.tau / 7
                    pygame.draw.circle(self.screen, GOLD, (int(x + age * 50 * math.cos(a)), int(y + age * 50 * math.sin(a) - age * 22)), max(1, int(4 * (1 - age / 1.1))))
        if now < self.toast_until:
            self.panel((478, 111, 324, 43), radius=16)
            self.text(self.toast, self.label_font, (640, 132), INK)

    def play(self, name):
        super().play(name)
        if name == "pop":
            self.toast, self.toast_until = "A little sweetness to share", time.perf_counter() + 1.3
        if name == "bloom":
            self.toast, self.toast_until = "Another moonflower opens", time.perf_counter() + 1.3

    def picnic(self):
        pygame.draw.polygon(self.screen, (229, 201, 157), [(305, 520), (870, 520), (1015, 620), (226, 620)])
        for i in range(12):
            pygame.draw.line(self.screen, (180, 106, 98), (310 + i * 45, 521), (245 + i * 65, 617), 3)
        for y in range(538, 620, 21):
            pygame.draw.line(self.screen, (180, 106, 98), (300 - (y - 520), y), (870 + (y - 520), y), 3)
        pygame.draw.ellipse(self.screen, CREAM, (480, 530, 150, 52))
        pygame.draw.ellipse(self.screen, (190, 130, 70), (495, 535, 120, 38))
        for i in range(5):
            pygame.draw.line(self.screen, (239, 192, 117), (510 + i * 20, 540), (500 + i * 20, 565), 5)
        pygame.draw.ellipse(self.screen, TEAL, (690, 506, 67, 52))
        pygame.draw.polygon(self.screen, TEAL, [(748, 526), (782, 511), (761, 544)])
        pygame.draw.arc(self.screen, TEAL, (666, 512, 36, 40), 1, 5, 6)
        pygame.draw.ellipse(self.screen, GOLD, (706, 500, 35, 11))
        self.mabel(1120, 620, 1.05)
        self.bird((357, 548), "left", 1.35, False)
        self.bird((805, 570), "right", 1.35, False)

    def card_frame(self, rows):
        final = self.chapter == "picnic"
        self.background(dusk=final)
        if final:
            self.picnic()
            self.panel((155, 177, 800, 257))
            self.text(rows[0], self.heading_font, (555, 218), INK)
            y = 257
            for row in rows[1:]:
                y = self.wrapped(row, self.body_font, INK, 200, y, 710)
        else:
            self.mabel(283, 592, 1.55)
            self.bird((143, 535), "left", 1.4, False)
            self.bird((418, 550), "right", 1.4, False)
            self.panel((490, 199, 727, 364))
            self.screen.blit(self.label_font.render("A NOTE FROM MABEL", True, TEAL), (530, 224))
            y = self.wrapped(rows[0], self.heading_font, INK, 530, 270, 640, 4)
            for row in rows[1:]:
                y = self.wrapped(row, self.body_font, INK, 530, y + 14, 640, 3)
        self.text("Mabel's Moonflower Garden", self.title_font, (640, 65), INK if not final else CREAM)
        if self.synthetic:
            self.text("DEMO INPUT  |  WASD + arrow keys", self.small_font, (640, 709), INK)

    def continue_prompt(self, label="Press X to continue", progress=None):
        self.panel((340, 644, 600, 50), radius=16)
        self.text(label, self.label_font, (640, 669 if progress is None else 664), INK)
        if progress is not None:
            pygame.draw.rect(self.screen, (214, 215, 186), (365, 684, 550, 4), border_radius=2)
            pygame.draw.rect(self.screen, TEAL, (365, 684, int(550 * progress), 4), border_radius=2)

    def card(self, rows, min_s=0.6, auto_s=None, prompt="Continue"):
        self.in_card = True
        if rows[0] == "A lovely evening together":
            self.chapter = "picnic"
        self.rec.suspend()
        try:
            started = time.perf_counter()
            while True:
                self.tick()
                self.card_frame(rows)
                if not auto_s:
                    label = "Press X to finish" if self.chapter == "picnic" else "Press X to continue"
                    self.continue_prompt(label)
                pygame.display.flip()
                elapsed = time.perf_counter() - started
                if elapsed >= min_s and (self.pressed or (auto_s and elapsed >= auto_s)):
                    return
        finally:
            self.in_card = False
            self.rec.resume()
            self.break_hold.reset()

    def wait_for_controller(self):
        while self.reader.state is None:
            self.tick()
            self.card_frame(["Your garden is waiting", "Connect your controller with its USB cable.",
                             "Pip and Poppy will be ready when you are."])
            pygame.display.flip()

    def calibrate(self):
        self.card(["Come over for a garden picnic", "I'm Mabel. Would you help me get the garden ready?",
                   "Two little birds, a few apples, and some good company."])
        # Centre is the released stick, so a leftover tilt is never stored as rest.
        samples = []
        started = None
        self.in_card = True
        try:
            while True:
                self.tick()
                s = self.reader.state
                values = {k: s[k] for k in ("lx", "ly", "rx", "ry")} if s else None
                stable = values is not None and all(64 <= v <= 192 for v in values.values())
                if stable and samples:
                    stable = all(abs(values[k] - samples[0][k]) <= 10 for k in values)
                if not stable:
                    samples, started = [], None
                else:
                    started = started if started is not None else time.perf_counter()
                    samples.append(values)
                self.card_frame(["Let your birds settle", "Release both sticks for a moment.",
                                 "The garden is waking up..." if s else "Reconnect your controller to join us."])
                pygame.display.flip()
                if started is not None and time.perf_counter() - started >= 1.5:
                    break
        finally:
            self.in_card = False
        self.centers = {k: statistics.median(r[k] for r in samples) for k in samples[0]}
        self.rec.centers = self.centers
        self.rec.live.event("calibrated")
        self.meta["calibration"] = {
            "centers": self.centers, "samples_60hz": len(samples),
            "rest_sd": {k: round(statistics.pstdev(r[k] for r in samples), 3) for k in self.centers},
            "rest_range": {k: [min(r[k] for r in samples), max(r[k] for r in samples)] for k in self.centers},
        }
        self.write_session()

    def meet_helpers(self):
        self.layout = core.LAYOUT_BOTH
        seen = {"left": False, "right": False}
        self.rec.suspend()
        try:
            while not all(seen.values()):
                self.tick()
                self.scene("", "", "meadow")
                for hand in seen:
                    seen[hand] |= math.hypot(*self.cur_of(hand)) > 0.25
                    self.draw_helper(hand, "dot")
                pygame.display.flip()
            self.card(["Lovely. Let's take a wander.", "Pip wears blue. Poppy wears a little flower.",
                       "For a break, hold both sticks OUTWARD, away from each other."])
        finally:
            self.rec.resume()

    def pause_screen(self, lost):
        self.meta["disconnects" if lost else "pauses"] += 1
        self.rec.suspend()
        was_card, self.in_card = self.in_card, True
        self.leave_hold.reset()
        try:
            while True:
                self.clock.tick(core.FPS)
                s, pressed, _ = self._events()
                leave = self.navigation(s, self.leave_hold, 1)
                if s is None:
                    self.card_frame(["We'll keep your place", "Reconnect the controller with its cable.",
                                     "The garden can wait as long as you need."])
                else:
                    self.card_frame(["A moment on the garden bench", "Stay as long as you like.",
                                     "Hold either stick DOWN to save and finish for now."])
                    if self.leave_hold.progress:
                        self.continue_prompt("Finishing for now...", self.leave_hold.progress)
                    else:
                        self.continue_prompt("Press X to return to the garden")
                    if leave:
                        raise core.QuitGame()
                    if pressed:
                        return
                pygame.display.flip()
        finally:
            self.in_card = was_card
            self.rec.resume()
            self.break_hold.reset()

    def run_level(self, lv):
        self.chapter = lv
        self.seen_blooms.clear()
        self.effects.clear()
        super().run_level(lv)

    def preview(self, folder):
        """Render representative real game screens for visual QA, with no recording."""
        os.makedirs(folder, exist_ok=True)
        self.card_frame(["Come over for a garden picnic", "I'm Mabel. Would you help me get the garden ready?",
                         "Two little birds, a few apples, and some good company."])
        self.continue_prompt()
        pygame.image.save(self.screen, os.path.join(folder, "welcome.png"))
        for name, kind in (("apples", "tree"), ("butterfly_left", "meadow"), ("water", "soil")):
            self.chapter = name
            self.layout = {"left": core.LAYOUT_ONE} if kind == "meadow" else core.LAYOUT_BOTH
            self.scene("", "", kind)
            for hand in self.layout:
                self.disp[hand] = core.mir(hand, (-0.25, 0.1))
                if kind == "tree":
                    self.draw_basket(hand, 3)
                    self.apple_at(*self.px(hand, core.mir(hand, (0.25, -0.5))))
                elif kind == "meadow":
                    self.draw_butterfly(hand, (0.25, -0.25), True)
                else:
                    for i, fp in enumerate(core.FLOWERS):
                        self.draw_flower(hand, core.mir(hand, fp), i < 6)
                    self.draw_cloud(hand, core.mir(hand, (0.1, 0.0)))
                self.draw_helper(hand, "can" if kind == "soil" else "dot")
            pygame.image.save(self.screen, os.path.join(folder, name + ".png"))
        self.chapter = "picnic"
        self.card_frame(["A lovely evening together", "The kettle is on. Your friends are here.",
                         "Thank you for spending a little time in the garden."])
        self.continue_prompt("Press X to finish")
        pygame.image.save(self.screen, os.path.join(folder, "picnic.png"))
        pygame.quit()

