-- ============================================================
-- Orbit — Supabase Schema
-- Run this in: Supabase Dashboard → SQL Editor → New Query
-- ============================================================

-- Profiles table (single user — we keep at most one row)
CREATE TABLE IF NOT EXISTS profiles (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  skills           text[]      NOT NULL DEFAULT '{}',
  roles            text[]      NOT NULL DEFAULT '{}',
  locations        text[]      NOT NULL DEFAULT '{}',
  companies        text[]      NOT NULL DEFAULT '{}',
  experience_level text        NOT NULL DEFAULT '',
  updated_at       timestamptz NOT NULL DEFAULT now()
);

-- Matches table
CREATE TABLE IF NOT EXISTS matches (
  id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  title     text        NOT NULL,
  company   text,
  url       text        UNIQUE NOT NULL,
  score     integer     NOT NULL CHECK (score BETWEEN 1 AND 10),
  reason    text,
  query     text,
  dismissed boolean     NOT NULL DEFAULT false,
  found_at  timestamptz NOT NULL DEFAULT now()
);

-- Index for common query patterns
CREATE INDEX IF NOT EXISTS matches_score_idx      ON matches (score DESC);
CREATE INDEX IF NOT EXISTS matches_dismissed_idx  ON matches (dismissed);
CREATE INDEX IF NOT EXISTS matches_found_at_idx   ON matches (found_at DESC);
