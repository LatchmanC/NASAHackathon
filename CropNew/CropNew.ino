#include <WiFi.h>
#include <HTTPClient.h>
#include <Wire.h>
#include <Adafruit_BMP085.h>

// 1. Replace with your home or local Wi-Fi credentials (must have internet access)
const char* ssid = "qahwah time cafe";
const char* password = "qahwahtime66";

// 2. Replace with your deployed website's API endpoint URL
const char* serverName = "https://your-deployed-website.com/api/data";

Adafruit_BMP085 bmp;
const int rainPin = 34;

// Timer variables for non-blocking delay
unsigned long lastTime = 0;
unsigned long timerDelay = 5000; // Send data every 5 seconds

void setup() {
  Serial.begin(115200);

  // Initialize sensors
  if (!bmp.begin()) {
    Serial.println("Could not find a valid BMP180 sensor!");
    while (1) { delay(10); }
  }

  // Connect to the local Wi-Fi network
  WiFi.begin(ssid, password);
  Serial.print("Connecting to Wi-Fi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  
  Serial.println("\nConnected to Wi-Fi");
  Serial.print("IP Address: ");
  Serial.println(WiFi.localIP());
}

void loop() {
  // Check if it's time to send data and if Wi-Fi is connected
  if ((millis() - lastTime) > timerDelay) {
    if (WiFi.status() == WL_CONNECTED) {
      HTTPClient http;
      
      // Start connection to the deployed website
      http.begin(serverName);
      http.addHeader("Content-Type", "application/json");

      // Read sensor data
      float temp = bmp.readTemperature();
      float pressure = bmp.readPressure() / 100.0;
      float altitude = bmp.readAltitude();
      int rainVal = analogRead(rainPin);

      String rainStatus = "Dry";
      if (rainVal <= 1500) {
        rainStatus = "Heavy Rain / Wet";
      } else if (rainVal <= 3000) {
        rainStatus = "Light Rain / Damp";
      }

      // Format data as JSON
      String json = "{";
      json += "\"temp\":" + String(temp) + ",";
      json += "\"pressure\":" + String(pressure) + ",";
      json += "\"altitude\":" + String(altitude) + ",";
      json += "\"rain\":" + String(rainVal) + ",";
      json += "\"status\":\"" + rainStatus + "\"";
      json += "}";

      // Send the HTTP POST request
      int httpResponseCode = http.POST(json);

      // Print response for debugging
      Serial.print("HTTP Response code: ");
      Serial.println(httpResponseCode);

      http.end(); // Free resources
    } else {
      Serial.println("WiFi Disconnected. Reconnecting...");
      WiFi.reconnect();
    }
    
    // Reset the timer
    lastTime = millis();
  }
}