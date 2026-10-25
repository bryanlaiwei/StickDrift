# UX spec: Mabel's Moonflower Garden

Status: implemented prototype; senior playtesting and real-controller verification pending.
Platform: existing Windows/Pygame game, DualSense two analog sticks.

## Purpose and player need

Help Mabel host a garden picnic with Pip and Poppy, two bird companions. The
player has a social purpose, a place to care about, and a visible ending. Apples
become a shared tart; butterflies become invited guests; flowers prepare the
picnic garden. No scores, medical terms, accuracy reports, countdowns or trial
numbers appear in the player interface. Participation/data-collection consent
still belongs to the surrounding facilitator workflow.

## Player context and journey

Invitation -> release sticks while the garden wakes -> discover the two birds
by moving each stick -> orchard -> left meadow flight -> right cottage flight
-> moonflower beds -> evening picnic. Chapter notes wait for the player.
Short celebrations automatically yield to the next chapter note. Familiar
garden activities and one instruction at a time reduce the memory burden.

## Navigation and entry/exit points

The existing garden.py command launches this presentation. An optional --level
argument starts a single chapter after the same introduction. Holding either
stick upward advances a note; after the picnic it finishes and saves. Holding
both sticks outward opens the bench from play. There, either stick upward
resumes, and either downward saves and finishes early. Esc/window close remain
facilitator shortcuts. Disconnect pauses the active clock and recording until
the device returns and the player explicitly resumes.

## Layout specification

The main field is a continuous landscape: cottage, garden path, orchard, flower
beds, distant hills and picnic bunting. Large targets and birds occupy the
foreground. Mabel stands beside the activity. A cream header names the current
story purpose and four places on the journey; a bottom strip gives one action.
Bird nameplates identify LEFT/RIGHT along with distinct crests/accessories.
Story cards pair Mabel's portrait with a short note. The title and body fonts
are Georgia and Segoe UI, with system fallbacks. Art is original procedural
Pygame geometry, cached scenery plus animated foregrounds; no external assets.
The `3d-games` follow-up adds original mesh-based characters, birds, apples,
flowers, trees and cottage. An orthographic camera, directional sun and ambient
fill shade the geometry. Back-face culling and depth-sorted triangle rasterization
produce antialiased cached sprites. This is a fixed-view 2.5D presentation: no
free camera, perspective aiming or extra player controls. Trees use coarser mesh
detail than the close-up host; reused poses avoid per-frame mesh rendering.

Hierarchy: actionable object -> controllable bird -> current instruction ->
story title -> journey milestones. Performance numbers stay in exported data.

## States and variants

| State | Presentation and behavior |
|---|---|
| No device | Friendly waiting note; no data recorded |
| Welcome/chapter | Mabel's note; explicit neutral-then-up gesture |
| Settling | Wait for released, stable sticks before setting centers |
| Practice | Move both birds once; no results recorded |
| Playing | Large objects, immediate pick/bloom sound and visual feedback |
| Pause/disconnect | Garden bench; active clock and sampling suspended |
| Finish | Dusk, fireflies, picnic, companions and a thank-you |
| Keyboard demo | Explicit DEMO INPUT label; session marked synthetic |
| Reduced motion | Still scenery and birds; particle bursts disabled |

## Interaction map

| Action | Input | Feedback/outcome |
|---|---|---|
| Advance | Release, then either stick upward >0.6 for 0.8s | Visible fill strip, next note |
| Fly | Each stick controls its corresponding bird | Direct analog placement, display smoothing only |
| Pick | Bird overlaps apple | Apple carried, warm chime; release to bank |
| Invite | Stay near butterfly | Sparkle reward along the flight |
| Water | Bird/can passes flowers | Flowers open and chime |
| Break | Both sticks outward >0.8 for 1.4s | Visible opening cue, bench |
| Resume | Release, then hold either stick up | Returns with active time preserved |
| Finish early | At bench, hold either stick down for 1.4s | Current records saved, game closes |

Hold gestures fire once and require a neutral reset. The pause gesture is beyond
the target field. Normal game targets remain inside 0.6 deflection.

## Data requirements and events

Garden.Game owns targets, chapter state and outcomes. Recorder owns raw HID
samples. StoryGame reads their state to draw; it adds presentation version,
synthetic-input identity and reduced-motion flags to session metadata. Existing
per-level CSV headers and level.json results remain available. Menus, practice
and breaks are excluded from active recording. No cloud upload is added here.

Protocol is now garden-v3. Apple time allowance changes from 5 to 12 seconds;
all four chapter types, mirrored paths and sample context remain. Visual changes
also affect behavior: do not pool v2 and v3 sessions into one baseline. A finished
chapter is a story milestone, not a claim of successful motor performance.

## Transitions and animation

Screens change directly without camera motion. Cloud drift, bird wings and
brief flower particles bring the landscape to life. Rewards combine sound and
visible changes. --reduced-motion freezes ambient movement and removes bursts;
the moving butterfly/cloud targets still move because movement is the activity.
--mute leaves all visual feedback intact.

## Input completeness and accessibility

The intended player path uses sticks alone, including notes, pause, resume and
finishing. Both sticks are needed for paired activities; either one navigates
notes. Keyboard simulation uses WASD/arrows; Space/Enter, P and Esc are optional
facilitator shortcuts. Mouse/touch/D-pad navigation are outside this game's
input design. No gameplay requirement depends on color alone. Main text is
27px at 1280x720; actions are on opaque cream panels. Lower-priority nameplates
are 19px. Fullscreen scaling is available. Formal contrast/accessibility audit,
screen-reader support and adjustable text scale are not complete.

## Localization

Story paragraphs wrap within fixed-width cards. English is implemented. Titles,
nameplates and the HUD need separate translation/layout testing; do not assume
40% longer strings fit. All live controls are rendered as text as well as color.

## Acceptance criteria

- Complete the chapter-note flow using sticks only, without accidental repeats.
- Disconnect and resume without advancing the activity clock or logging menu input.
- A full synthetic playthrough produces four nonempty, consistent CSV/JSON pairs.
- Apples, birds, instructions and character remain distinct at 1280x720.
- The ending depicts a picnic and a thank-you, with no performance report.
- Cached scenery supports a 60Hz target on the deployment laptop; measure it there.
- Real senior playtest: player can explain why they are gathering apples and
  voluntarily wants another visit. This is a research question, not a verified claim.

## Open questions

Test two-stick outward pause discoverability, instruction reading time, visual
comfort and target reachability on the actual controller with intended players.
Verify 60Hz on the deployment laptop and HID recording rate with real hardware.
The browser landing page and TigerData importer are separate integration work.

## Skill usage and decision record

Applied the linked Claude Code Game Studios ux-design skill's purpose-first
layout, player journey, explicit state map, interaction completeness, accessibility
and acceptance-criteria structure. Source:
https://github.com/Donchitos/Claude-Code-Game-Studios/tree/main/.claude/skills/ux-design

Also installed and applied `3d-games` from Dokhacgiakhoa/antigravity-ide with the
user's requested skills CLI, targeting Claude Code. Its rendering pipeline,
camera, directional/ambient lighting, baked shadow, LOD and batching guidance
informed `garden_3d.py`. Local source: `.claude/skills/3d-games/SKILL.md`;
installation provenance: `skills-lock.json`.

The user's request delegated a complete redesign and implementation. Routine
creative choices were made within that scope: original storybook garden,
gardener host, two bird companions, in-world rewards, existing Pygame engine and
raw recorder. No existing UX specs or player-journey documents were present.
This document records the design assumptions for review; it does not claim
formal studio approval or completed accessibility certification.
