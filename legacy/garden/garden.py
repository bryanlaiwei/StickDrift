"""
garden.py - Mabel's Moonflower Garden (garden-v3), played with both thumbsticks.

Run:  python garden.py --player P01 --session 1 --label normal [--level apples] [--mute] [--fullscreen]
Sticks: press X to continue between screens; hold both OUTWARD to rest; DOWN at the bench to finish.
Optional facilitator keys: Space/Enter = continue, P = break, Esc = quit. Files are saved.

Four garden chapters, with generous time for collecting apples:
  1 apples           both sticks at once, mirrored apples on two trees
  2 butterfly_left   follow a butterfly with the left stick
  3 butterfly_right  the same flight, mirrored, with the right stick
  4 water            both sticks at once, mirrored flower beds

The course is identical on every run; --label only tags the output folder.
Each level writes its own folder. Its CSV starts when the level starts and stops when it ends, and holds
every HID report (~500 Hz over USB): the Example PS5 Data columns (read_data.CSV_HEADER), then game context.

Stick coordinates: normalized to -1..1 around the centre measured at the start of the session,
y grows downward (same as the raw bytes and the screen). Right-stick targets are the left ones mirrored (x flipped).

Output (player, session and --label are added only when they are not the defaults):
  data/{date}_{time}_garden_all-levels/session.json
  data/{date}_{time}_garden_all-levels/level_{n}_{name}/controller_data.csv
  data/{date}_{time}_garden_all-levels/level_{n}_{name}/level.json
"""
import argparse
import array
import csv
import json
import math
import os
import re
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

import pygame

import live
from read_data import CSV_HEADER, Reader, parse, to_row

PROTOCOL = "garden-v3"
LEVELS = ("apples", "butterfly_left", "butterfly_right", "water")


def session_dirname(args, when=None):
    """Readable session folder. Defaults (anon, session 1, unlabeled) are left out."""
    safe = lambda v: re.sub(r"[^A-Za-z0-9_-]", "_", str(v))
    parts = [(when or time.strftime("%Y-%m-%d_%H-%M-%S")), "garden"]
    if str(args.player) != "anon":
        parts.append(safe(args.player))
    if args.session != 1:
        parts.append(f"session-{args.session}")
    if str(args.label) != "unlabeled":
        parts.append(safe(args.label))
    parts.append("all-levels" if args.level == "all" else safe(args.level))
    return "_".join(parts)

W, H = 1280, 720
FPS = 60
PLOT_R = 230
LAYOUT_BOTH = {"left": (320, 420), "right": (960, 420)}
LAYOUT_ONE = (640, 420)
DISPLAY_SMOOTHING = 0.35    # per-frame blend toward the stick, drawing only; logged values are unsmoothed

REST_R = 0.20               # "stick resting in the middle"
REST_HOLD = 0.3             # s resting before the next apple pair
REST_MAX = 2.5              # s before the next apple pair appears anyway
START_TOL = 0.20            # close enough to a start point
START_HOLD = 0.3
START_MAX = 3.0

# Apples, in left-stick space: (screen angle in degrees, distance), y down so 270 = up, 180 = outward (left).
NEAR, FAR = 0.40, 0.60      # NEAR - APPLE_R must stay above REST_R, or a pick and return happen at once
APPLES = [(270, FAR), (180, NEAR), (135, FAR), (315, NEAR), (90, NEAR), (225, FAR)]
APPLE_R = 0.18              # reach radius
APPLE_TIMEOUT = 12.0        # generous pacing; versioned separately from garden-v2
APPLE_ITI = 0.8             # minimum s between pairs

# Butterfly, left-stick space: r = R0 + RA*sin(LOBES*theta), theta = 2*pi*t/LAP. One lap.
FLY_R0, FLY_RA, FLY_LOBES, FLY_LAP = 0.40, 0.06, 2, 12.0
SPARKLE_R = 0.20

# Watering, left-stick space: Catmull-Rom through these points, equal arc length, constant speed.
WATER_CTRL = [(-0.55, 0.25), (-0.30, -0.10), (0.0, 0.20), (0.30, -0.10), (0.55, 0.20)]
WATER_SECS = 15.0
WATER_N = 241
FLOWER_R = 0.22

INK, SOFT_INK = (40, 56, 40), (110, 125, 110)
SKY_TOP, SKY_LOW, GRASS, HILL = (186, 222, 244), (236, 246, 236), (140, 196, 108), (122, 182, 96)
CANOPY, MEADOW, SOIL, BED = (120, 182, 96), (196, 230, 176), (226, 200, 160), (156, 112, 74)
CARD = (255, 252, 242)
HAND_COL = {"left": (40, 100, 210), "right": (220, 110, 30)}
APPLE, LEAF, BASKET, TRUNK = (210, 45, 45), (60, 140, 50), (160, 108, 56), (125, 88, 56)

EXTRA_HEADER = ["label", "level", "trial", "hand", "phase", "t_trial",
                "target_lx", "target_ly", "target_rx", "target_ry",
                "cursor_lx", "cursor_ly", "cursor_rx", "cursor_ry",
                "reached_l", "reached_r", "t_wall"]

CARDS = {
    "apples": ["An apple tart to share", "Pip and Poppy know where the sweetest apples grow.",
               "Guide each bird to an apple. Let go to bring it home."],
    "butterfly_left": ["An invitation on the breeze", "A butterfly will show Pip the way through the meadow.",
                       "Use the LEFT stick to fly alongside your guest."],
    "butterfly_right": ["One more friend to invite", "Poppy has spotted another visitor by the cottage.",
                        "Use the RIGHT stick to follow its gentle flight."],
    "water": ["A little rain, a little magic", "The moonflowers need a drink before our picnic.",
              "Move BOTH birds beneath the clouds to tend the garden."],
}
CHEERS = {
    "apples": "There is always room at Mabel's table.",
    "butterfly_left": "A new friend knows the way.",
    "butterfly_right": "The garden is lovely with company.",
    "water": "Time to put the kettle on.",
}


class QuitGame(Exception):
    pass


def catmull(p0, p1, p2, p3, t):
    return tuple(0.5 * (2 * b + (-a + c) * t + (2 * a - 5 * b + 4 * c - d) * t * t
                        + (-a + 3 * b - 3 * c + d) * t ** 3)
                 for a, b, c, d in zip(p0, p1, p2, p3))


def build_water_path():
    c = WATER_CTRL
    dense = []
    for i in range(len(c) - 1):
        p0, p1, p2, p3 = c[max(i - 1, 0)], c[i], c[i + 1], c[min(i + 2, len(c) - 1)]
        dense += [catmull(p0, p1, p2, p3, k / 50) for k in range(50)]
    dense.append(c[-1])
    cum = [0.0]
    for a, b in zip(dense, dense[1:]):
        cum.append(cum[-1] + math.dist(a, b))
    out, j = [], 0
    for k in range(WATER_N):
        target = cum[-1] * k / (WATER_N - 1)
        while j < len(cum) - 2 and cum[j + 1] < target:
            j += 1
        u = (target - cum[j]) / ((cum[j + 1] - cum[j]) or 1.0)
        a, b = dense[j], dense[j + 1]
        out.append((round(a[0] + (b[0] - a[0]) * u, 4), round(a[1] + (b[1] - a[1]) * u, 4)))
    return out


WATER_PATH = build_water_path()
FLOWERS = WATER_PATH[12::24]


def water_at(dt):
    f = min(max(dt / WATER_SECS, 0.0), 1.0) * (WATER_N - 1)
    i = min(int(f), WATER_N - 2)
    u = f - i
    a, b = WATER_PATH[i], WATER_PATH[i + 1]
    return a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u


def fly_at(dt):
    th = 2 * math.pi * min(max(dt, 0.0), FLY_LAP) / FLY_LAP
    r = FLY_R0 + FLY_RA * math.sin(FLY_LOBES * th)
    return r * math.cos(th), r * math.sin(th)


def polar(deg, dist):
    a = math.radians(deg)
    return round(dist * math.cos(a), 4), round(dist * math.sin(a), 4)


def mir(hand, p):
    """Left-stick-space point -> that hand's stick space (right is mirrored)."""
    return (0.0 - p[0], p[1]) if hand == "right" else (p[0], p[1])


def hands_of(hand):
    return ("left", "right") if hand == "both" else (hand,)


def targets(hand, p):
    """(left target, right target) for the hand(s) in use; p is in left-stick space."""
    hs = hands_of(hand)
    return (mir("left", p) if "left" in hs else None, mir("right", p) if "right" in hs else None)


def norm_axis(raw, c):
    d = raw - c
    v = d / (255 - c) if d > 0 else d / c
    return max(-1.0, min(1.0, v))


def cursor(s, centers):
    return tuple(norm_axis(s[k], centers[k]) for k in ("lx", "ly", "rx", "ry"))


class Ctx:
    """What the game is asking for right now. Replaced as a whole, never mutated."""
    __slots__ = ("trial", "hand", "phase", "trial_t0", "target", "reached")

    def __init__(self, trial, hand, phase, trial_t0, target, reached=(0, 0)):
        self.trial, self.hand, self.phase, self.trial_t0 = trial, hand, phase, trial_t0
        self.target = target    # f(seconds since trial_t0, or None) -> (left xy or None, right xy or None)
        self.reached = reached


class Recorder:
    """Writes the current level's CSV from the reader thread. Suspended time (cards, breaks) is not
    written and does not advance the active clock used for t, t_trial and moving targets."""

    def __init__(self, label):
        self.label = label
        self.centers = None
        self.ctx = None
        self.lock = threading.Lock()
        self.f = self.w = None
        self.level = None
        self.t0_wall = self.a0 = 0.0
        self.rows = 0
        self.depth = 0
        self.offset = 0.0
        self._t_suspend = 0.0
        self.live = live.from_env()

    def active(self, now=None):
        return (time.perf_counter() if now is None else now) - self.offset

    def suspend(self):
        with self.lock:
            if self.depth == 0:
                self._t_suspend = time.perf_counter()
                if self.w is not None:
                    self.live.event("paused")
            self.depth += 1

    def resume(self):
        with self.lock:
            self.depth -= 1
            if self.depth == 0:
                self.offset += time.perf_counter() - self._t_suspend
                if self.w is not None:
                    self.live.event("resumed")

    def open(self, folder, level):
        os.makedirs(folder, exist_ok=True)
        f = open(os.path.join(folder, "controller_data.csv"), "w", newline="", buffering=1 << 16)
        w = csv.writer(f, lineterminator="\n")
        w.writerow(CSV_HEADER + EXTRA_HEADER)
        with self.lock:
            self.f, self.w, self.level, self.ctx, self.rows = f, w, level, None, 0
            self.t0_wall = time.perf_counter()
            self.a0 = self.t0_wall - self.offset
        self.live.event("level_start", level=level)

    def close(self):
        """Close the level file; returns (rows, active seconds)."""
        with self.lock:
            f, self.f, self.w, self.ctx = self.f, None, None, None
            rows, dur = self.rows, self.active() - self.a0
        if f:
            f.close()
        return rows, round(dur, 3)

    def sample(self, now, s):
        ctx = self.ctx
        with self.lock:
            if self.w is None or ctx is None or self.depth or self.centers is None:
                return
            a = now - self.offset
            dt = None if ctx.trial_t0 is None else a - ctx.trial_t0
            lt, rt = ctx.target(dt)
            cur = cursor(s, self.centers)
            xy = lambda p: ["", ""] if p is None else [f"{p[0]:.4f}", f"{p[1]:.4f}"]
            self.w.writerow(
                to_row(a - self.a0, s)
                + [self.label, self.level, ctx.trial, ctx.hand, ctx.phase, "" if dt is None else f"{dt:.4f}"]
                + xy(lt) + xy(rt) + [f"{v:.4f}" for v in cur]
                + [ctx.reached[0], ctx.reached[1], f"{now - self.t0_wall:.4f}"])
            self.rows += 1
            self.live.sample(a - self.a0, ctx, (lt, rt), cur)


class GardenReader(Reader):
    """read_data.Reader, but hands every parsed report to a callback with a perf_counter timestamp."""

    def __init__(self, on_sample):
        super().__init__()
        self.on_sample = on_sample

    def run(self):
        while True:
            dev = self.open_device()
            if not dev:
                self.state = None
                self.status = "No controller found. Plug it in via USB."
                time.sleep(1)
                continue
            self.status = "Connected"
            last = time.perf_counter()
            try:
                while True:
                    data = dev.read(78, 100)
                    now = time.perf_counter()
                    if not data:
                        if now - last > 1.5:
                            break
                        continue
                    last = now
                    s = parse(data)
                    if not s:
                        continue
                    self.state = s
                    self.on_sample(now, s)
            except (OSError, ValueError):
                pass
            finally:
                dev.close()
                self.state = None


def make_sounds():
    """Soft tones generated in code; empty dict if audio is unavailable."""
    try:
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        freq, size, ch = pygame.mixer.get_init()
        if abs(size) != 16:
            return {}

        def tone(notes, dur, vol):
            buf = array.array("h")
            for f in notes:
                n = int(freq * dur)
                for i in range(n):
                    env = min(1.0, i / (0.01 * freq)) * (1 - i / n) ** 2
                    buf.extend([int(vol * env * math.sin(2 * math.pi * f * i / freq))] * ch)
            return pygame.mixer.Sound(buffer=buf.tobytes())

        return {"pop": tone([660, 880], 0.07, 7000), "bloom": tone([1175], 0.08, 3500),
                "chime": tone([523, 659, 784, 1047], 0.14, 7000)}
    except Exception:
        return {}


class Game:
    def __init__(self, args):
        self.args = args
        self.folder = os.path.join("data", session_dirname(args))
        os.makedirs(self.folder, exist_ok=True)
        self.levels = LEVELS if args.level == "all" else (args.level,)

        self.rec = Recorder(args.label)
        self.reader = self.make_reader()
        self.reader.start()

        pygame.mixer.pre_init(44100, -16, 1, 512)
        pygame.init()
        flags = pygame.FULLSCREEN | pygame.SCALED if args.fullscreen else 0
        self.screen = pygame.display.set_mode((W, H), flags)
        pygame.display.set_caption("Garden Rescue")
        self.clock = pygame.time.Clock()
        self.f_big = pygame.font.SysFont("georgia,arial", 54, bold=True)
        self.f_mid = pygame.font.SysFont("georgia,arial", 34)
        self.f_small = pygame.font.SysFont("arial", 26)
        self.sky = self.build_sky()
        self.sounds = {} if args.mute else make_sounds()

        self.centers = None
        self.cur = (0.0, 0.0, 0.0, 0.0)
        self.disp = {"left": (0.0, 0.0), "right": (0.0, 0.0)}
        self.layout = LAYOUT_BOTH
        self.pressed = False
        self.prev_cross = self.prev_opt = False
        self.done = []
        self.results = []

        self.meta = {
            "protocol": PROTOCOL, "game": "garden", "player": args.player, "session": args.session,
            "label": args.label, "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "controller": "Sony DualSense / DualSense Edge over HID (read_data.parse)",
            "screen": [W, H], "display_smoothing": DISPLAY_SMOOTHING,
            "coordinates": ("target_* and cursor_* are sticks normalized to -1..1 around calibration.centers "
                            "(positive side divided by 255-centre, negative side by centre), y grows downward. "
                            "Right-stick targets are the left-stick targets mirrored (x flipped)."),
            "columns": {
                "t": "active seconds since the level started (breaks are skipped)",
                "t_wall": "wall-clock seconds since the level started (includes breaks)",
                "t_trial": "active seconds since the apple pair appeared / the flight began; empty while waiting",
                "phase": "wait = resting in the middle or moving to the start, cue = apples showing, "
                         "return = both apples picked and coming back, track = following a moving target",
                "hand": "left, right or both: which stick(s) the level uses",
                "reached_l / reached_r": "1 once that hand has picked its apple in this pair",
                "cursor_*": "unsmoothed normalized stick positions (the drawn cursor is smoothed)",
            },
            "levels_requested": list(self.levels), "levels": [],
            "pauses": 0, "disconnects": 0,
        }

    # ------------------------------------------------------------ loop helpers
    def make_reader(self):
        return GardenReader(self.rec.sample)

    def now(self):
        return self.rec.active()

    def _events(self):
        cross_key = pause_key = False
        for e in pygame.event.get():
            if e.type == pygame.QUIT or (e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE):
                raise QuitGame()
            if e.type == pygame.KEYDOWN:
                cross_key |= e.key in (pygame.K_SPACE, pygame.K_RETURN)
                pause_key |= e.key == pygame.K_p
        s = self.reader.state
        cross, opt = bool(s and s["Cross"]), bool(s and s["Options"])
        pressed = cross_key or (cross and not self.prev_cross)
        pause = pause_key or (opt and not self.prev_opt)
        self.prev_cross, self.prev_opt = cross, opt
        return s, pressed, pause

    def tick(self):
        self.clock.tick(FPS)
        s, self.pressed, pause = self._events()
        if self.centers is not None and (pause or s is None):
            self.pause_screen(lost=s is None)
            s, self.pressed = self.reader.state, False
        if s is not None and self.centers is not None:
            self.cur = cursor(s, self.centers)
        for h in ("left", "right"):
            (dx, dy), (cx, cy) = self.disp[h], self.cur_of(h)
            self.disp[h] = (dx + DISPLAY_SMOOTHING * (cx - dx), dy + DISPLAY_SMOOTHING * (cy - dy))

    def pause_screen(self, lost):
        self.meta["disconnects" if lost else "pauses"] += 1
        self.rec.suspend()
        try:
            while True:
                self.clock.tick(FPS)
                s, pressed, pause = self._events()
                if s is not None and (pressed or pause):
                    return
                if s is None:
                    self.card_frame(["The controller came unplugged", "Plug it back in with the cable,",
                                     "then press X."])
                else:
                    self.card_frame(["Taking a break", "Rest as long as you like.", "",
                                     "Press X when you're ready."])
                pygame.display.flip()
        finally:
            self.rec.resume()

    def cur_of(self, hand):
        return self.cur[0:2] if hand == "left" else self.cur[2:4]

    def set_ctx(self, trial, hand, phase, trial_t0, target, reached=(0, 0)):
        self.rec.ctx = Ctx(trial, hand, phase, trial_t0, target, reached)

    def play(self, name):
        snd = self.sounds.get(name)
        if snd:
            snd.play()

    # ------------------------------------------------------------ drawing: scenery
    def build_sky(self):
        surf = pygame.Surface((W, H))
        for y in range(H):
            u = min(y / 560, 1.0)
            surf.fill(tuple(int(a + (b - a) * u) for a, b in zip(SKY_TOP, SKY_LOW)), (0, y, W, 1))
        pygame.draw.circle(surf, (255, 236, 160), (W - 90, 80), 62)
        pygame.draw.circle(surf, (255, 222, 120), (W - 90, 80), 46)
        pygame.draw.ellipse(surf, HILL, (-200, 560, 900, 320))
        pygame.draw.ellipse(surf, HILL, (600, 580, 900, 300))
        pygame.draw.rect(surf, GRASS, (0, 640, W, H - 640))
        return surf

    def text(self, s, font, center, color=INK):
        img = font.render(s, True, color)
        self.screen.blit(img, img.get_rect(center=center))

    def progress(self):
        for i, lv in enumerate(LEVELS):
            x, y = 44 + i * 52, 44
            if lv not in self.done:
                pygame.draw.circle(self.screen, (225, 235, 225), (x, y), 18)
                pygame.draw.circle(self.screen, (200, 212, 200), (x, y), 18, 2)
            elif lv == "apples":
                pygame.draw.circle(self.screen, APPLE, (x, y + 2), 15)
                pygame.draw.ellipse(self.screen, LEAF, (x, y - 20, 14, 9))
            elif lv.startswith("butterfly"):
                for sx in (-1, 1):
                    pygame.draw.ellipse(self.screen, (235, 150, 40), (x - 18 if sx < 0 else x, y - 14, 18, 16))
                    pygame.draw.ellipse(self.screen, (245, 195, 80), (x - 14 if sx < 0 else x, y, 14, 12))
                pygame.draw.line(self.screen, INK, (x, y - 12), (x, y + 12), 3)
            else:
                self.flower_at(x, y, 1.0)

    def card_frame(self, rows):
        self.screen.blit(self.sky, (0, 0))
        self.progress()
        box = pygame.Rect(0, 0, 900, 120 + 58 * len(rows))
        box.center = (W // 2, H // 2)
        pygame.draw.rect(self.screen, CARD, box, border_radius=28)
        pygame.draw.rect(self.screen, (214, 226, 200), box, 3, border_radius=28)
        y = box.top + 70
        for i, row in enumerate(rows):
            self.text(row, self.f_big if i == 0 else self.f_mid, (W // 2, y), INK)
            y += 66 if i == 0 else 52

    def scene(self, title, hint, kind):
        self.screen.blit(self.sky, (0, 0))
        self.progress()
        self.text(title, self.f_mid, (W // 2, 46))
        if hint:
            self.text(hint, self.f_small, (W // 2, 92), SOFT_INK)
        for h, (cx, cy) in self.plots():
            if kind == "tree":
                pygame.draw.rect(self.screen, TRUNK, (cx - 26, cy + 150, 52, 700))
            fill = {"tree": CANOPY, "meadow": MEADOW, "soil": SOIL}[kind]
            pygame.draw.circle(self.screen, fill, (cx, cy), PLOT_R + 18)
            for k in range(12):
                a = k * math.pi / 6
                pygame.draw.circle(self.screen, fill, (int(cx + (PLOT_R + 8) * math.cos(a)),
                                                       int(cy + (PLOT_R + 8) * math.sin(a))), 46)
            if kind == "tree":
                for k in range(9):
                    a, d = k * 2.4, PLOT_R * (0.35 + 0.07 * (k % 4))
                    pygame.draw.circle(self.screen, (138, 196, 110), (int(cx + d * math.cos(a)), int(cy + d * math.sin(a))), 34)
            if kind == "meadow":
                for k in range(10):
                    a = k * math.pi / 5 + 0.3
                    self.flower_at(int(cx + (PLOT_R + 28) * math.cos(a)), int(cy + (PLOT_R + 28) * math.sin(a)), 0.6)
            label = f"{h} hand"
            img = self.f_small.render(label, True, HAND_COL[h])
            r = img.get_rect(center=(cx, min(cy + PLOT_R + 52, H - 18)))
            pygame.draw.rect(self.screen, CARD, r.inflate(20, 8), border_radius=12)
            self.screen.blit(img, r)

    def plots(self):
        return list(self.layout.items())

    def px(self, hand, p):
        cx, cy = self.layout[hand]
        return int(cx + p[0] * PLOT_R), int(cy + p[1] * PLOT_R)

    # ------------------------------------------------------------ drawing: things
    def draw_helper(self, hand, style):
        p = self.px(hand, self.disp[hand])
        col = HAND_COL[hand]
        if style == "net":
            pygame.draw.line(self.screen, TRUNK, (p[0] + 26, p[1] + 26), (p[0] + 58, p[1] + 58), 7)
            pygame.draw.circle(self.screen, col, p, 36, 6)
        elif style == "can":
            pygame.draw.rect(self.screen, col, (p[0] - 20, p[1] - 14, 40, 30), border_radius=8)
            pygame.draw.line(self.screen, col, (p[0] + 16, p[1] - 4), (p[0] + 38, p[1] - 22), 6)
            pygame.draw.arc(self.screen, col, (p[0] - 30, p[1] - 22, 22, 28), 1.2, 4.6, 5)
        else:
            pygame.draw.circle(self.screen, col, p, 18)
            pygame.draw.circle(self.screen, (255, 255, 255), p, 18, 4)

    def apple_at(self, x, y, scale=1.0):
        r = int(26 * scale)
        pygame.draw.circle(self.screen, APPLE, (x, y), r)
        pygame.draw.circle(self.screen, (255, 150, 150), (x - r // 3, y - r // 3), max(2, r // 4))
        pygame.draw.line(self.screen, TRUNK, (x, y - r), (x + 2, y - r - 8), 3)
        pygame.draw.ellipse(self.screen, LEAF, (x + 2, y - r - 10, r, r // 2 + 2))

    def draw_basket(self, hand, count):
        x, y = self.px(hand, (0, 0))
        for i in range(min(count, 6)):
            self.apple_at(x - 20 + (i % 3) * 20, y - 6 - (i // 3) * 12, 0.45)
        pygame.draw.rect(self.screen, BASKET, (x - 34, y - 6, 68, 32), border_radius=10)
        pygame.draw.arc(self.screen, BASKET, (x - 28, y - 34, 56, 56), 0, math.pi, 5)

    def draw_butterfly(self, hand, p, sparkle):
        x, y = self.px(hand, p)
        if sparkle:
            t = time.perf_counter()
            for k in range(6):
                a = t * 3 + k * math.pi / 3
                pygame.draw.circle(self.screen, (255, 230, 90), (int(x + 40 * math.cos(a)), int(y + 40 * math.sin(a))), 5)
        flap = 0.55 + 0.45 * abs(math.sin(time.perf_counter() * 8))
        wx = int(28 * flap)
        for sx in (-1, 1):
            pygame.draw.ellipse(self.screen, (235, 140, 40), (x if sx > 0 else x - wx, y - 26, wx, 28))
            pygame.draw.ellipse(self.screen, (245, 195, 80), (x if sx > 0 else x - int(wx * 0.8), y, int(wx * 0.8), 20))
        pygame.draw.line(self.screen, INK, (x, y - 22), (x, y + 18), 4)

    def draw_cloud(self, hand, p):
        x, y = self.px(hand, p)
        y -= 46
        t = time.perf_counter()
        for i in range(4):
            k = (t * 2 + i / 4) % 1.0
            pygame.draw.line(self.screen, (90, 150, 230), (x - 18 + i * 12, y + 16 + int(k * 26)),
                             (x - 20 + i * 12, y + 24 + int(k * 26)), 3)
        for dx, dy, r in ((-18, 0, 16), (0, -10, 21), (19, 0, 16)):
            pygame.draw.circle(self.screen, (255, 255, 255), (x + dx, y + dy), r)

    def flower_at(self, x, y, scale):
        for k in range(5):
            a = k * 2 * math.pi / 5
            pygame.draw.circle(self.screen, (232, 96, 156),
                               (int(x + 11 * scale * math.cos(a)), int(y + 11 * scale * math.sin(a))), int(8 * scale))
        pygame.draw.circle(self.screen, (250, 210, 60), (x, y), int(7 * scale))

    def draw_flower(self, hand, p, bloomed):
        x, y = self.px(hand, p)
        if bloomed:
            self.flower_at(x, y, 1.1)
        else:
            pygame.draw.line(self.screen, LEAF, (x, y + 8), (x, y - 4), 3)
            pygame.draw.circle(self.screen, LEAF, (x, y - 6), 7)

    # ------------------------------------------------------------ screens
    def card(self, rows, min_s=0.6, auto_s=None, prompt="Press X when you're ready"):
        self.rec.suspend()
        try:
            t = time.perf_counter()
            while True:
                self.tick()
                waited = time.perf_counter() - t
                self.card_frame(rows + ([] if auto_s else ["", prompt]))
                pygame.display.flip()
                if (self.pressed and waited >= min_s) or (auto_s and waited >= auto_s):
                    return
        finally:
            self.rec.resume()

    def wait_for_controller(self):
        while self.reader.state is None:
            self.tick()
            self.card_frame(["Garden Rescue", "Connect the controller with its cable to begin."])
            pygame.display.flip()

    def calibrate(self):
        self.card(["Welcome to the garden", "The garden needs a little help today.",
                   "Hold the controller however is comfortable.",
                   "Press Options any time to take a break."])
        samples, t_end = [], time.perf_counter() + 2.0
        while time.perf_counter() < t_end:
            self.tick()
            s = self.reader.state
            if s is not None and time.perf_counter() > t_end - 1.5:
                samples.append({k: s[k] for k in ("lx", "ly", "rx", "ry")})
            self.card_frame(["Rest your thumbs", "while the garden wakes up..."])
            pygame.display.flip()
        if not samples:
            samples = [{"lx": 127.5, "ly": 127.5, "rx": 127.5, "ry": 127.5}]
        self.centers = {k: statistics.median(r[k] for r in samples) for k in ("lx", "ly", "rx", "ry")}
        self.meta["calibration"] = {
            "centers": self.centers, "samples_60hz": len(samples),
            "rest_sd": {k: round(statistics.pstdev(r[k] for r in samples), 3) for k in self.centers},
            "rest_range": {k: [min(r[k] for r in samples), max(r[k] for r in samples)] for k in self.centers},
        }
        self.rec.centers = self.centers
        self.rec.live.event("calibrated")
        self.write_session()

    def meet_helpers(self):
        self.layout = LAYOUT_BOTH
        self.rec.suspend()
        try:
            while True:
                self.tick()
                self.scene("Say hello to your helpers", "Wiggle both sticks. Press X when you're ready.", "meadow")
                for h in ("left", "right"):
                    self.draw_helper(h, "dot")
                pygame.display.flip()
                if self.pressed:
                    return
        finally:
            self.rec.resume()

    def go_to_start(self, hand, start, draw):
        self.set_ctx(1, hand, "wait", None, lambda dt, v=targets(hand, start): v)
        t_start, t_in = self.now(), None
        while True:
            self.tick()
            now = self.now()
            ok = all(math.dist(self.cur_of(h), mir(h, start)) < START_TOL for h in hands_of(hand))
            t_in = (t_in if t_in is not None else now) if ok else None
            draw()
            pygame.display.flip()
            if (t_in is not None and now - t_in >= START_HOLD) or now - t_start >= START_MAX:
                return

    # ------------------------------------------------------------ level 1: apples (both sticks)
    def level_apples(self):
        self.layout = LAYOUT_BOTH
        hs = ("left", "right")
        center = targets("both", (0.0, 0.0))
        baskets = {"left": 0, "right": 0}

        def draw(apples, carrying, hint=""):
            self.scene("Apple picking", hint, "tree")
            for h in hs:
                self.draw_basket(h, baskets[h])
                if apples.get(h):
                    self.apple_at(*self.px(h, apples[h]))
                self.draw_helper(h, "dot")
                if carrying.get(h):
                    x, y = self.px(h, self.disp[h])
                    self.apple_at(x, y - 26, 0.7)
            pygame.display.flip()

        for trial, (deg, dist) in enumerate(APPLES, 1):
            apple = polar(deg, dist)
            goal = {"left": mir("left", apple), "right": mir("right", apple)}

            self.set_ctx(trial, "both", "wait", None, lambda dt: center)
            t_start, t_in = self.now(), None
            while True:
                self.tick()
                now = self.now()
                resting = all(math.hypot(*self.cur_of(h)) < REST_R for h in hs)
                t_in = (t_in if t_in is not None else now) if resting else None
                draw({}, {}, "Let both sticks rest in the middle" if t_in is None and now - t_start > 1.5 else "")
                if now - t_start >= APPLE_ITI and (
                        (t_in is not None and now - t_in >= REST_HOLD) or now - t_start >= REST_MAX):
                    break

            t0 = self.now()
            reached = {"left": None, "right": None}
            banked = {"left": False, "right": False}

            def update_ctx():
                tg = tuple(center[i] if reached[h] is not None else goal[h] for i, h in enumerate(hs))
                phase = "return" if all(v is not None for v in reached.values()) else "cue"
                flags = (int(reached["left"] is not None), int(reached["right"] is not None))
                self.set_ctx(trial, "both", phase, t0, lambda dt, v=tg: v, flags)

            update_ctx()
            while True:
                self.tick()
                now = self.now()
                for h in hs:
                    c = self.cur_of(h)
                    if reached[h] is None and math.dist(c, goal[h]) < APPLE_R:
                        reached[h] = now - t0
                        self.play("pop")
                        update_ctx()
                    if reached[h] is not None and not banked[h] and math.hypot(*c) < REST_R:
                        banked[h] = True
                        baskets[h] += 1
                if all(banked.values()) or now - t0 >= APPLE_TIMEOUT:
                    break
                draw({h: goal[h] for h in hs if reached[h] is None},
                     {h: reached[h] is not None and not banked[h] for h in hs})
            self.results.append({
                "trial": trial, "target_left": goal["left"], "target_right": goal["right"],
                "reached_l": reached["left"] is not None, "t_reach_l": None if reached["left"] is None else round(reached["left"], 4),
                "reached_r": reached["right"] is not None, "t_reach_r": None if reached["right"] is None else round(reached["right"], 4),
                "t_end": round(self.now() - t0, 4)})

    # ------------------------------------------------------------ levels 2-3: butterfly (one stick)
    def level_butterfly(self, hand):
        self.layout = {hand: LAYOUT_ONE}
        start = fly_at(0.0)
        path = [mir(hand, fly_at(k * FLY_LAP / 120)) for k in range(121)]

        def draw(p, hint="", sparkle=False):
            self.scene("Follow the butterfly", hint, "meadow")
            pts = [self.px(hand, q) for q in path]
            for q in pts[::4]:
                pygame.draw.circle(self.screen, (170, 205, 150), q, 3)
            self.draw_helper(hand, "net")
            self.draw_butterfly(hand, mir(hand, p), sparkle)
            pygame.display.flip()

        self.go_to_start(hand, start, lambda: draw(start, "Bring your net to the butterfly"))
        t0 = self.now()
        self.set_ctx(1, hand, "track", t0, lambda dt: targets(hand, fly_at(dt or 0.0)))
        frames = near = 0
        while True:
            self.tick()
            dt = self.now() - t0
            if dt >= FLY_LAP:
                break
            p = fly_at(dt)
            close = math.dist(self.cur_of(hand), mir(hand, p)) < SPARKLE_R
            frames, near = frames + 1, near + close
            draw(p, sparkle=close)
        self.results.append({"trial": 1, "hand": hand, "frames_60hz": frames, "frames_within_sparkle_radius": near})

    # ------------------------------------------------------------ level 4: water (both sticks)
    def level_water(self):
        self.layout = LAYOUT_BOTH
        hs = ("left", "right")
        blooms = {h: set() for h in hs}
        start = WATER_PATH[0]

        def draw(p, hint=""):
            self.scene("Watering the flowers", hint, "soil")
            for h in hs:
                for q in WATER_PATH[::2]:
                    pygame.draw.circle(self.screen, BED, self.px(h, mir(h, q)), 14)
                for i, fp in enumerate(FLOWERS):
                    self.draw_flower(h, mir(h, fp), i in blooms[h])
                self.draw_cloud(h, mir(h, p))
                self.draw_helper(h, "can")
            pygame.display.flip()

        self.go_to_start("both", start, lambda: draw(start, "Bring each watering can under its cloud"))
        t0 = self.now()
        self.set_ctx(1, "both", "track", t0, lambda dt: targets("both", water_at(dt or 0.0)))
        while True:
            self.tick()
            dt = self.now() - t0
            if dt >= WATER_SECS:
                break
            for h in hs:
                c = self.cur_of(h)
                new = {i for i, fp in enumerate(FLOWERS) if math.dist(c, mir(h, fp)) < FLOWER_R} - blooms[h]
                if new:
                    blooms[h] |= new
                    self.play("bloom")
            draw(water_at(dt))
        self.results.append({"trial": 1, "hand": "both", "flowers": len(FLOWERS),
                             "bloomed_l": sorted(blooms["left"]), "bloomed_r": sorted(blooms["right"])})

    # ------------------------------------------------------------ files
    def level_params(self, lv):
        common = {"rest_radius": REST_R, "start_tolerance": START_TOL, "start_hold_s": START_HOLD,
                  "start_max_s": START_MAX}
        if lv == "apples":
            return {**common, "hand": "both", "rest_hold_s": REST_HOLD, "rest_max_s": REST_MAX,
                    "min_gap_s": APPLE_ITI, "reach_radius": APPLE_R, "timeout_s": APPLE_TIMEOUT,
                    "apples_left_deg_dist": APPLES,
                    "apples_left_xy": [mir("left", polar(a, d)) for a, d in APPLES],
                    "apples_right_xy": [mir("right", polar(a, d)) for a, d in APPLES]}
        if lv.startswith("butterfly"):
            hand = lv.split("_")[1]
            return {**common, "hand": hand, "mirrored": hand == "right",
                    "path": "r = R0 + RA*sin(LOBES*theta), theta = 2*pi*t/LAP_S, x = r cos(theta), y = r sin(theta)"
                            + ("; then x -> -x" if hand == "right" else ""),
                    "R0": FLY_R0, "RA": FLY_RA, "LOBES": FLY_LOBES, "LAP_S": FLY_LAP, "laps": 1,
                    "sparkle_radius": SPARKLE_R}
        return {**common, "hand": "both", "duration_s": WATER_SECS, "control_points_left": WATER_CTRL,
                "path_left": WATER_PATH, "path_right": [mir("right", q) for q in WATER_PATH],
                "flowers_left": FLOWERS, "flowers_right": [mir("right", q) for q in FLOWERS],
                "flower_radius": FLOWER_R}

    def write_session(self):
        with open(os.path.join(self.folder, "session.json"), "w") as f:
            json.dump(self.meta, f, indent=1)

    def run_level(self, lv):
        num = LEVELS.index(lv) + 1
        folder = os.path.join(self.folder, f"level_{num}_{lv}")
        self.card(CARDS[lv])
        info = {"protocol": PROTOCOL, "level": lv, "number": num, "label": self.args.label,
                "player": self.args.player, "session": self.args.session,
                "params": self.level_params(lv), "completed": False}
        self.results = []
        self.rec.open(folder, lv)
        try:
            if lv.startswith("butterfly"):
                self.level_butterfly(lv.split("_")[1])
            else:
                getattr(self, f"level_{lv}")()
            info["completed"] = True
        finally:
            info["rows"], info["duration_s"] = self.rec.close()
            info["results"] = self.results
            with open(os.path.join(folder, "level.json"), "w") as f:
                json.dump(info, f, indent=1)
            self.meta["levels"].append({"level": lv, "folder": os.path.basename(folder),
                                        "completed": info["completed"], "rows": info["rows"],
                                        "duration_s": info["duration_s"]})
            self.write_session()
            self.rec.live.event("level_end", level=lv, completed=info["completed"],
                                duration_s=info["duration_s"], results=self.results)
        self.done.append(lv)
        self.play("chime")
        self.card([CHEERS[lv]], auto_s=1.8)

    def run(self):
        completed = False
        self.rec.live.event("session_start", folder=os.path.abspath(self.folder),
                            synthetic=bool(self.meta.get("is_synthetic")), levels=list(self.levels))
        try:
            self.wait_for_controller()
            self.calibrate()
            self.meet_helpers()
            for lv in self.levels:
                self.run_level(lv)
            self.card(["A lovely evening together", "The kettle is on. Your friends are here.",
                       "Thank you for spending a little time in the garden."], prompt="Finish")
            completed = True
        except (QuitGame, KeyboardInterrupt):
            print("Stopped early.")
        finally:
            self.rec.close()
            self.meta["completed"] = completed
            self.meta["ended"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            self.write_session()
            self.rec.live.event("session_end", completed=completed, folder=os.path.abspath(self.folder))
            self.rec.live.close()
            pygame.quit()
            print(f"Saved to {self.folder}")
            for lv in self.meta["levels"]:
                print(f"  {lv['folder']}/controller_data.csv  ({lv['rows']} rows, {lv['duration_s']} s)")


def main():
    p = argparse.ArgumentParser(description="Mabel's Moonflower Garden (garden-v3)")
    p.add_argument("--player", default="anon", help="player ID (default anon)")
    p.add_argument("--session", type=int, default=1, help="session number (default 1)")
    p.add_argument("--label", default="unlabeled",
                   help="tag for this run, e.g. normal, small_slow, shaky, weak_left (does not change the game)")
    p.add_argument("--level", choices=("all",) + LEVELS, default="all", help="play one level only")
    p.add_argument("--mute", action="store_true", help="no sounds")
    p.add_argument("--fullscreen", action="store_true")
    p.add_argument("--demo", action="store_true", help="synthetic keyboard input: WASD and arrow keys")
    p.add_argument("--reduced-motion", action="store_true", help="still scenery and fewer visual effects")
    p.add_argument("--preview", metavar="DIRECTORY", help="save art previews without playing or recording")
    p.add_argument("--no-tiger-sync", action="store_true", help="keep this recording local only")
    from garden_diorama import DioramaGame
    args = p.parse_args()
    game = DioramaGame(args)
    if args.preview:
        game.preview(args.preview)
    else:
        try:
            game.run()
        finally:
            # Import the files the game actually wrote, after its CSV writers
            # close. Failed imports leave those files intact for a later retry.
            if not args.no_tiger_sync:
                backend = Path(__file__).resolve().parents[2] / "backend"
                configured = (os.environ.get("DATABASE_URL") or
                              os.environ.get("TIMESCALE_SERVICE_URL") or
                              (backend / ".env").is_file())
                if configured:
                    candidates = (backend / ".venv" / "Scripts" / "python.exe",
                                  backend / ".venv" / "bin" / "python")
                    python = next((str(path) for path in candidates if path.is_file()), sys.executable)
                    try:
                        result = subprocess.run(
                            [python, "-m", "scripts.import_garden", str(Path(game.folder).resolve())],
                            cwd=backend, check=False,
                        )
                        if result.returncode:
                            print("TigerData sync failed; CSV/JSON is saved. Retry with the import command.")
                    except OSError as error:
                        print(f"TigerData sync could not start: {error}. CSV/JSON is saved.")
                else:
                    print("TigerData is not configured; CSV/JSON is saved for a later import.")


if __name__ == "__main__":
    main()
