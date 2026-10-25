"""HTTP routes for live sessions: the resident's lobby tab streams in, caregivers read."""
import threading
from typing import Any, Dict, List, Optional, Union
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from ..auth import current_caregiver, current_resident
from ..db import pool
from .session import OPEN, LiveSession, apply_batch, create
from .visit import end_idle_visits, end_visit, prune, save_so_far
from .watch import recent, samples_since, state

router = APIRouter(tags=["live"])


# ---- the resident's lobby tab --------------------------------------------------

class LobbyStart(BaseModel):
    keyboard: bool = False


@router.post("/me/lobby/start", status_code=201)
def lobby_start(body: LobbyStart, me: dict = Depends(current_resident)):
    end_idle_visits()
    with pool.connection() as conn:
        old = [r["live_id"] for r in conn.execute(
            "SELECT live_id FROM live_sessions WHERE levels ? 'lobby' AND participant_id = %s AND status = ANY(%s)",
            (me["account_id"], OPEN),
        ).fetchall()]
    for live_id in old:
        end_visit(live_id)  # one open lobby per resident; a reload replaces the old tab
    s = LiveSession(me["account_id"], me["display_name"], body.keyboard)
    token = create(s)
    prune()
    return {"live_id": s.id, "token": token}


class LiveEnd(BaseModel):
    """The last samples ride with the close, so they are scored before the session is closed."""
    items: List[Union[List[Any], Dict[str, Any]]] = Field(default_factory=list, max_length=5000)


@router.post("/live/end", status_code=204)
def lobby_end(x_live_token: str = Header(...), body: Optional[LiveEnd] = None):
    end_visit(token=x_live_token, items=body.items if body is not None else [])


class IngestIn(BaseModel):
    items: List[Union[List[Any], Dict[str, Any]]] = Field(max_length=5000)


@router.post("/live/ingest")
def ingest(body: IngestIn, x_live_token: str = Header(...)):
    with pool.connection() as conn, conn.transaction():
        s = apply_batch(conn, x_live_token, body.items)
    if s is None:
        raise HTTPException(410, "This live session is no longer open.")
    if s.needs_save:
        threading.Thread(target=save_so_far, args=(s.id,), daemon=True).start()
    return {"ok": True}




# ---- caregivers -------------------------------------------------------------------

@router.get("/caregiver/live")
def live_list(_: dict = Depends(current_caregiver)):
    return recent()


@router.get("/caregiver/live/{live_id}")
def live_snapshot(live_id: UUID, since: int = 0, limit: int = 2000, _: dict = Depends(current_caregiver)):
    limit = max(1, min(limit, 4000))
    st = state(live_id)
    if st is None:
        raise HTTPException(404, "That live session was not found.")
    return {**st, "samples": samples_since(live_id, since, limit)}
