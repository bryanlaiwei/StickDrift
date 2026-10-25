-- Stick Drift schema for Tiger Data (TimescaleDB / PostgreSQL).
-- The single source of truth: the API applies this file at startup (app/db.py ensure_schema),
-- and `psql "$DATABASE_URL" -f sql/schema.sql` does the same by hand. Safe to re-run. It never
-- drops anything, so tables and columns the app no longer uses stay in older databases.
-- Each table: CREATE for a new database, then ADD COLUMN IF NOT EXISTS for columns added since
-- (no-ops on a new database), then indexes.

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ---- accounts ------------------------------------------------------------------

-- Residents. Pseudonyms only: never store real names here.
CREATE TABLE IF NOT EXISTS participants (
    participant_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    alias           TEXT NOT NULL UNIQUE CHECK (length(alias) BETWEEN 1 AND 40),
    dominant_hand   TEXT NOT NULL CHECK (dominant_hand IN ('left', 'right', 'unknown')),
    username        TEXT,
    password_hash   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE participants
    ADD COLUMN IF NOT EXISTS username TEXT,
    ADD COLUMN IF NOT EXISTS password_hash TEXT;
-- Usernames are unique case-insensitively among residents that have one.
CREATE UNIQUE INDEX IF NOT EXISTS participants_username_key
    ON participants (lower(username)) WHERE username IS NOT NULL;

-- Caregivers review residents; they never play.
CREATE TABLE IF NOT EXISTS caregivers (
    caregiver_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username       TEXT NOT NULL,
    password_hash  TEXT NOT NULL,
    display_name   TEXT NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS caregivers_username_key ON caregivers (lower(username));

-- One row per login. Only a SHA-256 of the cookie token is stored. account_id points at
-- participants (role 'senior', i.e. a resident) or caregivers; there is no foreign key.
CREATE TABLE IF NOT EXISTS auth_sessions (
    token_hash   TEXT PRIMARY KEY,
    role         TEXT NOT NULL CHECK (role IN ('senior', 'caregiver')),
    account_id   UUID NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at   TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS auth_sessions_expires_idx ON auth_sessions (expires_at);

-- ---- visits ----------------------------------------------------------------------

-- One row per lobby visit (protocol_version lobby-v1, mode free_play).
CREATE TABLE IF NOT EXISTS sessions (
    session_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    participant_id    UUID NOT NULL REFERENCES participants (participant_id) ON DELETE CASCADE,
    mode              TEXT NOT NULL CHECK (mode IN ('assessment', 'free_play')),
    protocol_version  TEXT NOT NULL,
    controller_id     TEXT,
    connection        TEXT CHECK (connection IN ('usb', 'bluetooth', 'simulated', 'unknown')),
    placement         TEXT CHECK (placement IN ('hands', 'table', 'lap', 'other')),
    status            TEXT NOT NULL DEFAULT 'in_progress'
                      CHECK (status IN ('in_progress', 'completed', 'abandoned')),
    quality           TEXT CHECK (quality IN ('good', 'flagged', 'invalid')),
    is_synthetic      BOOLEAN NOT NULL DEFAULT false,  -- played with the keyboard, not the controller
    started_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at      TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS sessions_participant_started_idx
    ON sessions (participant_id, started_at DESC);

-- Per-visit results in metrics: per-game, per-hand measurements (games), the visit report
-- (visit) and the pattern-model scores (tcn).
CREATE TABLE IF NOT EXISTS session_summaries (
    session_id    UUID PRIMARY KEY REFERENCES sessions (session_id) ON DELETE CASCADE,
    metrics       JSONB NOT NULL DEFAULT '{}'::jsonb,
    code_version  TEXT NOT NULL,
    computed_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE session_summaries
    ADD COLUMN IF NOT EXISTS metrics JSONB NOT NULL DEFAULT '{}'::jsonb;

-- In-game stick samples of each visit (~60 Hz), tagged by game. A hypertable partitioned on `time`.
CREATE TABLE IF NOT EXISTS raw_samples (
    time        TIMESTAMPTZ NOT NULL,
    session_id  UUID NOT NULL REFERENCES sessions (session_id) ON DELETE CASCADE,
    seq         INTEGER NOT NULL,
    t_ms        DOUBLE PRECISION NOT NULL,  -- milliseconds since the visit started
    lx          REAL NOT NULL,
    ly          REAL NOT NULL,
    rx          REAL NOT NULL,
    ry          REAL NOT NULL,
    connected   BOOLEAN NOT NULL,
    activity    TEXT,
    game        TEXT,  -- apple, fish or rat
    trial_id    SMALLINT,
    target_lx   REAL, target_ly REAL, target_rx REAL, target_ry REAL,
    cursor_lx   REAL, cursor_ly REAL, cursor_rx REAL, cursor_ry REAL  -- the in-game hand
);
ALTER TABLE raw_samples
    ADD COLUMN IF NOT EXISTS activity TEXT,
    ADD COLUMN IF NOT EXISTS game TEXT,
    ADD COLUMN IF NOT EXISTS trial_id SMALLINT,
    ADD COLUMN IF NOT EXISTS target_lx REAL, ADD COLUMN IF NOT EXISTS target_ly REAL,
    ADD COLUMN IF NOT EXISTS target_rx REAL, ADD COLUMN IF NOT EXISTS target_ry REAL,
    ADD COLUMN IF NOT EXISTS cursor_lx REAL, ADD COLUMN IF NOT EXISTS cursor_ly REAL,
    ADD COLUMN IF NOT EXISTS cursor_rx REAL, ADD COLUMN IF NOT EXISTS cursor_ry REAL;
DO $$ BEGIN
    ALTER TABLE raw_samples ADD CONSTRAINT raw_samples_activity_check
        CHECK (activity IS NULL OR activity IN ('target_reach', 'target_tracking', 'bilateral_control'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
SELECT create_hypertable('raw_samples', by_range('time'), if_not_exists => TRUE);
-- TimescaleDB requires unique indexes on a hypertable to include its time key.
CREATE UNIQUE INDEX IF NOT EXISTS raw_samples_time_session_seq_uidx
    ON raw_samples (time, session_id, seq);
CREATE INDEX IF NOT EXISTS raw_samples_session_idx ON raw_samples (session_id, time);

-- One reconstructed-hands GIF per visit (ml/hand_replay/), drawn when the visit ends.
CREATE TABLE IF NOT EXISTS session_hand_replays (
    session_id        UUID PRIMARY KEY REFERENCES sessions (session_id) ON DELETE CASCADE,
    gif               BYTEA NOT NULL,
    game              TEXT,
    window_start_s    REAL,
    duration_s        REAL,
    frames            INT,
    has_motion        BOOLEAN,
    renderer_version  TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---- live sessions ---------------------------------------------------------------
-- A visit in progress, shared through Tiger Data so a caregiver on any computer can watch
-- and any API process can serve any request. Rows are short-lived and pruned after a day.

CREATE TABLE IF NOT EXISTS live_sessions (
    live_id         UUID PRIMARY KEY,
    participant_id  UUID NOT NULL REFERENCES participants (participant_id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    status          TEXT NOT NULL,
    token_hash      TEXT,  -- SHA-256 of the session's ingest token
    keyboard        BOOLEAN NOT NULL DEFAULT false,
    level           TEXT,
    levels          JSONB NOT NULL DEFAULT '[]',
    levels_done     JSONB NOT NULL DEFAULT '[]',
    trial           INTEGER,
    phase           TEXT,
    synthetic       BOOLEAN NOT NULL DEFAULT false,
    seq             BIGINT NOT NULL DEFAULT 0,
    running         JSONB,  -- the running measurements (measurements.SessionMetrics.to_state())
    metrics         JSONB,  -- their caregiver-facing summary
    result          JSONB,
    db_session_id   UUID,
    error           TEXT,
    host            TEXT,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at        TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE live_sessions
    ADD COLUMN IF NOT EXISTS token_hash TEXT,
    ADD COLUMN IF NOT EXISTS keyboard BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS running JSONB;
CREATE INDEX IF NOT EXISTS live_sessions_updated_idx ON live_sessions (updated_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS live_sessions_token_idx ON live_sessions (token_hash);

-- Every streamed sample, including lobby walking (level 'lobby'). Columns follow
-- measurements.SAMPLE_KEYS under older short names (tgt_*, reached_*, cur_*).
CREATE TABLE IF NOT EXISTS live_samples (
    live_id    UUID NOT NULL REFERENCES live_sessions (live_id) ON DELETE CASCADE,
    seq        BIGINT NOT NULL,
    level      TEXT NOT NULL,
    t          REAL NOT NULL,
    trial      INTEGER,
    phase      TEXT,
    lx REAL, ly REAL, rx REAL, ry REAL,
    tgt_lx REAL, tgt_ly REAL, tgt_rx REAL, tgt_ry REAL,
    reached_l SMALLINT, reached_r SMALLINT,
    cur_lx REAL, cur_ly REAL, cur_rx REAL, cur_ry REAL,
    -- DualSense motion when the lobby reads it over WebHID (blank, not zero, when it doesn't)
    gyro_x REAL, gyro_y REAL, gyro_z REAL, acc_x REAL, acc_y REAL, acc_z REAL,
    PRIMARY KEY (live_id, seq)
);
ALTER TABLE live_samples
    ADD COLUMN IF NOT EXISTS cur_lx REAL, ADD COLUMN IF NOT EXISTS cur_ly REAL,
    ADD COLUMN IF NOT EXISTS cur_rx REAL, ADD COLUMN IF NOT EXISTS cur_ry REAL,
    ADD COLUMN IF NOT EXISTS gyro_x REAL, ADD COLUMN IF NOT EXISTS gyro_y REAL, ADD COLUMN IF NOT EXISTS gyro_z REAL,
    ADD COLUMN IF NOT EXISTS acc_x REAL, ADD COLUMN IF NOT EXISTS acc_y REAL, ADD COLUMN IF NOT EXISTS acc_z REAL;

-- The in-game events a visit's report needs (apple picked, trace finished, rat slammed).
CREATE TABLE IF NOT EXISTS live_events (
    id       BIGSERIAL PRIMARY KEY,
    live_id  UUID NOT NULL REFERENCES live_sessions (live_id) ON DELETE CASCADE,
    level    TEXT NOT NULL,
    event    JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS live_events_live_idx ON live_events (live_id, id);
