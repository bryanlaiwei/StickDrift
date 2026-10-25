import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import assistant, auth, clinician_report, residents
from .db import ensure_schema, pool
from .live import routes as live_routes, stream as live_stream


@asynccontextmanager
async def lifespan(app: FastAPI):
    pool.open()
    ensure_schema()
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
app.include_router(residents.router)
app.include_router(assistant.router)
app.include_router(clinician_report.router)
app.include_router(live_routes.router)
app.include_router(live_stream.router)


@app.get("/health")
def health():
    with pool.connection() as conn:
        conn.execute("SELECT 1")
    return {"ok": True}
