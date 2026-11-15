# Cropaganda ESP32 uploader — 30-second live updates

This sketch is a **new, separate example** for the authenticated Cropaganda
sensor ingestion API. It does not replace firmware already flashed on a real
ESP32. It is based on the BMP180/BMP085 and analog rain probe used in the
repository's older demonstration sketches. Adapt the sensor reading function
if your actual board has different sensors.

## What changes

- Sensor measurements are sent to `https://cropaganda.garden/api/device/ingest`
  **once every 30 seconds** while Wi-Fi and HTTPS are working.
- No change to the Cropaganda website, Vercel environment, authentication,
  database schema or SQL cadence is required. The deployed FastAPI endpoint
  currently permits uploads at least 2 seconds apart when TigerData is enabled.
- **TigerData live reading** updates on each accepted upload (approximately
  every 30 seconds); **historical archive** still stores only the first accepted
  reading in each 10-minute UTC bucket.
- The dashboard already polls the live API about every 2 seconds while visible,
  so it generally displays the latest sensor reading shortly after an upload.

**Database writes do increase:** TigerData updates the live row on every
accepted POST. This example does *not* implement an alternate in-memory live
cache; that would require separate backend infrastructure and was not needed
to enable the requested 30-second send rate.

## Set up and flash

1. In Arduino IDE, install **ESP32 by Espressif Systems** and the
   **Adafruit BMP085 Library**. Select the correct ESP32 board and port.
2. Open `CropagandaESP32.ino`. Copy `device_config.example.h` to
   `device_config.h` in the *same sketch directory*.
3. Fill in your Wi-Fi SSID and password in the local config file.
4. Sign in to your **real Auth0** account at
   [Cropaganda](https://cropaganda.garden) and open the ESP32 pairing panel.
   Generate a pairing token for your chosen device ID (for example
   `esp32-01`). Put its exact ID in `CROPOGANDA_DEVICE_ID` and the private
   token in `CROPOGANDA_DEVICE_TOKEN`. Tokens expire after 180 days.
5. Obtain the **public root-CA certificate PEM** that validates the HTTPS
   certificate chain currently used by `cropaganda.garden`. Put the PEM in
   `CROPOGANDA_ROOT_CA_PEM` in your local configuration.
   Never copy the *private* key or trust an arbitrary intercepted certificate.
   Root CA/certificate chains may rotate; update the CA when required.
   See the [Arduino-ESP32 TLS documentation](https://github.com/espressif/arduino-esp32/blob/master/libraries/NetworkClientSecure/README.md).
   This sketch deliberately does not call `setInsecure()` because the request
   carries a private bearer token.
6. Flash the sketch to your physical ESP32 and open Serial Monitor at
   **115200 baud**. Wait for Wi-Fi and NTP clock synchronization.
7. Confirm `HTTP 200` / `Cropaganda sensor upload accepted` messages.
   Open Cropaganda's live sensor dashboard to check the timestamp and values.

Never commit, screenshot, or paste your Wi-Fi credentials or device token.
The local `device_config.h` is Git-ignored.

## Troubleshooting

| Result | Meaning | Action |
|---|---|---|
| HTTP 2xx | Reading accepted | Verify latest timestamp in the real Auth0 dashboard |
| HTTP 401 | Bad/expired pairing token | Pair the ESP32 again in your own account |
| HTTP 403 | Device ID does not match the token | Match `CROPOGANDA_DEVICE_ID` to the ID used at pairing |
| HTTP 422 | Measurement field/value rejected | Use supported fields and valid ranges |
| HTTP 429 | Uploaded faster than allowed | Sketch honors `Retry-After` and delays the next upload |
| HTTP 503 | Sensor/cloud database unavailable | Check production TigerData and retry later |
| Negative HTTP result | Wi-Fi/TLS/transport failure | Check Wi-Fi, clock sync, trusted root CA and HTTPS access |

Do not manually set `FIELDSHIFT_MIN_SENSOR_SECONDS` to 30: that setting is
only used with the legacy Vercel Blob fallback and is clamped to **60 seconds
minimum**. For TigerData the live backend already supports the faster rate
via `CROPOGANDA_MIN_SENSOR_SECONDS` (defaults to 2 seconds).

### Supported JSON fields

The server recognizes `device_id`, `temperature_c`, `humidity_pct`,
`pressure_hpa`, `altitude_m`, `rain_wetness_pct`, `light_pct`,
`soil_moisture_pct`, `gas_index`, and `ph`. Each POST needs one or more
actual measurements. The example supplies BMP sensor values plus an **uncalibrated**
wetness index derived from GPIO 34; it is not a true rainfall percentage.
Calibrate or replace that conversion for your own rain sensor.

The old `CropNew/CropNew.ino` is a legacy example: it posts to a placeholder
URL using a different JSON schema. It is **not** the authenticated uploader
for the current site. This new sketch must be adapted and physically flashed
before the running ESP32 will change its send interval.
