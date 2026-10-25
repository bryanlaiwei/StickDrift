import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import assistant, auth, live, live_stream, report, views
from .db import pool


@asynccontextmanager
async def lifespan(app: FastAPI):
    pool.open()
    live.ensure_schema()
    yield
    live_stream.hub.close()
    pool.close()


app = FastAPI(title="Stick Drift API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,  # the login cookie needs this on cross-origin calls
)
app.include_router(auth.router)
app.include_router(views.router)
app.include_router(assistant.router)
app.include_router(report.router)
app.include_router(live.router)
app.include_router(live_stream.router)


class GardenRecording(BaseModel):
    session_id: UUID
    source_group: Optional[str]
    sample_count: int
    level_count: int
    started_at: datetime
    status: str
    is_synthetic: bool


class GardenSecond(BaseModel):
    bucket: datetime
    activity: Optional[str]
    sample_count: int
    left_magnitude: Optional[float]
    right_magnitude: Optional[float]
    disconnected_count: int


@app.get("/health")
def health():
    with pool.connection() as conn:
        conn.execute("SELECT 1")
    return {"ok": True}


@app.get('/garden/recordings', response_model=List[GardenRecording])
def garden_recordings(limit: int = 100, _: dict = Depends(auth.current_caregiver)):
    with pool.connection() as conn:
        return conn.execute(
            """SELECT s.session_id, i.source_group, i.sample_count, s.started_at,
                      s.status, s.is_synthetic,
                      (SELECT count(*) FROM garden_level_results l
                       WHERE l.session_id = s.session_id)::int AS level_count
               FROM garden_imports i
               JOIN sessions s ON s.session_id = i.session_id
               ORDER BY s.started_at DESC LIMIT %s""",
            (max(1, min(limit, 500)),),
        ).fetchall()


@app.get('/sessions/{session_id}/garden-timeline', response_model=List[GardenSecond])
def garden_timeline(session_id: UUID, _: dict = Depends(auth.current_caregiver)):
    with pool.connection() as conn:
        exists = conn.execute(
            'SELECT 1 FROM garden_imports WHERE session_id = %s', (session_id,)
        ).fetchone()
        if exists is None:
            raise HTTPException(404, 'Garden recording not found.')
        return conn.execute(
            """SELECT bucket, activity, sample_count, left_magnitude,
                      right_magnitude, disconnected_count
               FROM garden_sample_seconds
               WHERE session_id = %s
               ORDER BY bucket, activity""",
            (session_id,),
        ).fetchall()
