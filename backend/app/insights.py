"""Turn a resident's history into measured findings and potential concerns.

Everything here is deterministic and computed from the resident's own history:
the latest results are compared with the median of their earlier ones. Lobby game
visits (`analyze_lobby`) are the baseline for real residents; the older
reaction-test sessions (`analyze`) only exist for demo residents and are used when
there are not enough game visits. Concerns describe a *functional* change worth
checking (e.g. "one-sided slowing") with possible everyday contributors and
recommended caregiver checks. They never name a disease.
"""
from statistics import median
from typing import Dict, List, Optional

# How far a measurement must move from the personal baseline to count.
LATENCY_RISE_MS = 150.0
ACCURACY_DROP = 0.15  # share of prompts, ~2 of 12
GAP_CHANGE_MS = 150.0
ENJOYMENT_DROP = 2
MIN_USABLE = 4
# Lobby games: a change has to clear both the absolute and the relative step.
SECONDS_RISE = 0.15     # reaction / reach time
DISTANCE_RISE = 0.03    # distance from the fishing lane (stick units, -1..1)
RELATIVE_RISE = 0.20    # and at least 20% worse than usual
SHARE_DROP = 0.10       # 10 points less time on the lane

REFERENCES = {
    "der_deary": "Der G, Deary IJ. Age and sex differences in reaction time in adulthood: results from the "
                 "United Kingdom Health and Lifestyle Survey. Psychol Aging. 2006;21(1):62-73.",
    "macdonald": "MacDonald SWS, Hultsch DF, Dixon RA. Performance variability is related to change in "
                 "cognition: evidence from the Victoria Longitudinal Study. Psychol Aging. 2003;18(3):510-523.",
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


def _acc(correct: Optional[int], valid: Optional[int]) -> Optional[float]:
    return correct / valid if correct is not None and valid else None


def _metrics(s: dict) -> Dict[str, Optional[float]]:
    left, right = s.get("left_median_latency_ms"), s.get("right_median_latency_ms")
    return {
        "left_latency": left,
        "right_latency": right,
        "left_accuracy": _acc(s.get("left_correct"), s.get("left_valid")),
        "right_accuracy": _acc(s.get("right_correct"), s.get("right_valid")),
        "both_accuracy": _acc(s.get("both_correct"), s.get("both_valid")),
        "lr_gap": left - right if left is not None and right is not None else None,
        "enjoyment": s.get("enjoyment"),
    }


# key -> (label, hand, kind). kind decides formatting and which direction is worse.
MEASURES = {
    "left_latency": ("Left-hand response time", "left", "latency"),
    "right_latency": ("Right-hand response time", "right", "latency"),
    "left_accuracy": ("Left-hand accuracy", "left", "accuracy"),
    "right_accuracy": ("Right-hand accuracy", "right", "accuracy"),
    "both_accuracy": ("Both-hands accuracy", "both", "accuracy"),
    "lr_gap": ("Left minus right response time", None, "gap"),
    "enjoyment": ("Enjoyment rating", None, "enjoyment"),
}


def fmt(kind: str, v: float) -> str:
    if kind == "latency":
        return f"{v / 1000:.2f} s"
    if kind == "gap":
        return f"{v / 1000:+.2f} s"
    if kind == "seconds":
        return f"{v:.2f} s"
    if kind in ("accuracy", "distance", "share"):
        return f"{round(v * 100)}%"
    return f"{v:.0f}/5" if float(v).is_integer() else f"{v:.1f}/5"


def _fmt_change(kind: str, delta: float) -> str:
    if kind in ("latency", "gap"):
        return f"{delta / 1000:+.2f} s"
    if kind == "seconds":
        return f"{delta:+.2f} s"
    if kind in ("accuracy", "distance", "share"):
        return f"{round(delta * 100):+d} pts"
    return f"{delta:+.1f}"


def _worse(kind: str, base: float, now: float) -> bool:
    if kind == "latency":
        return now - base >= LATENCY_RISE_MS
    if kind == "accuracy":
        return base - now >= ACCURACY_DROP - 1e-9
    if kind == "gap":
        return abs(now - base) >= GAP_CHANGE_MS
    if kind == "seconds":
        return now - base >= SECONDS_RISE and now >= base * (1 + RELATIVE_RISE)
    if kind == "distance":
        return now - base >= DISTANCE_RISE and now >= base * (1 + RELATIVE_RISE)
    if kind == "share":
        return base - now >= SHARE_DROP - 1e-9
    return base - now >= ENJOYMENT_DROP


def _better(kind: str, base: float, now: float) -> bool:
    if kind == "latency":
        return base - now >= LATENCY_RISE_MS
    if kind == "accuracy":
        return now - base >= ACCURACY_DROP - 1e-9
    if kind == "gap":
        return False
    if kind == "seconds":
        return base - now >= SECONDS_RISE and now <= base * (1 - RELATIVE_RISE)
    if kind == "distance":
        return base - now >= DISTANCE_RISE and now <= base * (1 - RELATIVE_RISE)
    if kind == "share":
        return now - base >= SHARE_DROP - 1e-9
    return now - base >= ENJOYMENT_DROP


def _finding(key: str, baseline: List[dict], recent: List[dict], measure: Optional[tuple] = None) -> Optional[dict]:
    label, hand, kind = measure or MEASURES[key]
    base_vals = [m[key] for m in baseline if m[key] is not None]
    latest = recent[0]
    now = latest[key]
    if not base_vals or now is None:
        return None
    base = median(base_vals)
    flagged_ids = [m["session_id"] for m in recent if m[key] is not None and _worse(kind, base, m[key])]
    worse = _worse(kind, base, now)
    direction = "worse" if worse else "better" if _better(kind, base, now) else "steady"
    text = f"{label}: {fmt(kind, now)} vs usual {fmt(kind, base)} ({_fmt_change(kind, now - base)})."
    return {
        "key": key, "label": label, "hand": hand, "kind": kind,
        "baseline": base, "latest": now, "change": now - base,
        "baseline_text": fmt(kind, base), "latest_text": fmt(kind, now),
        "change_text": _fmt_change(kind, now - base),
        "direction": direction, "flagged": worse,
        "persistent": worse and len(flagged_ids) == len(recent) and len(recent) > 1,
        "flagged_session_ids": flagged_ids if worse else [],
        "text": text,
    }


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


def _concerns(f: Dict[str, dict], recent_abandoned: int) -> List[dict]:
    def worse(k):
        return k in f and f[k]["flagged"]

    def level(keys):
        hits = [f[k] for k in keys if worse(k)]
        return "check" if len(hits) >= 2 or any(h["persistent"] for h in hits) else "watch"

    out: List[dict] = []
    general = (worse("left_latency") and worse("right_latency")) or (
        worse("left_accuracy") and worse("right_accuracy"))

    if general:
        keys = [k for k in ("left_latency", "right_latency", "left_accuracy", "right_accuracy",
                            "both_accuracy") if worse(k)]
        out.append(_general_concern(level(keys), [f[k]["text"] for k in keys], keys))
    else:
        for hand, other in (("left", "right"), ("right", "left")):
            keys = [k for k in (f"{hand}_latency", f"{hand}_accuracy") if worse(k)]
            if not keys:
                continue
            keys += [k for k in ("lr_gap", "both_accuracy") if worse(k)]
            steady = [f[k]["text"] for k in (f"{other}_latency", f"{other}_accuracy") if k in f]
            out.append(_one_sided_concern(hand, level(keys), [f[k]["text"] for k in keys], steady, keys))

    if worse("both_accuracy") and not general and not out:
        keys = ["both_accuracy"]
        out.append(_concern(
            "coordination", "Lower two-hand coordination", level(keys),
            "Using both sticks together got harder while each hand on its own stayed close to usual.",
            [f["both_accuracy"]["text"]],
            ["Reduced concentration or divided attention", "Tiredness",
             "A noisy or distracting setting", "Feeling unwell"],
            ["Note anything distracting in the room during the session.",
             "Ask about concentration, sleep and how they are feeling.",
             "Repeat the activity in a quiet setting in 1-2 days.",
             "If it persists alongside changes in memory or daily routines, raise it with the care team and "
             "consider a cognitive screen under your facility's process."],
            ["macdonald"], keys))

    if worse("enjoyment") or recent_abandoned >= 2:
        keys = ["enjoyment"] if worse("enjoyment") else []
        evidence = [f["enjoyment"]["text"]] if worse("enjoyment") else []
        if recent_abandoned >= 2:
            evidence.append(f"{recent_abandoned} of the last 3 sessions were stopped early.")
        out.append(_concern(
            "engagement", "Less engagement than usual", "watch",
            "The resident is enjoying or finishing the activity less than usual.",
            evidence,
            ["Low mood", "Pain or discomfort", "Tiredness", "Frustration with the activity"],
            ["Ask how they are feeling and what they thought of the activity.",
             "Check for pain or discomfort.",
             "Offer the activity at a different time of day.",
             "If low mood continues, mention it at the next care-team review."],
            ["macdonald"], keys))

    return out


def analyze(sessions: List[dict]) -> dict:
    """Sessions come newest-first, as returned by views._fetch_sessions."""
    usable = [s for s in sessions if s["status"] == "completed" and s["quality"] in ("good", "flagged")]
    synthetic = any(s.get("is_synthetic") for s in sessions)
    recent_abandoned = sum(1 for s in sessions[:3] if s["status"] == "abandoned")
    base = {"source": "sessions", "usable_sessions": len(usable), "synthetic": synthetic, "disclaimer": DISCLAIMER}

    if len(usable) < MIN_USABLE:
        return {**base, "status": "insufficient", "risk": "none", "baseline_sessions": 0,
                "recent_session_ids": [], "findings": [], "concerns": [],
                "summary": f"Not enough completed sessions yet to set a personal baseline "
                           f"({len(usable)} of {MIN_USABLE})."}

    # With enough history, compare the last two sessions so a persisting change is visible
    # and the baseline isn't contaminated by it.
    recent_n = 2 if len(usable) >= 5 else 1
    recent = [{"session_id": s["session_id"], **_metrics(s)} for s in usable[:recent_n]]
    baseline = [{"session_id": s["session_id"], **_metrics(s)} for s in usable[recent_n:]]

    findings = [x for x in (_finding(k, baseline, recent) for k in MEASURES) if x]
    by_key = {x["key"]: x for x in findings}
    concerns = _concerns(by_key, recent_abandoned)

    risk = "check" if any(c["level"] == "check" for c in concerns) else "watch" if concerns else "none"
    if concerns:
        summary = "; ".join(c["title"] for c in concerns) + "."
    else:
        summary = "Recent sessions are in line with this resident's usual pattern."
    return {**base, "status": "ok", "risk": risk, "baseline_sessions": len(baseline),
            "recent_session_ids": [m["session_id"] for m in recent], "findings": findings, "concerns": concerns, "summary": summary}


def review_from(insights: dict) -> dict:
    """Short card form used in lists: flagged + the measurements that moved."""
    concerns = insights["concerns"]
    keys = {k for c in concerns for k in c["measurements"]}
    reasons = [f["text"] for f in insights["findings"] if f["key"] in keys]
    reasons += [c["evidence"][0] for c in concerns if c["id"].startswith("model_") and c["evidence"]]
    if concerns and not reasons:
        reasons = [e for c in concerns for e in c["evidence"]]
    return {"flagged": bool(concerns), "reasons": reasons}


# ---- lobby game visits ------------------------------------------------------------

# (game, measurement, label, kind), read from each visit's games.<game>.hands.<hand>.
LOBBY_MEASURES = [
    ("apple", "reaction_s", "Apple Picking reaction time", "seconds"),
    ("apple", "reach_s", "Apple Picking time to reach", "seconds"),
    ("fish", "tracking_error", "Harbour Fishing distance from the lane", "distance"),
    ("fish", "on_target", "Harbour Fishing time on the lane", "share"),
    ("rat", "reach_s", "Rat Catching time to slam", "seconds"),
]


def _lobby_metrics(visit: dict) -> Dict[str, Optional[float]]:
    games = visit.get("games") or {}
    out: Dict[str, Optional[float]] = {}
    for game, field, _, _ in LOBBY_MEASURES:
        hands = (games.get(game) or {}).get("hands") or {}
        for hand in ("left", "right"):
            out[f"{game}_{field}_{hand}"] = (hands.get(hand) or {}).get(field)
    return out


def _lobby_measure(key: str) -> tuple:
    """(label, hand, kind) for a key such as apple_reach_s_left."""
    hand = key.rsplit("_", 1)[1]
    for game, field, label, kind in LOBBY_MEASURES:
        if key == f"{game}_{field}_{hand}":
            return f"{label}, {hand} hand", hand, kind
    raise KeyError(key)


def analyze_lobby(visits: List[dict]) -> dict:
    """Lobby visits come newest-first, as returned by views._fetch_games. Keyboard visits are left out."""
    usable = [v for v in visits if not v.get("is_synthetic") and v["status"] in ("completed", "abandoned")
              and v.get("games")]
    base = {"source": "lobby", "usable_sessions": len(usable), "synthetic": False, "disclaimer": DISCLAIMER}
    if len(usable) < MIN_USABLE:
        return {**base, "status": "insufficient", "risk": "none", "baseline_sessions": 0,
                "recent_session_ids": [], "findings": [], "concerns": [],
                "summary": f"Not enough game visits with the controller yet to set a personal baseline "
                           f"({len(usable)} of {MIN_USABLE})."}

    recent_n = 2 if len(usable) >= 5 else 1
    recent = [{"session_id": v["session_id"], **_lobby_metrics(v)} for v in usable[:recent_n]]
    baseline = [{"session_id": v["session_id"], **_lobby_metrics(v)} for v in usable[recent_n:]]
    keys = [f"{g}_{f}_{h}" for g, f, _, _ in LOBBY_MEASURES for h in ("left", "right")]
    findings = [x for x in (_finding(k, baseline, recent, _lobby_measure(k)) for k in keys) if x]

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
    return {**base, "status": "ok", "risk": risk, "baseline_sessions": len(baseline),
            "recent_session_ids": [m["session_id"] for m in recent], "findings": findings, "concerns": concerns,
            "summary": summary}


def resident_insights(sessions: List[dict], game_visits: List[dict]) -> dict:
    """Game visits are the baseline. Demo residents' older reaction-test sessions stand in when there are
    not enough visits yet."""
    lobby = analyze_lobby(game_visits)
    if lobby["status"] == "ok" or not sessions:
        return lobby
    return analyze(sessions)


# ---- TCN pattern model --------------------------------------------------------------

MODEL_WATCH = 50.0
MODEL_CHECK = 70.0

# Model output keys -> the neutral wording caregivers and the assistant see. The keys are condition
# names only because of how the training folders are labelled (tcn/config.py); no condition name is
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


def add_model_concerns(insights: dict, garden_sessions: List[dict], kind: str = "garden") -> dict:
    """Add a concern when the newest TCN-judged session of this kind resembles a movement pattern.

    `kind` is "garden" (the pygame garden) or "lobby" (web lobby visits, where Apple Picking and
    Harbour Fishing are scored). Scores are 0-100 pattern resemblance, not disease probabilities.
    One high visit is something to keep an eye on; "check soon" needs the two latest judged visits
    at or above MODEL_CHECK, so a single noisy visit can't raise it.
    """
    judged = [g for g in garden_sessions
              if g.get("tcn") and any((g["tcn"].get("scores") or {}).get(k) is not None for k in PATTERN_LABELS)]
    noun = "garden session" if kind == "garden" else "game visit"
    if kind == "garden":
        visits, n_judged = len(garden_sessions), len(judged)
        insights = {**insights, "garden_visits": visits, "garden_judged": n_judged}
        if insights["status"] == "insufficient" and visits:
            # A baseline from earlier session summaries needs 4 sessions; garden visits are judged on their own.
            insights["summary"] = (
                f"{visits} garden {'visit' if visits == 1 else 'visits'} recorded"
                f"{f', {n_judged} judged by the pattern model' if n_judged else ''}."
            )
    if not judged:
        return insights
    latest = judged[0]
    when = latest["started_at"].strftime("%b %d") if hasattr(latest["started_at"], "strftime") else "latest"
    simulated = " (simulated input)" if latest.get("is_synthetic") else ""
    concerns = list(insights["concerns"])
    added = False
    for key, label in PATTERN_LABELS.items():
        score = latest["tcn"]["scores"].get(key)
        if score is None or score < MODEL_WATCH:
            continue
        previous = judged[1]["tcn"]["scores"].get(key) if len(judged) > 1 else None
        repeated = score >= MODEL_CHECK and previous is not None and previous >= MODEL_CHECK
        contributors, checks = PATTERN_GUIDE[key]
        per_part = [f"{lv['level'].replace('_', ' ')}: {lv['scores'][key]:.0f}/100"
                    for lv in latest["tcn"].get("levels", []) if lv.get("scores", {}).get(key) is not None]
        per_part += [f"{GAME_LABELS.get(g, g)}: {part['scores'][key]:.0f}/100"
                     for g, part in (latest["tcn"].get("by_game") or {}).items()
                     if (part.get("scores") or {}).get(key) is not None]
        concerns.append(_concern_raw(
            f"model_{key}" if kind == "garden" else f"model_{kind}_{key}",
            f"Movement pattern: {label.lower()}", "check" if repeated else "watch",
            f"At the end of the {when} {noun}{simulated}, the movement pattern model rated it "
            f"{score:.0f} out of 100 for resemblance to this pattern"
            f"{f', and {previous:.0f} the {noun} before' if repeated else ''}.",
            [f"{label}: {score:.0f}/100 pattern resemblance ({noun}, {when})."] + per_part,
            contributors, checks,
        ))
        added = True
    risk = "check" if any(c["level"] == "check" for c in concerns) else "watch" if concerns else "none"
    if concerns:
        summary = "; ".join(c["title"] for c in concerns) + "."
    elif insights["status"] == "insufficient" and kind == "garden":
        summary = f"{insights['summary']} The latest visit showed no movement pattern worth flagging."
    else:
        summary = insights["summary"]
    if kind != "garden" and not added:
        return insights
    return {**insights, "concerns": concerns, "risk": risk, "summary": summary}


def _concern_raw(cid, title, level, summary, evidence, contributors, checks):
    return {"id": cid, "title": title, "level": level, "summary": summary, "evidence": evidence,
            "possible_contributors": contributors, "recommended_checks": checks,
            "references": ["Stick Drift movement pattern model (tcn/), trained on teammate-acted and synthetic "
                           "recordings. Scores are pattern resemblance, not clinical validation."],
            "measurements": []}
