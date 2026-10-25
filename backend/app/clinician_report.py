"""Clinician summary report (PDF).

Gemini writes the narrative as structured JSON in a clinical-documentation register
(objective observations kept apart from interpretation, graded hedging, explicit
limitations). The facts, tables, charts, scope statement and disclaimer are built
deterministically, so the model never touches them. Every Gemini draft is checked:
a condition name, a number that is not in the facts, or emotive wording sends it
back for one revision and then falls back to a template built from the same facts.
"""
import json
import logging
import re
from datetime import datetime, timezone, tzinfo
from io import BytesIO
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from reportlab.graphics.charts.legends import Legend
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.widgets.markers import makeMarker
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from . import gemini
from .assistant import baseline_unit, build_facts, game_parts, names_condition, unverified
from .auth import current_caregiver
from .db import pool
from .insights import fmt
from .residents import resident_profile

log = logging.getLogger(__name__)
router = APIRouter(tags=["report"])

SCOPE = ("This report summarises measurements recorded by the Stick Drift two-thumbstick activity (PS5 "
         "controller). It describes what was measured and how it compares with the resident's own earlier "
         "results. It is not a diagnostic or screening instrument, does not identify any medical condition, and "
         "is not a substitute for clinical assessment. Interpretation and any action rest with the reviewing "
         "clinician.")

# ---- Gemini draft ---------------------------------------------------------------

STYLE = """You are drafting a one-to-two page data summary for a clinician (nurse, physician, occupational \
therapist) who may attach it to a resident's record. Write like a careful clinical author.

Register and structure
- Separate observation from interpretation. "observations" contain only measured facts and comparisons. \
Interpretation appears only in "irregularities" and "considerations", and is always hedged.
- Be objective, specific and measurable: state the measure, the value, the resident's own usual value, the \
direction and size of the change, and the number of sessions behind it. No adjectives such as "alarming", \
"poor", "worrying" or "excellent". No emotive or judgemental language.
- Lead with the most important finding. Short sentences, active voice, past tense for what was measured and \
present tense for what it may indicate. Plain words a clinician can scan in under a minute.
- Use graded hedging for interpretation and match it to the evidence: "was observed" (measured), \
"is consistent with" (two or more measures agree and the change persisted), "may reflect" (one measure or one \
session), "cannot be determined from these data" (insufficient). Never use "proves" or "confirms".
- Name what the data cannot show. State that comparison is against the resident's own baseline (not a \
population norm) and flag any simulated data.

Hard rules
- Use ONLY the FACTS block. Quote numbers exactly as written there (for example 0.82 s, 75%, -2 pts). Do not \
compute, round or invent numbers, dates, doses, diagnoses, history or caregiver actions.
- The pattern model rates resemblance to movement patterns, written in the facts as plain descriptions \
("slower, smaller movements in both hands, 34/100"). Use only those descriptions. NEVER name a disease or \
medical condition, and never state or imply that the resident has one. Otherwise describe the functional \
change ("slower left-hand responses").
- Possible contributors are everyday, non-diagnostic factors (tiredness, pain, medication change, vision, \
setup), offered for the clinician to consider, never as conclusions.
- If an irregularity involves new one-sided weakness, facial droop or speech difficulty, a consideration must \
say to follow the facility's urgent escalation protocol.
- "considerations" are suggestions for the clinician's review, phrased as "Consider ...", never orders.
- Plain text only: no Markdown, asterisks or headings inside field values.
- If there are no irregularities, return an empty list and say so in the summary.
"""

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "summary": {"type": "STRING", "description": "2-3 sentence bottom line, most important finding first."},
        "data_description": {"type": "STRING", "description": "What was recorded, sessions used, baseline definition."},
        "observations": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "measure": {"type": "STRING"},
            "statement": {"type": "STRING", "description": "Objective: value, usual value, change, direction."}},
            "required": ["measure", "statement"]}},
        "irregularities": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "title": {"type": "STRING"},
            "description": {"type": "STRING", "description": "What differed from the usual pattern, with numbers."},
            "interpretation": {"type": "STRING", "description": "Hedged, non-diagnostic statement of what it may reflect."},
            "evidence_strength": {"type": "STRING", "enum": ["single session", "repeated across sessions", "limited data"]},
            "possible_contributors": {"type": "ARRAY", "items": {"type": "STRING"}}},
            "required": ["title", "description", "interpretation", "evidence_strength", "possible_contributors"]}},
        "limitations": {"type": "ARRAY", "items": {"type": "STRING"}},
        "considerations": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["summary", "data_description", "observations", "irregularities", "limitations", "considerations"],
}

def _call_gemini(facts: str, feedback: Optional[str]) -> dict:
    from google.genai import types

    prompt = f"FACTS:\n{facts}\n\nWrite the clinician summary now."
    if feedback:
        prompt += f"\n\nYour previous draft was rejected: {feedback} Revise it and fix this."
    config = types.GenerateContentConfig(
        system_instruction=STYLE, temperature=0.2, max_output_tokens=3000,
        response_mime_type="application/json", response_schema=SCHEMA,
        thinking_config=types.ThinkingConfig(thinking_budget=0),
    )
    return json.loads(gemini.generate(prompt, config, timeout_ms=60000))


def _strings(v) -> List[str]:
    if isinstance(v, str):
        return [v]
    if isinstance(v, list):
        return [s for x in v for s in _strings(x)]
    if isinstance(v, dict):
        return [s for x in v.values() for s in _strings(x)]
    return []


def _problems(draft: dict, facts: str, has_concerns: bool) -> Optional[str]:
    text = "\n".join(_strings(draft))
    if names_condition(text):
        return "It named a medical condition. Describe only the measured functional change."
    extra = unverified(text, facts)
    if extra:
        return f"These numbers are not in the FACTS block: {', '.join(extra[:6])}. Use only numbers from FACTS."
    if re.search(r"\b(alarming|worrying|poor|terrible|excellent|proves?|confirms?)\b", text, re.I):
        return "It used emotive or overly certain wording. Keep the register objective and hedged."
    if has_concerns and not draft.get("irregularities"):
        return "FACTS list potential concerns but irregularities was empty."
    if not draft.get("summary") or not draft.get("observations"):
        return "summary and observations are required."
    return None


def _template_draft(p: dict) -> dict:
    """Same shape as the Gemini draft, built from the deterministic insights."""
    ins = p["insights"]
    if ins["status"] != "ok":
        games = [g for g in p.get("game_sessions", []) if g["games"]]
        garden = p.get("garden_sessions", [])
        if not games and not garden:
            return {"summary": ins["summary"],
                    "data_description": f"{_n(ins['usable_sessions'], 'usable ' + baseline_unit(ins))} on record.",
                    "observations": [], "irregularities": [],
                    "limitations": [f"A personal baseline needs at least 4 usable {baseline_unit(ins)}s."],
                    "considerations": ["Consider generating this report again after more visits are recorded."]}
        latest = next((g for g in games if not g["is_synthetic"]), games[0]) if games else None
        observations = [{"measure": f"{name} ({_fmt_when(latest['started_at'])})", "statement": text.capitalize() + "."}
                        for name, text in game_parts(latest)] if latest else []
        return {"summary": f"{len(games)} game visits and {len(garden)} garden visits are recorded. "
                           f"{ins['summary']}",
                "data_description": "Measurements come from the web lobby games (Apple Picking, Harbour Fishing, "
                                    "Rat Catching) and the garden game. Until enough visits with the controller "
                                    "are recorded, each visit is shown on its own.",
                "observations": observations, "irregularities": [],
                "limitations": ["A personal baseline needs at least 4 game visits with the controller, so changes "
                                "are not flagged yet."],
                "considerations": ["Consider comparing left and right hands across the visits listed below."]}
    unit = baseline_unit(ins)
    return {
        "summary": ins["summary"],
        "data_description": f"The latest {unit} was compared with the median of {ins['baseline_sessions']} "
                            f"earlier {unit}s from the same resident.",
        "observations": [{"measure": f["label"], "statement": f["text"]} for f in ins["findings"]],
        "irregularities": [{
            "title": c["title"], "description": c["summary"] + " " + " ".join(c["evidence"]),
            "interpretation": "These measurements differ from the resident's usual pattern; the cause cannot be "
                              "determined from these data.",
            "evidence_strength": "repeated across sessions" if c["level"] == "check" else "single session",
            "possible_contributors": c["possible_contributors"]} for c in ins["concerns"]],
        "limitations": [],
        "considerations": [x for c in ins["concerns"] for x in c["recommended_checks"]],
    }


def draft_report(p: dict, facts: str):
    """Returns (draft, source, note)."""
    has_concerns = bool(p["insights"]["concerns"])
    if not gemini.available():
        return _template_draft(p), "template", "Template wording (no Gemini key configured)."
    feedback = None
    for attempt in range(2):
        try:
            draft = _call_gemini(facts, feedback)
        except Exception:
            log.exception("Gemini report draft failed")
            return _template_draft(p), "template", "Template wording (the AI service did not respond)."
        feedback = _problems(draft, facts, has_concerns)
        if feedback is None:
            return draft, "gemini", "Revised once after an automated check." if attempt else None
        log.warning("Report draft rejected (attempt %d): %s", attempt + 1, feedback)
    return _template_draft(p), "template", "Template wording (the AI draft did not pass automated checks)."


# ---- PDF ------------------------------------------------------------------------

INK = colors.HexColor("#1f2933")
MUTED = colors.HexColor("#5b6773")
ACCENT = colors.HexColor("#1f5f8b")
RULE = colors.HexColor("#c9d1d9")
# hands match the games and the site: red = left stick, blue = right stick
RED, BLUE, GREEN = colors.HexColor("#e02424"), colors.HexColor("#2a78d6"), colors.HexColor("#3b8a5a")

SS = getSampleStyleSheet()
BODY = ParagraphStyle("body", parent=SS["BodyText"], fontName="Helvetica", fontSize=9.5, leading=13,
                      textColor=INK, alignment=TA_LEFT)
SMALL = ParagraphStyle("small", parent=BODY, fontSize=8, leading=10.5, textColor=MUTED)
H1 = ParagraphStyle("h1", parent=BODY, fontName="Helvetica-Bold", fontSize=17, leading=21, spaceAfter=2)
H2 = ParagraphStyle("h2", parent=BODY, fontName="Helvetica-Bold", fontSize=11, leading=14, textColor=ACCENT,
                    spaceBefore=10, spaceAfter=4)
CELL = ParagraphStyle("cell", parent=BODY, fontSize=8.5, leading=11)
CELLB = ParagraphStyle("cellb", parent=CELL, fontName="Helvetica-Bold")
TITLE = ParagraphStyle("title", parent=BODY, fontName="Helvetica-Bold")
BULLET = ParagraphStyle("bullet", parent=BODY, leftIndent=12, firstLineIndent=-12, spaceAfter=2)


def esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def P(text, style=BODY):
    return Paragraph(esc(text), style)


def bullets(items: List[str]):
    return [Paragraph("&bull;&nbsp;&nbsp;" + esc(i), BULLET) for i in items]


def _fmt_date(d) -> str:
    return d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)[:10]


def _fmt_when(d) -> str:
    return d.strftime("%Y-%m-%d %H:%M") if hasattr(d, "strftime") else str(d)[:16]


def _localize(p: dict, tz: tzinfo) -> dict:
    """Copy of the profile with every start time in the reader's time zone, so the PDF matches the site."""
    def conv(rows):
        return [{**r, "started_at": r["started_at"].astimezone(tz)} if hasattr(r["started_at"], "astimezone") else r
                for r in rows]
    return {**p, "sessions": conv(p["sessions"]), "garden_sessions": conv(p.get("garden_sessions", [])),
            "game_sessions": conv(p.get("game_sessions", []))}


def _zone(name: Optional[str]) -> tzinfo:
    if name:
        try:
            from zoneinfo import ZoneInfo
            return ZoneInfo(name)
        except Exception:
            log.warning("Unknown time zone %r for the report; using UTC", name)
    return timezone.utc


def _chart(title: str, series: List[tuple], baseline: Optional[float], yfmt: str,
           xlabel: str = "Session (oldest to newest)") -> Drawing:
    """series: [(name, [(x, y), ...], color)]; x is the session or visit number."""
    w, h = 250, 150
    d = Drawing(w, h + 18)
    d.add(String(0, h + 6, title, fontName="Helvetica-Bold", fontSize=8.5, fillColor=INK))
    series = [s for s in series if s[1]]
    pts = [y for _, s, _ in series for _, y in s]
    if not pts:
        d.add(String(10, h / 2, "No data yet", fontSize=8, fillColor=MUTED))
        return d
    lo, hi = min(pts), max(pts)
    if baseline is not None:
        lo, hi = min(lo, baseline), max(hi, baseline)
    pad = (hi - lo) * 0.2 or 0.1
    xs = [x for _, s, _ in series for x, _ in s]
    lp = LinePlot()
    lp.x, lp.y, lp.width, lp.height = 38, 28, w - 50, h - 52
    lp.data = [s for _, s, _ in series] + ([[(min(xs), baseline), (max(xs), baseline)]] if baseline is not None else [])
    for i, (_, _, c) in enumerate(series):
        lp.lines[i].strokeColor, lp.lines[i].strokeWidth = c, 1.6
        lp.lines[i].symbol = makeMarker("FilledCircle", size=4, fillColor=c, strokeColor=c)
    if baseline is not None:
        k = len(series)
        lp.lines[k].strokeColor, lp.lines[k].strokeWidth, lp.lines[k].strokeDashArray = MUTED, 0.8, [3, 2]
    lp.yValueAxis.valueMin, lp.yValueAxis.valueMax = max(0, lo - pad), hi + pad
    lp.yValueAxis.labelTextFormat = yfmt
    lp.yValueAxis.labels.fontSize = lp.xValueAxis.labels.fontSize = 7
    lp.yValueAxis.visibleGrid, lp.yValueAxis.gridStrokeColor = True, RULE
    lp.xValueAxis.valueMin, lp.xValueAxis.valueMax = min(xs), max(max(xs), min(xs) + 1)
    lp.xValueAxis.labelTextFormat = "%d"
    lp.xValueAxis.valueSteps = list(range(int(min(xs)), int(max(max(xs), min(xs) + 1)) + 1))
    d.add(lp)
    d.add(String(lp.x + 20, 6, xlabel, fontSize=7, fillColor=MUTED))
    lg = Legend()
    lg.x, lg.y, lg.fontSize, lg.alignment = lp.x, h - 2, 7, "right"
    lg.colorNamePairs = [(c, n) for n, _, c in series] + ([(MUTED, "Usual")] if baseline is not None else [])
    lg.dxTextSpace, lg.deltax, lg.deltay, lg.columnMaximum = 3, 48, 9, 1
    d.add(lg)
    return d


def _tbl(rows, widths, header=True):
    t = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
    style = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE),
             ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
             ("LEFTPADDING", (0, 0), (-1, -1), 4)]
    if header:
        style.append(("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef3f7")))
    t.setStyle(TableStyle(style))
    return t


def _page(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(0.75 * inch, 0.5 * inch, "Stick Drift data summary. Not a diagnostic document. For clinician review.")
    canvas.drawRightString(letter[0] - 0.75 * inch, 0.5 * inch, f"Page {doc.page}")
    canvas.restoreState()


def _n(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def _game_cell(g: dict, key: str) -> str:
    """Headline result of one lobby game in one visit, as on the Game visits tab."""
    r = g["games"].get(key)
    if not r:
        return "Not played"
    h = r.get("hands") or {}
    l, rt = h.get("left") or {}, h.get("right") or {}
    if key == "fish":
        on = [x for x in (l.get("on_target"), rt.get("on_target")) if x is not None]
        txt = f"On lane {round(100 * sum(on) / len(on))}%" if on else "Played"
    else:
        got = (l.get("apples_reached") or 0) + (rt.get("apples_reached") or 0)
        total = (l.get("apples_total") or 0) + (rt.get("apples_total") or 0)
        txt = (f"Picked {got} of {total}" if key == "apple" else f"Caught {got} of {total}") if total else "Played"
        score = (((g.get("visit") or {}).get("games") or {}).get("rat") or {}).get("score") if key == "rat" else None
        if score is not None:
            txt += f", {score} pts"
    if key not in (g.get("games_finished") or []):
        txt += " (left early)"
    return txt


def _per_hand(rows: List[dict], get) -> List[tuple]:
    """Left and right series over visits (x = 1, 2, ...), skipping visits without a value."""
    out = []
    for name, side, color in (("Left", "left", RED), ("Right", "right", BLUE)):
        pts = []
        for i, r in enumerate(rows):
            v = get(r, side)
            if v is not None:
                pts.append((i + 1, v))
        out.append((name, pts, color))
    return out


def build_pdf(p: dict, draft: dict, source: str, note: Optional[str], tz: tzinfo = timezone.utc) -> bytes:
    ins = p["insights"]
    done = [s for s in reversed(p["sessions"]) if s["status"] == "completed"]
    games = [g for g in p.get("game_sessions", []) if g["games"]]  # newest first
    garden = p.get("garden_sessions", [])
    keyboard = sum(1 for g in games if g["is_synthetic"])
    now = datetime.now(tz)
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=0.75 * inch, rightMargin=0.75 * inch,
                            topMargin=0.7 * inch, bottomMargin=0.8 * inch,
                            title=f"Stick Drift summary - {p['display_name']}", author="Stick Drift")
    W = letter[0] - 1.5 * inch
    el = [P("Movement Activity Data Summary", H1),
          P("Prepared for clinician review. Descriptive only; no diagnosis is made.", SMALL), Spacer(1, 6)]

    starts = [x["started_at"] for x in done + games + garden]
    period = f"{_fmt_date(min(starts))} to {_fmt_date(max(starts))}" if starts else "no recorded activity yet"
    activity = [_n(len(games), "game visit")] if games else []
    activity += [_n(len(garden), "garden visit")] if garden else []
    if p["sessions"]:
        activity.append(_n(len(done), "reaction-test session"))
    if ins["status"] == "ok":
        activity.append(f"baseline from {_n(ins['usable_sessions'], baseline_unit(ins))}")
    if ins["synthetic"] or any(g["is_synthetic"] for g in garden):
        synth = "Yes. Some or all data are simulated and not from a real person."
    elif keyboard:
        synth = f"No. {keyboard} of {_n(len(games), 'game visit')} used keyboard input, not the controller."
    else:
        synth = "No"
    narrative = "Drafted by Gemini, checked automatically" if source == "gemini" else "Template wording"
    meta = [[P("Resident (alias)", CELLB), P(p["display_name"], CELL), P("Report generated", CELLB),
             P(now.strftime("%Y-%m-%d %H:%M %Z"), CELL)],
            [P("Dominant hand", CELLB), P(p["dominant_hand"], CELL), P("Period covered", CELLB), P(period, CELL)],
            [P("Recorded activity", CELLB), P(", ".join(activity) or "None yet", CELL),
             P("Simulated data", CELLB), P(synth, CELL)],
            [P("Instrument", CELLB), P("Stick Drift two-thumbstick activity, PS5 controller", CELL),
             P("Narrative", CELLB), P(narrative, CELL)]]
    el += [_tbl(meta, [1.2 * inch, 2.3 * inch, 1.2 * inch, W - 4.7 * inch], header=False), Spacer(1, 8)]

    el += [P("1. Summary", H2), P(draft["summary"]), P("2. Data and method", H2), P(draft["data_description"]),
           Spacer(1, 3), P(SCOPE, SMALL)]

    el.append(P("3. Observations (measured)", H2))
    if draft["observations"]:
        rows = [[P("Measure", CELLB), P("Finding", CELLB)]] + [
            [P(o["measure"], CELL), P(o["statement"], CELL)] for o in draft["observations"]]
        el.append(_tbl(rows, [1.8 * inch, W - 1.8 * inch]))
    else:
        el.append(P("No comparison measures are available yet."))

    el.append(P("4. Irregularities relative to the resident's own baseline", H2))
    if draft["irregularities"]:
        for ir in draft["irregularities"]:
            block = [P(f"{ir['title']}  ({ir['evidence_strength']})", TITLE), P(ir["description"]),
                     P("Interpretation: " + ir["interpretation"])]
            if ir["possible_contributors"]:
                block.append(P("Everyday factors to consider: " + "; ".join(ir["possible_contributors"]) + ".", SMALL))
            block.append(Spacer(1, 5))
            el.append(KeepTogether(block))
    else:
        el.append(P("No measurements moved beyond the thresholds used to flag a change."))

    charts, notes = [], []
    if done:
        left = [(i + 1, s["left_median_latency_ms"] / 1000) for i, s in enumerate(done)
                if s["left_median_latency_ms"] is not None]
        right = [(i + 1, s["right_median_latency_ms"] / 1000) for i, s in enumerate(done)
                 if s["right_median_latency_ms"] is not None]

        def accs(c, v):
            return [(i + 1, 100 * s[c] / s[v]) for i, s in enumerate(done) if s[c] is not None and s[v]]

        by = {f["key"]: f for f in ins["findings"]}
        base = by["left_latency"]["baseline"] / 1000 if "left_latency" in by else None
        charts += [_chart("Reaction test: median response time (s)", [("Left", left, RED), ("Right", right, BLUE)],
                          base, "%.2f"),
                   _chart("Reaction test: accuracy (% correct)", [("Left", accs("left_correct", "left_valid"), RED),
                          ("Right", accs("right_correct", "right_valid"), BLUE),
                          ("Both", accs("both_correct", "both_valid"), GREEN)], None, "%.0f")]
        if base is not None:
            notes.append("Dashed line: the resident's usual left-hand response time (median of earlier sessions).")

    # lobby games: controller visits only, oldest first, one chart per game's headline measure
    real = [g for g in reversed(games) if not g["is_synthetic"]]
    hand = lambda r, game, side: (((r["games"].get(game) or {}).get("hands") or {}).get(side) or {})
    for game, title, key, scale, yfmt in (
            ("apple", "Apple Picking: time to pick (s)", "reach_s", 1, "%.2f"),
            ("fish", "Harbour Fishing: time on the lane (%)", "on_target", 100, "%.0f"),
            ("rat", "Rat Catching: time to slam (s)", "reach_s", 1, "%.2f")):
        rows = [g for g in real if game in g["games"]]
        series = _per_hand(rows, lambda r, side: None if hand(r, game, side).get(key) is None
                           else hand(r, game, side)[key] * scale)
        if any(pts for _, pts, _ in series):
            charts.append(_chart(title, series, None, yfmt, "Visit with this game (oldest to newest)"))
    seen = [g for g in reversed(garden) if g.get("live") and not g["is_synthetic"]]
    live = lambda r, side: ((r["live"].get("hands") or {}).get(side) or {})
    for title, key, scale, yfmt in (("Garden: time to reach an apple (s)", "reach_s", 1, "%.2f"),
                                    ("Garden: distance from target (%)", "tracking_error", 100, "%.0f")):
        series = _per_hand(seen, lambda r, side: None if live(r, side).get(key) is None else live(r, side)[key] * scale)
        if any(pts for _, pts, _ in series):
            charts.append(_chart(title, series, None, yfmt, "Garden visit (oldest to newest)"))
    if games or garden:
        notes.append("Game and garden charts: each point is one visit. Free-play games have no usual level, so "
                     "nothing is marked as changed." + (" Keyboard visits are left out." if keyboard else ""))

    el.append(P("5. Trends across visits", H2))
    if charts:
        if len(charts) % 2:
            charts.append("")
        el.append(Table([charts[i:i + 2] for i in range(0, len(charts), 2)], colWidths=[W / 2, W / 2]))
        el += [P(n, SMALL) for n in notes]
    else:
        el.append(P("No measurements to chart yet."))

    el.append(P("6. Recorded activity (most recent first)", H2))
    if not (games or garden or p["sessions"]):
        el.append(P("Nothing has been recorded for this resident yet."))
    if games:
        rows = [[P(h, CELLB) for h in ("Date", "Games", "Apple Picking", "Harbour Fishing", "Rat Catching", "Input")]]
        for g in games[:12]:
            rows.append([P(_fmt_when(g["started_at"]) + (" (in progress)" if g["status"] == "in_progress" else ""), CELL),
                         P(f"{len(g['games'])} of 3", CELL)]
                        + [P(_game_cell(g, k), CELL) for k in ("apple", "fish", "rat")]
                        + [P("Keyboard" if g["is_synthetic"] else "Controller", CELL)])
        shown = f", latest {min(len(games), 12)} shown" if len(games) > 12 else ""
        el += [P(f"Game visits ({len(games)}{shown})", TITLE),
               _tbl(rows, [1.15 * inch, 0.55 * inch] + [(W - 2.45 * inch) / 3] * 3 + [0.75 * inch]), Spacer(1, 6)]
    if garden:
        secs = lambda v: "-" if v is None else f"{v:.2f} s"
        rows = [[P(h, CELLB) for h in ("Date", "Chapters", "Reach (left)", "Reach (right)", "Status")]]
        for g in garden[:10]:
            hands = (g.get("live") or {}).get("hands") or {}
            rows.append([P(_fmt_when(g["started_at"]) + (" (sim.)" if g["is_synthetic"] else ""), CELL),
                         P(f"{g.get('levels_completed') or 0}/{g.get('levels_total') or 4}", CELL),
                         P(secs((hands.get("left") or {}).get("reach_s")), CELL),
                         P(secs((hands.get("right") or {}).get("reach_s")), CELL),
                         P("Finished" if g["status"] == "completed" else "Stopped early", CELL)])
        el += [P(f"Garden visits ({len(garden)}{', latest 10 shown' if len(garden) > 10 else ''})", TITLE), _tbl(rows, [1.35 * inch] + [(W - 1.35 * inch) / 4] * 4),
               Spacer(1, 6)]
    if p["sessions"]:
        rows = [[P(h, CELLB) for h in ("Date", "Status/quality", "Left RT", "Right RT", "Left acc.", "Right acc.", "Both acc.")]]
        for s in p["sessions"][:10]:
            a = lambda c, v: f"{round(100 * s[c] / s[v])}%" if s[c] is not None and s[v] else "-"
            ms = lambda k: fmt("latency", s[k]) if s[k] is not None else "-"
            rows.append([P(_fmt_date(s["started_at"]) + (" (sim.)" if s.get("is_synthetic") else ""), CELL),
                         P(f"{s['status']}/{s['quality'] or '-'}", CELL),
                         P(ms("left_median_latency_ms"), CELL), P(ms("right_median_latency_ms"), CELL),
                         P(a("left_correct", "left_valid"), CELL), P(a("right_correct", "right_valid"), CELL),
                         P(a("both_correct", "both_valid"), CELL)])
        el += [P(f"Reaction-test sessions ({len(p['sessions'])})", TITLE),
               _tbl(rows, [1.35 * inch, 1.1 * inch] + [(W - 2.45 * inch) / 5] * 5)]

    lim = list(draft["limitations"]) + [
        "Comparison is against this resident's own earlier visits, not a population norm.",
        "Controller input reflects thumb movement and attention during a game; it cannot identify a cause.",
        "Results can be affected by tiredness, pain, medication, vision, mood, seating and how the controller was held."]
    if ins["synthetic"]:
        lim.append("Some data are simulated for demonstration and must not be read as a real person's results.")
    el += [P("7. Limitations", H2)] + bullets(lim)
    el += [P("8. Points for clinician consideration", H2)]
    el += bullets(draft["considerations"] or ["No specific items. Continue routine observation."])
    el += [Spacer(1, 8), P("Any new, sudden weakness, facial droop or speech difficulty should be handled under "
                           "the facility's urgent escalation protocol, not by waiting for this activity.", SMALL)]

    sign = _tbl([[P("Reviewed by (name / role)", CELLB), P("", CELL), P("Date", CELLB), P("", CELL)],
                 [P("Outcome", CELLB), P("[ ] Acknowledged    [ ] Needs assessment    [ ] No action", CELL),
                  P("", CELL), P("", CELL)]],
                [1.6 * inch, 3.0 * inch, 0.7 * inch, W - 5.3 * inch], header=False)
    el += [Spacer(1, 10), KeepTogether([P("Clinician review", H2), sign])]
    if note:
        el.append(P(note, SMALL))
    doc.build(el, onFirstPage=_page, onLaterPages=_page)
    return buf.getvalue()


@router.get("/caregiver/residents/{participant_id}/report.pdf")
def report_pdf(participant_id: UUID, tz: Optional[str] = Query(None, max_length=64),
               _: dict = Depends(current_caregiver)):
    with pool.connection() as conn:
        p = resident_profile(conn, participant_id)
    if p is None:
        raise HTTPException(404, "Resident not found.")
    zone = _zone(tz)
    p = _localize(p, zone)
    facts = build_facts([p], p)
    draft, source, note = draft_report(p, facts)
    pdf = build_pdf(p, draft, source, note, zone)
    name = re.sub(r"[^A-Za-z0-9]+", "_", p["display_name"]).strip("_") or "resident"
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="stick-drift-summary-{name}.pdf"',
                             "X-Report-Source": source})
