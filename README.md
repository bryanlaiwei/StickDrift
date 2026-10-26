<p align="center">
  <img src="web/public/stickdrift-mark.svg" alt="Stick Drift" width="96" />
</p>

# Stick Drift

Short controller games for senior-living and long-term-care residents. While a resident plays, Stick Drift measures how each hand moves, so their care team can notice a change and check in early.

<p align="center">
  <img src="https://img.shields.io/badge/TypeScript-3178C6?style=flat&logo=typescript&logoColor=white" alt="TypeScript" />
  <img src="https://img.shields.io/badge/React-20232A?style=flat&logo=react&logoColor=61DAFB" alt="React" />
  <img src="https://img.shields.io/badge/Vite-646CFF?style=flat&logo=vite&logoColor=white" alt="Vite" />
  <img src="https://img.shields.io/badge/three.js-000000?style=flat&logo=threedotjs&logoColor=white" alt="three.js" />
  <img src="https://img.shields.io/badge/Python-3776AB?style=flat&logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/FastAPI-009688?style=flat&logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/PyTorch-EE4C2C?style=flat&logo=pytorch&logoColor=white" alt="PyTorch" />
  <img src="https://img.shields.io/badge/PostgreSQL-4169E1?style=flat&logo=postgresql&logoColor=white" alt="PostgreSQL" />
  <img src="https://img.shields.io/badge/TimescaleDB-FDB515?style=flat&logo=timescale&logoColor=black" alt="TimescaleDB" />
  <img src="https://img.shields.io/badge/Google_Gemini-8E75B2?style=flat&logo=googlegemini&logoColor=white" alt="Google Gemini" />
  <img src="https://img.shields.io/badge/Cloudflare-F38020?style=flat&logo=cloudflare&logoColor=white" alt="Cloudflare" />
</p>

<p align="center">
  <img src="web/public/lobby/lobby.jpg" alt="The lobby" width="24%" />
  <img src="web/public/lobby/apple.jpg" alt="Apple Picking" width="24%" />
  <img src="web/public/lobby/fish.jpg" alt="Harbour Fishing" width="24%" />
  <img src="web/public/lobby/rat.jpg" alt="Rat Catching" width="24%" />
</p>

> [!NOTE]
> Stick Drift was built in a weekend at **Hack the Valley 11** (October 2026) for **PointClickCare's "Catch It Early"** sponsor track, by Ayan Saiyed, Hreem Pandya, Zain Rizvi and Bryan Wei. This repository is a fork of the team's original, [AyanASaiyed/StickDrift](https://github.com/AyanASaiyed/StickDrift). After the event I cleaned up and reorganized the code and fixed a few measurement bugs. The product is the same one we built at the hackathon.

## The problem

In a care home, changes in how someone moves (slower reactions, one hand getting weaker, a new shake) are easy to miss between formal assessments, and the formal tests themselves are tiring. Stick Drift turns the check into a few minutes of play. The games are the part residents see. The measurement runs in the background, and the care team gets each resident's results over time compared with their own usual level.

The output is always **a change worth checking**, never a diagnosis. Stick Drift does not name conditions or decide whether something is urgent. A nurse or caregiver reads the numbers and decides what happens next.

## How it fits together

```mermaid
flowchart LR
  pad["PS5 controller"] --> lobby["3D lobby and games<br/>(browser)"]
  lobby -- "samples and events" --> api["FastAPI"]
  api --> db["Postgres + TimescaleDB"]
  db -- "LISTEN / NOTIFY" --> api
  api -- "WebSocket" --> care["Caregiver dashboard"]
  api -- "end of visit" --> ml["Pattern model<br/>and hand replay"]
  ml --> db
```

The resident plays in a three.js lobby in Chrome or Edge. The controller's sticks come in through the Gamepad API, and its gyroscope and accelerometer through WebHID when the resident turns on motion sensors. `web/lobby/measure.js` watches each game's state without changing it and streams samples (60 per second) and in-game events (a reach started, an apple picked, a rat slammed) to the API.

The API stores the live session in the database and sends a Postgres `NOTIFY`. Every caregiver API that is watching `LISTEN`s and pushes the update to the browser over a WebSocket, so a caregiver on another computer sees the session about a tenth of a second behind. The database is the only shared state, so the API can run with several workers or on several laptops.

When the resident leaves through the exit door, the visit is saved to their history. The API then runs the pattern model and draws a short GIF of the reconstructed hands and controller, both in a separate Python environment.

## What you can do

**Residents** sign up with a nickname and their dominant hand, then walk Grandma around the lobby and step onto a pad to play:

| Game | What the resident does | What it measures, per hand |
| --- | --- | --- |
| **Apple Picking** | Steer a red glove (left stick) and a blue glove (right stick) to matching apples and carry them to the basket | Reaction time, time to pick, peak speed, wrong-colour touches |
| **Harbour Fishing** | Trace a fish's path with the rod tip, one hand at a time | Distance from the path, time on the path, shake and its rhythm |
| **Rat Catching** | Flick a stick to slam a hand down when the target rat runs underneath, and hold back for the others | Target rats caught, wrong slams, reaction time |

Each game shows the resident a score and up to three stars. Those are just for fun and are separate from what caregivers see.

**Caregivers** see:

- A **dashboard** of every resident with a status ("No concerns", "Keep an eye on", "Check soon"), who is playing right now, and visits that just finished.
- A **live view** of each hand against its target, with measurements updating as the resident plays.
- A **resident page** with trends per hand across visits, every visit's per-game results, the reconstructed-hands GIF, and any concerns, each with what changed and what to check first.
- An **assistant** (Google Gemini) that answers questions from that resident's recorded numbers only. Answers that use a number not in the records are flagged, and answers that name a condition are replaced with a referral to a clinician.
- A one-click **clinician report** as a PDF.

The left hand is always red and the right hand always blue, in the games and on every chart.

### How a visit is scored

Two things raise a concern:

- **Change from the resident's usual level.** From the fourth controller visit on, each result is compared with that resident's earlier visits.
- **The pattern model** (`ml/pattern_model/`), a small temporal convolutional network in PyTorch. It scores Apple Picking and Harbour Fishing 0–100 for resemblance to three movement patterns: slower, smaller movements in both hands; one hand weaker or slower than the other; and rhythmic shake while moving. A score of 50 or more means "Keep an eye on", and two visits in a row at 70 or more mean "Check soon". Caregivers only ever see those neutral descriptions.

Rat Catching is not scored by the model. Its catches, wrong slams and reaction times are counted directly from the game.

The model was trained by the team on recordings of ourselves acting out each pattern, plus synthetic data. The trained checkpoint is committed at `ml/runs/pattern_model/model.pt`. The recordings are not in the repository, so a clone can run the model but not retrain it.

## Research basis

No published study uses a modern gamepad thumbstick for this exactly, so Stick Drift applies established movement measures to a cheap device people already enjoy. The work it builds on:

**Joysticks and game peripherals for movement disorders**

- [Allen et al., 2007](https://eprints.whiterose.ac.uk/2663). An unmodified game joystick and steering wheel, with tracking tasks much like Harbour Fishing, told people with Parkinson's from controls and separated patients by how slow their movements were. It was small (13 patients, 5 controls), and it is the closest precedent for Stick Drift.
- [Feng & Winters, 2009](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC2705666/). A joystick platform for stroke survivors. Accuracy, steadiness and speed consistency separated patients by level of arm impairment.

**Slower, smaller movements (Harbour Fishing and Apple Picking)**

- [Oishi et al.](https://digital-library.theiet.org/content/journals/10.1049/iet-cta.2010.0464) and [a study of submovements in manual tracking](https://cris.iucc.ac.il/en/publications/submovements-in-manual-tracking-people-with-parkinsons-disease-pr/). People with Parkinson's make more tracking errors and more small corrective movements when following a moving target.
- [Giancardo et al., 2016 (neuroQWERTY)](https://www.physionet.org/content/nqmitcsxpd/1.0.0/MIT-CS1PD/data_MIT-CS1PD/). How long keys are held down during ordinary typing flagged early Parkinson's in 85 people.
- [Deep learning on mPower tapping, 2022](https://pmc.ncbi.nlm.nih.gov/articles/PMC8763910). Smartphone tapping from 6,418 people identified Parkinson's with an AUC of 0.93.

**One hand weaker than the other (Apple Picking's left-right comparison)**

- [Coderre et al., 2010](https://pubmed.ncbi.nlm.nih.gov/20233965). A robotic reaching task with 52 subacute stroke patients and 91 controls. Differences between the two arms stood out even when each arm looked normal on its own, which is why Stick Drift compares the hands with each other.

**Shake**

- [White & Horvitz, 2019](https://pmc.ncbi.nlm.nih.gov/articles/PMC6760188). Hand tremor estimated from ordinary mouse-cursor movement across a large population matched self-reports and clinical findings. Thumbstick evidence for tremor is thin, which is why Stick Drift also records the PS5 controller's motion sensors.

**Tracking older adults over time**

- [Haynes et al., 2017](https://eprints.whiterose.ac.uk/116209/). A review of 22 long-term studies: older adults whose reaction times vary more from one try to the next are at higher risk of later cognitive decline and death.
- [Seelye et al., 2015](https://experts.umn.edu/en/publications/computer-mouse-movement-patterns-a-potential-marker-of-mild-cogni/). A week of ordinary home mouse use showed measurable differences in people with mild cognitive impairment, a precedent for monitoring through everyday activity.

## Project structure

| Path | Role |
|---|---|
| [`web/src`](web/src) | React site: welcome and login pages, resident home, caregiver dashboard, live view, resident page |
| [`web/lobby`](web/lobby) | The 3D lobby and the three games (three.js). `measure.js` measures, `live.js` streams, `motion.js` reads the PS5 motion sensors |
| [`backend/app`](backend/app) | FastAPI: accounts, live sessions, measurements, concerns, assistant, clinician report |
| [`backend/sql/schema.sql`](backend/sql/schema.sql) | The database schema, applied by the API when it starts |
| [`ml/pattern_model`](ml/pattern_model) | The pattern model: network, training and scoring |
| [`ml/visit_report`](ml/visit_report) | Scores one finished visit |
| [`ml/hand_replay`](ml/hand_replay) | Draws the reconstructed-hands GIF |
| [`tests`](tests) | Backend, model and web tests |
| [`docs`](docs) | Product brief and design notes, with the decision log |
| [`deploy`](deploy) | Cloudflare Worker for the hosted site (config in `wrangler.jsonc`) |

## Run it locally

- [Node.js 20](https://nodejs.org/) or newer
- Python 3.14 and [uv](https://docs.astral.sh/uv/)
- Postgres with the TimescaleDB extension: [Docker Desktop](https://www.docker.com/products/docker-desktop/) for a local one, or a free [Tiger Data](https://www.tigerdata.com/) service
- Chrome or Edge, and a PS5 (DualSense) controller

**1. Database.** The quickest option is a local container:

```bash
docker run -d --name stickdrift-db -p 5432:5432 -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=stickdrift timescale/timescaledb:2.17.2-pg16
```

**2. Settings.** Copy `backend/.env.example` to `backend/.env` and fill it in. Do not commit `.env`.

| Variable | What it is |
|---|---|
| `DATABASE_URL` | The database connection string. For the container above: `postgresql://postgres:postgres@localhost:5432/stickdrift` |
| `CAREGIVER_INVITE_CODE` | An access code you choose. Caregivers must enter it to sign up, because caregivers can see every resident's results. Leave it empty to turn caregiver sign-up off |
| `GEMINI_API_KEY` | Optional. Turns on the Gemini assistant and the written part of the PDF |

**3. API.** From the repository root:

```bash
uv sync                                  # pattern model and hand replays (torch, numpy, ...)
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --port 8000         # creates the tables on first start
```

**4. Website.** In a second terminal, from the repository root:

```bash
cd web
npm install
npm run dev
```

Open `http://localhost:5173`. Sign up as a resident and open the lobby from the home page. In a second browser profile or a private window, sign up as a caregiver at `/caregiver/signup` with your access code, and you can watch the resident play live.

The Vite dev server forwards `/api`, including the live WebSocket, to the API on port 8000, so the browser sees a single origin.

> [!TIP]
> Without `GEMINI_API_KEY` everything still works: the assistant answers from fixed rules and the PDF uses template wording. Without an access code, run `python -m scripts.create_caregiver` in `backend/` for a caregiver login.

> [!IMPORTANT]
> The API runs the pattern model with `../.venv/bin/python`, the environment `uv sync` creates. On Windows, set `STICKDRIFT_ML_PYTHON` in `backend/.env` to the full path of `.venv\Scripts\python.exe`. If the API can't find it, visits are still saved but have no pattern scores or hand replay.

To run the tests from the repository root:

```bash
backend/.venv/bin/python -m unittest discover -s tests/backend -t .
MPLBACKEND=Agg .venv/bin/python -m unittest discover -s tests/ml -t .
cd web && npm test && npm run lint && npm run build
```

## Limitations

- Stick Drift is a hackathon prototype, not a medical device, and it has not been clinically validated. The thresholds are design choices, not clinical cutoffs.
- The pattern model was trained only on the team acting out each pattern and on synthetic data, never on patients.
- A change in results can come from tiredness, medication, eyesight, unfamiliarity with game controllers or a faulty controller, not only a change in health.
- Timing is measured in the browser at about 60 samples per second, so it includes display and network delay and is not precise to the millisecond.
- Motion sensors need a PS5 controller in Chrome or Edge. Other gamepads drive the sticks only.
