"""The Tiger Data connection pool and the schema the API keeps applied."""
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

log = logging.getLogger(__name__)

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

DATABASE_URL = os.environ.get("DATABASE_URL") or os.environ.get("TIMESCALE_SERVICE_URL")
if not DATABASE_URL:
    raise RuntimeError("Set DATABASE_URL or TIMESCALE_SERVICE_URL in backend/.env.")

SCHEMA = Path(__file__).resolve().parents[1] / "sql" / "schema.sql"
SCHEMA_LOCK = 4_242_001  # pg advisory lock key, so API processes starting together apply the schema one at a time

pool = ConnectionPool(
    DATABASE_URL,
    min_size=1,
    max_size=5,
    kwargs={"row_factory": dict_row},
    open=False,
)


def ensure_schema():
    """Apply sql/schema.sql (idempotent). A database that refuses is logged, not fatal."""
    try:
        with pool.connection() as conn, conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(%s)", (SCHEMA_LOCK,))
            conn.execute(SCHEMA.read_text(encoding="utf-8"))
    except Exception:
        log.exception("Could not apply %s; apply it by hand with psql", SCHEMA)
