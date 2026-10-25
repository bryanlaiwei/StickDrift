# 3D lobby (browser version)

A three.js port of the Blender lobby in `../../legacy/blender_lobby`: grandma walks a top-down arena to three pads, each
opening a first-person game. No Blender needed - just a browser and (ideally) a PS5/Xbox controller.

```bash
cd web
npm install
npm run dev        # then open http://localhost:5173/lobby.html
```

`npm run build` also emits `dist/lobby.html` next to the main app.

| File | What it is |
|---|---|
| `main.js` | renderer, game switching, overlay text |
| `input.js` | Gamepad API (+ keyboard fallback) -> the same stick/button model the Blender version used |
| `hub.js` | the lobby, grandma, orbit camera |
| `apple.js` / `fish.js` / `rat.js` | Games 1-3 (Apple Picking, Harbour Fishing, Rat Catching) |
| `util.js`, `lights.js` | shared low-poly helpers, static-mesh merging, sun |

Controls: left stick walk, right stick orbit/tilt the camera, L1/R1 zoom, Triangle follow/overview, Cross enter a game,
**O (Circle) leaves a game** (games also return on their own 3 s after the results). Rat Catching: flick either stick up.
Chrome and Edge read PS5 pads best; press any button once so the browser exposes the controller.

Keyboard fallback (no pad): WASD = left stick, IJKL or arrows = right stick, Space = Cross, O = Circle, T = Triangle, Q/E = L1/R1.

## Scores and stars

Each game ends with a score and 0-3 stars; the best score (and best stars) per game is saved in `localStorage`
(`web/lobby/scores.js`) and shown in the lobby panel and next to each pad. Everything is stored per player id
(`setPlayer(id)`), currently one placeholder player, so hooking up the dashboard's users later only needs that call.

| Game | Score | Stars |
|---|---|---|
| Apple Picking | 100 per apple in the basket, -25 per wrong-colour touch | 1 per 2 red + 2 blue (2R+2B = 1, 4R+4B = 2, 6R+6B = 3) |
| Harbour Fishing | per trace: 6 x % on the lane + 25 per second under 12 s (max 900) | average % on the lane: 60 = 1, 80 = 2, 92 = 3 |
| Rat Catching | 300 per target caught, -100 wrong rat, -50 empty slam | 1 per 2 net catches (2 mistakes cancel 1 catch) |

## Sound

Music and effects are synthesised in the browser with the Web Audio API (`audio.js`) - there are no audio files.
Each game has its own generated music loop (lobby, apple, fishing with lapping water, rat chase), plus effects for walking,
entering pads, countdowns, picking/dropping apples, tracing, the splash, rat squeaks, the slam, and result fanfares
(more stars = longer fanfare, plus a sparkle for a new high score). The speaker button (bottom right) or the **M** key mutes;
the choice is remembered. There is no start screen: the lobby opens straight into the garden. Browsers keep sound locked until the first click, key press or button press, so the music begins at that point.

## Exit door

There is an exit door in the garden fence, right behind where grandma starts. Walk to it (the leaf swings open) and press
Cross: the live session is ended (`live.end()`) and the page goes back to the dashboard at `/`. The Blender version has the
same door; it stops the play loop and opens `DASHBOARD_URL` (set near the top of `legacy/blender_lobby/hub_world.py`) in your browser.
