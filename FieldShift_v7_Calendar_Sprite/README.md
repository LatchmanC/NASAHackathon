# FieldShift v7 — Crop calendar + Fieldy advisor

This is an updated **ESP32-only simulation** of the FieldShift browser dashboard.
The Raspberry Pi is **not** used. The Python demo emulates the ESP32 sensor
stream and a local SQL cloud receiver. The eventual physical ESP32 SoftAP and
TigerData deployment still require real ESP32 firmware and cloud configuration.

## Changes in v7

- Dashboard tab order: **1. Crop Management**, **2. Live Sensor Data**, **3. NASA POWER Daily**.
- Crop Management opens by default.
- New interactive **Farm calendar**: previous/next month, today, daily events,
  planting markers sourced from crop dates, add and delete watering, planting,
  harvest, fertilizing, inspection, and other tasks.
- Manual calendar tasks are written to a local JSON file under the app's data
  directory (by default `~/.fieldshift_simple_v5/calendar_events.json`). They
  survive application restarts. **Cloud calendar sync is not yet implemented.**
- The former AI chat panel is replaced by **Fieldy**, a tiny original SVG
  seedling mascot with a scrollable speech bubble. You can submit a farming
  question and read Gemini's response beside Fieldy.
- The Gemini model is `gemini-3.5-flash-lite`. The key is read **only on the
  Python backend**, not sent to or stored by the browser.
- Gemini receives crop allocations, recent local sensor readings, available
  NASA POWER history, weather source context, and up to 30 upcoming calendar
  tasks. Advice remains conditional, not an authoritative forecast.

## Quick start

Use Python 3.10+.

```bash
python -m pip install -r requirements.txt
python run_demo.py
```

Open http://127.0.0.1:8501 if your browser did not open automatically.
Run `python run_demo.py --no-browser` for testing without a browser launch.

**Existing v6 data:** This version continues to use the same local app data
folder, so saved farm plans and simulated sensor history remain compatible.

## Configure Gemini securely — once

**Do not use the API key previously posted in chat. Revoke it and generate a
new key from Google AI Studio.** We intentionally did NOT embed the posted key
in this source package or in the page, where anyone could retrieve it.

The simplest option is:

```bash
python configure_gemini.py
```

The command privately prompts for a **new** key (hidden input), saves it to a
local `.env` file in the project folder, and instructs you to restart the demo.
`.env` is ignored by Git and **excluded from the downloadable ZIP**. Python's
`python-dotenv` loads the file on the backend. On a shared machine, manage file
permissions appropriately. If the key is already stored in `GEMINI_API_KEY` in
your environment, that environment variable takes priority.

Alternatively:

Windows PowerShell:

```powershell
$env:GEMINI_API_KEY="YOUR_NEW_PRIVATE_KEY"
python run_demo.py
```

macOS/Linux:

```bash
export GEMINI_API_KEY="YOUR_NEW_PRIVATE_KEY"
python3 run_demo.py
```

In **Crop Management → Meet Fieldy**, press **Ask Fieldy for advice**. The
status text tells you whether the backend sees a configured key. **No API key
is needed to test the calendar, sensors, NASA demo graphs, or navigation.**

If Gemini returns model not found, confirm that the requested model is
available for your Google AI account. A working standalone SDK test confirms
only that the specific model used by that test is accessible.

## Calendar usage

1. On **Crop Management**, set the farm location, total area, crop list, and
   optional planting dates. Planting dates appear as green dots in the month
   calendar. Save the farm plan to make those dates survive restarts.
2. Click a day in the calendar. Fill in task type, crop (optional), and note.
3. Click **Save task**. Tasks are persisted on the local Python server.
4. Click the × next to a manually created task to delete it.

Manual tasks appear in Gemini's prompt context as planned tasks, not observed
plant growth or confirmed completed farm work.

## Existing functionality kept

- Synthetic ESP32 temperature, humidity, pressure, estimated altitude, light,
  rain-plate wetness, gas index, and soil moisture readings.
- Local station history, simulated cloud SQL receiver, cloud history export.
- NASA POWER Daily real-data option with verified HTTPS and an offline demo.
- Country/region/city dropdowns with offline location presets; exact GPS input.
- Weather forecast and official severe weather alert panel (separate sources).

The demo does **not** create a real ESP32 Wi-Fi hotspot; for actual sensors you
will need separate ESP32 SoftAP firmware and a secure cloud-upload pathway.
NASA POWER observations are historical/regional and cannot provide real-time
storm alerts or independently reliable short-term forecasts.

## Tests

```bash
python -m unittest discover -s tests -v
```

Tests cover crop allocation, HTTPS certificate verification, preset location
validation, the calendar CRUD API, secure Gemini status, and tab ordering.
