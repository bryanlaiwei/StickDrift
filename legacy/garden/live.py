"""Optional live stream of a garden session to the Stick Drift API.

Turned on only when the API launches the game and sets STICKDRIFT_LIVE_URL and
STICKDRIFT_LIVE_TOKEN. It never blocks or breaks the game: samples go into a
bounded queue and a background thread posts them. The CSV files stay the
source of record; the stream only feeds the caregiver's live view.
"""
import json
import os
import threading
import time
import urllib.error
import urllib.request
from collections import deque

SAMPLE_HZ = 100       # live view rate; the CSV keeps every HID report
POST_EVERY_S = 0.1


def _xy(p):
    return (None, None) if p is None else (round(p[0], 4), round(p[1], 4))


class NullPublisher:
    def event(self, kind, **data):
        pass

    def sample(self, t, ctx, targets, cur):
        pass

    def close(self):
        pass


class LivePublisher:
    def __init__(self, url, token):
        self.url, self.token = url, token
        self.queue = deque(maxlen=SAMPLE_HZ * 60)
        self.pending = []
        self.last_t = None
        self.stopping = threading.Event()
        self.thread = threading.Thread(target=self._run, name="live-publisher", daemon=True)
        self.thread.start()

    def event(self, kind, **data):
        if kind == "level_start":
            self.last_t = None
        self.queue.append({"type": kind, "at": time.time(), **data})

    def sample(self, t, ctx, targets, cur):
        """Called from the HID reader thread; keep it cheap."""
        if self.last_t is not None and t - self.last_t < 1.0 / SAMPLE_HZ:
            return
        self.last_t = t
        (tlx, tly), (trx, try_) = _xy(targets[0]), _xy(targets[1])
        self.queue.append([round(t, 3), ctx.trial, ctx.phase,
                           round(cur[0], 4), round(cur[1], 4), round(cur[2], 4), round(cur[3], 4),
                           tlx, tly, trx, try_, int(ctx.reached[0]), int(ctx.reached[1])])

    def _post(self, items):
        body = json.dumps({"items": items}).encode()
        req = urllib.request.Request(self.url, data=body, method="POST", headers={
            "Content-Type": "application/json", "X-Live-Token": self.token})
        with urllib.request.urlopen(req, timeout=2) as resp:
            resp.read()

    def _flush(self):
        while self.queue and len(self.pending) < 2000:
            self.pending.append(self.queue.popleft())
        if not self.pending:
            return True
        try:
            self._post(self.pending)
            self.pending = []
            return True
        except (urllib.error.URLError, OSError, ValueError):
            # Keep at most ~20 s of unsent samples; the live view is best effort.
            self.pending = self.pending[-SAMPLE_HZ * 20:]
            return False

    def _run(self):
        while not self.stopping.is_set():
            ok = self._flush()
            self.stopping.wait(POST_EVERY_S if ok else 1.0)

    def close(self):
        self.stopping.set()
        self.thread.join(timeout=2)
        for _ in range(3):
            if self._flush() and not self.queue:
                break
            time.sleep(0.3)


def from_env():
    url, token = os.environ.get("STICKDRIFT_LIVE_URL"), os.environ.get("STICKDRIFT_LIVE_TOKEN")
    return LivePublisher(url, token) if url and token else NullPublisher()
