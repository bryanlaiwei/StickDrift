# 🕹️ Stick Drift

Controller games for senior-living and long-term-care residents that help care teams notice when someone's movement changes.

A resident logs in, opens a small 3D game lobby, and plays short games with a PS5 controller: picking apples, tracing a fish through a harbour, catching rats. While they play, Stick Drift measures how each hand moves: how quickly it reacts, how fast and far it reaches, how closely it follows a path, and how much it shakes. A caregiver on any computer can watch the session live, then review every visit, see trends over time, and ask an AI assistant about the results.

The output is **a change worth checking**, never a diagnosis. Stick Drift does not name conditions, predict disease, or decide whether something is an emergency. A nurse or caregiver reads the numbers, adds context, and decides what happens next.

> 🏆 Built for Hack the Valley 11 (PointClickCare: Catch It Early). Live at [stickdrift.health](https://stickdrift.health).

## ⚙️ How it works

```
Resident's laptop                                         Caregiver's laptop (any computer)
─────────────────                                         ─────────────────────────────────
Browser: 3D lobby + games ──samples──► FastAPI ──┐   ┌──► FastAPI ──WebSocket──► Dashboard, live view,
(PS5 pad via Gamepad API)                        ▼   │                             history, trends, assistant
                                          Tiger Data (PostgreSQL + TimescaleDB)
                                          live buffer · NOTIFY · history · samples
```

1. 🎮 **Play.** The resident logs in and clicks **Open the lobby**. They walk Grandma around a 3D lobby with the left stick and step onto a pad to start a game.
2. 📡 **Stream.** The lobby sends stick samples, in-game hand and target positions, and one result per attempt to the resident's API, about ten times a second. That API writes them to Tiger Data and sends a Postgres `NOTIFY`.
3. 👀 **Watch live.** Any caregiver's API `LISTEN`s and pushes updates to their browser over a WebSocket. The live view shows the sticks, distance from target and measurements as they happen, about 0.1 s behind the resident.
4. 💾 **Save.** When the visit ends, it becomes a permanent session in the resident's history with per-game, per-hand results. Only in-game samples are kept for analysis and training. Walking around the lobby, menus and countdowns are dropped.
5. 📈 **Review.** Caregivers see each resident's visits, trends across visits, any potential concerns with recommended checks, and can ask the assistant questions grounded in the recorded numbers.

The two laptops share nothing but the Tiger Data database. If the resident's API runs older code and sends no notifications, the caregiver's API reads new samples directly every 0.15 s, so the view stays live either way.

## 🎮 The games

### 🏠 Web lobby (main experience)

A three.js lobby that runs in the browser at `/lobby.html`. Residents open it from their home page in a new tab.

| Game | What the resident does | What it measures, per hand |
| --- | --- | --- |
| 🍎 **Apple Picking** | Steer a red glove (left stick) and a blue glove (right stick) to matching apples, then carry them to the basket | Apples picked, time to pick, reaction time, peak speed, how far the stick was pushed |
| 🎣 **Harbour Fishing** | Trace a glowing lane with the fishing lure, one hand at a time | Distance from the lane, share of time on the lane, shake and its rhythm |
| 🐀 **Rat Catching** | Flick a stick up to slam the hand when the target rat runs underneath | Target rats caught, time to slam, reaction time |

Controls: left stick walks, right stick moves the camera, Cross enters a game, Circle leaves it. A keyboard fallback exists (WASD, IJKL, Space, O); visits played that way are labelled **keyboard input** everywhere. Each game shows a score and 0–3 stars to the resident. Those are for fun and are separate from the caregiver measurements.

The games move an in-game hand with the stick (velocity control), so distance from target compares that hand with its target, while speed and shake are read from the stick itself. The game logic lives in `web/lobby/*.js`. `web/lobby/measure.js` reads each game's state without changing it.

In Chrome or Edge, **Enable motion sensors** in the lobby opens the DualSense over WebHID (`web/lobby/motion.js`) and adds its gyroscope and accelerometer to the recording. Without it the games still work from the Gamepad API alone.

Visits are stored only in Tiger Data. The API writes no recording files; the pattern model trains from local recordings (see [Training the pattern model](#training-the-pattern-model)).

### 🌙 Mabel's Moonflower Garden (desktop game)

The original pygame game (`garden-v3`): four chapters of apple picking with both sticks, a left-stick and a right-stick butterfly flight, and watering with both sticks. It records every controller report (~500 Hz) to CSV, imports the recording into Tiger Data, and appears on the resident's page as **Garden visits**. The site no longer opens it, but it can still be run directly (see [Running the garden game](#running-the-garden-game)).

### 🧊 Blender lobby

`blender_hub/hub_world.py` is the same lobby and games built inside Blender 5 (Windows only). It is a design reference and does not send data to Stick Drift. See [blender_hub/README.md](blender_hub/README.md).

## 🩺 What caregivers see

- **Dashboard** (`/caregiver`). Every resident with a risk badge ("No concerns", "Keep an eye on", "Check soon"), who is playing right now, and visits that just finished.
- **Live view** (`/caregiver/live/:id`). Each in-game hand against its target, a rolling 20-second chart (distance from target or stick tilt), and measurements updating as the resident plays.
- **Resident page** (`/caregiver/residents/:id`):
  - **Overview.** Status banner and any potential concerns. Each concern shows what changed, what to check first, possible everyday reasons, and its research basis.
  - **Trends.** One line per hand across visits: time to pick an apple, time on the fishing lane, time to slam a rat (and garden or earlier sessions when the resident has them).
  - **Game visits.** The latest visit as one card per game, the pattern chart for that visit, and a table of every visit. Visits recorded since hand replays were added also have a short **reconstructed hands** GIF (the 3D hands and controller during the busiest few seconds, shake drawn ×10); it is also shown at the end of the live view.
  - **Ask the assistant.** Questions about this resident, answered from their recorded measurements.
  - **Clinician report (PDF).** A one-click summary of visits, per-hand results, pattern scores and concerns for a nurse or doctor (`backend/app/report.py`). Gemini writes the short narrative under the same checks as the assistant, with a template fallback.

The left hand is always red and the right hand always blue, in the games and on every chart.

### 🤖 AI assistant and guardrails

The assistant (Google Gemini, `backend/app/assistant.py`) receives only structured facts built from the database: measurements, changes from usual, concerns, recommended checks, and recent visits. Its answers are filtered before they are shown:

- Any number not present in the facts is flagged as unverified.
- Answers that name a disease or condition are replaced with a referral to a clinician.
- If the API key is missing or Gemini is unavailable, a rule-based answer built directly from the records is returned instead.

Potential concerns come from fixed rules (latest result vs that resident's own usual level) and the pattern model below. A pattern score of 50 or more gives "Keep an eye on", and 70 or more gives "Check soon". Concerns name the model's pattern, such as "Stroke", as a resemblance score, never as a diagnosis.

### 🧠 Pattern model (`tcn/`)

A temporal convolutional network (PyTorch) that scores each visit 0–100 for resemblance to three movement patterns. Caregivers only ever see the neutral label; the internal keys are condition names because of how the training folders are named.

- 🧓 **Slower, smaller movements in both hands** (key `parkinson`);
- ✋ **One hand weaker or slower than the other** (key `stroke`);
- 〰️ **Rhythmic shake while moving** (key `essential_tremor`).

One shared network reads short stretches of each hand's movement and gives two outputs per hand: tremor and impairment. Parkinson's is the impairment both hands share, stroke is the gap between the hands, and essential tremor is the higher tremor score of the two hands.

When a lobby visit ends, `visit/report.py` scores Apple Picking and Harbour Fishing with the model. Parkinson's and essential tremor are averaged across the two games; stroke comes from Apple Picking, the only game where both hands move together. **Rat Catching is not scored by the model.** Its correctness (target rats caught, misses, wrong slams) and reaction time are counted directly from the game's events. Garden visits are scored by `backend/scripts/score_garden.py`.

The model is trained locally by the team, on a laptop, from the lobby visits we played and recorded (plus synthetic data), and saved as `runs/tcn/model.pt`. That file is committed to the repo, and the backend loads it from disk each time it scores a visit, including at demo time. Nothing is trained or downloaded while the app runs. It was not trained on patients. Each score is resemblance to a movement pattern, never a diagnosis or a disease probability. The assistant and report refuse every condition name. The model no longer scores diabetes or ataxia, and the loader skips the old recordings for those patterns.

## 🚀 Running locally

You need Node 20+, Python 3.9+ for the backend, Python 3.14 with [uv](https://docs.astral.sh/uv/) for the games and model, Chrome or Edge, and a [Tiger Data](https://www.tigerdata.com/) service.

**1. Database.** Create a service in Tiger Console and copy its connection string. Apply both schemas (they are safe to re-run):

```bash
cd backend
cp .env.example .env               # set DATABASE_URL (and the other variables below)
psql "$DATABASE_URL" -f schema.sql
psql "$DATABASE_URL" -f auth_schema.sql
```

**2. Backend.**

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m scripts.seed_synthetic   # optional: two demo residents with SYNTHETIC history
python seed_accounts.py            # optional: logins for existing residents + a caregiver account (random passwords, printed once)
uvicorn app.main:app --port 8000
```

**2b. Game and model environment.** When a lobby visit ends, the API runs the pattern model (`visit.report`) and draws the reconstructed-hands GIF (`hand_replay.from_capture`) in the root Python 3.14 environment, so install it once from the repository root:

```bash
uv sync                            # numpy, torch, scipy, matplotlib, pillow, ...
```

The API looks for `../.venv/bin/python`. On Windows that file does not exist, so set `STICKDRIFT_GAME_PYTHON` in `backend/.env` to the full path of `.venv\Scripts\python.exe`. Without this environment the visit is still saved, but it has no pattern scores and no hand replay.

**3. Web app.**

```bash
cd web
npm install
npm run dev                        # http://localhost:5173 (the lobby is http://localhost:5173/lobby.html)
```

The Vite dev server proxies `/api` (including the live WebSocket) to `http://localhost:8000`, so the browser sees one origin and the login cookie just works. After pulling changes, restart both the API and the dev server.

**4. Use it.**

- Residents sign up at `/signup` and open the lobby from their home page.
- Caregivers register at `/caregiver/signup` with the access code from `CAREGIVER_INVITE_CODE`, or use the account from `seed_accounts.py`.

For the cross-laptop setup, each laptop runs its own API and web app against the same `DATABASE_URL`.

### 🔑 Environment variables (`backend/.env`)

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | Tiger Data connection string (never commit it) |
| `CAREGIVER_INVITE_CODE` | Access code required to register a caregiver; empty turns registration off |
| `GEMINI_API_KEY` | Enables the AI assistant and the PDF narrative; without it the rule-based and template text are used |
| `GEMINI_MODEL` | Optional model override (default `gemini-3.8-flash`, with fallbacks) |
| `CORS_ORIGINS` | Allowed web origins, comma separated (default `http://localhost:5173`) |
| `GARDEN_RECORDING_TIMEZONE` | Timezone of garden CSV timestamps (default `America/Toronto`) |
| `STICKDRIFT_GAME_PYTHON`, `STICKDRIFT_API_URL` | Where the API finds the root uv environment's Python (garden game, pattern model, hand replays; default `../.venv/bin/python`, on Windows set it to `.venv\Scripts\python.exe`), and its own URL |

### 🌻 Running the garden game

From the repository root:

```bash
uv sync
uv run python "Controller Data - Zain/Games/garden.py" --player P01 --session 1 --fullscreen
uv run python "Controller Data - Zain/Games/garden.py" --demo --mute     # keyboard, labelled synthetic
```

Each run writes `data/<timestamp>_garden_<player>_all-levels/` with one CSV and `level.json` per chapter, then imports it into Tiger Data when `backend/.env` is configured. Use `--no-tiger-sync` to skip the import, and `--reduced-motion` to still decorative motion. To import recordings later:

```bash
cd backend
python -m scripts.import_garden ../data --dry-run
python -m scripts.import_garden ../data
```

### 🏋️ Training the pattern model

The model trains in the root Python 3.14 environment (`uv sync`). Recordings are labelled by their folder names (Baseline, Parkinsons, Tremor, Stroke/Left Weak or Right Weak; see `tcn/labels.py`):

```bash
uv run python -m tcn.synthetic                                   # optional: writes data/Synthetic
uv run python -c "from tcn import fit, load_training_examples; fit(load_training_examples('data'))"
```

`load_training_examples` reads the apple and fishing recordings under `data/ultimate_data` and leaves out Rat Catching. Training writes `runs/tcn/model.pt`; the checkpoint carries a schema version, so code and checkpoint from different versions refuse to load together. Restart the API after replacing it.

## ☁️ Deployment

The public site runs on Cloudflare:

- A **Cloudflare Worker** (`wrangler.jsonc`, `cloudflare/worker.js`) builds `web/` and serves `web/dist`. It forwards `/api/*` to the FastAPI backend named by the Worker secret `BACKEND_URL`, so the login cookie and the live WebSocket stay on one origin. Pushing to `main` redeploys it through Cloudflare's GitHub integration.
- The backend runs on a laptop behind a named **Cloudflare Tunnel** (`api.stickdrift.health` → `localhost:8000`). Add the site's origins (`https://stickdrift.health`, the `workers.dev` URL) to `CORS_ORIGINS`, or the live WebSocket is refused.
- The pattern model needs the root `.venv` on the backend machine. Without it, visits are saved but not scored.

## 🔒 Data and privacy

Data lives in Tiger Data (managed PostgreSQL with TimescaleDB), so it leaves the laptop:

- **Profiles** hold only a nickname or code and a dominant hand, never a real name or health information.
- **Passwords** are hashed with argon2id, and logins use an HttpOnly session cookie.
- **No camera, microphone or other biometric capture.**

| Table | What it holds |
| --- | --- |
| `participants`, `caregivers`, `auth_sessions` | Accounts and logins |
| `sessions`, `session_summaries` | One row per visit (`lobby-v1` or `garden-v3`) and its per-game, per-hand results |
| `raw_samples` | Hypertable of in-game stick samples with target and in-game hand positions, tagged by game; the training data |
| `garden_level_results`, `garden_imports` | Imported garden recordings |
| `live_sessions`, `live_samples` | Short-term buffer for the live view, cleared after a day; finished visits are copied to `sessions` and `raw_samples` first |
| `session_hand_replays` | One reconstructed-hands GIF (under ~1.5 MB) per lobby visit, plus which game and window it shows; the API creates this table on first use |

Lobby visits are stored as free play: each visit is shown on its own and does not feed a statistical baseline yet. The multi-day histories of the demo residents are **synthetic and labelled as such**.

## 🗂️ Project layout

```
web/
  index.html, src/           React app: login and signup, resident home, caregiver dashboard, live view, resident pages
  src/components/            Charts, live feed (WebSocket + playback buffer), game visits, assistant, insights
  lobby.html, lobby/         Browser 3D lobby and games (three.js); live.js streams, measure.js measures
backend/
  schema.sql, auth_schema.sql   Tiger Data tables
  app/main.py                FastAPI app, health, and the low-level session API
  app/auth.py                Resident and caregiver accounts, sessions, access code
  app/live.py                Live sessions, lobby streaming, saving lobby visits, garden launch and scoring
  app/live_stream.py         LISTEN/NOTIFY hub and the caregiver WebSocket
  app/live_metrics.py        Per-hand movement measurements (reach, tracking, shake, left-right difference)
  app/views.py, insights.py  Caregiver resident data, concerns and recommended checks
  app/assistant.py           Gemini assistant with grounding and wording checks
  app/report.py              Clinician PDF report
  app/gemini.py              The Gemini client shared by the assistant and the report
  scripts/                   Synthetic demo data, garden import, garden scoring
  seed_accounts.py           Demo logins
tcn/                         Pattern model: data preparation, network, training, scoring
runs/tcn/model.pt            Trained pattern-model checkpoint
visit/report.py              Scores a finished lobby visit (pattern model + Rat Catching counts)
hand_replay/                 Reconstructed hands + controller GIFs from recordings and from a finished lobby visit
study/                       Tools for the Noy et al. (2025) mirror-game tracking dataset
tests/                       Python and Node tests (visit report, insights, live hand replay, measurements, rat timing)
cloudflare/, wrangler.jsonc  Cloudflare Worker that serves the site and proxies /api
Controller Data - Zain/      DualSense reader and the pygame garden game
blender_hub/                 Blender version of the lobby
Context.MD                   Project context, guardrails and decision log
```

### 🔌 API

All caregiver routes need a caregiver login; `/me/*` routes need a resident login.

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/auth/senior/signup`, `/auth/senior/login` | Resident accounts |
| POST | `/auth/caregiver/signup`, `/auth/caregiver/login` | Caregiver accounts (signup needs the access code) |
| GET / POST | `/auth/me`, `/auth/logout` | Current account, log out |
| POST | `/me/lobby/start` | Open a live session for the lobby; returns a one-time stream token |
| POST | `/live/ingest`, `/live/end` | Stream samples and events with the token; end the visit (saves it to history) |
| POST / GET | `/me/garden/launch`, `/me/garden` | Launch the desktop garden game on this computer and check its state |
| GET | `/caregiver/residents`, `/caregiver/residents/{id}` | Residents with risk; one resident's visits, insights and concerns |
| GET | `/caregiver/live`, `/caregiver/live/{id}` | Live and recently finished sessions; one session's state and samples |
| GET | `/caregiver/sessions/{id}/hand-replay.gif` | A lobby visit's reconstructed-hands GIF (404 when it has none) |
| WS | `/caregiver/live/{id}/ws` | Push stream of one live session |
| POST | `/caregiver/assistant` | Ask the assistant about all residents or one |
| GET | `/caregiver/residents/{id}/report.pdf` | Clinician PDF report (`?tz=` prints times in the reader's zone) |
| GET | `/health` | Database reachable |

`main.py` also serves `/garden/recordings` and `/sessions/{id}/garden-timeline` (caregivers only) for imported garden data. Live sessions are kept in Tiger Data, so the API can run with more than one worker and a restart doesn't drop a visit in progress.

## ⚠️ Limitations

- This is a hackathon prototype, not a medical device, and it has not been clinically validated. All thresholds are untested design choices, not clinical cutoffs.
- A change in results can come from fatigue, sleep, medication, vision, unfamiliarity with game controllers, how the controller is held, or a faulty device.
- Lobby measurements are sampled at about 60 Hz in the browser, including display and network delay. They are not precise to the millisecond and are not a pure motor-speed measure.
- The pattern model is trained on teammate-simulated and synthetic recordings only. Its scores have not been checked against real patients.
- Anyone with a sudden new neurological symptom needs normal urgent care. Nobody should wait on a game score.
