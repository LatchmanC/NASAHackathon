#include <WiFi.h>
#include <WebServer.h>
#include <Wire.h>
#include <Adafruit_BMP085.h>

// Set up Wi-Fi Access Point credentials
const char* ssid = "ESP32_WeatherStation";
const char* password = "password123"; // Must be at least 8 characters

WebServer server(80);
Adafruit_BMP085 bmp;

const int rainPin = 34;

// HTML page hosted directly on the ESP32 (Fixed declaration)
const char* _html = R"rawliteral(
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>MochiWeather Station</title>
  <style>
    body {
      font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
      background: linear-gradient(135deg, #e0f7fa, #fce4ec);
      margin: 0;
      padding: 20px;
      display: flex;
      flex-direction: column;
      align-items: center;
      color: #333;
    }
    h1 { color: #ff6f61; margin-bottom: 5px; }
    .subtitle { color: #78909c; margin-bottom: 25px; font-size: 0.95rem; }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 20px;
      width: 100%;
      max-width: 800px;
    }
    .card {
      background: white;
      padding: 20px;
      border-radius: 20px;
      box-shadow: 0 8px 20px rgba(0,0,0,0.06);
      text-align: center;
      border: 2px solid #ffebee;
    }
    .card h3 { margin: 0 0 10px 0; color: #546e7a; font-size: 1.1rem; }
    .value { font-size: 2rem; font-weight: bold; color: #ff6f61; }
    .unit { font-size: 1rem; color: #90a4ae; }
    .status { margin-top: 10px; font-weight: bold; color: #26a69a; }
  </style>
</head>
<body>
  <h1>🌸 MochiWeather</h1>
  <div class="subtitle">Live from your ESP32 Weather Station</div>

  <div class="grid">
    <div class="card">
      <h3>Temperature</h3>
      <div class="value" id="temp">--</div>
      <div class="unit">&deg;C</div>
    </div>
    <div class="card">
      <h3>Pressure</h3>
      <div class="value" id="pressure">--</div>
      <div class="unit">hPa</div>
    </div>
    <div class="card">
      <h3>Altitude</h3>
      <div class="value" id="altitude">--</div>
      <div class="unit">meters</div>
    </div>
    <div class="card">
      <h3>Rain Status</h3>
      <div class="value" id="rainVal">--</div>
      <div class="status" id="rainStatus">Loading...</div>
    </div>
  </div>

  <script>
    function fetchData() {
      fetch('/data')
        .then(response => response.json())
        .then(data => {
          document.getElementById('temp').innerText = data.temp.toFixed(1);
          document.getElementById('pressure').innerText = data.pressure.toFixed(1);
          document.getElementById('altitude').innerText = data.altitude.toFixed(1);
          document.getElementById('rainVal').innerText = data.rain;
          document.getElementById('rainStatus').innerText = data.status;
        })
        .catch(err => console.error('Error fetching data:', err));
    }
    setInterval(fetchData, 2000); // Update every 2 seconds
    fetchData();
  </script>
</body>
</html>
)rawliteral";

void handleRoot() {
  server.send(200, "text/html", _html);
}

void handleData() {
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

  // Create JSON response
  String json = "{";
  json += "\"temp\":" + String(temp) + ",";
  json += "\"pressure\":" + String(pressure) + ",";
  json += "\"altitude\":" + String(altitude) + ",";
  json += "\"rain\":" + String(rainVal) + ",";
  json += "\"status\":\"" + rainStatus + "\"";
  json += "}";

  server.send(200, "application/json", json);
}

void setup() {
  Serial.begin(115200);

  // Initialize sensors
  if (!bmp.begin()) {
    Serial.println("Could not find a valid BMP180 sensor!");
    while (1) { delay(10); }
  }

  // Start ESP32 Wi-Fi Access Point
  Serial.println("Setting up Access Point...");
  WiFi.softAP(ssid, password);
  
  IPAddress myIP = WiFi.softAPIP();
  Serial.print("AP IP address: ");
  Serial.println(myIP);

  // Setup web server routes
  server.on("/", handleRoot);
  server.on("/data", handleData);
  server.begin();
  Serial.println("HTTP server started");
}

void loop() {
  server.handleClient();
}