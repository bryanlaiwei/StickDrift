# Stick Drift — project context and scope guardrails

> Living document for the Hack the Valley 11 team and any coding or research agents helping us. Last updated: 2026-10-25 (America/Toronto). Change decisions in the log at the bottom rather than silently changing the mission.
>
> **Read §0 first** for what is actually built. Sections 1–13 are the plan and the guardrails. `README.md` has setup steps, the API and the project layout.

## 0. Current build state (2026-10-25)

**The product pivoted from the planned arrow assessment (`assess-v1`) to games.** Residents play a **web 3D lobby** with three games (Apple Picking, Harbour Fishing, Rat Catching) in the browser with a PS5 controller. Caregivers on any computer watch live and review each resident's visits. The arrow game was built briefly in the browser, then removed (§13). The pygame **Mabel's Moonflower Garden** remains as a desktop game whose recordings train the pattern model.

**Hardware:** one Sony DualSense (PS5) controller per resident laptop, read through the browser Gamepad API (~60 Hz). The Python HID reader (~500 Hz) is used by the garden game.

**Database:** Tiger Data (managed PostgreSQL + TimescaleDB). It is also the only link between laptops: live sessions are shared through it.

| Area | State | Where |
| --- | --- | --- |
| Accounts | **Built.** Residents sign up with a username, password and dominant hand. Caregivers register with an access code (`CAREGIVER_INVITE_CODE`) and have their own login pages. argon2id passwords, HttpOnly session cookie, two-role guard. | `backend/app/auth.py`, `backend/sql/auth_schema.sql`, `web/src/pages/AuthPage.tsx` |
| Resident home | **Built.** One button opens the web lobby in a new tab. Residents see no scores or history. | `web/src/pages/Home.tsx` |
| Web 3D lobby + games (`lobby-v1`) | **Built by a teammate; played with real controllers.** three.js lobby, three games, scores/stars for the resident, synthesised sound. | `web/lobby/`, `web/lobby.html` |
| Lobby measurement | **Built.** `measure.js` reads each game's state (read-only) and sends in-game hand and target positions with every sample, plus one result per attempt (apple picked, rat slammed). Server turns these into per-hand reach, tracking and shake measurements. | `web/lobby/measure.js`, `backend/app/measurements.py` |
| Live view across laptops | **Built and tested across two APIs.** Lobby → resident's API → Tiger Data `live_sessions`/`live_samples` + Postgres `NOTIFY`; caregiver's API `LISTEN`s and pushes over a WebSocket; the page plays samples back through a 150 ms buffer. ~0.1 s stick-to-screen. Falls back to server-side reads (0.15 s) if no notifications arrive, and to polling if the WebSocket can't connect. A session's state, token hash, running measurements and in-game events live in Tiger Data (`live_sessions`, `live_samples`, `live_events`), so any API process can serve any request and restarting the API doesn't drop a visit in progress. | `backend/app/live.py`, `backend/app/live_stream.py`, `web/src/components/useLiveFeed.ts`, `web/src/pages/LiveSession.tsx` |
| Lobby history | **Built.** Each finished visit becomes a `lobby-v1` session with per-game, per-hand results; only in-game samples (no lobby walking, menus or countdowns) are copied to `raw_samples`, tagged by game. Unsaved visits are swept on caregiver views and before the live buffer is pruned. Earlier visits from 2026-10-17 were backfilled. | `backend/app/live.py` (`save_lobby`) |
| Caregiver dashboard | **Built.** Residents with risk badges, who is playing now, recently finished visits; the AI assistant and the teammate's garden-recordings panel sit in collapsible tools. | `web/src/pages/CaregiverDashboard.tsx` |
| Resident page | **Built.** Overview (status banner, potential concerns with evidence, recommended checks, possible reasons, research basis), Trends (per-game lines per hand across visits; garden and earlier sessions when present), Game visits, Garden visits, Ask the assistant. | `web/src/pages/ResidentDetail.tsx` |
| Rule-based insights | **Built.** Lobby game visits are the personal baseline: the latest 1–2 controller visits against the median of earlier ones, per game and hand (reaction time, time to reach, distance from the lane, time on the lane); needs 4 visits, keyboard visits left out. Demo residents' older session summaries stand in when there are too few visits. | `backend/app/insights.py` |
| AI assistant | **Built.** Gemini (`gemini-3.8-flash` with fallbacks) answers from structured facts only; numbers not in the facts are flagged, disease names trigger a clinician referral, and a rule-based answer is used when Gemini is unavailable. | `backend/app/assistant.py` |
| Pattern model (TCN) | **Built by a teammate; checkpoint committed (`ml/runs/pattern_model/model.pt`).** Scores garden and lobby recordings 0–100 for resemblance to three patterns, keyed `parkinson`, `stroke`, `essential_tremor`. Caregivers and the assistant see only neutral movement labels (§4.1). One visit ≥ 50 is "keep an eye on"; "check soon" needs the two latest judged visits ≥ 70. These thresholds are untested choices. No held-out evaluation is recorded. | `ml/pattern_model/`, `ml/pattern_model/score_garden.py` |
| Mabel's Moonflower Garden (`garden-v3`) | **Implemented and played with real controllers.** Four chapters, full-rate HID CSV per level, imported into Tiger Data. The API can still launch it (`/me/garden/launch`, with live streaming and model judging at the end), but the site no longer links to it. | `legacy/garden/` |
| Blender lobby | **Built by a teammate (Windows only).** Design reference; sends no data. | `legacy/blender_lobby/` |
| Synthetic demo data | **Built.** Demo Resident A/B with 7 labelled-synthetic arrow-style sessions each, shown as "Earlier sessions". | `backend/scripts/seed_synthetic.py` |
| Review-card workflow (acknowledge / needs assessment / dismiss with note) | **Not built.** Concerns are shown but staff can't record an outcome yet. | — |

**Run it:** see `README.md` → *Running locally*. Each laptop needs `backend/.env` with the Tiger Data connection string (copy `backend/.env.example`). Never commit `.env`. After pulling, restart both the API and the web dev server.

**Python environments:** the root `uv` project (Python ≥ 3.14: `hidapi`, `pygame-ce`, `torch`, `numpy`) runs the garden game and the pattern model. The backend uses `backend/requirements.txt` in `backend/.venv` (tested on 3.9) and calls the root environment for scoring.

## 1. The project in one paragraph

Stick Drift is a set of **short, enjoyable controller games** that can be repeated in a senior-living or long-term-care setting. A resident walks a character around a small 3D lobby and plays games such as picking apples with two gloves, tracing a fish through a harbour, or catching rats, using the two thumbsticks of a PS5 controller. The software measures how each hand moves: reaction time, time to reach a target, speed, how closely the hand follows a path, and leftover shake. It shows those measurements to a **care team**, live and across visits, with supporting data. Its promised output is **"a change worth checking,"** never a diagnosis, predicted disease, or emergency determination. A nurse or caregiver supplies the interpretation and decides what to do next.

## 2. Mission, user, and why it matters

**Mission:** Make a brief movement and attention check pleasant enough to repeat, and make changes visible early enough for a care team to follow up. We are testing whether an accessible game can collect useful, consistent observations without feeling like yet another clinical test.

**Primary user:** Older adult living in a senior-care setting. **Primary customer/workflow user:** Care team member (nurse, CNA, wellness director, therapist). **Secondary stakeholders:** Family and clinicians, if the care facility chooses to share information. **Possible future audience:** Children in pediatric rehabilitation; this is *not* the lead story for the PointClickCare sponsor challenge.

**The gap:** Staff have limited time to notice subtle changes between formal assessments. A one-off reaction score means little; a repeated, standardized activity may reveal a change relative to the resident's own pattern. Game design may help participation, but engagement is a hypothesis we should test, not a fact to assume.

**Value loop:** Resident plays → calibrated movement events are recorded → features are compared against a personal baseline → an explainable, appropriately cautious review prompt reaches the care team → a human records context and follows up.

**Why the physical interface matters:** A standard, inexpensive controller gives the same left- and right-thumb input every session and a tangible live demo. We record continuous stick position, not just button presses. The controller is a prototype interaction device, **not a clinically validated neurologic instrument**. It cannot directly measure grip strength, applied pressure, true hand tremor, posture, or a specific illness. Both hands are on one device, so the hands are not mechanically independent the way two separately mounted sticks would be; record how the controller was held or placed.

## 3. Track fit and judging story

| Prize / track | Fit | What the demo must prove |
| --- | --- | --- |
| **PointClickCare: Catch It Early** | **Primary**. Its brief explicitly asks for an AI-powered solution that helps a nursing-home/senior-living **care team** notice a health risk before an emergency. Our narrower use case is a new change in hand movement or response pattern worth follow-up. | A caregiver receives a useful, evidence-linked review card, sees how today's measurements differ from the resident's own history, records an observation, and can dismiss or escalate the prompt. A game alone does not satisfy this track. |
| **Best Healthcare & Well-being Hack** | Strong secondary fit: accessible resident experience plus measurable caregiver workflow. | A working physical interface, a usable resident experience, trustworthy measurement and honest limits. |
| **Best AI for Social Impact Hack** | Possible if the AI adds a defensible capability to early review or usable summaries. | Compare the AI layer with a simple baseline, show actual measured numbers and failure handling; avoid a decorative chatbot. |
| **Best Use of Gemini API** | Optional only if we actually use Gemini meaningfully, such as a grounded narrative summary from structured measurements and care notes. | Demonstrate a faithful explanation with source values, and a deterministic fallback when the API is unavailable. Do not switch models just to claim a sponsor prize. |

Hack the Valley's judging also emphasizes technical quality, design, impact, presentation, inspiration, and authenticity. A polished, honest end-to-end story beats an unsupported disease classifier. The School of Cities challenge requires a Toronto civic problem grounded in urban data; **this product does not naturally fit that track**. Do not force that claim.

**Four-minute demo arc:** (1) A resident logs in on one laptop and plays the lobby games on the controller. (2) On a second laptop, a caregiver watches the sticks, distance from target and measurements update live. (3) The visit ends and appears in the resident's history with per-hand results and trends across earlier visits. (4) Open a resident with a clearly labelled *simulated* history and show a potential concern: what changed, what to check, possible everyday reasons. (5) Ask the assistant a question and show that it answers with recorded numbers and says **check in**, never "Parkinson's detected." Any numbers shown are illustrative, not clinical cutoffs.

## 4. Non-negotiable product boundaries

1. The product is an **observation and review tool**, not a diagnostic, treatment, or emergency-response device. No model output names stroke, Parkinson's, MS, dementia, or another disease from joystick performance. The pattern model's internal keys are condition names because of how its training folders are labelled; **everything a caregiver or the assistant sees uses neutral movement labels**, and the assistant's answers are checked for disease names.
2. A change may be caused by fatigue, sleep, medications, vision, instructions, unfamiliarity with games, device placement, or a faulty controller. The interface shows context and confidence/quality rather than hiding uncertainty.
3. Preserve comparability: every session stores a protocol version (`lobby-v1`, `garden-v3`), and a change to a game's targets, timing, speed or scoring rules that affects movement needs a new version and its own history. Teammates are actively tuning the lobby games (for example rat speed, number of fishing rounds), so compare visits across such changes with care. Do not automatically increase difficulty and then compare raw results.
4. Do not use childlike visuals or a competitive leaderboard for the older-adult pitch. Make the experience age-respectful: large targets, high contrast, adjustable sound, clear instructions, no penalty or shame for missing, an easy way to leave a game. The lobby's per-player scores and stars are personal bests, not a leaderboard, and residents never see their health measurements.
5. No hidden camera or biometric collection is required. The DualSense also reports gyro, accelerometer and touchpad data. **Motion data may feed the pattern model, and its output is shown only as resemblance to a movement pattern; never present motion data as tremor detection.** Use synthetic, clearly labeled data for any multi-day change we cannot actually observe during the hackathon.
6. A sudden new neurological symptom in real life warrants ordinary urgent clinical procedures; no one should wait for the game or an AI score.

## 5. Game and measurement protocol

The fixed arrow assessment (`assess-v1`) planned here was never kept; see §13. The protocols in use are:

### Web lobby (`lobby-v1`)

1. The resident logs in on their own laptop and opens the lobby from the home page. Chrome or Edge only exposes the controller after a button press; keyboard play is allowed and every visit played that way is labelled **keyboard input**. A visit first marked keyboard is corrected to controller when analog stick values show up.
2. Walking around the lobby, menus, countdowns and result screens are streamed for the live view but **never saved for analysis**. Only samples with a game phase (`cue`/`carry` in apples, `track` in fishing, `run` in rats) are copied to `raw_samples`.
3. The games use **velocity control**: the stick steers an in-game glove or lure. Distance from target therefore compares the in-game hand with its target (normalised to −1…1 of the play area), while speed, push and shake are read from the stick itself.

| Game | Attempt / phase | Measurements per hand |
| --- | --- | --- |
| Apple Picking (both hands at once) | One attempt per apple: from an apple of that glove's colour being available until the glove grabs it; an apple that disappears first is a miss | Apples picked/total, time to pick, reaction time (stick pushed toward the apple, only counted if it wasn't already heading there), peak stick speed, peak push |
| Harbour Fishing (one hand at a time, alternating) | Tracking while tracing a lane | Distance from the lane, share of time on the lane (the game's own lane width), shake (wobble left after removing the slow path) and its rhythm in Hz |
| Rat Catching (either hand flicks up) | One attempt per target rat: from the rat appearing until the slam; the stick pushed up furthest gets the credit | Target rats caught, time to slam, reaction time, peak speed |

Left-right differences are computed for every measurement both hands produce. Each visit is stored with its per-game summaries (`session_summaries.metrics.games`) and every attempt (`reach_trials`).

### Mabel's Moonflower Garden (`garden-v3`)

Position-controlled (stick position is the cursor), fixed course, four chapters: apples with both hands (mirrored targets), a left-hand butterfly, a right-hand butterfly, watering with both hands. Records every HID report (~500 Hz) per chapter to CSV/JSON; story screens and breaks are not recorded. These recordings, played by teammates simulating movement patterns, are the pattern model's training data. Keep `garden-v2` and `garden-v3` separate.

### Caveats that apply to both

- Browser samples are ~60 Hz and include display, USB/Bluetooth and network delay; do not claim millisecond precision. Use a USB-C data cable where possible.
- Measurements mix seeing, deciding and moving; none is a pure motor measure.
- Keep raw signals, per-attempt results and protocol version so measurements can be recomputed if the logic changes.

## 6. Establishing a controlled personal baseline

**A baseline is the person's own stable reference under a fixed protocol, not a population-wide “healthy” score.**

*Status (2026-10-25):* implemented for lobby visits (`insights.analyze_lobby`): median of earlier controller visits as the reference, the latest one or two visits compared against it, needs 4 visits. Robust spread, quality gates and resets are not built yet.

1. **Hardware/calibration baseline:** With both sticks untouched, gather 1–2 seconds of readings per axis for centers and neutral jitter. Move each axis slowly in both directions to find comfortable, observed ranges; store controller-specific calibration. Recheck each session. If the center or range shifts substantially, re-calibrate and mark the session as potentially noncomparable.
2. **Practice effect:** Run unscored practice first. If the person is still learning the controls, record “baseline pending.” Avoid treating the first game ever as a stable reference.
3. **Controlled sessions:** As a proposed starting protocol, collect at least **3 separate sessions over 2–3 different days**, with the same block definitions, prompt windows, display, controller, placement, connection type, and assistance policy. These numbers are design choices to be tested, **not published clinical thresholds**. Record time of day, dominant hand, assistive needs, interruptions, tiredness/pain or other context if voluntarily supplied. Repeat the exact protocol on follow-up days.
4. **Quality gates:** Reject or flag a session with disconnects, dropped reports, bad neutral calibration, too many unreadable trials, a changed controller, or interrupted instructions. Do not interpret missed sessions as declining health.
5. **Compute reference:** For each feature, take the median of session summaries as center; compute a robust spread (for example `1.4826 × median(|x - median(x)|)`), with a floor informed by instrument noise to avoid dividing by zero. Retain the actual session range and count. Separate baseline by protocol version; store controller ID, connection type, calibration, and assistance status.
6. **Review logic:** Compare later sessions to the personal reference; show raw values, absolute change, baseline range, and context. A prototype rule might request review when **two distinct reliable metrics move materially in the same direction**, or when a large within-person change repeats on the next valid session. Exact cutoffs require validation and false-alert measurement; do not represent illustrative thresholds as medical cutoffs. Allow a human to review a sudden large shift immediately even if there is no second session.
7. **Updating:** Do not automatically absorb flagged values into the baseline. After caregiver review, a clinician-approved or explicitly documented reset may establish a new reference; retain the earlier history.

**Hackathon reality:** We cannot gather a real multi-day resident baseline during 36 hours. We can demonstrate a short **engineering baseline** from three standardized rounds with consenting adult teammates, explicitly labeled nonclinical, and use a **clearly labeled synthetic multi-day timeline** to show the intended dashboard (`backend/scripts/seed_synthetic.py`; every row has `is_synthetic = true` and the UI labels it). Never present fabricated patient measurements as collected evidence.

**More meaningful controlled comparison for the demo:** Have a few consenting teammates complete the identical task under two conditions—normal and, for example, a deliberate alternate-hand or distracted **demo condition**. Show that the signal pipeline reflects the condition, while acknowledging that this does not simulate disease and is not clinical validation. If testing enjoyment, compare a plain prompt screen with the gamified one on the same fixed motor protocol; record participant preference and completion, while controlling for order.

## 7. Hardware and software architecture

### Hardware

**Confirmed:** one Sony DualSense (PS5) controller per resident laptop (macOS or Windows), and Chrome or Edge. **Needed:** a USB-C cable that carries **data** (not charge-only). No Arduino, wiring, camera, or extra sensors are needed for v1.

- **Connect over USB-C for assessments.** Bluetooth works with both readers but adds latency and jitter. Record the connection type on every session (`sessions.connection`).
- **Same controller for baseline and follow-ups.** Record a controller ID on every session (`sessions.controller_id`).
- **Placement:** in hands, on a table, or on a lap. Test what is comfortable for someone with reduced dexterity, use it consistently, and record it (`sessions.placement`).
- **Browser reader:** Chrome only exposes a gamepad after a button on it is pressed. The lobby's start screen asks for a button press first, and visits are corrected from "keyboard" to "controller" once analog stick values arrive. The standard mapping puts the left stick on axes 0/1 and the right stick on 2/3. DualSense is vendor `054c`, product `0ce6` (Edge: `0df2`).
- **Python HID reader:** `uv run "legacy/garden/read_data.py"` (or `pip install hidapi`). Shows a live viewer; press **R** to record a CSV, **Esc** to quit. Only one program may hold the HID device; close it before another reader opens the controller.
- **Do not use haptics, adaptive triggers or the light bar in assessment mode** unless they are identical in every session.
- **Fallback:** the lobby can be played with the keyboard (WASD, IJKL, Space, O) using the same data format; those visits are labelled **keyboard input** on every caregiver screen.

### Software

```
Resident laptop                                           Caregiver laptop (any computer)
Browser: lobby + games (Gamepad API)                      Browser: dashboard, live view, resident pages
   │ samples + events, ~10 POSTs/s                           ▲ WebSocket (push)
   ▼                                                         │
FastAPI ──INSERT + NOTIFY──► Tiger Data ◄──LISTEN / reads── FastAPI
            live_sessions, live_samples ─(visit ends)─► sessions, session_summaries, raw_samples
```

- **Web:** Vite + React + TypeScript (`web/src`) plus the three.js lobby (`web/lobby`, a second Vite page). Routes: `/`, `/login`, `/signup`, `/caregiver/login`, `/caregiver/signup`, `/caregiver`, `/caregiver/residents/:id`, `/caregiver/live/:id`, and `/lobby.html`. The Vite dev server proxies `/api` (with WebSockets) to the local API.
- **API:** Python, FastAPI, psycopg 3 with a connection pool, plus one dedicated `LISTEN` connection while a caregiver is watching. Connection string from `DATABASE_URL` in `backend/.env`.
- **Database:** Tiger Data. `raw_samples` is a hypertable; `live_sessions`/`live_samples` are a short-term buffer pruned after a day (unsaved finished visits are saved first). Apply `backend/sql/schema.sql` and `backend/sql/auth_schema.sql` (both safe to re-run).
- **Pattern model:** PyTorch in the root `uv` environment; the API runs `ml/pattern_model/score_garden.py` as a subprocess.
- Never make the game wait on the database or a model call: the lobby posts asynchronously and drops old samples if the network stalls.

## 8. AI/ML strategy: useful, bounded, and honest

### Layer A — deterministic measurements and rules (built)

Per-attempt and per-hand measurements (`measurements.py`), and for the older session summaries a comparison of the latest session with the median of earlier ones (`insights.py`: latency rise ≥ 150 ms, accuracy drop ≥ 15%, at least 4 usable sessions). This is the **control** any trained model must beat, and the source of every number shown to staff.

### Layer B — TCN pattern model (built by a teammate)

A temporal convolutional network (`ml/pattern_model/`) scores each hand's movement stretches in garden recordings and fuses them into three 0–100 pattern-resemblance scores. It is trained on **teammate-simulated** recordings (folders such as "Parkinsons Data", "Left Weak") and **synthetic** recordings (`ml/pattern_model/synthetic.py`); there is no clinical data. This goes beyond the original "no disease classifier" plan, so the guardrails are strict:

- Scores are described everywhere as *resemblance to a movement pattern*, never a probability of disease.
- Caregivers and the assistant see neutral movement labels only ("Slower, smaller movements in both hands", "One hand weaker or slower than the other", "Rhythmic shake while moving"; `insights.PATTERN_LABELS`). The assistant and report refuse every condition name, including the ones the training folders are named after.
- The checkpoint is committed (`ml/runs/pattern_model/model.pt`) and scores Apple Picking and Harbour Fishing at the end of each lobby visit. It is trained from local recordings; the API does not write training files.

### Layer C — language assistance for the care team (built)

Gemini receives only structured facts built from the database (measurements, changes, concerns, checks, recent visits) and answers caregiver questions. Every number in an answer is checked against the facts, disease names trigger a clinician-referral answer, and a rule-based answer from the records is used if the API key is missing or Gemini fails. Staff notes are not generated.

**Evaluation still to do:** compare lobby measurements against manually observed play; report model sample counts and splits by participant; check false concerns on routine visits; confirm assistant numbers match their source. None of this establishes clinical safety or effectiveness.

## 9. Data contracts and review workflow

The schema in `backend/sql/schema.sql` implements these contracts. Change the schema and this section together.

**Minimum identifiers:** `participant_id` (UUID; the profile holds only an `alias`/username, a hashed password and `dominant_hand`), `session_id`, `protocol_version`, `connection`, `is_synthetic`, timestamps. Avoid real names and other health information.

**Lobby visit:** `sessions` row (`mode = free_play`, `protocol_version = lobby-v1`, `status` completed if any game was played through), `session_summaries.metrics` = `{games: {apple|fish|rat: {hands, left_right_difference_pct, attempts, samples, play_s, finished}}, games_finished, reach_trials}`. **Raw sample** (`raw_samples`, hypertable): `time`, `session_id`, `seq`, `t_ms`, four stick axes (y down), `activity` (`target_reach`/`target_tracking`), `game`, `trial_id`, `target_l*/r*` and `cursor_l*/r*` (in-game hand). **Live buffer** (`live_sessions`, `live_samples`): state, metrics and every streamed sample, including lobby walking, for at most a day. **Garden visit:** `sessions` (`garden-v3`), `garden_level_results`, `garden_imports`, `raw_samples`, and `session_summaries.metrics` with `live` measurements and the `ml.pattern_model` result when judged. **Accounts:** `participants` (residents), `caregivers`, `auth_sessions`.

**Human workflow (planned; the outcome buttons are not built yet):** New card → staff reviews underlying sessions and possible context → staff chooses `acknowledged`, `needs assessment`, or `dismissed with reason` → outcome is retained for learning and error analysis. The app never autonomously notifies family, writes a medical record, or issues a diagnosis. A future care-system integration would require permissions, privacy review, clinical validation, and a defined workflow; do not imply that we integrated PointClickCare's EHR during this hackathon.

**Privacy defaults:** Opt-in participant testing; pseudonyms only; no raw camera/audio; residents and caregivers have separate logins, and only caregivers see results; caregiver registration needs an access code. **Data now leaves the laptop** because Tiger Data is a cloud service, so profiles must never hold real names or health details. Keep the connection string in `backend/.env` (git-ignored). Do not commit personal data, API secrets, or a resident's information to GitHub. CSV recordings in the repo must come from consenting teammates only.

## 10. Build priorities for the 36-hour hackathon

| Priority | Deliverable | Definition of done | Status |
| --- | --- | --- | --- |
| P0 | Controller + stable data stream | Both sticks map to four live normalized axes; disconnects visible. | Done in the browser lobby and the garden game; tested with real controllers. |
| P0 | Games residents enjoy | Accessible, age-respectful games with clear instructions and an easy exit. | Lobby with three games built; garden game built. Older-adult playtesting not done. |
| P0 | Baseline and trends | Transparent personal comparison, quality labels, clearly marked simulated data. | Trends across visits built; rule-based baseline on lobby visits built. |
| P0 | Care-team view | Clear potential concerns with raw evidence and context; live view. | Dashboard, live view, resident page and concerns built; acknowledgement workflow not built. |
| P1 | Useful AI | Grounded assistant and/or model **with** rule-based comparison and stated limits. | Assistant built with checks; pattern model built and committed, no held-out evaluation yet. |
| P1 | Evaluation + pitch | Record real gameplay, inspect timing, show data provenance, rehearse the demo. | Real cross-laptop sessions recorded; formal evaluation not done. |
| P2 | Extra themes, haptics, future integration | Only after P0 works. No camera/YOLO, IMU "tremor" metrics, multi-sensor sprawl, or rushed EHR integration. | — |

**Next steps, in order:** acknowledgement workflow on concerns → held-out evaluation of the pattern model → older-adult playtesting. When the controller fails, play with the keyboard; those visits are labelled and the care-team loop still works.

**Scope-drift test for agents:** Before adding a feature, ask: (1) Does it improve resident engagement **without corrupting comparability**? (2) Does it improve a **measured change** or its quality? (3) Does it help a **care team** act on a reviewable observation? (4) Can it be shown working during the 36-hour demo? If none apply, defer it. If it makes a disease claim, changes a game's measured task without a new protocol version, presents motion data as tremor detection, or targets children as the main PointClickCare story, stop and return to this document.

## 11. Open decisions for the team

- **When does a lobby game change need a new protocol version?** Teammates are tuning rat speed, fishing rounds and lane position. Agree which changes bump `lobby-v1`.
- **Lobby baseline:** how many visits, over how many days, before lobby visits feed concerns (see §6)?
- **Pattern model:** who trains the checkpoint, on which recordings, and how is it evaluated per participant before its scores are shown?
- **Garden game:** keep it as a data-collection tool only, or link it from the site again?
- **One Python environment:** root `uv` (3.14) vs `backend/requirements.txt` (3.9). Fold them together or keep them separate on purpose.
- Is holding the controller comfortable for someone with reduced dexterity, or should it rest on a table? Test placement and let people decline without that becoming a score.
- Can we recruit any **consenting older adults and care staff** for feedback? Without them, label usability conclusions preliminary.

## 12. Evidence and references

These sources inform the direction; none validate *this joystick protocol*.

1. Hack the Valley 11 [PointClickCare: Catch It Early brief and prize categories](https://hack-the-valley-11.devpost.com/) and [event rules and deadlines](https://hack-the-valley-11.devpost.com/rules). The rules say submitted code is created during the hackathon window; this document is planning context, not prebuilt submission code.
2. MDN [Gamepad API](https://developer.mozilla.org/en-US/docs/Web/API/Gamepad_API) and the W3C [standard gamepad mapping](https://w3c.github.io/gamepad/#remapping), used by the browser reader.
3. [Tiger Data documentation](https://docs.tigerdata.com/) for service setup, connection strings and hypertables.
4. [Balance Assessment Using Gamified Digital Technology in Community-Dwelling Older Adults](https://games.jmir.org/2026/1/e80747/): 30 older adults, gamified versus plain digital assessment, higher reported enjoyment and intention to continue; single-session and balance-task findings do **not** prove long-term joystick adherence.
5. [Evaluating the User Experience and Usability of Game-Based Cognitive Assessments for Older People](https://aging.jmir.org/2025/1/e65252/): review of eight studies; accessibility, appropriate difficulty, and user-centered design matter; game elements do not universally improve experience or measurement.
6. [Exergames versus self-regulated exercises during geriatric rehabilitation](https://pubmed.ncbi.nlm.nih.gov/28330455/): a counterexample in which conventional exercises had better adherence, enjoyment, and motivation than the exergame.
7. [Neurological assessment overview](https://www.ncbi.nlm.nih.gov/books/NBK596731/): clinical examinations may include rapid alternating movements, but this joystick task is **inspired by the general idea of comparing movements** and is not an implementation of a validated examination.
8. PyTorch [building models with `torch.nn`](https://docs.pytorch.org/tutorials/beginner/basics/buildmodel_tutorial) for an optional, honestly evaluated ML experiment.

## 13. Decision log

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
| 2026-10-25 | Lobby visits set the personal baseline; "check soon" from the pattern model needs two judged visits in a row. | One noisy visit should not raise the strongest prompt. |

**Editing rule:** When changing this document, update §0, the protocol version/assumptions, this decision log, and the demo claims together. Preserve the mission and evidence boundaries unless the team explicitly decides to pivot.
