-- Auth for Stick Drift: senior (player) accounts and caregiver accounts.
-- Additive and idempotent: it never drops or clears existing data.
-- Apply with: psql "$DATABASE_URL" -f auth_schema.sql

-- Seniors are the existing `participants` rows. Add login columns to them so
-- their profiles and session history are preserved.
ALTER TABLE participants
    ADD COLUMN IF NOT EXISTS username      TEXT,
    ADD COLUMN IF NOT EXISTS password_hash TEXT;

-- Usernames are unique case-insensitively, but only among rows that have one
-- (existing demo rows get one via the seed script).
CREATE UNIQUE INDEX IF NOT EXISTS participants_username_key
    ON participants (lower(username)) WHERE username IS NOT NULL;

-- Caregivers view residents; they never play, so they are a separate table.
CREATE TABLE IF NOT EXISTS caregivers (
    caregiver_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username       TEXT NOT NULL,
    password_hash  TEXT NOT NULL,
    display_name   TEXT NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS caregivers_username_key ON caregivers (lower(username));

-- One row per login. Only a SHA-256 of the cookie token is stored. account_id
-- points at participants or caregivers depending on role (no FK, resolved in code).
CREATE TABLE IF NOT EXISTS auth_sessions (
    token_hash   TEXT PRIMARY KEY,
    role         TEXT NOT NULL CHECK (role IN ('senior', 'caregiver')),
    account_id   UUID NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at   TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS auth_sessions_expires_idx ON auth_sessions (expires_at);
