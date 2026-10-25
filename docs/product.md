# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Two audiences arrive on the same welcome page and matter equally (confirmed):

- **Residents** of senior-living and long-term-care homes: older adults, often with age-related changes in sight and fine motor control, sitting at a laptop with a PS5 controller. Their job is to log in and play a few short games.
- **Care teams** (nurses, personal support workers, clinicians) who log in on any computer to see how each resident played, who is playing right now, and anything worth checking in on.

## Product Purpose

Stick Drift is a set of short, enjoyable controller games for care-home residents. While a resident plays, each hand's reaction time, reach, tracking and steadiness are measured, so a care team can notice when someone's movement changes and check in early. Success: residents want to play again, and staff see a change worth checking before it becomes a problem.

## Positioning

The games are the way in and the measurement stays behind the scenes: it records how each thumb moves during ordinary play, with no clinical test to sit through. It reports "a change worth checking", never a diagnosis.

## Operating Context

- Resident: a laptop and one Sony DualSense controller, in a shared or private room, in short sessions that can stop at any time.
- Care team: the dashboard on a staff computer, live view while a resident plays, history and trends across visits.
- Built for Hack the Valley 11 (PointClickCare: Catch It Early).

## Capabilities and Constraints

- Playable today in the 3D lobby: Apple Picking, Harbour Fishing, Rat Catching. More games are only mock-ups on the resident's home page and must be labelled as not playable yet.
- The product never names a disease or condition, never predicts, and never says whether something is an emergency. The UI uses neutral movement language.
- Residents see a score and 0-3 stars for fun; they do not see clinical measurements.
- Auth: resident accounts (username, password, dominant hand) and care-team accounts (access code).

## Brand Commitments

- Name: Stick Drift. Mark: two thumbsticks (already in the top bar).
- Voice: warm and plain (confirmed). Short sentences, no jargon, reassuring, no exclamation-mark hype, no clinical vocabulary on resident-facing pages.

## Evidence on Hand

- Real captures of the lobby and the three games in `web/public/lobby/` (lobby.jpg, apple.jpg, fish.jpg, rat.jpg).
- No customer testimonials, numbers from trials or care-home names exist. Do not invent any.

## Product Principles

1. Play comes first; measurement stays out of the resident's way.
2. Two doors of equal weight: resident and care team.
3. Say "worth checking", never anything that sounds like a diagnosis.
4. Big, calm and legible beats clever.
5. Show the real games, not decoration.

## Accessibility & Inclusion

- Large, easy-to-read type with high contrast (confirmed).
- The app follows the visitor's light or dark system theme today (inferred; kept so the top bar and other pages stay consistent).
- Everything reachable by keyboard with a visible focus ring; motion is gentle and removed for reduced-motion users (inferred).
