-- Optional Cropaganda Soil & Rotation cache. Backend also creates this lazily.
-- Run in TigerData SQL editor if automatic CREATE TABLE is disabled.
CREATE TABLE IF NOT EXISTS cropaganda_soil_cache (
 account_key TEXT NOT NULL,
 latitude DOUBLE PRECISION NOT NULL,
 longitude DOUBLE PRECISION NOT NULL,
 data_kind TEXT NOT NULL,
 saved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 payload JSONB NOT NULL,
 PRIMARY KEY(account_key,latitude,longitude,data_kind)
);
CREATE INDEX IF NOT EXISTS cropaganda_soil_cache_recent_idx
  ON cropaganda_soil_cache(account_key,data_kind,saved_at DESC);
