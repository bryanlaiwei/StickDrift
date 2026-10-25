#!/usr/bin/env python3
"""
Real-time DualSense (PS5) input viewer. Works over USB or Bluetooth.

Setup:   uv sync
Run:     uv run python "legacy/garden/read_data.py"
Keys:    R = start/stop CSV recording, Esc = quit
"""
import csv
import struct
import threading
import time
import tkinter as tk

import hid

IDS = [(0x054C, 0x0CE6), (0x054C, 0x0DF2)]  # DualSense, DualSense Edge
DPAD = {0: "N", 1: "NE", 2: "E", 3: "SE", 4: "S", 5: "SW", 6: "W", 7: "NW"}
FACE = ["Square", "Cross", "Circle", "Triangle"]
SHOULDER = ["L1", "R1", "L2", "R2", "Create", "Options", "L3", "R3"]
SYSTEM = ["PS", "Touchpad", "Mute"]
BTN_NAMES = FACE + SHOULDER + SYSTEM
CHARGE = {0: "discharging", 1: "charging", 2: "full"}


def parse(data):
    """Parse a raw HID report (USB 0x01 or Bluetooth 0x31) into a dict."""
    if not data:
        return None
    if data[0] == 0x01 and len(data) >= 54:
        b = bytes(data[1:])
    elif data[0] == 0x31 and len(data) >= 56:
        b = bytes(data[2:])
    else:
        return None

    s = dict(zip(["lx", "ly", "rx", "ry", "l2", "r2"], b[0:6]))
    b0, b1, b2 = b[7], b[8], b[9]
    s["dpad"] = DPAD.get(b0 & 0x0F, "-")
    for i, n in enumerate(FACE):
        s[n] = (b0 >> (4 + i)) & 1
    for i, n in enumerate(SHOULDER):
        s[n] = (b1 >> i) & 1
    for i, n in enumerate(SYSTEM):
        s[n] = (b2 >> i) & 1

    s["gyro"] = struct.unpack_from("<3h", b, 15)
    s["accel"] = struct.unpack_from("<3h", b, 21)

    touches = []
    for o in (32, 36):
        active = not (b[o] & 0x80)
        x = b[o + 1] | ((b[o + 2] & 0x0F) << 8)
        y = (b[o + 2] >> 4) | (b[o + 3] << 4)
        touches.append((int(active), x, y))
    s["touch"] = touches

    status = b[52]
    s["battery"] = min((status & 0x0F) * 10, 100)
    s["charge"] = CHARGE.get(status >> 4, "?")
    return s


CSV_HEADER = (
    ["t", "lx", "ly", "rx", "ry", "l2", "r2", "dpad"] + BTN_NAMES
    + ["gyro_x", "gyro_y", "gyro_z", "acc_x", "acc_y", "acc_z",
       "t1_active", "t1_x", "t1_y", "t2_active", "t2_x", "t2_y", "battery"]
)


def to_row(t, s):
    return (
        [round(t, 4), s["lx"], s["ly"], s["rx"], s["ry"], s["l2"], s["r2"], s["dpad"]]
        + [s[n] for n in BTN_NAMES]
        + list(s["gyro"]) + list(s["accel"])
        + list(s["touch"][0]) + list(s["touch"][1]) + [s["battery"]]
    )


class Reader(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.state = None
        self.status = "Searching for controller..."
        self.rate = 0
        self.record = False
        self.filename = ""

    def open_device(self):
        for vid, pid in IDS:
            try:
                d = hid.device()
                d.open(vid, pid)
                try:
                    d.get_feature_report(0x05, 41)  # switches Bluetooth to full reports
                except Exception:
                    pass
                return d
            except (OSError, ValueError):
                continue
        return None

    def run(self):
        while True:
            dev = self.open_device()
            if not dev:
                self.state = None
                self.status = "No controller found. Plug it in via USB."
                time.sleep(1)
                continue

            self.status = "Connected"
            f = writer = None
            count, t_rate, last_data = 0, time.time(), time.time()
            t0 = time.time()
            try:
                while True:
                    data = dev.read(78, 100)
                    now = time.time()
                    if not data:
                        if now - last_data > 1.5:
                            break  # controller went away
                        continue
                    last_data = now
                    s = parse(data)
                    if not s:
                        continue
                    self.state = s

                    count += 1
                    if now - t_rate >= 1:
                        self.rate, count, t_rate = count, 0, now

                    if self.record and writer is None:
                        self.filename = time.strftime("controller_log_%Y%m%d_%H%M%S.csv")
                        f = open(self.filename, "w", newline="")
                        writer = csv.writer(f)
                        writer.writerow(CSV_HEADER)
                        t0 = now
                    elif not self.record and writer is not None:
                        f.close()
                        f = writer = None
                    if writer:
                        writer.writerow(to_row(now - t0, s))
            except (OSError, ValueError):
                pass
            finally:
                if f:
                    f.close()
                dev.close()
                self.state = None
                self.rate = 0


class App:
    W, H = 960, 560
    BG, FG, DIM, ON = "#16181d", "#e6e6e6", "#3a3f4b", "#4ea1ff"

    def __init__(self, root):
        self.reader = Reader()
        self.reader.start()
        root.title("DualSense Input Viewer")
        root.configure(bg=self.BG)
        self.c = tk.Canvas(root, width=self.W, height=self.H, bg=self.BG, highlightthickness=0)
        self.c.pack()
        root.bind("<Key-r>", self.toggle_record)
        root.bind("<Key-R>", self.toggle_record)
        root.bind("<Escape>", lambda e: root.destroy())
        self.root = root
        self.tick()

    def toggle_record(self, _=None):
        self.reader.record = not self.reader.record

    # --- drawing helpers ---
    def box(self, x, y, w, h, label, on):
        self.c.create_rectangle(x, y, x + w, y + h, fill=self.ON if on else self.DIM, outline="")
        self.c.create_text(x + w / 2, y + h / 2, text=label, fill=self.FG, font=("Segoe UI", 9, "bold"))

    def circle_btn(self, x, y, label, on):
        self.c.create_oval(x - 20, y - 20, x + 20, y + 20, fill=self.ON if on else self.DIM, outline="")
        self.c.create_text(x, y, text=label, fill=self.FG, font=("Segoe UI", 8, "bold"))

    def stick(self, cx, cy, vx, vy, pressed, label):
        r = 70
        self.c.create_oval(cx - r, cy - r, cx + r, cy + r, outline=self.DIM, width=3)
        self.c.create_line(cx - r, cy, cx + r, cy, fill=self.DIM)
        self.c.create_line(cx, cy - r, cx, cy + r, fill=self.DIM)
        px, py = cx + (vx - 127.5) / 127.5 * r, cy + (vy - 127.5) / 127.5 * r
        self.c.create_oval(px - 14, py - 14, px + 14, py + 14,
                           fill=self.ON if pressed else "#8fb8e8", outline="")
        self.c.create_text(cx, cy + r + 18, text=f"{label}  X:{vx:3d}  Y:{vy:3d}",
                           fill=self.FG, font=("Consolas", 10))

    def trigger(self, x, y, value, label, pressed):
        w, h = 34, 110
        self.c.create_rectangle(x, y, x + w, y + h, outline=self.DIM, width=2)
        fh = h * value / 255
        self.c.create_rectangle(x, y + h - fh, x + w, y + h, fill=self.ON, outline="")
        self.c.create_text(x + w / 2, y - 12, text=label, fill=self.ON if pressed else self.FG,
                           font=("Segoe UI", 10, "bold"))
        self.c.create_text(x + w / 2, y + h + 12, text=str(value), fill=self.FG, font=("Consolas", 10))

    # --- main loop ---
    def tick(self):
        c, s = self.c, self.reader.state
        c.delete("all")
        c.create_text(20, 18, anchor="w", text=self.reader.status, fill=self.FG, font=("Segoe UI", 11, "bold"))

        if s is None:
            self.root.after(100, self.tick)
            return

        rec = self.reader.record
        c.create_text(self.W - 20, 18, anchor="e",
                      text=(f"REC  {self.reader.filename}" if rec else "Press R to record CSV")
                      + f"    {self.reader.rate} Hz",
                      fill="#ff5f5f" if rec else self.FG, font=("Segoe UI", 10))

        # triggers and shoulder buttons
        self.trigger(60, 70, s["l2"], "L2", s["L2"])
        self.trigger(866, 70, s["r2"], "R2", s["R2"])
        self.box(110, 70, 90, 28, "L1", s["L1"])
        self.box(760, 70, 90, 28, "R1", s["R1"])

        # d-pad
        dx, dy = 150, 240
        for name, (ox, oy) in {"N": (0, -34), "S": (0, 34), "W": (-34, 0), "E": (34, 0)}.items():
            on = s["dpad"] == name or (len(s["dpad"]) == 2 and name in s["dpad"])
            c.create_rectangle(dx + ox - 15, dy + oy - 15, dx + ox + 15, dy + oy + 15,
                               fill=self.ON if on else self.DIM, outline="")
        c.create_text(dx, dy + 62, text=f"D-pad: {s['dpad']}", fill=self.FG, font=("Consolas", 10))

        # face buttons
        fx, fy = 810, 240
        self.circle_btn(fx, fy - 38, "Tri", s["Triangle"])
        self.circle_btn(fx, fy + 38, "X", s["Cross"])
        self.circle_btn(fx - 38, fy, "Sq", s["Square"])
        self.circle_btn(fx + 38, fy, "O", s["Circle"])

        # touchpad
        tx0, ty0, tw, th = 340, 70, 280, 120
        c.create_rectangle(tx0, ty0, tx0 + tw, ty0 + th, outline=self.ON if s["Touchpad"] else self.DIM, width=3)
        for i, (act, x, y) in enumerate(s["touch"]):
            if act:
                px, py = tx0 + x / 1920 * tw, ty0 + y / 1080 * th
                col = "#ffcc4d" if i == 0 else "#ff7ac6"
                c.create_oval(px - 9, py - 9, px + 9, py + 9, fill=col, outline="")
        c.create_text(tx0 + tw / 2, ty0 + th + 14, fill=self.FG, font=("Consolas", 9),
                      text="  ".join(f"T{i+1}:{'(%d,%d)' % (x, y) if a else 'off'}"
                                     for i, (a, x, y) in enumerate(s["touch"])))

        # center buttons
        self.box(330, 235, 70, 26, "Create", s["Create"])
        self.box(410, 235, 50, 26, "PS", s["PS"])
        self.box(470, 235, 50, 26, "Mute", s["Mute"])
        self.box(530, 235, 70, 26, "Options", s["Options"])

        # sticks
        self.stick(250, 400, s["lx"], s["ly"], s["L3"], "L")
        self.stick(710, 400, s["rx"], s["ry"], s["R3"], "R")

        # motion + battery readout
        g, a = s["gyro"], s["accel"]
        lines = [
            "Gyro  " + " ".join(f"{v:7d}" for v in g),
            "Accel " + " ".join(f"{v:7d}" for v in a),
            "",
            f"Battery {s['battery']}% ({s['charge']})",
        ]
        c.create_text(480, 370, text="\n".join(lines), fill=self.FG, font=("Consolas", 10), justify="center")

        self.root.after(16, self.tick)


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()