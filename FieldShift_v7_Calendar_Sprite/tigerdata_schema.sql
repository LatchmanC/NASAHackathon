-- Execute using the TigerData SQL editor after creating a TigerData PostgreSQL service.
-- Same payload contract as cloud_mock.py; raw ESP32 readings are retained.
CREATE TABLE IF NOT EXISTS sensor_readings (
  recorded_at TIMESTAMPTZ NOT NULL,
  reading_id TEXT NOT NULL,
  device_id TEXT NOT NULL,
  source TEXT NOT NULL,
  temperature_c DOUBLE PRECISION,
  humidity_pct DOUBLE PRECISION,
  pressure_hpa DOUBLE PRECISION,
  altitude_m DOUBLE PRECISION,
  rain_wetness_pct DOUBLE PRECISION,
  light_pct DOUBLE PRECISION,
  gas_index DOUBLE PRECISION,
  soil_moisture_pct DOUBLE PRECISION,
  PRIMARY KEY (recorded_at, reading_id)
);

-- Run this statement once when the table is still empty.
SELECT create_hypertable('sensor_readings', by_range('recorded_at'), if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_sensor_device_time ON sensor_readings (device_id, recorded_at DESC);

CREATE TABLE IF NOT EXISTS station_context (
  station_id TEXT PRIMARY KEY,
  context_json JSONB NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
