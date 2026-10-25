"""Turn a resident's game visits into measured findings and potential concerns.

Everything here is deterministic and computed from the resident's own history:
their latest lobby visits are compared with the median of their earlier ones,
per game and hand. Concerns describe a *functional* change worth checking (e.g.
"one-sided slowing") with possible everyday contributors and recommended
caregiver checks. The pattern model adds its own concerns (`add_model_concerns`).
Nothing here names a disease.
"""
from statistics import median
from typing import Dict, List, Optional

MIN_VISITS = 4          # controller visits needed before a baseline is set
# A change has to clear both the absolute and the relative step.
SECONDS_RISE = 0.15     # reaction / reach time
DISTANCE_RISE = 0.03    # distance from the fishing lane (stick units, -1..1)
RELATIVE_RISE = 0.20    # and at least 20% worse than usual
SHARE_DROP = 0.10       # 10 points less time on the lane

REFERENCES = {
    "der_deary": "Der G, Deary IJ. Age and sex differences in reaction time in adulthood: results from the "
                 "United Kingdom Health and Lifestyle Survey. Psychol Aging. 2006;21(1):62-73.",
    "ranganathan": "Ranganathan VK, Siemionow V, Sahgal V, Yue GH. Effects of aging on hand function. "
                   "J Am Geriatr Soc. 2001;49(11):1478-1484.",
    "beers": "2023 American Geriatrics Society Beers Criteria Update Expert Panel. American Geriatrics Society "
             "2023 updated AGS Beers Criteria for potentially inappropriate medication use in older adults. "
             "J Am Geriatr Soc. 2023;71(7):2052-2081.",
    "cam": "Inouye SK, et al. Clarifying confusion: the Confusion Assessment Method. "
           "Ann Intern Med. 1990;113(12):941-948.",
    "steadi": "Centers for Disease Control and Prevention. STEADI: Stopping Elderly Accidents, Deaths & "
              "Injuries - older adult fall prevention toolkit.",
}

DISCLAIMER = ("A prompt to check in, not a diagnosis. Changes can come from tiredness, pain, medication, "
              "vision, mood or an unfamiliar setup.")



# ---- comparing one measurement with its baseline ------------------------------------
# kind: "seconds" (higher is worse), "distance" (higher is worse) or "share" (lower is worse).

def fmt(kind: str, v: float) -> str:
    return f"{v:.2f} s" if kind == "seconds" else f"{round(v * 100)}%"


def _fmt_change(kind: str, delta: float) -> str:
    return f"{delta:+.2f} s" if kind == "seconds" else f"{round(delta * 100):+d} pts"


def _worse(kind: str, base: float, now: float) -> bool:
    if kind == "seconds":
        return now - base >= SECONDS_RISE and now >= base * (1 + RELATIVE_RISE)
    if kind == "distance":
        return now - base >= DISTANCE_RISE and now >= base * (1 + RELATIVE_RISE)
    return base - now >= SHARE_DROP - 1e-9


def _better(kind: str, base: float, now: float) -> bool:
    if kind == "seconds":
        return base - now >= SECONDS_RISE and now <= base * (1 - RELATIVE_RISE)
    if kind == "distance":
        return base - now >= DISTANCE_RISE and now <= base * (1 - RELATIVE_RISE)
    return now - base >= SHARE_DROP - 1e-9


def _finding(key: str, label: str, hand: str, kind: str, baseline: List[dict], recent: List[dict]) -> Optional[dict]:
    base_vals = [m[key] for m in baseline if m[key] is not None]
    now = recent[0][key]
    if not base_vals or now is None:
        return None
    base = median(base_vals)
    flagged_ids = [m["session_id"] for m in recent if m[key] is not None and _worse(kind, base, m[key])]
    worse = _worse(kind, base, now)
    direction = "worse" if worse else "better" if _better(kind, base, now) else "steady"
    return {
        "key": key, "label": label, "hand": hand, "kind": kind,
        "baseline": base, "latest": now, "change": now - base,
        "baseline_text": fmt(kind, base), "latest_text": fmt(kind, now),
        "change_text": _fmt_change(kind, now - base),
        "direction": direction, "flagged": worse,
        "persistent": worse and len(flagged_ids) == len(recent) and len(recent) > 1,
        "flagged_visit_ids": flagged_ids if worse else [],
        "text": f"{label}: {fmt(kind, now)} vs usual {fmt(kind, base)} ({_fmt_change(kind, now - base)}).",
    }


# ---- concerns -------------------------------------------------------------------

def _concern(cid, title, level, summary, evidence, contributors, checks, refs, keys):
    return {
        "id": cid, "title": title, "level": level, "summary": summary,
        "evidence": evidence, "possible_contributors": contributors,
        "recommended_checks": checks, "references": [REFERENCES[r] for r in refs],
        "measurements": keys,
    }


def _general_concern(level: str, evidence: List[str], keys: List[str]) -> dict:
    return _concern(
        "general_slowing", "Slower or less accurate in both hands", level,
        "Both hands changed together, which points to something affecting the whole person rather than "
        "one hand.",
        evidence,
        ["Tiredness or poor sleep", "Acute illness, infection or dehydration",
         "A new or changed medication, especially a sedating one", "Pain, low mood or distraction"],
        ["Ask how they slept and how they are feeling today.",
         "Check temperature, fluid intake and any signs of infection.",
         "Review medication changes from the last two weeks with the pharmacist or prescriber.",
         "Watch for new confusion or a drop in alertness. If it is sudden, escalate to the nurse the same day.",
         "Consider a falls-risk check, since slower reactions can raise fall risk.",
         "Repeat the activity at the usual time in 1-2 days. If the change persists, request a nursing or "
         "physician assessment."],
        ["der_deary", "beers", "cam", "steadi"], keys)


def _one_sided_concern(hand: str, level: str, evidence: List[str], steady: List[str], keys: List[str]) -> dict:
    other = "right" if hand == "left" else "left"
    return _concern(
        f"one_sided_{hand}", f"One-sided change: {hand} hand", level,
        f"The {hand} hand changed while the {other} hand stayed close to usual. Tiredness and "
        "attention usually affect both hands, so a one-sided change is worth a closer look.",
        evidence + [f"Unchanged for comparison - {t}" for t in steady],
        [f"Pain, stiffness or injury in the {hand} hand, wrist or thumb",
         "An arthritis flare or swelling",
         f"New numbness, tingling, weakness or clumsiness on the {hand} side",
         f"Difficulty seeing the {hand} side of the screen",
         "A change in how the controller was held or placed"],
        [f"Ask about pain, stiffness or injury in the {hand} hand, wrist or thumb, and look for swelling.",
         "Compare grip and finger movement between both hands (for example, ask them to squeeze both "
         "of your hands).",
         f"Ask about new numbness, tingling or clumsiness on the {hand} side. If weakness, facial droop "
         "or speech difficulty is new or sudden, follow your facility's urgent escalation protocol now.",
         "Check the setup: glasses, seating and screen position, and how the controller was held.",
         "Repeat the activity in 1-2 days. If the change persists, request a nursing or physician "
         "assessment, and consider an occupational therapy hand-function review."],
        ["ranganathan", "der_deary"], keys)


# ---- the baseline from lobby visits -----------------------------------------------

# (game, measurement, label, kind), read from each visit's games.<game>.hands.<hand>.
MEASURES = [
    ("apple", "reaction_s", "Apple Picking reaction time", "seconds"),
    ("apple", "reach_s", "Apple Picking time to reach", "seconds"),
    ("fish", "tracking_error", "Harbour Fishing distance from the lane", "distance"),
    ("fish", "on_target", "Harbour Fishing time on the lane", "share"),
    ("rat", "reach_s", "Rat Catching time to slam", "seconds"),
]


def _visit_metrics(visit: dict) -> Dict[str, Optional[float]]:
    games = visit.get("games") or {}
    out: Dict[str, Optional[float]] = {}
    for game, field, _, _ in MEASURES:
        hands = (games.get(game) or {}).get("hands") or {}
        for hand in ("left", "right"):
            out[f"{game}_{field}_{hand}"] = (hands.get(hand) or {}).get(field)
    return out


def _measure(key: str) -> tuple:
    """(label, hand, kind) for a key such as apple_reach_s_left."""
    hand = key.rsplit("_", 1)[1]
    for game, field, label, kind in MEASURES:
        if key == f"{game}_{field}_{hand}":
            return f"{label}, {hand} hand", hand, kind
    raise KeyError(key)


def analyze(visits: List[dict]) -> dict:
    """Visits come newest-first, as returned by residents._fetch_visits. Keyboard visits are left out."""
    usable = [v for v in visits if not v.get("is_synthetic") and v["status"] in ("completed", "abandoned")
              and v.get("games")]
    base = {"usable_visits": len(usable), "disclaimer": DISCLAIMER}
    if len(usable) < MIN_VISITS:
        return {**base, "status": "insufficient", "risk": "none", "baseline_visits": 0,
                "recent_visit_ids": [], "findings": [], "concerns": [],
                "summary": f"Not enough game visits with the controller yet to set a personal baseline "
                           f"({len(usable)} of {MIN_VISITS})."}

    # With enough history, compare the last two visits so a persisting change is visible
    # and the baseline isn't contaminated by it.
    recent_n = 2 if len(usable) >= 5 else 1
    recent = [{"session_id": v["session_id"], **_visit_metrics(v)} for v in usable[:recent_n]]
    baseline = [{"session_id": v["session_id"], **_visit_metrics(v)} for v in usable[recent_n:]]
    keys = [f"{g}_{f}_{h}" for g, f, _, _ in MEASURES for h in ("left", "right")]
    findings = [x for x in (_finding(k, *_measure(k), baseline, recent) for k in keys) if x]

    hits = {h: [x for x in findings if x["hand"] == h and x["flagged"]] for h in ("left", "right")}

    def level(found):
        return "check" if len(found) >= 2 or any(x["persistent"] for x in found) else "watch"

    concerns: List[dict] = []
    if hits["left"] and hits["right"]:
        found = hits["left"] + hits["right"]
        concerns.append(_general_concern(level(found), [x["text"] for x in found], [x["key"] for x in found]))
    else:
        for hand in ("left", "right"):
            if hits[hand]:
                steady = [x["text"] for x in findings if x["hand"] != hand and not x["flagged"]]
                concerns.append(_one_sided_concern(hand, level(hits[hand]), [x["text"] for x in hits[hand]],
                                                   steady, [x["key"] for x in hits[hand]]))

    risk = "check" if any(c["level"] == "check" for c in concerns) else "watch" if concerns else "none"
    summary = ("; ".join(c["title"] for c in concerns) + ".") if concerns else \
        "Recent game visits are in line with this resident's usual pattern."
    return {**base, "status": "ok", "risk": risk, "baseline_visits": len(baseline),
            "recent_visit_ids": [m["session_id"] for m in recent], "findings": findings, "concerns": concerns,
            "summary": summary}


def review_from(insights: dict) -> dict:
    """Short card form used in lists: flagged + the measurements that moved."""
    concerns = insights["concerns"]
    keys = {k for c in concerns for k in c["measurements"]}
    reasons = [f["text"] for f in insights["findings"] if f["key"] in keys]
    reasons += [c["evidence"][0] for c in concerns if c["id"].startswith("model_") and c["evidence"]]
    if concerns and not reasons:
        reasons = [e for c in concerns for e in c["evidence"]]
    return {"flagged": bool(concerns), "reasons": reasons}


# ---- TCN pattern model --------------------------------------------------------------

MODEL_WATCH = 50.0
MODEL_CHECK = 70.0

# Model output keys -> the neutral wording caregivers and the assistant see. The keys are condition
# names only because of how the training folders are labelled (ml/pattern_model/config.py); no condition name is
# ever shown. Each score is resemblance to that movement pattern, not a diagnosis.
# Keep in step with web/src/components/liveData.ts.
PATTERN_LABELS = {
    "parkinson": "Slower, smaller movements in both hands",
    "stroke": "One hand weaker or slower than the other",
    "essential_tremor": "Rhythmic shake while moving",
}

PATTERN_GUIDE = {
    "parkinson": (
        ["Tiredness or poor sleep", "A new or changed medication", "Stiffness or pain in both hands",
         "Low mood or reduced energy"],
        ["Ask how they slept and how they are feeling today.",
         "Watch them do an everyday two-handed task (opening a container, buttoning) and note any slowness.",
         "Review medication changes from the last two weeks with the pharmacist or prescriber.",
         "Repeat the games in 1-2 days. If the pattern persists, request a nursing or physician assessment."],
    ),
    "stroke": (
        ["Pain, stiffness or injury in one hand", "New numbness, tingling or weakness on one side",
         "Difficulty seeing one side of the screen", "How the controller was held"],
        ["Compare grip and finger movement between both hands.",
         "Ask about new numbness, tingling or clumsiness on one side. If weakness, facial droop or speech "
         "difficulty is new or sudden, follow your facility's urgent escalation protocol now.",
         "Check the setup: glasses, seating and screen position.",
         "Repeat the games in 1-2 days. If the difference persists, request a nursing or physician assessment."],
    ),
    "essential_tremor": (
        ["Caffeine, anxiety or feeling cold", "A new or changed medication", "Tiredness",
         "Shaking the controller on purpose or an unsteady grip"],
        ["Watch their hands while they reach for a cup and while resting in their lap; note when the shake appears.",
         "Ask about caffeine, stress, cold and recent medication changes.",
         "If the shake is new or getting worse, mention it at the next nursing review."],
    ),
}


GAME_LABELS = {"apple": "Apple Picking", "fish": "Harbour Fishing"}


def add_model_concerns(insights: dict, visits: List[dict]) -> dict:
    """Add a concern when the newest scored game visit resembles a movement pattern.

    Apple Picking and Harbour Fishing are scored. Scores are 0-100 pattern resemblance, not disease
    probabilities. One high visit is something to keep an eye on; "check soon" needs the two latest
    scored visits at or above MODEL_CHECK, so a single noisy visit can't raise it.
    """
    judged = [v for v in visits
              if v.get("tcn") and any((v["tcn"].get("scores") or {}).get(k) is not None for k in PATTERN_LABELS)]
    if not judged:
        return insights
    latest = judged[0]
    when = latest["started_at"].strftime("%b %d") if hasattr(latest["started_at"], "strftime") else "latest"
    simulated = " (simulated input)" if latest.get("is_synthetic") else ""
    concerns = list(insights["concerns"])
    for key, label in PATTERN_LABELS.items():
        score = latest["tcn"]["scores"].get(key)
        if score is None or score < MODEL_WATCH:
            continue
        previous = judged[1]["tcn"]["scores"].get(key) if len(judged) > 1 else None
        repeated = score >= MODEL_CHECK and previous is not None and previous >= MODEL_CHECK
        contributors, checks = PATTERN_GUIDE[key]
        per_game = [f"{GAME_LABELS.get(g, g)}: {part['scores'][key]:.0f}/100"
                    for g, part in (latest["tcn"].get("by_game") or {}).items()
                    if (part.get("scores") or {}).get(key) is not None]
        concerns.append(_concern_raw(
            f"model_{key}",
            f"Movement pattern: {label.lower()}", "check" if repeated else "watch",
            f"At the end of the {when} game visit{simulated}, the movement pattern model rated it "
            f"{score:.0f} out of 100 for resemblance to this pattern"
            f"{f', and {previous:.0f} the game visit before' if repeated else ''}.",
            [f"{label}: {score:.0f}/100 pattern resemblance (game visit, {when})."] + per_game,
            contributors, checks,
        ))
    if len(concerns) == len(insights["concerns"]):
        return insights
    risk = "check" if any(c["level"] == "check" for c in concerns) else "watch"
    return {**insights, "concerns": concerns, "risk": risk, "summary": "; ".join(c["title"] for c in concerns) + "."}


def _concern_raw(cid, title, level, summary, evidence, contributors, checks):
    return {"id": cid, "title": title, "level": level, "summary": summary, "evidence": evidence,
            "possible_contributors": contributors, "recommended_checks": checks,
            "references": ["Stick Drift movement pattern model (ml/pattern_model/), trained on teammate-acted and synthetic "
                           "recordings. Scores are pattern resemblance, not clinical validation."],
            "measurements": []}
