"""Caregiver assistant: natural-language questions about residents' results.

Answers are grounded in a facts block built only from stored visits and the
deterministic insights. Gemini writes the answer when GEMINI_API_KEY is set;
otherwise (or on any failure) a rule-based answer is built from the same facts.
Every Gemini answer is checked: any disease or condition name withholds it, and
numbers that do not appear in the facts are reported back as unverified.
"""
import logging
import re
from typing import List, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import gemini
from .auth import current_caregiver
from .db import pool
from .insights import PATTERN_LABELS, fmt
from .views import all_profiles, resident_profile

log = logging.getLogger(__name__)
router = APIRouter(tags=["assistant"])

# Caregivers only ever see neutral movement labels (insights.PATTERN_LABELS), so every condition name is
# refused, including the ones the pattern model's training folders are named after.
BANNED_WORDS = re.compile(
    r"\b(parkinson\w*|strokes?|tremors?|diabet\w*|ataxi\w*|dementia|alzheimer\w*|multiple sclerosis|"
    r"amyotrophic|huntington\w*|neuropath\w*|tumou?rs?|cancer|transient ischa?emic|seizures?|epilep\w*)\b",
    re.IGNORECASE,
)
BANNED_ACRONYMS = re.compile(r"\b(MS|ALS|TIA|PD|CVA)\b")


def names_condition(text: str) -> bool:
    return bool(BANNED_WORDS.search(text) or BANNED_ACRONYMS.search(text))

SYSTEM = """You are the Stick Drift care-team assistant in a long-term-care home. Caregivers ask about \
residents' results from short games played with the two thumbsticks of a PS5 controller in a 3D lobby: \
Apple Picking (reaching for apples with each hand), Harbour Fishing (steering along a moving lane with one \
stick) and Rat Catching (flicking a stick toward a rat). The games measure each hand: reaction time, time to \
reach a target, distance from the lane, time on the lane and leftover shake. A resident's latest game \
visits are compared with their own earlier visits.

Rules:
- Use ONLY the FACTS block. Quote numbers exactly as written there; do not compute new numbers.
- If the facts do not answer the question, say so plainly and suggest what to observe or record.
- The pattern model rates resemblance to movement patterns, written in the facts as plain descriptions \
("slower, smaller movements in both hands, 34/100"). Use only those descriptions. Never name a disease or \
medical condition, and never say or suggest a resident has one. The games are not a medical device. Talk \
about measured changes, possible everyday contributors and the recommended checks that appear in the facts.
- If a sudden new weakness, facial droop or speech difficulty is mentioned, tell the caregiver to follow \
the facility's urgent escalation protocol.
- Say when data is simulated (synthetic).
- Be concise: at most about 150 words, plain language, short bullet points when listing.
- Plain text only, no Markdown: no asterisks, bold or headings. Start list items with "- ".
"""


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(max_length=4000)


class Ask(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    participant_id: Optional[UUID] = None
    history: List[Turn] = Field(default_factory=list, max_length=12)


class Answer(BaseModel):
    answer: str
    source: Literal["gemini", "rules"]
    grounded: bool
    unverified_numbers: List[str]
    note: Optional[str] = None


# ---- facts ------------------------------------------------------------------

def _session_line(s: dict) -> str:
    def score(c, v):
        return f"{c}/{v}" if c is not None and v else "-"

    def sec(ms):
        return fmt("latency", ms) if ms is not None else "-"

    when = s["started_at"].strftime("%a %b %d %Y %H:%M") if hasattr(s["started_at"], "strftime") else s["started_at"]
    return (f"{when} | {s['status']} | quality {s['quality'] or '-'} | left {sec(s['left_median_latency_ms'])}, "
            f"{score(s['left_correct'], s['left_valid'])} | right {sec(s['right_median_latency_ms'])}, "
            f"{score(s['right_correct'], s['right_valid'])} | both {score(s['both_correct'], s['both_valid'])} | "
            f"enjoyment {str(s['enjoyment']) + '/5' if s['enjoyment'] else '-'}"
            f"{' | simulated' if s.get('is_synthetic') else ''}")


def baseline_unit(ins: dict) -> str:
    """What the baseline is made of: game visits, or a demo resident's older reaction-test sessions."""
    return "game visit" if ins.get("source") == "lobby" else "reaction-test session"


def _resident_facts(p: dict, full: bool) -> str:
    ins = p["insights"]
    games, garden = p.get("game_sessions", []), p.get("garden_sessions", [])
    unit = baseline_unit(ins)
    activity = [f"{len(games)} game visits", f"{len(garden)} garden visits"]
    if p["sessions"]:
        activity.append(f"{len(p['sessions'])} earlier reaction-test sessions")
    lines = [f"RESIDENT: {p['display_name']} (dominant hand: {p['dominant_hand']}, recorded activity: "
             f"{', '.join(activity)}; {ins['usable_sessions']} {unit}s usable for a baseline"
             f"{', data is SIMULATED/synthetic' if ins['synthetic'] else ''})",
             f"Overall: risk level '{ins['risk']}'. {ins['summary']}"]
    if ins["status"] == "ok":
        lines.append(f"Baseline = median of {ins['baseline_sessions']} earlier {unit}s; latest = most recent {unit}.")
        lines.append("Measurements (latest vs usual, change):")
        for f in ins["findings"]:
            tag = "CHANGED" if f["flagged"] else f["direction"]
            lines.append(f"  - {f['text']} [{tag}{f', persisted across recent {unit}s' if f['persistent'] else ''}]")
    for c in ins["concerns"]:
        lines.append(f"POTENTIAL CONCERN ({c['level']}): {c['title']} - {c['summary']}")
        lines.append("  Evidence: " + " ".join(c["evidence"]))
        lines.append("  Possible contributors: " + "; ".join(c["possible_contributors"]))
        lines.append("  Recommended caregiver checks: " + " ".join(c["recommended_checks"]))
        if full:
            lines.append("  Research basis: " + " | ".join(c["references"]))
    if games:
        pad = [g for g in games if not g.get("is_synthetic")]
        lines.append(f"Game visits (web lobby games, newest first, {len(games)} total):")
        lines += [f"  {_game_line(g)}" for g in pad[: 10 if full else 1]]
        if len(pad) < len(games):
            lines.append(f"  {len(games) - len(pad)} other game visits used keyboard input instead of the controller. "
                         "They do not reflect thumb movement, so their measurements are left out.")
    if garden:
        lines.append(f"Garden visits (newest first, {len(garden)} total):")
        lines += [f"  {_garden_line(g)}" for g in garden[: 10 if full else 1]]
    if full and p["sessions"]:
        lines.append("Reaction-test session history (newest first):")
        lines += [f"  {_session_line(s)}" for s in p["sessions"][:30]]
    return "\n".join(lines)


GAME_NAMES = {"apple": "Apple Picking", "fish": "Harbour Fishing", "rat": "Rat Catching"}


def _lr(hands, key, fmt):
    vals = [(hands or {}).get(h, {}).get(key) for h in ("left", "right")]
    return None if all(v is None for v in vals) else "left " + " / right ".join(
        "n/a" if v is None else fmt(v) for v in vals)


def _secs(v):
    return f"{v:.2f}s"


def _pct(v):
    return f"{v * 100:.0f}%"


def _when(d) -> str:
    return d.strftime("%b %d %H:%M") if hasattr(d, "strftime") else str(d)


def game_parts(g: dict) -> List[tuple]:
    """(game name, measurements as text) for each game played in one lobby visit."""
    lr, secs, pct = _lr, _secs, _pct
    parts = []
    for key in ("apple", "fish", "rat"):
        game = (g.get("games") or {}).get(key)
        if not game:
            continue
        h = game.get("hands", {})
        bits = []
        caught = [f"{side} {h[side]['apples_reached']}/{h[side]['apples_total']}" for side in ("left", "right")
                  if h.get(side, {}).get("apples_total")]
        if caught:
            bits.append("caught " + " / ".join(caught))
        for label, k, f in (("time to pick/slam", "reach_s", secs), ("reaction", "reaction_s", secs),
                            ("distance from lane", "tracking_error", pct), ("time on lane", "on_target", pct)):
            v = lr(h, k, f)
            if v:
                bits.append(f"{label} {v}")
        parts.append((f"{GAME_NAMES[key]}{'' if game.get('finished') else ' (left early)'}",
                      "; ".join(bits or ["no measurements"])))
    return parts


def _game_line(g: dict) -> str:
    """One lobby visit as text, left/right per measurement."""
    parts = [f"{name}: {text}" for name, text in game_parts(g)]
    scores = ((g.get("tcn") or {}).get("scores") or {})
    pattern = [f"{PATTERN_LABELS[k].lower()} {v:.0f}/100" for k, v in scores.items() if v is not None and k in PATTERN_LABELS]
    if pattern:
        parts.append("pattern model (resemblance, not diagnosis): " + ", ".join(pattern))
    rat = ((g.get("visit") or {}).get("games") or {}).get("rat") or {}
    if rat.get("score") is not None:
        stars = f", {rat['stars']} stars" if rat.get("stars") is not None else ""
        parts.append(f"rat score {rat['score']} points{stars}")
    if rat.get("median_reaction_s") is not None:
        parts.append(f"rat timing: median {rat['median_reaction_s']:.2f}s nose-to-slam")
    return f"{_when(g['started_at'])}{' [keyboard input]' if g.get('is_synthetic') else ''} - " + " | ".join(
        parts or ["no games played"])


def _garden_line(g: dict) -> str:
    """One garden visit as text: chapters, reach and tracking per hand, pattern scores."""
    parts = [f"{g.get('levels_completed') or 0}/{g.get('levels_total') or 4} chapters finished"]
    hands = (g.get("live") or {}).get("hands")
    for label, k, f in (("reaction", "reaction_s", _secs), ("time to reach", "reach_s", _secs),
                        ("distance from target", "tracking_error", _pct), ("time on target", "on_target", _pct)):
        v = _lr(hands, k, f)
        if v:
            parts.append(f"{label} {v}")
    scores = (g.get("tcn") or {}).get("scores") or {}
    pattern = [f"{PATTERN_LABELS[k].lower()} {v:.0f}/100" for k, v in scores.items() if v is not None and k in PATTERN_LABELS]
    if pattern:
        parts.append("pattern model (resemblance, not diagnosis): " + ", ".join(pattern))
    return f"{_when(g['started_at'])}{' [simulated input]' if g.get('is_synthetic') else ''} - " + " | ".join(parts)


def build_facts(profiles: List[dict], focus: Optional[dict]) -> str:
    if focus is not None:
        return _resident_facts(focus, full=True)
    blocks = [f"ALL RESIDENTS ({len(profiles)}):"]
    blocks += [_resident_facts(p, full=False) for p in profiles]
    return "\n\n".join(blocks)


# ---- grounding check --------------------------------------------------------

NUM = re.compile(r"[+-]?\d+(?:\.\d+)?\s*(?:s\b|%|/\d+|\s?pts)")


def _nums(text: str) -> List[str]:
    return [re.sub(r"\s+", "", m.group(0)).lstrip("+") for m in NUM.finditer(text)]


def unverified(answer: str, facts: str) -> List[str]:
    allowed = set(_nums(facts))
    allowed |= {n.lstrip("-") for n in allowed}
    return sorted({n for n in _nums(answer) if n not in allowed and n.lstrip("-") not in allowed})


# ---- rule-based fallback ----------------------------------------------------

def _rules_answer(q: str, profiles: List[dict], focus: Optional[dict]) -> str:
    q = q.lower()
    if focus is None:
        flagged = [p for p in profiles if p["insights"]["concerns"]]
        stable = [p for p in profiles if not p["insights"]["concerns"]]
        if any(w in q for w in ("stable", "fine", "okay", "doing well", "no concern")):
            if not stable:
                return "Every resident currently has a potential concern; open each one for details."
            return "Stable, in line with their usual pattern:\n" + "\n".join(
                f"- {p['display_name']}: {p['insights']['summary']}" for p in stable)
        if any(w in q for w in ("summar", "everyone", "all resident", "overview", "trend")):
            return "\n".join(f"- {p['display_name']} ({p['insights']['risk']}): {p['insights']['summary']} "
                             + " ".join(p["review"]["reasons"][:2]) for p in profiles)
        if not flagged:
            return f"None of the {len(profiles)} residents show a change worth checking right now."
        out = [f"{len(flagged)} of {len(profiles)} residents {'has' if len(flagged) == 1 else 'have'} a potential concern:"]
        for p in flagged:
            titles = ", ".join(c["title"] for c in p["insights"]["concerns"])
            out.append(f"- {p['display_name']}: {titles}. " + " ".join(p["review"]["reasons"][:2]))
        out.append("Open a resident for the full evidence and recommended checks.")
        return "\n".join(out)

    ins, name = focus["insights"], focus["display_name"]
    unit = baseline_unit(ins)
    findings = ins["findings"]

    def pick(*words):
        return any(w in q for w in words)

    if pick("recommend", "should", "check", "next", "do ", "action"):
        if not ins["concerns"]:
            return f"No checks are recommended for {name} right now; recent {unit}s match their usual pattern."
        out = []
        for c in ins["concerns"]:
            out.append(f"{c['title']}:")
            out += [f"- {x}" for x in c["recommended_checks"]]
        return "\n".join(out)

    if ins["status"] != "ok":
        out = [f"{name}: {ins['summary']}"]
        latest = next((g for g in focus.get("game_sessions", []) if not g.get("is_synthetic") and g.get("games")), None)
        if latest is not None:
            out.append(f"Latest game visit ({_when(latest['started_at'])}):")
            out += [f"- {game}: {text}" for game, text in game_parts(latest)]
        out += [f"Potential concern ({c['level']}): {c['title']}." for c in ins["concerns"]]
        return "\n".join(out)

    hand = "left" if pick("left") else "right" if pick("right") else None
    kinds = None
    if hand is None:
        if pick("accura", "correct", "miss", "lane", "track", "distance"):
            kinds = {"accuracy", "distance", "share"}
        elif pick("slow", "fast", "speed", "response", "reaction", "time", "reach"):
            kinds = {"latency", "gap", "seconds"}
        elif pick("enjoy", "mood", "engag", "like"):
            kinds = {"enjoyment"}
        elif pick("both", "coordinat", "two"):
            hand = "both"

    if hand or kinds:
        rows = [f"- {f['text']}" for f in findings
                if (hand and f["hand"] == hand) or (hand in ("left", "right") and f["key"] == "lr_gap")
                or (kinds and f["kind"] in kinds)]
        return f"{name}, latest {unit} compared with their usual:\n" + "\n".join(rows or ["- No data for that yet."])

    out = [f"{name}: {ins['summary']}"]
    changed = [f for f in findings if f["flagged"]]
    out += [f"- {f['text']}" for f in changed] or ["- All measurements are close to their usual."]
    for c in ins["concerns"]:
        out.append(f"Potential concern ({c['level']}): {c['title']}. Possible contributors: "
                   + "; ".join(c["possible_contributors"][:3]) + ".")
    return "\n".join(out)


# ---- Gemini -----------------------------------------------------------------

def _gemini(facts: str, body: Ask) -> Optional[str]:
    if not gemini.available():
        return None
    from google.genai import types

    contents = [types.Content(role="model" if t.role == "assistant" else "user", parts=[types.Part(text=t.text)])
                for t in body.history[-10:]]
    contents.append(types.Content(role="user", parts=[types.Part(text=f"FACTS:\n{facts}\n\nQUESTION: {body.question}")]))
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM,
        temperature=0.2,
        max_output_tokens=700,
        thinking_config=types.ThinkingConfig(thinking_budget=0),
    )
    text = gemini.generate(contents, config, timeout_ms=30000)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text).replace("**", "")
    return text.strip() or None


@router.post("/caregiver/assistant", response_model=Answer)
def ask(body: Ask, _: dict = Depends(current_caregiver)):
    with pool.connection() as conn:
        focus = None
        if body.participant_id is not None:
            focus = resident_profile(conn, body.participant_id)
            if focus is None:
                raise HTTPException(404, "Resident not found.")
        profiles = [focus] if focus else all_profiles(conn)
    facts = build_facts(profiles, focus)

    note = None
    try:
        text = _gemini(facts, body)
    except Exception:
        log.exception("Gemini request failed")
        text, note = None, "The AI service did not respond, so this answer was built from the records directly."

    asked_condition = names_condition(body.question)
    if text is not None and names_condition(text):
        text, note = None, ("Answers about specific medical conditions are built from the records only."
                            if asked_condition else
                            "The AI answer named a medical condition, which this tool cannot support, so it was "
                            "withheld. This answer was built from the records directly.")

    if text is None:
        if note is None and not gemini.available():
            note = "Rule-based answer. Add GEMINI_API_KEY to backend/.env for conversational AI answers."
        answer = _rules_answer(body.question, profiles, focus)
        if asked_condition:
            answer = ("This tool can't say whether a resident has a specific condition; that needs a clinician's "
                      "assessment. Here is what the records show, with the recommended checks.\n\n"
                      + _rules_answer("overview", profiles, focus)
                      + ("\n\n" + _rules_answer("what should I check", profiles, focus) if focus else ""))
        return {"answer": answer, "source": "rules", "grounded": True, "unverified_numbers": [], "note": note}

    extra = unverified(text, facts)
    return {"answer": text, "source": "gemini", "grounded": not extra, "unverified_numbers": extra,
            "note": None if not extra else "Some numbers in this answer were not found in the records; "
                                            "check them against the charts before acting."}
