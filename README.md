<p align="center">
  <img src="web/public/stickdrift-mark.svg" alt="Stick Drift" width="96" />
</p>

# Stick Drift

Short, simple controller games designed for seniors. While a resident plays, a model reads how each hand moves, so their care team can catch early signs of motion-related diseases like Parkinson's, stroke and essential tremor.

<p align="center">
  <img src="https://img.shields.io/badge/TypeScript-3178C6?style=flat&logo=typescript&logoColor=white" alt="TypeScript" />
  <img src="https://img.shields.io/badge/React-20232A?style=flat&logo=react&logoColor=61DAFB" alt="React" />
  <img src="https://img.shields.io/badge/Vite-646CFF?style=flat&logo=vite&logoColor=white" alt="Vite" />
  <img src="https://img.shields.io/badge/three.js-000000?style=flat&logo=threedotjs&logoColor=white" alt="three.js" />
  <img src="https://img.shields.io/badge/Python-3776AB?style=flat&logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/FastAPI-009688?style=flat&logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/PyTorch-EE4C2C?style=flat&logo=pytorch&logoColor=white" alt="PyTorch" />
  <img src="https://img.shields.io/badge/PostgreSQL-4169E1?style=flat&logo=postgresql&logoColor=white" alt="PostgreSQL" />
  <img src="https://img.shields.io/badge/Tiger_Data-F5A623?style=flat" alt="Tiger Data" />
  <img src="https://img.shields.io/badge/Google_Gemini-8E75B2?style=flat&logo=googlegemini&logoColor=white" alt="Google Gemini" />
  <img src="https://img.shields.io/badge/Cloudflare-F38020?style=flat&logo=cloudflare&logoColor=white" alt="Cloudflare" />
</p>


<p align="center">
  <a href="https://youtu.be/d01z2tL992U">
    <img src="https://img.youtube.com/vi/d01z2tL992U/maxresdefault.jpg" alt="Watch the Stick Drift demo on YouTube" width="75%" />
  </a>
  <br />
  <sub>▶ Watch the demo</sub>
</p>

> [!NOTE]
> Built at **Hack the Valley 11** for **PointClickCare's "Catch It Early"** sponsor track. This repository is a fork of the team's original, [AyanASaiyed/StickDrift](https://github.com/AyanASaiyed/StickDrift). After the event I cleaned up and reorganized the code and fixed bugs. The product is the same one we built at the hackathon.

## The problem

Early signs of Parkinson's, stroke and essential tremor, like slower reactions, one hand getting weaker or a new shake, are easy to miss in the months between formal assessments, and those assessments are long and tiring. Stick Drift is something a resident can play every day: easy enough for anyone, fun enough to come back to, and measuring each hand's motion the whole time.

## How it fits together

```mermaid
flowchart LR
  pad["PS5 controller"] --> lobby["3D lobby and games<br/>(browser)"]
  lobby -- "samples and events" --> api["FastAPI"]
  api --> db["Tiger Data<br/>(Postgres + TimescaleDB)"]
  db -- "LISTEN / NOTIFY" --> api
  api -- "WebSocket" --> care["Caregiver dashboard"]
  api -- "end of visit" --> ml["Pattern model<br/>and hand replay"]
  ml --> db
```

The resident plays in a three.js lobby in Chrome or Edge, using the controller's sticks and, when turned on, its motion sensors. Each game streams hand samples (60 per second) and events, like an apple picked or a rat slammed, to the API.

The API keeps a short-lived live buffer in the database, cleared after a day, and pushes new samples to watching caregivers over a WebSocket. When the resident leaves, the visit's in-game movement is sent to a machine-learning model, which scores how closely each hand's movement resembles three patterns linked to Parkinson's, stroke and essential tremor. Only the in-game movement, the per-game results and the scores are kept, for building the caregiver dashboard that tracks each resident's movement from visit to visit.

## The model

The model is a small neural network (a temporal convolutional network in PyTorch) that reads the raw movement of each hand from Apple Picking and Harbour Fishing. For each of three patterns it gives a score from 0 to 100: the model's confidence that the visit looks like that pattern.

| What the model looks for | Sign of |
|---|---|
| Slower, smaller movements in both hands | Parkinson's |
| One hand weaker or slower than the other | Stroke |
| Rhythmic shake while moving | Essential tremor |

These scores drive the dashboard. A score of 50 or more marks a resident "Keep an eye on", and two visits in a row at 70 or more mark them "Check soon". The resident page charts the scores across visits next to the plain measurements, so a caregiver can see what changed and what it resembles.

**Why a model instead of fixed formulas?** Because these signs are hard to write down as formulas. Parkinson's slowness shows up as movements that shrink and slow as they continue [[4]](https://pubmed.ncbi.nlm.nih.gov/26474316/), and tremor as shake that appears only while the hand moves [[6]](https://utsouthwestern.elsevierpure.com/en/publications/consensus-statement-on-the-classification-of-tremors-from-the-tas). A formula would need a hand-picked cutoff for each of these, which would be guesses. The model instead learns each pattern from labelled examples.

The model was trained on recordings of the team acting out each pattern, plus synthetic data.

## What you can do

**Residents** sign up with a nickname, open the lobby and walk to a game:

- **Apple Picking:** steer a red glove and a blue glove to matching apples and drop them in the basket.
- **Harbour Fishing:** trace a fish's path with the rod tip, one hand at a time.
- **Rat Catching:** flick a stick to catch the target rat, and hold back for the others.

**Caregivers** sign up with the care team's access code, then:

- See every resident on one dashboard, marked "No concerns", "Keep an eye on" or "Check soon", plus who is playing right now.
- Watch a resident play live from any computer.
- Open a resident's page to see:
  - how each hand's reaction time, speed and steadiness change from visit to visit
  - each game's results: apples picked, time on the fishing path, rats caught
  - the model's 0–100 scores for slower movements, one hand weaker than the other, and shake, which correspond to signs of Parkinson's, stroke and essential tremor
- Ask the AI assistant about a resident, answered only from their recorded numbers.
- Download a one-page PDF report for a nurse or doctor.

## Research basis

**Game controllers have been used for this before.** Researchers have used off-the-shelf joysticks and game peripherals to assess movement disorders for years. A standard game joystick told people with Parkinson's apart from healthy adults, using tracking tasks much like Harbour Fishing [[1]](https://eprints.whiterose.ac.uk/2663). A joystick graded arm impairment in stroke survivors [[2]](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC2705666/), and reaching tasks picked up stroke most clearly as a difference between the two arms [[3]](https://pubmed.ncbi.nlm.nih.gov/20233965).

**What the model looks for comes from clinical criteria,** and each condition is common in older adults, where catching it early matters:

| Condition | Clinical sign the model looks for | How common |
|---|---|---|
| Parkinson's | Slowness, with movements that shrink as they continue [[4]](https://pubmed.ncbi.nlm.nih.gov/26474316/) | 6.1 million people in 2016, more than double 1990, driven by ageing [[7]](https://www.healthdata.org/node/6677) |
| Stroke | Weakness on one side of the body [[5]](https://cpr.heart.org/-/media/Files/Health-Topics/Answers-by-Heart/What-Are-the-Warning-Signs-of-Stroke.pdf) | Risk rises with age [[9]](https://www.cdc.gov/stroke/data-research/facts-stats/index.html) |
| Essential tremor | Shake in both arms while moving [[6]](https://utsouthwestern.elsevierpure.com/en/publications/consensus-statement-on-the-classification-of-tremors-from-the-tas) | About 1 in 20 people over 65 [[8]](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC8269764/) |

1. [Allen et al., 2007](https://eprints.whiterose.ac.uk/2663). Low-cost computer peripherals for assessing motor dysfunction in Parkinson's.
2. [Feng & Winters, 2009](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC2705666/). A joystick platform for upper-limb assessment after stroke.
3. [Coderre et al., 2010](https://pubmed.ncbi.nlm.nih.gov/20233965). Visually guided reaching in subacute stroke.
4. [Postuma et al., 2015](https://pubmed.ncbi.nlm.nih.gov/26474316/). MDS clinical diagnostic criteria for Parkinson's disease.
5. [American Heart Association](https://cpr.heart.org/-/media/Files/Health-Topics/Answers-by-Heart/What-Are-the-Warning-Signs-of-Stroke.pdf). Warning signs of stroke.
6. [Bhatia et al., 2018](https://utsouthwestern.elsevierpure.com/en/publications/consensus-statement-on-the-classification-of-tremors-from-the-tas). Consensus statement on the classification of tremors.
7. [GBD 2016 Parkinson's Disease Collaborators, 2018](https://www.healthdata.org/node/6677). Global burden of Parkinson's disease, 1990–2016.
8. [Louis & Ferreira, 2010](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC8269764/). Worldwide prevalence of essential tremor (the link is the 2021 update, which also reports the 2010 figure).
9. [CDC](https://www.cdc.gov/stroke/data-research/facts-stats/index.html). Stroke facts.

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

You need Node.js 20+, Python 3.14 with [uv](https://docs.astral.sh/uv/), a [Tiger Data](https://www.tigerdata.com/) service, Chrome or Edge, and a PS5 (DualSense) controller.

**1. Settings.** Copy `backend/.env.example` to `backend/.env` and fill it in. Do not commit `.env`.

| Variable | What it is |
|---|---|
| `DATABASE_URL` | Your Tiger Data connection string |
| `CAREGIVER_INVITE_CODE` | An access code you choose. Caregivers must enter it to sign up, because they can see every resident's results |
| `GEMINI_API_KEY` | Optional. Turns on the Gemini assistant and the written part of the PDF |

No Tiger Data account? Any Postgres with TimescaleDB works, for example a local one in Docker, with `DATABASE_URL=postgresql://postgres:postgres@localhost:5432/stickdrift`:

```bash
docker run -d --name stickdrift-db -p 5432:5432 -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=stickdrift timescale/timescaledb:2.17.2-pg16
```

**2. API.** From the repository root:

```bash
uv sync                                  # pattern model and hand replays (torch, numpy, ...)
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --port 8000         # creates the tables on first start
```

**3. Website.** In a second terminal, from the repository root:

```bash
cd web
npm install
npm run dev
```

Open `http://localhost:5173`. Sign up as a resident and open the lobby from the home page. In a private window, sign up as a caregiver at `/caregiver/signup` with your access code to watch the resident play live.

> [!NOTE]
> Without `GEMINI_API_KEY`, the assistant answers from fixed rules and the PDF uses template wording. Without an access code, run `python -m scripts.create_caregiver` in `backend/` for a caregiver login. On Windows, set `STICKDRIFT_ML_PYTHON` in `backend/.env` to the full path of `.venv\Scripts\python.exe`, or visits won't get model scores.

To run the tests from the repository root:

```bash
backend/.venv/bin/python -m unittest discover -s tests/backend -t .
MPLBACKEND=Agg .venv/bin/python -m unittest discover -s tests/ml -t .
cd web && npm test && npm run lint && npm run build
```

## Scope and limitations

- Stick Drift is a hackathon prototype, not a medical device, and it has not been clinically validated. The thresholds are design choices, not clinical cutoffs.
- The pattern model was trained only on the team acting out each pattern and on synthetic data, never on patients.
- A change in results can come from tiredness, medication, eyesight, unfamiliarity with game controllers or a faulty controller, not only a change in health.
- Timing is measured in the browser at about 60 samples per second, so it includes display and network delay and is not precise to the millisecond.
- Motion sensors need a PS5 controller in Chrome or Edge. Other gamepads drive the sticks only.
