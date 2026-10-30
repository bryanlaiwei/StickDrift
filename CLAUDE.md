# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Stick Drift is a hackathon prototype: browser controller games (three.js) for care-home residents, a FastAPI backend on Tiger Data (Postgres + TimescaleDB), and a PyTorch model that scores each hand's movement. `docs/context.md` is the living design doc and decision log. Read it before changing behaviour, and add a row to its decision log when you change the mission, boundaries or data flow. `docs/product.md` holds the voice and UX principles.

## Commands

The repo has **two separate Python environments** on purpose:

- **Root uv env** (`.venv/`, Python 3.14, torch/numpy/scipy/matplotlib) for `ml/`. Run `uv sync` at the repo root.
- **Backend venv** (`backend/.venv/`, from `backend/requirements.txt`: FastAPI, psycopg, google-genai, reportlab) for `backend/`.

```bash
# API (needs backend/.env with DATABASE_URL; see backend/.env.example)
cd backend && source .venv/bin/activate && uvicorn app.main:app --port 8000

# Web (Vite on :5173, proxies /api -> :8000 and strips the /api prefix; lobby at /lobby.html)
cd web && npm run dev

# Tests, from the repo root
backend/.venv/bin/python -m unittest discover -s tests/backend -t .
MPLBACKEND=Agg .venv/bin/python -m unittest discover -s tests/ml -t .
cd web && npm test && npm run lint && npm run build

# One test module or case (from the repo root, with the matching env)
backend/.venv/bin/python -m unittest tests.backend.test_insights
MPLBACKEND=Agg .venv/bin/python -m unittest tests.ml.test_visit_report.SharedMeasurementsTest
node tests/web/lobby_measure.mjs

# A caregiver login without the invite code
cd backend && python -m scripts.create_caregiver
```

- Tests import packages from the repo root (`backend.app...`, `ml...`), so run them from the root with `-t .`.
- Backend tests mock the database and need only a placeholder `DATABASE_URL`. Some skip themselves when backend packages are missing.
- `tests/web/*.mjs` are plain Node `assert` scripts that import the lobby modules directly. There is no test framework.
- ESLint covers only `web/**/*.{ts,tsx}`. The lobby's plain JS is not linted. `npm run build` runs `tsc -b`.

## Architecture

**Two front ends in one Vite build.** `index.html` is the React app (`web/src`: welcome/auth, resident home, caregiver dashboard, live view, resident page). `lobby.html` is the three.js lobby and games (`web/lobby`), a separate plain-JS page. The React side embeds a self-playing lobby through `web/lobby/preview.js` (types in `preview.d.ts`). All browser calls go to `/api`: in dev the Vite proxy handles it, and in production `deploy/worker.js` (Cloudflare Worker, `wrangler.jsonc`) forwards it to `BACKEND_URL`. Both strip `/api`, so backend routes have no `/api` prefix. Keeping a single origin is what lets the HttpOnly session cookie and the WebSocket work without CORS.

**Lobby measurement is read-only.** The game files (`apple.js`, `fish.js`, `rat.js`, `hub.js`) are teammates' code. `measure.js` observes each game's state every frame without changing it, and emits samples and events. `live.js` batches them to `POST /live/ingest` with an `X-Live-Token` from `/me/lobby/start`. `motion.js` adds DualSense gyro/accelerometer over WebHID when available. `input.js` maps Gamepad API and keyboard input to one stick model. Keyboard play is flagged `is_synthetic` and left out of baselines.

**Live sessions are stateless across API processes** (`backend/app/live/`, see its `__init__.py`):
- `session.py`: each ingest request loads the session row, applies the batch and writes it back in one transaction, so any process can serve any request.
- `stream.py`: caregivers' WebSocket, fed by Postgres `LISTEN/NOTIFY`, with fallbacks to server reads and then polling.
- `visit.py`: ending a visit (tab close, or 60 s of silence). It writes one `sessions` row plus `session_summaries`, copies only in-game samples to `raw_samples`, then runs the ML as **subprocesses in the root uv env** (`STICKDRIFT_ML_PYTHON`, default `.venv/bin/python`, `cwd` = repo root):
  - `python -m ml.visit_report.report`: capture JSON on stdin, report JSON (pattern scores and per-game numbers) on stdout.
  - `python -m ml.hand_replay.from_capture --out hands.gif`: a reconstructed-hands GIF stored in `session_hand_replays`.
  A periodic sweep re-runs reports lost mid-way. The hand replay must never change or delay the report.
- `live_*` tables are pruned after a day.

**Shared measurement code.** `backend/app/measurements.py` is the only definition of shake, tracking error and per-hand reach numbers. The live path uses it, and `ml/visit_report/report.py` imports it as `backend.app.measurements`. That's why the ML subprocess runs from the repo root. Change it in one place.

**Insights.** `backend/app/insights.py` builds the personal baseline (from the 4th controller visit, compared with the median of earlier visits) and concerns. `assistant.py` (Gemini, with a rule-based fallback when `GEMINI_API_KEY` is unset) and `clinician_report.py` (PDF) work only from structured facts built from the DB. The model in `ml/pattern_model/` is a TCN with a committed checkpoint at `ml/runs/pattern_model/model.pt`. Training reads local recordings under `data/` (git-ignored) through `load_examples`/`fit`.

**Schema.** `backend/sql/schema.sql` is the only schema definition. The API applies it at startup under an advisory lock, so it must stay idempotent and never drop anything.

## Rules that are easy to break

- **Neutral labels only.** The model's output keys are `parkinson`, `stroke` and `essential_tremor` because of its training-folder names, but nothing a caregiver, the assistant or the PDF shows may name a condition. Use `PATTERN_LABELS` (`web/src/labels.ts`, mirrored in `backend/app/insights.py`). The assistant's `BANNED_WORDS` and `BANNED_ACRONYMS` refuse condition names. Output is "a change worth checking", never a diagnosis, prediction or emergency call.
- **Residents never see measurements.** They see only game scores and 0–3 stars (personal bests in `localStorage` through `web/lobby/scores.js`). Only caregivers see results.
- **Protocol versioning.** Visits store `protocol_version = lobby-v1` (`LOBBY_PROTOCOL` in `live/visit.py`). A change to a game's targets, timing, speed or scoring that affects movement needs a new version.
- **Thresholds are design choices** (pattern score 50 = "keep an eye on", two visits in a row at 70 or more = "check soon"; baseline steps in `insights.py`). They are not clinical cutoffs, so don't describe them as validated.
- Pseudonyms only. Data goes to a cloud DB, so never add fields for real names or health details. Keep `backend/.env` out of git.
- Resident-facing copy is warm and plain, with large high-contrast targets and no clinical vocabulary (`docs/product.md`).
