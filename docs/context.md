# Stick Drift — what it is and how it fits together

> Living document for the team and any coding agents helping us. Last updated: 2026-10-25 (America/Toronto). `README.md` has setup, the API and the project layout. Record decisions in the log at the bottom rather than silently changing the mission or the boundaries.

## 1. What Stick Drift is

Stick Drift is a set of **short, enjoyable controller games** that can be repeated in a senior-living or long-term-care home. A resident walks grandma around a small 3D garden lobby in the browser and plays three games with the two thumbsticks of a PS5 controller: Apple Picking, Harbour Fishing and Rat Catching. The app measures how each hand moves (reaction time, time to reach a target, how closely the hand follows a lane, leftover shake) and shows those measurements to the **care team**, live and across visits. Its promised output is **"a change worth checking,"** never a diagnosis, predicted disease or emergency determination. A nurse or caregiver supplies the interpretation and decides what to do next.

**Users.** Residents only play: they never see scores, history or health measurements. Care team members (nurse, CNA, wellness director, therapist) watch live, review each resident's visits and read concerns with recommended checks. Clinicians can receive a PDF summary.

**Why a controller.** An inexpensive, standard controller gives the same left- and right-thumb input every visit and continuous stick position, not just button presses. It is a prototype interaction device, **not a clinically validated instrument**: it cannot measure grip strength, true tremor or a specific illness, and both hands are on one device.

## 2. Boundaries

1. Stick Drift is an **observation and review tool**, not a diagnostic, treatment or emergency-response device. The pattern model's internal keys are condition names only because of how its training folders are labelled; **everything a caregiver, the assistant or the PDF shows uses neutral movement labels**, and the assistant and report refuse every condition name.
2. A change may come from tiredness, sleep, medication, vision, unfamiliar games, how the controller was held or a faulty controller. Concerns list these everyday contributors and recommended checks.
3. Preserve comparability: every visit stores its protocol version (`lobby-v1`). A change to a game's targets, timing, speed or scoring that affects movement needs a new version and its own history.
4. Age-respectful design: large targets, high contrast, adjustable sound, clear instructions, no shame for missing, an easy exit. Per-player scores and stars in the lobby are personal bests, not a leaderboard.
5. No camera or hidden biometric collection. The DualSense's gyroscope and accelerometer may feed the pattern model, shown only as resemblance to a movement pattern, **never as tremor detection**.
6. A sudden new neurological symptom needs ordinary urgent clinical procedures; nobody should wait for the game or a score.

## 3. How a visit flows

```
Resident laptop                                           Caregiver (any computer)
Browser: lobby + games (Gamepad API, WebHID motion)       Browser: dashboard, live view, resident page
   │ samples + events, ~10 POSTs/s, with a token             ▲ WebSocket (push)
   ▼                                                         │
FastAPI ──INSERT + NOTIFY──► Tiger Data ◄──LISTEN / reads── FastAPI
             live_sessions, live_samples, live_events
                    │ visit ends
                    ▼
     sessions, session_summaries, raw_samples ──► visit report + hand replay (ml/, Python 3.14)
```

1. **Log in.** A resident signs up with a username, password and dominant hand; caregivers register with an access code (`CAREGIVER_INVITE_CODE`) or use `scripts/create_caregiver.py`. argon2id passwords, an HttpOnly session cookie, two roles (`backend/app/auth.py`).
2. **Play.** The resident home opens `/lobby.html` (`web/lobby/`). `measure.js` reads each game's state without changing it and `live.js` streams 17-value samples (plus 6 motion values when the pad reports them over WebHID) and game events to `/live/ingest`.
3. **Live session.** Each request loads the session row from Tiger Data, applies the batch and writes it back in one transaction (`backend/app/live/session.py`), so any API process can serve any request and a restart doesn't lose a visit. The running per-hand measurements come from `backend/app/measurements.py`.
4. **Watch.** The caregiver's API `LISTEN`s for Postgres notifications and pushes samples over a WebSocket (`live/stream.py`); the page plays them back through a 150 ms buffer (~0.1 s stick-to-screen), falling back to server reads and then polling.
5. **Save.** When a game ends, the visit so far is copied to the resident's history; when the tab closes (or goes quiet for 60 s) the visit is closed (`live/visit.py`). It becomes one `sessions` row; only in-game samples (no lobby walking or menus) go to `raw_samples`, tagged by game.
6. **Score.** The visit's samples and events are read back and two subprocesses run in the root uv environment: `ml.visit_report` (pattern scores for Apple Picking and Harbour Fishing, Rat Catching counted from its events, per-trace details) and `ml.hand_replay.from_capture` (a short reconstructed-hands GIF). A report lost mid-way is re-run by a later sweep.
7. **Review.** The resident page (`web/src/pages/ResidentDetail.tsx`) shows the overview and concerns, trends per game and hand, every game visit with its hand replay, and the assistant. The clinician PDF (`backend/app/clinician_report.py`) summarizes the same facts.

## 4. The games and what is measured (`lobby-v1`)

The games use **velocity control**: the stick steers an in-game glove or lure. Distance from target compares the in-game hand with its target (normalised to −1…1 of the play area), while speed, push and shake are read from the stick itself. Keyboard play works and every visit played that way is labelled **keyboard input** and left out of baselines; a visit first marked keyboard is corrected once analog stick values show up.

| Game | Attempt / phase | Measurements per hand |
| --- | --- | --- |
| Apple Picking (both hands at once) | One attempt per apple: from an apple of that glove's colour being available until the glove grabs it; an apple that disappears first is a miss | Apples picked/total, time to pick, reaction time, peak stick speed, peak push |
| Harbour Fishing (one hand at a time, alternating) | Tracking while tracing a lane | Distance from the lane, share of time on the lane (the game's own lane width), shake and its rhythm in Hz |
| Rat Catching (either hand flicks up) | One attempt per target rat: from the rat appearing until the slam; the stick pushed up furthest gets the credit | Target rats caught, time to slam, reaction time, peak speed |

Left-right differences are computed for every measurement both hands produce. `measurements.py` is the only definition of shake, tracking error and the per-hand reach numbers; the end-of-visit report imports it.

**Caveats.** Browser samples are ~60 Hz and include display, USB/Bluetooth and network delay, so don't claim millisecond precision. Measurements mix seeing, deciding and moving; none is a pure motor measure. Raw signals, per-attempt results and the protocol version are kept so measurements can be recomputed if the logic changes.

## 5. Insights: baseline, concerns, pattern model, assistant

**Personal baseline (`backend/app/insights.py`).** From the fourth game visit with the controller, the latest visit (the latest two from the fifth) is compared with the median of the resident's earlier visits, per game and hand: reaction time, time to reach, distance from the lane, time on the lane. A change counts when it clears both an absolute step (0.15 s, 0.03 of the play area, 10 points on the lane) and 20%. Changes in both hands give "Slower or less accurate in both hands"; one hand gives "One-sided change", each with everyday contributors and recommended checks. A change in both recent visits makes it "check soon".

*Still to adopt:* a robust spread instead of fixed steps, quality gates (disconnects, changed controller) and a documented baseline reset after review.

**Pattern model (`ml/pattern_model/`, built by a teammate).** A temporal convolutional network scores each hand's movement stretches and fuses them into three 0–100 resemblance scores: slower, smaller movements in both hands; one hand weaker or slower than the other; rhythmic shake while moving. It is trained on **teammate-acted** and **synthetic** recordings only, there is no clinical data, and no held-out evaluation is recorded. The checkpoint is committed (`ml/runs/pattern_model/model.pt`). One visit at 50 or more is "keep an eye on"; "check soon" needs the two latest scored visits at 70 or more. These thresholds are untested choices.

**Assistant (`backend/app/assistant.py`).** Gemini receives only structured facts built from the database (measurements, changes, concerns, checks, recent visits) and answers caregiver questions. Every number in an answer is checked against the facts, condition names withhold the answer, and a rule-based answer is used if the API key is missing or Gemini fails. The clinician PDF uses the same facts and checks.

## 6. Data

`backend/sql/schema.sql` is the only definition of the schema; the API applies it at startup and it never drops anything, so older databases keep tables the app no longer uses.

- **Accounts:** `participants` (residents: alias, username, hashed password, dominant hand), `caregivers`, `auth_sessions` (role `'senior'` means resident).
- **Visits:** `sessions` (`mode = free_play`, `protocol_version = lobby-v1`, `is_synthetic` = keyboard input), `session_summaries.metrics` = `{games: {apple|fish|rat: {hands, left_right_difference_pct, attempts, samples, play_s, finished}}, games_finished, reach_trials, tcn, visit}`, `raw_samples` (hypertable of in-game samples), `session_hand_replays` (one GIF per visit).
- **Live sessions:** `live_sessions` (state, token hash, running measurements), `live_samples` (every streamed sample, including lobby walking), `live_events`; pruned after a day, after any unsaved visit has been saved.

**Privacy.** Pseudonyms only; no camera or audio; only caregivers see results; caregiver registration needs an access code. Data leaves the laptop because Tiger Data is a cloud service, so profiles must never hold real names or health details. Keep the connection string in `backend/.env` (git-ignored).

**Hardware.** One DualSense per resident laptop, Chrome or Edge, a USB-C cable that carries data (Bluetooth works with more latency). Chrome only exposes a gamepad after a button is pressed. Don't use haptics, adaptive triggers or the light bar while measuring unless they are identical every visit.

## 7. Not built yet

- **Review workflow:** concerns are shown, but staff can't record acknowledged / needs assessment / dismissed with a reason yet. The app never notifies family, writes a medical record or diagnoses.
- **Evaluation:** compare lobby measurements with observed play, report the model's evaluation by participant, check false concerns on routine visits.
- **Per-resident personal bests:** the lobby keeps best scores in the browser under one placeholder player (`web/lobby/scores.js`, `setPlayer` is the hook), so residents sharing a laptop share them.
- **Training data export:** training reads local recordings under `data/`; the API no longer writes recording files, so retraining on new visits needs an export from `raw_samples`.

## 8. Open questions

- When does a lobby game change need a new protocol version? Teammates tune rat speed, fishing rounds and lane position.
- One Python environment or two? The backend (`backend/requirements.txt`) and the root uv environment (Python 3.14, torch) are separate on purpose today; the API calls the latter as subprocesses.
- Is holding the controller comfortable for someone with reduced dexterity, or should it rest on a table?
- Can we recruit consenting older adults and care staff for feedback? Without them, usability conclusions are preliminary.

## 9. Evidence and references

These sources inform the direction; none validate *this joystick protocol*.

1. Hack the Valley 11 [PointClickCare: Catch It Early brief](https://hack-the-valley-11.devpost.com/), the challenge Stick Drift was built for.
2. MDN [Gamepad API](https://developer.mozilla.org/en-US/docs/Web/API/Gamepad_API) and the W3C [standard gamepad mapping](https://w3c.github.io/gamepad/#remapping), used by the browser reader.
3. [Tiger Data documentation](https://docs.tigerdata.com/) for service setup, connection strings and hypertables.
4. [Balance Assessment Using Gamified Digital Technology in Community-Dwelling Older Adults](https://games.jmir.org/2026/1/e80747/): 30 older adults, gamified versus plain digital assessment, higher reported enjoyment and intention to continue; single-session and balance-task findings do **not** prove long-term joystick adherence.
5. [Evaluating the User Experience and Usability of Game-Based Cognitive Assessments for Older People](https://aging.jmir.org/2025/1/e65252/): review of eight studies; accessibility, appropriate difficulty, and user-centered design matter; game elements do not universally improve experience or measurement.
6. [Exergames versus self-regulated exercises during geriatric rehabilitation](https://pubmed.ncbi.nlm.nih.gov/28330455/): a counterexample in which conventional exercises had better adherence, enjoyment, and motivation than the exergame.
7. [Neurological assessment overview](https://www.ncbi.nlm.nih.gov/books/NBK596731/): clinical examinations may include rapid alternating movements, but this joystick task is **inspired by the general idea of comparing movements** and is not an implementation of a validated examination.
8. PyTorch [building models with `torch.nn`](https://docs.pytorch.org/tutorials/beginner/basics/buildmodel_tutorial) for an optional, honestly evaluated ML experiment.

## 10. Decision log

| Date | Decision | Reason / revisit condition |
| --- | --- | --- |
| 2026-10-16 | Lead with older adult and care-team experience for PointClickCare. | Matches the sponsor's stated senior-care workflow. Revisit for a separate pediatric product after the hackathon. |
| 2026-10-16 | ~~Use two existing thumbsticks and Arduino over USB serial.~~ Superseded below. | — |
| 2026-10-16 | Establish a personal controlled baseline and flag **change worth checking**. | Honest with available data; human review is the product outcome. |
| 2026-10-16 | Rules first; PyTorch anomaly prototype only if data and validation permit. | Avoid impressive-sounding but unsupported disease labels. |
| 2026-10-16 | **Use a PS5 DualSense controller instead of Arduino + thumbstick modules.** | No wiring or serial parsing; same four axes; familiar, sturdy device. Revisit if holding it is too hard for target users. |
| 2026-10-16 | **Use Tiger Data (Postgres + TimescaleDB) instead of local SQLite.** | Shared database for the team; hypertable for raw samples. Consequence: data leaves the laptop, so pseudonyms only. |
| 2026-10-16 | Name the fixed assessment protocol `assess-v1`. | Every session stores its protocol version; any change to blocks, timing or thresholds needs a new version and its own baseline. |
| 2026-10-16 | DualSense IMU (gyro/accelerometer) is recorded by the HID tool but excluded from v1 metrics. | Too easy to oversell as tremor detection; not part of the validated-by-us task. |
| 2026-10-17 | Add Garden Rescue (`garden-v1`) as a fixed-course data-collection game for teammate-simulated movement patterns, separate from `assess-v1`. | Position-mapped sticks (not velocity) so reduced range shows up; no random layouts so recordings are comparable. The game only records; a teammate builds the model. Labels are demo tags, never diagnoses. |
| 2026-10-17 | Garden Rescue `garden-v2`: shorter (4 levels, ~60-90 s), easier (bigger tolerances, slower near-round butterfly), friendlier garden visuals and wording, both sticks at once with mirrored targets for apples and watering, butterfly one stick per level; one data folder per level. | v1 felt too hard, too long and like a clinical test. Butterfly stays one-handed because two-stick tracking was the hardest part. v1 and v2 recordings are not comparable. |
| 2026-10-17 | Two roles with separate logins: residents (self sign-up) and caregivers (access code). Residents never see scores or history. | Keeps results with the care team; residents just play. |
| 2026-10-17 | Use Tiger Data as the link between laptops for live sessions; push to caregivers over a WebSocket fed by Postgres `LISTEN/NOTIFY`, with server-side reads as a fallback. | The resident's and caregiver's laptops share nothing else. Polling every 250 ms per viewer was replaced; latency ~0.1 s. |
| 2026-10-17 | **Remove the browser arrow game (`assess-v1`) and everything tied to it.** Old arrow-style demo sessions stay as "Earlier sessions". | The team chose games over an arrow test. Revisit only if a fixed short assessment is needed again. |
| 2026-10-17 | **The web 3D lobby (`lobby-v1`) is the resident experience;** the site opens it instead of the pygame garden. | Teammates built it; it runs in the browser on any laptop. The garden stays as the model's data source. |
| 2026-10-17 | Measure lobby games from their state with a read-only observer (`measure.js`), using the in-game hand for distance and the stick for speed and shake. | The games are velocity-controlled; teammates' game files stay untouched. |
| 2026-10-17 | Save every lobby visit to history, but copy only in-game samples to `raw_samples`, tagged by game. | Caregivers need history; lobby walking and menus would pollute training data. |
| 2026-10-17 | The pattern model now has five patterns; show only neutral movement labels and keep model scores out of any diagnostic wording. | Its keys are condition names from training folders; the product must still never name a disease. |
| 2026-10-25 | **Neutral labels are the policy.** The code had drifted to showing "Model pattern: Parkinson's / Stroke"; caregivers, the assistant and the report now see only neutral movement labels, and every condition name is refused. | Restores §4.1. |
| 2026-10-25 | **Motion data (gyro/accelerometer) may feed the pattern model.** Supersedes the 2026-10-16 exclusion. | The model already reads it; its output stays pattern resemblance, never tremor detection. |
| 2026-10-25 | Live sessions live in Tiger Data instead of the API's memory; the API no longer writes lobby CSVs to disk. | Restarts and more than one worker no longer drop visits; one copy of each visit, linked to the resident. Training reads local recordings. |
| 2026-10-25 | **Remove the pygame garden game and the Blender lobby** (the old `legacy/` folder) and the API route that launched the garden. | The browser lobby replaced both; imported garden visits stay viewable. |
| 2026-10-25 | Lobby visits set the personal baseline; "check soon" from the pattern model needs two judged visits in a row. | One noisy visit should not raise the strongest prompt. |
| 2026-10-25 | Remove the garden from the app entirely (its visits, panels and import) and the arrow-test "Earlier sessions" (demo data, table, charts, comparison cards, sparkline). | Neither is played any more; lobby visits are the only data shown and the only baseline. Nothing was dropped from the database. |
| 2026-10-25 | Clean-up pass: one vocabulary in code (resident, visit), the live API split into `backend/app/live/`, one schema file applied at startup, components and styles grouped by area. | Easier to read and navigate; no behaviour change beyond the removals above. |

**Editing rule:** When the app changes, update the sections above and add a row here rather than silently changing the mission or the boundaries.
