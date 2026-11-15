// Cropaganda ESP32 authenticated HTTPS telemetry (30-second cadence).
// This is a SEPARATE ready-to-adapt uploader, NOT the old CropNew demo sketch.
// To use: copy device_config.example.h -> device_config.h and fill it locally.
// device_config.h contains secrets, is ignored by Git, and must never be posted.
#include <Arduino.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <Wire.h>
#include <Adafruit_BMP085.h>
#include <time.h>
#include "device_config.h"

static constexpr uint32_t UPLOAD_INTERVAL_MS = 30000UL;
static constexpr uint32_t RECONNECT_INTERVAL_MS = 10000UL;
static constexpr uint32_t MAX_RETRY_AFTER_MS = 3600000UL;
static constexpr int RAIN_PIN = 34;
static constexpr char INGEST_URL[] = "https://cropaganda.garden/api/device/ingest";

Adafruit_BMP085 bmp;
bool bmpReady = false;
uint32_t nextUploadAt = 0;
uint32_t nextReconnectAt = 0;

// Unsigned millisecond subtraction handles wraparound (intervals < 2^31 ms).
bool due(uint32_t now, uint32_t deadline) {
  return static_cast<int32_t>(now - deadline) >= 0;
}

bool configReady() {
  // Abort rather than ever transmit a signed device token over unverified TLS.
  return strlen(CROPOGANDA_WIFI_SSID) > 0 &&
         strlen(CROPOGANDA_WIFI_PASSWORD) > 0 &&
         strlen(CROPOGANDA_DEVICE_TOKEN) >= 30 &&
         strlen(CROPOGANDA_DEVICE_ID) > 0 &&
         strstr(CROPOGANDA_ROOT_CA_PEM, "BEGIN CERTIFICATE") != nullptr;
}

void tryWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;
  const uint32_t now = millis();
  if (!due(now, nextReconnectAt)) return;
  nextReconnectAt = now + RECONNECT_INTERVAL_MS;
  Serial.println("Connecting to Wi-Fi...");
  WiFi.disconnect(false);
  WiFi.begin(CROPOGANDA_WIFI_SSID, CROPOGANDA_WIFI_PASSWORD);
}

bool tlsClockReady() {
  // Root-CA verification requires a valid device clock.
  struct tm currentTime;
  return getLocalTime(&currentTime, 100) &&
         (currentTime.tm_year + 1900 >= 2025);
}

String sensorJson() {
  // Cropaganda accepts only specific normalized names, not temp/rain/status.
  String body;
  body.reserve(240);
  body = "{\"device_id\":\"";
  body += CROPOGANDA_DEVICE_ID;
  body += "\"";
  if (bmpReady) {
    body += ",\"temperature_c\":" + String(bmp.readTemperature(), 2);
    body += ",\"pressure_hpa\":" + String(bmp.readPressure() / 100.0f, 2);
    body += ",\"altitude_m\":" + String(bmp.readAltitude(), 2);
  }
  // Optional raindrop sensor index, not a calibrated rainfall measurement.
  // This assumes a lower ADC reading means a wetter surface, as in CropNew.
  const int rainAdc = analogRead(RAIN_PIN);
  const float wetnessIndex = 100.0f * (4095.0f - rainAdc) / 4095.0f;
  body += ",\"rain_wetness_pct\":" + String(wetnessIndex, 1);
  body += "}";
  return body;
}

void sendReading() {
  if (WiFi.status() != WL_CONNECTED) return;
  if (!tlsClockReady()) {
    Serial.println("Clock not synchronized yet; waiting for verified TLS.");
    return;
  }
  WiFiClientSecure tls;
  tls.setCACert(CROPOGANDA_ROOT_CA_PEM);  // NEVER setInsecure() for a bearer token.

  HTTPClient request;
  if (!request.begin(tls, INGEST_URL)) {
    Serial.println("Unable to initialize HTTPS connection.");
    return;
  }
  request.setTimeout(16000);
  request.addHeader("Content-Type", "application/json");
  request.addHeader("Authorization", String("Bearer ") + CROPOGANDA_DEVICE_TOKEN);
  const char *headers[] = {"Retry-After"};
  request.collectHeaders(headers, 1);

  const int status = request.POST(sensorJson());
  if (status >= 200 && status < 300) {
    Serial.printf("Cropaganda sensor upload accepted: HTTP %d\n", status);
  } else if (status == 429) {
    // Follow the server's upload-rate limit; do not hammer the endpoint.
    const long seconds = request.header("Retry-After").toInt();
    if (seconds > 0) {
      const uint32_t retryMs =
          min(static_cast<uint32_t>(seconds) * 1000UL + 1000UL, MAX_RETRY_AFTER_MS);
      nextUploadAt = millis() + retryMs;
      Serial.printf("Rate limited: retry in %lu seconds.\n",
                    static_cast<unsigned long>(retryMs / 1000UL));
    } else {
      Serial.println("Rate limited: will retry at next upload interval.");
    }
  } else if (status == 401 || status == 403) {
    Serial.println("Device upload rejected: check pairing token and device_id.");
  } else {
    Serial.printf("Upload failed, HTTP status %d (retry at next interval).\n", status);
  }
  // Do not print HTTP response bodies or authentication tokens.
  request.end();
}

void setup() {
  Serial.begin(115200);
  delay(200);

  if (!configReady()) {
    Serial.println("Missing device_config.h values or trusted root CA. Upload disabled.");
    while (true) delay(3000); // Fail closed rather than leak the bearer token.
  }
  Wire.begin();
  bmpReady = bmp.begin();
  if (!bmpReady) Serial.println("BMP180/BMP085 unavailable; sending only rain index.");
  analogReadResolution(12);
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  // Start attempts immediately. NTP is configured after a Wi-Fi connection.
  nextReconnectAt = millis();
  nextUploadAt = millis();
}

void loop() {
  tryWiFi();
  if (WiFi.status() == WL_CONNECTED) {
    static bool ntpStarted = false;
    if (!ntpStarted) {
      configTime(0, 0, "pool.ntp.org", "time.google.com");
      ntpStarted = true;
    }
    if (due(millis(), nextUploadAt)) {
      sendReading();
      // The 30s interval counts from completion, keeping accepted uploads
      // at least 30 seconds apart. Preserve longer Retry-After deadlines.
      const uint32_t normalDue = millis() + UPLOAD_INTERVAL_MS;
      if (due(normalDue, nextUploadAt)) nextUploadAt = normalDue;
    }
  }
  delay(50);
}
