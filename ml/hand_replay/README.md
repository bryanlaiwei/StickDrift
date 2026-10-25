# Hand replay

Rebuilds the player's hands moving the DualSense from a lobby recording and renders it as a GIF.

```
uv run python -m ml.hand_replay.make_gifs --all
uv run python -m ml.hand_replay.make_gifs --session "data/ultimate_data/Tremor/2026-10-18_02-16-51_lobby" --level apple
```

Output goes to `ml/hand_replay/gifs/<condition>/<session>_<level>.gif`.

## Lobby visits (the dashboard GIF)

When a lobby visit ends, the API (`backend/app/live.py`) runs this beside the visit report, in the same Python:

```
python -m ml.hand_replay.from_capture --out hands.gif < capture.json
```

stdin is the in-memory capture `ml.visit_report` gets (`{"apple": {"frames": [...]}, "fish": ..., "rat": ...}`). It picks one window per visit, the busiest 6 s of Apple Picking if it has at least 3 s of frames, else Harbour Fishing, else Rat Catching, and draws only the hands and controller (the `natural` style, no panels or text) at 25 fps. It prints one JSON line (`game`, `window_start_s`, `duration_s`, `frames`, `has_motion`, `bytes`, `renderer_version`) and exits non-zero when no game has enough frames.

- The GIF is 400x300 and under 1.5 MB. Busy, shaky windows are drawn again smaller (about 320-360 px wide) to stay under that.
- About 11 s to render on a laptop CPU, or about 22 s when the smaller second render is needed.
- The live lobby sends no trigger or button values, so the index fingers rest and the right thumb stays on its stick.
- Without gyroscope values (`has_motion` false) the controller holds still and only the thumbs move.

## What is measured vs. modelled

- **Thumbs and sticks**: straight from `lx/ly/rx/ry`. Each thumb is solved onto its stick cap with inverse kinematics.
- **Index fingers**: curl with `l2_value/r2_value`. They move to the bumpers on L1/R1, and the right thumb moves to a face button when one is pressed.
- **Controller tilt**: pitch and roll from the low-passed accelerometer, yaw from the high-passed gyroscope.
- **Shake**: the gyroscope's 3-12 Hz band. The controller has one IMU, so the shake is split between the hands by each thumb stick's own fast jitter (the "hand share" in the footer). Each hand moves its grip by its share, and the controller pose is fitted to both grips, so the motion starts in the hands.
- **Drawn size**: shake is drawn x10 with a soft cap at 2 cm, so baseline and tremor stay readable on the same scale. The strip chart shows the real size in cm.
- The arm, palm and finger shapes are a fixed stylized model. Hand size and grip are not measured.

## Files

- `reconstruct.py`: recording (CSV or live capture frames) to per-frame pose signals, picks the busiest window
- `rig.py`: 3D controller, arm and hand skeleton, inverse kinematics
- `render.py`: camera projection, depth-sorted drawing, side panels, GIF export (full replay and hands-only)
- `make_gifs.py`: command-line entry point and session selection for recordings
- `from_capture.py`: the one hands-only GIF for a finished lobby visit
