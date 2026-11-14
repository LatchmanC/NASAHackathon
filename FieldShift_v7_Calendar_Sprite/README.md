# FieldShift v9 — Vercel-ready Preview

This edition migrates the FieldShift v8 three-tab dashboard to **stateless FastAPI** for Vercel's Python runtime. It keeps the original responsive layout and Fieldy mascot, but changes Fieldy's output to compact cards rather than raw technical essays.

## What works in this preview

- **Crop Management first**: country → region → city selection (or exact GPS coordinates); crop allocations, planting dates, notes and an interactive calendar.
- **NASA POWER Daily**: get up to 120 days of real regional historical weather data, graph it, and retain the result in the same browser. This is not a forecast.
- **Upcoming weather**: Open-Meteo forecast (independent from NASA) and, in supported U.S. locations, National Weather Service warnings. If a provider cannot be checked, its status is shown as unavailable—not safe.
- **Fieldy + Gemini 3.5 Flash-Lite**: concise headline, 2–4 next actions, short crop-specific guidance and a small data limitations note. Backend-only Gemini API key. Requires Auth0 login for public deployment.
- **Live readings page**: shows ESP32 offline, with no invented telemetry. Real sensor uploads/TigerData are intentionally not implemented in this preview.

## What isn't ready yet

This version is **not** a multi-user cloud farm database. Crop plans, selected location, calendar tasks and cached NASA results are saved only in the current browser's `localStorage`, scoped by Auth0 identity when logged in. They won't sync between computers, and shared machines aren't safe places to store sensitive data. The next step for actual farm accounts and ESP32 ingest is TigerData with farm-level authorization and device-specific credentials.

### Fastest deployment path — Vercel CLI

1. Extract the ZIP. Open a terminal in the folder containing `app.py`, `requirements.txt`, `public/` and `location_catalog.py`.
2. Install Vercel CLI (requires Node.js):

   ```bash
   npm install -g vercel
   vercel login
   ```

3. Run `vercel` from the project root. Create a new Vercel project when prompted. Vercel auto-detects FastAPI via `app.py`; choose the root directory containing `app.py`. No custom build command is required.
4. Visit the preview deployment URL. It works as an **unprotected public demo** without user records, Gemini credentials, or ESP32 readings.
5. When you are ready to restrict access and enable Gemini, add the environment variables listed below in **Vercel → Project → Settings → Environment Variables**. Redeploy once the settings are correct:

   ```bash
   vercel --prod
   ```

**Alternative:** Put the contents of the ZIP into a GitHub repository and import it from the Vercel dashboard. The important point is to deploy the *folder contents*, not upload the ZIP as a single website file.

### Auth0 configuration before enabling public Gemini

In Auth0, create a **Regular Web Application** and configure:

- Allowed Callback URLs: `https://YOUR-PROJECT.vercel.app/auth/callback`
- Allowed Logout URLs: `https://YOUR-PROJECT.vercel.app/`
- Allowed Web Origins: `https://YOUR-PROJECT.vercel.app`

In Vercel **server-side environment variables** (all deployments where needed), add:

```dotenv
AUTH0_ENABLED=1
FIELDSHIFT_DEMO=0
APP_BASE_URL=https://YOUR-PROJECT.vercel.app
AUTH0_DOMAIN=YOUR-TENANT.us.auth0.com
AUTH0_CLIENT_ID=YOUR-AUTH0-CLIENT-ID
AUTH0_CLIENT_SECRET=YOUR-AUTH0-CLIENT-SECRET
AUTH0_ALLOWED_EMAILS=your-email@example.com
SESSION_SECRET=replace-with-64-random-characters
GEMINI_API_KEY=YOUR_NEW_PRIVATE_GEMINI_KEY
FIELDSHIFT_GEMINI_MODEL=gemini-3.5-flash-lite
```

If you have an **Auth0 API Audience**, you may also add `AUTH0_AUDIENCE` for a backend API access token. The Audience alone does **not** replace Auth0 Domain, Client ID, Client Secret, or the callback URL. The demo uses a single-farm verified-email allowlist; it does not yet implement secure per-farm TigerData permissions.

**Never reuse the Gemini key previously posted in chat**; revoke it and generate a new one. Don't put keys or Auth0 secrets in frontend JavaScript or GitHub. If you enable Auth0 in production, configure *all* required values before deploying; the backend refuses to start if production auth configuration is incomplete.

### Local testing

Python 3.12 recommended:

```bash
python -m pip install -r requirements.txt
python -m uvicorn app:app --reload --host 127.0.0.1 --port 8501
```

Open http://127.0.0.1:8501. Without Auth0, this is an offline-friendly preview: plan/calendar state is kept in your browser, and Gemini is intentionally locked until sign-in is configured. `GET /api/health` reports basic API health.

### Why no SQLite in Vercel Functions?

Vercel Functions don't offer durable, shared writable local storage; file changes vanish across function instances and deployments. This project's former JSON/SQLite persistence was replaced with browser-only *preview storage* until TigerData is connected. Avoid writing mutable data to the deployed source folder.

### NASA API reliability and certificate errors

Country/state/city selections use bundled coordinates instead of calling a geocoding API. NASA downloads still require internet and valid HTTPS certificate chains. Certificate verification stays on; `certifi` and `truststore` are installed. The optional extra modeled soil-wetness request is disabled by default to keep the daily request responsive. Enable with `FIELDSHIFT_SOIL_LAYER=1` if needed.

### Security notes and limitations

- No ESP32 Wi-Fi or upload endpoint is provided. Build an authenticated device-ingestion API and route it to TigerData before installing physical sensors in the field.
- No multi-tenant database or server-side calendar persistence exists yet. Browser storage is not a secure replacement.
- The public preview doesn't permit Gemini API calls without Auth0, to prevent anyone from draining your AI quota.
- Severe-weather checking is not a substitute for official warning systems.
- Gemini advice is *assistance*, not a guaranteed weather forecast, planting outcome or harvest prediction. It cannot calculate growth progress or harvest timing without actual planting/cultivar data.

### Files

- `app.py` — Vercel-discoverable FastAPI entrypoint and API routes
- `public/index.html`, `public/static/` — dashboard, style, sprite and browser-side preview storage
- `intelligence.py`, `fieldshift_core.py` — NASA data and weather-source processing
- `auth0_integration.py` — optional Auth0 Universal Login and protected API routes
- `gemini_client.py` — Google Gemini SDK with structured JSON response mode
- `locations_catalog.json` — bundled offline location presets
- `.env.example` — placeholders only; never commit real credentials

No site has been published from this ZIP by the project builder: complete Vercel CLI or GitHub import steps above and obtain your deployment URL from Vercel.
