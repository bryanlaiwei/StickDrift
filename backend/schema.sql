-- Stick Drift schema for Tiger Data (TimescaleDB / PostgreSQL).
-- Apply with: psql "$DATABASE_URL" -f schema.sql
-- Safe to re-run.

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Resident profiles. Pseudonyms only: never store real names here.
CREATE TABLE IF NOT EXISTS participants (
    participant_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    alias           TEXT NOT NULL UNIQUE CHECK (length(alias) BETWEEN 1 AND 40),
    dominant_hand   TEXT NOT NULL CHECK (dominant_hand IN ('left', 'right', 'unknown')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One row per play session. Only completed assessment sessions with good
-- quality feed the personal baseline; free play never does.
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
    is_synthetic      BOOLEAN NOT NULL DEFAULT false,
    started_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at      TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS sessions_participant_started_idx
    ON sessions (participant_id, started_at DESC);

-- Per-session results, computed from responses. Counts keep their
-- denominators so accuracy is never shown without context.
CREATE TABLE IF NOT EXISTS session_summaries (
    session_id               UUID PRIMARY KEY REFERENCES sessions (session_id) ON DELETE CASCADE,
    left_median_latency_ms   REAL,
    right_median_latency_ms  REAL,
    left_correct             SMALLINT,
    left_valid               SMALLINT,
    right_correct            SMALLINT,
    right_valid              SMALLINT,
    both_correct             SMALLINT,
    both_valid               SMALLINT,
    lr_gap_ms                REAL,
    bimanual_gap_ms          REAL,
    enjoyment                SMALLINT CHECK (enjoyment BETWEEN 1 AND 5),
    metrics                  JSONB NOT NULL DEFAULT '{}'::jsonb,
    code_version             TEXT NOT NULL,
    computed_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE session_summaries
    ADD COLUMN IF NOT EXISTS metrics JSONB NOT NULL DEFAULT '{}'::jsonb;

-- Prompt schedule as shown to the resident.
CREATE TABLE IF NOT EXISTS trials (
    session_id    UUID NOT NULL REFERENCES sessions (session_id) ON DELETE CASCADE,
    trial_id      SMALLINT NOT NULL,
    block         TEXT NOT NULL CHECK (block IN ('practice', 'left', 'right', 'both')),
    hand          TEXT NOT NULL CHECK (hand IN ('left', 'right', 'both')),
    direction_l   TEXT CHECK (direction_l IN ('up', 'down', 'left', 'right')),
    direction_r   TEXT CHECK (direction_r IN ('up', 'down', 'left', 'right')),
    cue_onset_ms  DOUBLE PRECISION NOT NULL,
    deadline_ms   DOUBLE PRECISION NOT NULL,
    activity      TEXT NOT NULL DEFAULT 'target_reach',
    details       JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (session_id, trial_id)
);

ALTER TABLE trials
    ADD COLUMN IF NOT EXISTS activity TEXT NOT NULL DEFAULT 'target_reach',
    ADD COLUMN IF NOT EXISTS details JSONB NOT NULL DEFAULT '{}'::jsonb;

DO $$ BEGIN
    ALTER TABLE trials ADD CONSTRAINT trials_activity_check
        CHECK (activity IN ('target_reach', 'target_tracking', 'bilateral_control'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- Detected response for each trial.
CREATE TABLE IF NOT EXISTS responses (
    session_id    UUID NOT NULL,
    trial_id      SMALLINT NOT NULL,
    outcome       TEXT NOT NULL
                  CHECK (outcome IN ('correct', 'wrong_direction', 'omission', 'false_start', 'invalid')),
    detected_l    TEXT,
    detected_r    TEXT,
    cross_l_ms    DOUBLE PRECISION,
    cross_r_ms    DOUBLE PRECISION,
    latency_ms    DOUBLE PRECISION,
    metrics       JSONB NOT NULL DEFAULT '{}'::jsonb,
    code_version  TEXT NOT NULL,
    PRIMARY KEY (session_id, trial_id),
    FOREIGN KEY (session_id, trial_id) REFERENCES trials (session_id, trial_id) ON DELETE CASCADE
);

ALTER TABLE responses
    ADD COLUMN IF NOT EXISTS metrics JSONB NOT NULL DEFAULT '{}'::jsonb;

-- Raw stick samples (~60 Hz from the Gamepad API). This is the time-series
-- table, so it is a hypertable partitioned on `time`.
CREATE TABLE IF NOT EXISTS raw_samples (
    time        TIMESTAMPTZ NOT NULL,
    session_id  UUID NOT NULL REFERENCES sessions (session_id) ON DELETE CASCADE,
    seq         INTEGER NOT NULL,
    t_ms        DOUBLE PRECISION NOT NULL,  -- performance.now() in the browser
    lx          REAL NOT NULL,
    ly          REAL NOT NULL,
    rx          REAL NOT NULL,
    ry          REAL NOT NULL,
    connected   BOOLEAN NOT NULL,
    activity    TEXT,
    trial_id    SMALLINT,
    target_x    REAL,
    target_y    REAL,
    cursor_x    REAL,
    cursor_y    REAL
);

ALTER TABLE raw_samples
    ADD COLUMN IF NOT EXISTS activity TEXT,
    ADD COLUMN IF NOT EXISTS trial_id SMALLINT,
    ADD COLUMN IF NOT EXISTS target_x REAL,
    ADD COLUMN IF NOT EXISTS target_y REAL,
    ADD COLUMN IF NOT EXISTS cursor_x REAL,
    ADD COLUMN IF NOT EXISTS cursor_y REAL,
    ADD COLUMN IF NOT EXISTS target_lx REAL,
    ADD COLUMN IF NOT EXISTS target_ly REAL,
    ADD COLUMN IF NOT EXISTS target_rx REAL,
    ADD COLUMN IF NOT EXISTS target_ry REAL,
    ADD COLUMN IF NOT EXISTS cursor_lx REAL,
    ADD COLUMN IF NOT EXISTS cursor_ly REAL,
    ADD COLUMN IF NOT EXISTS cursor_rx REAL,
    ADD COLUMN IF NOT EXISTS cursor_ry REAL,
    ADD COLUMN IF NOT EXISTS game TEXT;  -- web lobby game (apple, fish, rat); NULL for the garden

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

-- Imported garden recordings keep their source result structure. This avoids
-- inventing assessment outcomes for tracking and watering levels.
CREATE TABLE IF NOT EXISTS garden_level_results (
    session_id UUID NOT NULL REFERENCES sessions (session_id) ON DELETE CASCADE,
    level_number SMALLINT NOT NULL,
    level_name TEXT NOT NULL,
    completed BOOLEAN NOT NULL,
    sample_count INTEGER NOT NULL,
    duration_s DOUBLE PRECISION NOT NULL,
    params JSONB NOT NULL,
    results JSONB NOT NULL,
    PRIMARY KEY (session_id, level_number)
);

CREATE TABLE IF NOT EXISTS garden_imports (
    source_hash TEXT PRIMARY KEY,
    session_id UUID NOT NULL UNIQUE REFERENCES sessions (session_id) ON DELETE CASCADE,
    source_group TEXT,
    sample_count INTEGER NOT NULL,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS garden_imports_group_idx ON garden_imports (source_group);

-- One-second buckets make the ~500 Hz recordings quick to plot. Current
-- unmaterialized rows are included by the real-time aggregate setting.
CREATE MATERIALIZED VIEW IF NOT EXISTS garden_sample_seconds
WITH (timescaledb.continuous) AS
SELECT time_bucket('1 second', time) AS bucket,
       session_id,
       activity,
       count(*) AS sample_count,
       avg(sqrt(lx * lx + ly * ly)) AS left_magnitude,
       avg(sqrt(rx * rx + ry * ry)) AS right_magnitude,
       sum(CASE WHEN connected THEN 0 ELSE 1 END) AS disconnected_count
FROM raw_samples
GROUP BY bucket, session_id, activity
WITH NO DATA;
ALTER MATERIALIZED VIEW garden_sample_seconds
    SET (timescaledb.materialized_only = false);
SELECT add_continuous_aggregate_policy('garden_sample_seconds',
    start_offset => INTERVAL '7 days',
    end_offset => INTERVAL '10 seconds',
    schedule_interval => INTERVAL '1 minute',
    if_not_exists => TRUE);

-- Low-volume event stream for phase changes, pauses, calibration, and other
-- auditable game events. High-rate axes remain in raw_samples.
CREATE TABLE IF NOT EXISTS session_events (
    event_id    UUID PRIMARY KEY,
    session_id  UUID NOT NULL REFERENCES sessions (session_id) ON DELETE CASCADE,
    t_ms        DOUBLE PRECISION NOT NULL,
    event_type  TEXT NOT NULL CHECK (length(event_type) BETWEEN 1 AND 80),
    payload     JSONB NOT NULL DEFAULT '{}'::jsonb,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS session_events_session_idx
    ON session_events (session_id, t_ms);

-- Live sessions (web lobby and garden game), shared through TigerData so a caregiver
-- on any computer can watch a resident playing on another. Any API process reads and
-- writes them. Rows are short-lived and pruned after a day.
CREATE TABLE IF NOT EXISTS live_sessions (
    live_id UUID PRIMARY KEY,
    participant_id UUID NOT NULL REFERENCES participants (participant_id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    level TEXT,
    levels JSONB NOT NULL DEFAULT '[]',
    levels_done JSONB NOT NULL DEFAULT '[]',
    trial INTEGER,
    phase TEXT,
    synthetic BOOLEAN NOT NULL DEFAULT false,
    seq BIGINT NOT NULL DEFAULT 0,
    metrics JSONB,
    result JSONB,
    db_session_id UUID,
    error TEXT,
    host TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS live_sessions_updated_idx ON live_sessions (updated_at DESC);

CREATE TABLE IF NOT EXISTS live_samples (
    live_id UUID NOT NULL REFERENCES live_sessions (live_id) ON DELETE CASCADE,
    seq BIGINT NOT NULL,
    level TEXT NOT NULL,
    t REAL NOT NULL,
    trial INTEGER,
    phase TEXT,
    lx REAL, ly REAL, rx REAL, ry REAL,
    tgt_lx REAL, tgt_ly REAL, tgt_rx REAL, tgt_ry REAL,
    reached_l SMALLINT, reached_r SMALLINT,
    PRIMARY KEY (live_id, seq)
);
-- Web lobby games move an in-game hand with the stick, so they also send where that hand is.
ALTER TABLE live_samples ADD COLUMN IF NOT EXISTS cur_lx REAL;
ALTER TABLE live_samples ADD COLUMN IF NOT EXISTS cur_ly REAL;
ALTER TABLE live_samples ADD COLUMN IF NOT EXISTS cur_rx REAL;
ALTER TABLE live_samples ADD COLUMN IF NOT EXISTS cur_ry REAL;

-- Sessions live here, not in one API process's memory, so any API process can serve any
-- request and a restart loses nothing. The API also applies this block at startup (live.SCHEMA_SQL).
-- kind: 'lobby' or 'garden'. token_hash: SHA-256 of the session's ingest token.
-- running: the running measurements (live_metrics.SessionMetrics.to_state()).
ALTER TABLE live_sessions ADD COLUMN IF NOT EXISTS kind TEXT NOT NULL DEFAULT 'garden';
ALTER TABLE live_sessions ADD COLUMN IF NOT EXISTS token_hash TEXT;
ALTER TABLE live_sessions ADD COLUMN IF NOT EXISTS keyboard BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE live_sessions ADD COLUMN IF NOT EXISTS folder TEXT;
ALTER TABLE live_sessions ADD COLUMN IF NOT EXISTS running JSONB;
CREATE UNIQUE INDEX IF NOT EXISTS live_sessions_token_idx ON live_sessions (token_hash);
-- DualSense motion, when the lobby reads it over WebHID (blank, not zero, when it doesn't).
ALTER TABLE live_samples ADD COLUMN IF NOT EXISTS gyro_x REAL;
ALTER TABLE live_samples ADD COLUMN IF NOT EXISTS gyro_y REAL;
ALTER TABLE live_samples ADD COLUMN IF NOT EXISTS gyro_z REAL;
ALTER TABLE live_samples ADD COLUMN IF NOT EXISTS acc_x REAL;
ALTER TABLE live_samples ADD COLUMN IF NOT EXISTS acc_y REAL;
ALTER TABLE live_samples ADD COLUMN IF NOT EXISTS acc_z REAL;
-- The in-game events a lobby visit's report needs (apple picked, trace finished, rat slammed).
CREATE TABLE IF NOT EXISTS live_events (
    id BIGSERIAL PRIMARY KEY,
    live_id UUID NOT NULL REFERENCES live_sessions (live_id) ON DELETE CASCADE,
    level TEXT NOT NULL,
    event JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS live_events_live_idx ON live_events (live_id, id);

-- One reconstructed-hands GIF per lobby visit (hand_replay/), drawn when the visit ends.
-- The API also creates this table before its first insert (app/hand_replays.py).
CREATE TABLE IF NOT EXISTS session_hand_replays (
    session_id uuid PRIMARY KEY REFERENCES sessions (session_id) ON DELETE CASCADE,
    gif bytea NOT NULL,
    game text,
    window_start_s real,
    duration_s real,
    frames int,
    has_motion boolean,
    renderer_version text,
    created_at timestamptz NOT NULL DEFAULT now()
);
