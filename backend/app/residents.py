"""Caregiver read endpoints for residents' history and performance.

Residents do not get a history view; only caregivers see results. Insights compare
the latest game visits with the resident's own earlier visits (`insights.analyze`)
and add the pattern model's judgement of their latest scored game visits.
"""
from typing import Any, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from . import hand_replays, live
from .auth import current_caregiver
from .db import pool
from .insights import add_model_concerns, analyze, review_from

router = APIRouter(tags=["residents"])


class Review(BaseModel):
    flagged: bool
    reasons: List[str]


class ConcernBrief(BaseModel):
    id: str
    title: str
    level: str


class ResidentRow(BaseModel):
    participant_id: UUID
    username: Optional[str]
    display_name: str
    dominant_hand: str
    session_count: int
    last_played_at: Optional[Any]
    review: Review
    risk: str
    concerns: List[ConcernBrief]


class GameSession(BaseModel):
    """One visit to the web lobby: per-game results keyed apple / fish / rat."""
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
    participant_id: UUID
    username: Optional[str]
    display_name: str
    dominant_hand: str
    review: Review
    insights: dict
    game_sessions: List[GameSession]


def _fetch_games(conn, participant_id: UUID) -> List[dict]:
    replay = hand_replays.meta_sql("s.session_id") if hand_replays.exists(conn) else "NULL::jsonb"
    rows = conn.execute(
        f"""SELECT s.session_id, s.started_at, s.completed_at, s.status, s.is_synthetic,
                  COALESCE(ss.metrics->'games', '{{}}'::jsonb) AS games,
                  ARRAY(SELECT jsonb_array_elements_text(COALESCE(ss.metrics->'games_finished', '[]'::jsonb)))
                    AS games_finished,
                  ss.metrics->'tcn' AS tcn, ss.metrics->'visit' AS visit, {replay} AS hand_replay
           FROM sessions s
           LEFT JOIN session_summaries ss ON ss.session_id = s.session_id
           WHERE s.participant_id = %s AND s.protocol_version LIKE 'lobby-%%'
           ORDER BY s.started_at DESC LIMIT 50""",
        (participant_id,),
    ).fetchall()
    for row in rows:
        row["has_hand_replay"] = row["hand_replay"] is not None
    return rows


def _sweep():
    try:
        live.save_unsaved_lobbies()
    except Exception:
        pass  # a failed sweep must never block the caregiver's view; it retries on the next visit


def resident_profile(conn, participant_id: UUID) -> Optional[dict]:
    p = conn.execute(
        "SELECT participant_id, username, alias, dominant_hand FROM participants WHERE participant_id = %s",
        (participant_id,),
    ).fetchone()
    if p is None:
        return None
    games = _fetch_games(conn, participant_id)
    insights = add_model_concerns(analyze(games), games)
    insights["game_visits"] = len(games)
    return {
        "participant_id": p["participant_id"], "username": p["username"],
        "display_name": p["alias"], "dominant_hand": p["dominant_hand"],
        "review": review_from(insights), "insights": insights,
        "game_sessions": games,
    }


def all_profiles(conn) -> List[dict]:
    ids = conn.execute(
        """SELECT p.participant_id FROM participants p
           WHERE p.username IS NOT NULL
           ORDER BY p.alias"""
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
        latest = p["game_sessions"][:1]
        out.append({
            "participant_id": p["participant_id"], "username": p["username"],
            "display_name": p["display_name"], "dominant_hand": p["dominant_hand"],
            "session_count": len(p["game_sessions"]),
            "last_played_at": latest[0]["started_at"] if latest else None,
            "review": p["review"], "risk": p["insights"]["risk"],
            "concerns": p["insights"]["concerns"],
        })
    out.sort(key=lambda r: (RISK_ORDER[r["risk"]], r["display_name"].lower()))
    return out


@router.get("/caregiver/residents/{participant_id}", response_model=ResidentDetail)
def resident_detail(participant_id: UUID, _: dict = Depends(current_caregiver)):
    _sweep()
    with pool.connection() as conn:
        profile = resident_profile(conn, participant_id)
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
