-- Cropoganda: run once in TigerData SQL editor BEFORE setting TIGERDATA_DATABASE_URL.
-- Every accepted ESP32 upload updates the live row. Exactly one raw reading
-- per owner per UTC 10-minute bucket enters the archive (the first reading).
CREATE TABLE IF NOT EXISTS cropoganda_live (
  account_key TEXT PRIMARY KEY,
  device_id TEXT NOT NULL,
  observed_at TIMESTAMPTZ NOT NULL,
  readings JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS cropoganda_sensor_history (
  account_key TEXT NOT NULL,
  bucket_at TIMESTAMPTZ NOT NULL,
  observed_at TIMESTAMPTZ NOT NULL,
  device_id TEXT NOT NULL,
  readings JSONB NOT NULL,
  PRIMARY KEY (account_key,bucket_at)
);
CREATE INDEX IF NOT EXISTS cropoganda_history_time_idx
  ON cropoganda_sensor_history (account_key,bucket_at DESC);
CREATE TABLE IF NOT EXISTS cropoganda_nasa_daily (
  account_key TEXT NOT NULL,
  day DATE NOT NULL,
  latitude DOUBLE PRECISION NOT NULL,
  longitude DOUBLE PRECISION NOT NULL,
  observations JSONB NOT NULL,
  stored_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (account_key,day,latitude,longitude)
);
CREATE TABLE IF NOT EXISTS cropoganda_share_state (
  account_key TEXT PRIMARY KEY,
  version TEXT NOT NULL DEFAULT 'v1'
);
-- Optional on TigerData with TimescaleDB enabled, for larger histories:
-- SELECT create_hypertable('cropoganda_sensor_history','bucket_at',
--                          if_not_exists => TRUE);
-- Old private Vercel Blob data is retained as a fallback;
-- this migration does not import historical Blob snapshots.


-- Auth0 account-isolated editable farm documents (one JSONB section per account).
-- The app also creates this table automatically on its first authenticated use.
-- Existing ESP32 sensor tables and NASA POWER archive are unchanged.
CREATE TABLE IF NOT EXISTS cropoganda_farm_documents (
  account_key TEXT NOT NULL,
  section TEXT NOT NULL,
  value JSONB NOT NULL,
  revision BIGINT NOT NULL DEFAULT 1,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (account_key,section),
  CHECK(section IN ('plan','location','calendar','rotation_scenarios'))
);
-- Location is also registered in cropoganda_farm_locations for NASA Cron.
-- Do not bulk-import browser data into this SQL script: each user must
-- initiate a non-destructive browser import after Auth0 sign-in.
