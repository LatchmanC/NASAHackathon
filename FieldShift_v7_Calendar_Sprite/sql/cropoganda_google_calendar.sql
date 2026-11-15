-- Additional tables for Cropoganda calendar OAuth and NASA daily scheduled sync.
-- These CREATE TABLE statements are also run automatically when needed.
-- Safe to run repeatedly. They do not insert test readings.
CREATE TABLE IF NOT EXISTS cropoganda_google_calendar (
    account_key TEXT PRIMARY KEY,
    encrypted_refresh_token TEXT NOT NULL,
    connected_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS cropoganda_farm_locations (
    account_key TEXT PRIMARY KEY,
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    last_nasa_sync_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
