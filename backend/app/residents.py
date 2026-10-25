"""Caregiver read endpoints for residents' history and performance.

Residents do not get a history view; only caregivers see results. Insights compare
the latest game visits with the resident's own earlier visits (`insights.analyze`)
and add the pattern model's judgement of their latest scored game visits.
"""
from typing import Any, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from . import hand_replays
from .auth import current_caregiver
from .db import pool
from .insights import add_model_concerns, analyze, review_from
from .live.visit import save_unsaved_visits

router = APIRouter(tags=["residents"])


class Review(BaseModel):
    flagged: bool
    reasons: List[str]


class ConcernBrief(BaseModel):
    id: str
    title: str
    level: str


class ResidentRow(BaseModel):
    resident_id: UUID
    username: Optional[str]
    display_name: str
    dominant_hand: str
    visit_count: int
    last_played_at: Optional[Any]
    review: Review
    risk: str
    concerns: List[ConcernBrief]


class Visit(BaseModel):
    """One visit to the lobby: per-game results keyed apple / fish / rat."""
    session_id: UUID
    started_at: Any
    completed_at: Optional[Any]
    status: str
    is_synthetic: bool
    games: dict
    games_finished: List[str]
    tcn: Optional[dict] = None    # pattern-model scores for Apple Picking + Harbour Fishing (ml.visit_report)
    visit: Optional[dict] = None  # the full visit report: rat timing, traces, per-game results
    has_hand_replay: bool = False
    hand_replay: Optional[dict] = None  # game, window_start_s, duration_s, has_motion; the GIF is its own endpoint


class ResidentDetail(BaseModel):
    resident_id: UUID
    username: Optional[str]
    display_name: str
    dominant_hand: str
    review: Review
    insights: dict
    visits: List[Visit]


def _fetch_visits(conn, resident_id: UUID) -> List[dict]:
    rows = conn.execute(
        f"""SELECT s.session_id, s.started_at, s.completed_at, s.status, s.is_synthetic,
                  COALESCE(ss.metrics->'games', '{{}}'::jsonb) AS games,
                  ARRAY(SELECT jsonb_array_elements_text(COALESCE(ss.metrics->'games_finished', '[]'::jsonb)))
                    AS games_finished,
                  ss.metrics->'tcn' AS tcn, ss.metrics->'visit' AS visit,
                  {hand_replays.meta_sql('s.session_id')} AS hand_replay
           FROM sessions s
           LEFT JOIN session_summaries ss ON ss.session_id = s.session_id
           WHERE s.participant_id = %s AND s.protocol_version LIKE 'lobby-%%'
           ORDER BY s.started_at DESC LIMIT 50""",
        (resident_id,),
    ).fetchall()
    for row in rows:
        row["has_hand_replay"] = row["hand_replay"] is not None
    return rows


def _sweep():
    try:
        save_unsaved_visits()
    except Exception:
        pass  # a failed sweep must never block the caregiver's view; it retries on the next visit


def resident_profile(conn, resident_id: UUID) -> Optional[dict]:
    p = conn.execute(
        "SELECT username, alias, dominant_hand FROM participants WHERE participant_id = %s",
        (resident_id,),
    ).fetchone()
    if p is None:
        return None
    visits = _fetch_visits(conn, resident_id)
    insights = add_model_concerns(analyze(visits), visits)
    insights["visit_count"] = len(visits)
    return {
        "resident_id": resident_id, "username": p["username"],
        "display_name": p["alias"], "dominant_hand": p["dominant_hand"],
        "review": review_from(insights), "insights": insights,
        "visits": visits,
    }


def all_profiles(conn) -> List[dict]:
    ids = conn.execute(
        "SELECT participant_id FROM participants WHERE username IS NOT NULL ORDER BY alias"
    ).fetchall()
    return [resident_profile(conn, r["participant_id"]) for r in ids]


# ---- caregiver (all residents) -------------------------------------------

RISK_ORDER = {"check": 0, "watch": 1, "none": 2}


@router.get("/caregiver/residents", response_model=List[ResidentRow])
def residents(_: dict = Depends(current_caregiver)):
    _sweep()
    with pool.connection() as conn:
        profiles = all_profiles(conn)
    out = []
    for p in profiles:
        latest = p["visits"][:1]
        out.append({
            "resident_id": p["resident_id"], "username": p["username"],
            "display_name": p["display_name"], "dominant_hand": p["dominant_hand"],
            "visit_count": len(p["visits"]),
            "last_played_at": latest[0]["started_at"] if latest else None,
            "review": p["review"], "risk": p["insights"]["risk"],
            "concerns": p["insights"]["concerns"],
        })
    out.sort(key=lambda r: (RISK_ORDER[r["risk"]], r["display_name"].lower()))
    return out


@router.get("/caregiver/residents/{resident_id}", response_model=ResidentDetail)
def resident_detail(resident_id: UUID, _: dict = Depends(current_caregiver)):
    _sweep()
    with pool.connection() as conn:
        profile = resident_profile(conn, resident_id)
    if profile is None:
        raise HTTPException(404, "Resident not found.")
    return profile


@router.get("/caregiver/sessions/{session_id}/hand-replay.gif")
def hand_replay_gif(session_id: UUID, _: dict = Depends(current_caregiver)):
    """The visit's reconstructed-hands GIF (lobby visits from when replays began)."""
    gif = hand_replays.fetch_gif(session_id)
    if gif is None:
        raise HTTPException(404, "This visit has no hand replay.")
    return Response(gif, media_type="image/gif", headers={"Cache-Control": "private, max-age=86400"})
