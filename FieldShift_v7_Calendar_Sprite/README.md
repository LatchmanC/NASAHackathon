## Read-only public data in Demo Mode (November 2026)

Public sample sessions use live public services for their selected coordinates:
NASA POWER daily historical records, Open-Meteo seven-day forecasts,
US National Weather Service official alerts, and public Soil & Rotation
data from USDA SSURGO, NASA POWER climatology, USGS elevation/water,
USDA CDL and the pre-extracted PRISM historical reference table.

- **NASA POWER:** `GET /api/nasa?mode=auto|real` fetches actual public
  daily records in Demo. Only explicit `mode=demo` returns synthetic data.
  Responses are cached in-process for one hour and in the demo browser for
  six hours, without TigerData writes. Missing provider data is reported as
  unavailable, never replaced with mock readings.
- **Current weather/NWS:** `GET /api/weather?mode=live` returns
  real Open-Meteo and NWS data for demo coordinates, cached in-process
  for ten minutes; warnings are clearly official and sensor alerts remain
  synthetic or inactive. NWS coverage is US-specific.
- **Soil & Rotation:** `GET /api/soil/profile` and
  `GET /api/soil/context` use only public USDA/NASA/USGS/CDL
  providers, with in-process hourly caching and no account-owned cache.
  Official USDA/OSM public map overlays may load in Demo Mode.
  The hard-coded crop reference guide/rotation rules remain educational.
- **Isolation:** This feature does not grant Auth0 privileges or allow
  demo users to access TigerData farm/sensor history, Google Calendar,
  SMS/Twilio, device pairing, or the Gemini API key.
  Sample ESP32 readings, farm plans, and calendar data remain fictional
  and locally stored. Labels distinguish measurements, provider estimates,
  and historical PRISM reference points.
- **Upstream availability:** External public APIs may fail, be rate-limited
  or have no coverage. These are displayed as unavailable, not fake values.
  In-process caching is best effort on serverless infrastructure.

---

## One-click public Demo mode (safe sandbox)

The login screen now includes a **Demo** button using a first-party form POST
to `/auth/demo`; no username, password or Auth0 account is required.
Production must explicitly enable `FIELDSHIFT_SAMPLE_ACCOUNT=1` while
keeping `AUTH0_ENABLED=1`. The existing secure session cookie is retained,
with a public `mode=sample` session. Verified Auth0-only database/device
endpoints continue to reject demo users, and no TigerData records are read
or written for the sample account.

Every demo dashboard panel is clearly marked SIMULATED DEMO:

- Example farm, crop plan and calendar tasks are stored only in the visitor's
  browser, under an isolated sample account key.
- Simulated live ESP32 values, history charts, and dated archives
  remain fictional; NASA POWER daily regional climate is real for the
  demo coordinates when the external provider is available.
- Soil & Rotation retrieves public USDA, NASA POWER climate, USGS and
  CDL data for demo coordinates, without reading private cached accounts.
  PRISM is an archived historical reference table. Unsupported values
  are never invented. Public USDA/OSM map embeds are available.
- Open-Meteo forecasts and NWS official alerts are real public requests for
  the chosen demo coordinates. Failed checks are identified as unavailable.
- Google Calendar, SMS/Twilio and ESP32 pairing are disabled and explicitly
  labelled because they require genuine account credentials or hardware.
- **Fieldy:** Public demo does *not* use the paid Gemini API, even when
  production's secret is configured, to avoid unrestricted third-party
  consumption. The Fieldy panel reads **"Demo mode, key not available"**
  and supplies scripted, question-aware sample replies with clear
  source labels. Real Auth0 users retain normal Gemini-powered advice.

Legacy public `test/test` demo credentials remain accepted as a compatibility
path. Sample sessions do not contain an email or validated Auth0 subject and
cannot access real user information. Exiting demo logs the sample session out
without contacting Auth0.

Deployment: this branch restores the last known working Fieldy/farm calendar
frontend `941ace4` before adding the Demo feature; the previously rolled-back
automatic TigerData calendar sync does not return to production.

Validation:
`python -m unittest discover -s tests -p 'test_public_demo.py' -v` and
`python -m unittest discover -s tests -p 'test_sample_login.py' -v`.

---

## Fieldy Gemini conversation and Soil & Rotation context

- **Gemini attribution:** A visible "Powered by Gemini" badge sits beside
  Fieldy. Public sample responses are explicitly labelled **Demonstration**
  and are not presented as actual Gemini generations.
- **Multi-turn conversation:** The current browser tab's dialogue is kept in
  `sessionStorage` under a per-Auth0-user key. Reloading the same tab retains
  the transcript; closing the tab normally ends the session. Nothing is
  persisted to TigerData or cloud chat storage. Up to 20 chat messages are
  retained locally, and up to 12 short previous messages are supplied to the
  following Gemini request. The clear-chat button removes only this session's
  dialogue.
- **Soil & Rotation:** Fieldy uses matching farmer-owned TigerData cache
  records for USDA NRCS map units and NASA POWER, USGS and USDA CDL context,
  plus the historical PRISM point samples, farm crop plan and the farmer's
  crop-guide / rotation selection. If values are only currently visible in
  the browser, they are identified as a **browser view, not independently
  verified by the server**. Fieldy never labels published map-unit estimates
  as farm sensor tests and does not reuse the disabled SMAP integration.
- **Important numbers:** Gemini can return 0–4 highlighted, attributed data
  cards, with selective bold emphasis for actual important details. All
  text is HTML-escaped before rendering; no model-authored HTML is executed.
- **Calendar:** Existing Fieldy Google Calendar and farm task confirmation
  remains opt-in; its status message appears in the same chat transcript.
- **Deployment safety:** This feature restores the previously rolled-back
  stable farm/calendar frontend, rather than reintroducing the automatic
  TigerData calendar synchronization code that previously caused issues.

Checks: `python -m unittest discover -s tests -p 'test_fieldy*.py' -v`,
`node --test tests/test_fieldy_frontend.cjs`, and `node --check
public/static/app.js`. Gemini requests require a verified Auth0 login and
a configured `GEMINI_API_KEY`; offline tests mock the provider and do not
make chargeable Gemini calls.

---

## Farm profiles, calendar and rotation drafts in TigerData (Nov 2026)

Signed-in Cropaganda accounts use TigerData as the **primary** store for their
farm plan (acreage, crops, planting dates and notes), farm location, manual
calendar tasks and saved rotation drafts. Each account is isolated using a
SHA-256 lookup key derived server-side from its verified Auth0 subject.

**First visit after the upgrade:** Open **My Farm**. If this browser contains
farm records from an earlier browser-only version, select **Import browser
data into TigerData**. The old browser records stay as backups. Existing cloud
plans and locations are never overwritten by an import; calendar tasks and
rotation drafts are merged by ID without replacing stored entries. The import
can be re-opened using **Import earlier browser data**. An explicit **Reload
from TigerData** button refreshes cross-device changes; it warns that unsaved
form edits will be lost.

A saved plan, location or rotation must successfully complete its TigerData API
write before the UI reports success. The server enforces optimistic revisions
and rejects stale writes from another device (HTTP 409). Calendar operations
are serialized in the database. If the production connection is unavailable,
the user is warned and writes are refused instead of silently pretending
browser data is saved. Demo/sample sessions stay browser-only and cannot
access real farm documents.

- API: `GET /api/farm/state`, `PUT /api/farm/state/{plan|location|rotation_scenarios|calendar}`,
  `POST /api/farm/calendar`, `DELETE /api/farm/calendar/{id}`,
  `POST /api/farm/import`. These require verified Auth0 sessions.
- Schema: `cropoganda_farm_documents` in
  `sql/cropoganda_tigerdata.sql`, created automatically on first authenticated
  use if the database user has CREATE permission.
- The existing `cropoganda_farm_locations` is updated atomically with location
  saves so NASA POWER daily syncing still works.
- Vercel project variable `TIGERDATA_DATABASE_URL` must be set in **Production**.
  It is not exposed to JavaScript. Preview deployments without this variable
  cannot perform real cloud writes.
- This migration does **not** move historic sensor records, Google Calendar
  events stored by Google, or downloaded NASA cache records: those already
  have separate storage and access mechanisms. No previous browser data is
  deleted automatically.

Validation: `python -m unittest discover -s tests -p 'test_farm_profile_api.py' -v`.
Deployment readiness cannot certify actual database permissions or a real
signed-in write. Test the My Farm save/import flow with a verified account in
Production after rollout.

---

## Soil & Rotation data expansion — November 2026

The **Data Sources** section is an internal subtab of the existing **Soil & Rotation** tab alongside Overview, Soil Map, Crop Guide, and Rotation Planner. It is not a separate application page.

### Connected live/public source adapters

- **USDA NRCS SSURGO Soil Data Access**: `/api/soil/profile` now uses a **two-step spatial lookup**: WGS84 farm point → map-unit key → soil component properties. Surface texture is a separate optional query, so a failed texture lookup no longer prevents reading drainage. A rated secondary component is explicitly marked as secondary; unrated urban map units remain **Not rated** rather than being assigned synthetic drainage.
- **NASA POWER agroclimatology**: `/api/soil/context` provides real long-term regional temperature, humidity, precipitation, radiation, and surface pressure when the public POWER API responds. It never labels climatology as a current sensor reading or SMAP retrieval.
- **USGS 3DEP**: terrain elevation and a clearly labeled single-direction northward transect slope estimate (not a field gradient or soil drainage class).
- **USGS NWIS**: nearby water gauge observation summaries. These are regional hydrology, **not** field moisture.
- **USDA NASS Cropland Data Layer**: 2024 and 2025 point land-cover classification requests using an actual NAD83 CONUS Albers (EPSG:5070) projection, not the approximate degree scaling in the supplied Gemini script. A 30 m classification is not verified historic crop planting.

### Uploaded PRISM archive integration

- `prism_reference.py` contains directly sampled values from the provided **2022 2.5 arc-minute** annual GeoTIFFs: precipitation, mean/min/max temperature, dew point and total/sloped solar radiation.
- Includes the provided **2016 30-arcsecond** mean minimum/maximum temperatures, dew point and sloped solar samples.
- These historical grid-cell values are samples at **26 named reference points**. The UI reports the distance to the closest available point and never pretends a nearby sample is a farm-point measurement. It declines to show any reference values if the farm is more than 30 km from a sample point. For precise arbitrary coordinates, use the linked PRISM Explorer.
- The supplied 2016 and 2025 PRISM precipitation ZIPs were Git LFS pointer files rather than raster archives and are not represented as data.
- The ~185 MB source ZIP collection was **not committed** to GitHub; the small sampled archive is kept with provenance instead.

### Not connected / not fabricated

The supplied Gemini code described approximately 24 datasets but did not include functional authenticated access to each one. The Data Sources section links to **USDA QuickStats, AMS, OpenET**, and exposes the separately configured **NASA SMAP Level-3** service. No fake county yields, prices, ECOSTRESS ET, GEDI biomass, NDVI, or pseudo-SMAP values are substituted. Additional credentials and verified API adapters would be required before these sources can power numerical crop recommendations.

Server-side endpoints remain Auth0-protected and keyed to the selected location. Google Calendar OAuth and ESP32 device ingestion are unchanged.

To verify: from `FieldShift_v7_Calendar_Sprite`, run `python -m unittest discover -s tests -p 'test_soil*.py' -v` and `node --check public/static/soil-rotation.js`. CI runs the same checks plus a best-effort external USDA diagnostic. Vercel Preview/Production deploy only after a successful build.

---


### Troubleshooting mapped drainage and SMAP in New York

- In **My Farm**, use the actual farm latitude/longitude, not a city-center preset. Urban land, water, and disturbed map units may be present in SSURGO without a rated drainage class.
- The USDA endpoint reports `no_coverage` when there is no map unit, and `drainage_status: unrated` when a map unit exists but drainage was not rated. If a lower-percentage mapped component is the only one with a drainage rating, it is labeled **rated secondary component** and its dominant component is disclosed; it is not a field-level measurement.
- USDA and Earth Engine request exceptions are logged on the server for diagnostics, with no credentials or stack traces returned to the browser. Failed external requests can be retried by refreshing the tab.
- **SMAP Level-3** remains unavailable until both `EARTH_ENGINE_PROJECT` and `EARTH_ENGINE_SERVICE_ACCOUNT_JSON` are set securely on the server and the Earth Engine API/project authorization is complete. Missing configuration is reported explicitly. This is entirely separate from Google Calendar OAuth.
- NASA POWER's high-resolution SMAP Level-4 **modeled/assimilated** moisture is a different product and must not be silently substituted for the Level-3 radiometer readings shown here.

## Soil & Crop Rotation (November 2026)

The new **Soil & Rotation** tab keeps the existing Auth0, farm-plan, Fieldy, TigerData, ESP32, Google Calendar and NASA POWER API endpoints unchanged. It contains **Overview**, **Soil Map**, **Crop Guide** and **Rotation Planner** views.

- **USDA NRCS Soil Data Access:** `GET /api/soil/profile?latitude=...&longitude=...` uses a verified Auth0 session, server-side bounded point-intersection SQL at `https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest`, and returns the dominant published soil-map-unit component. No USDA API token is needed. The WMS imagery is served directly from USDA; the associated OpenStreetMap pane is for geographic context. Some locations have no published detailed survey.
- **NASA SMAP:** `GET /api/soil/smap?latitude=...&longitude=...` reads real morning `soil_moisture_am` and `retrieval_qual_flag_am` from `NASA/SMAP/SPL3SMP_E/006` via Google Earth Engine **only** with administrator configuration:
  - `EARTH_ENGINE_PROJECT`: an Earth Engine-enabled Google Cloud project ID.
  - `EARTH_ENGINE_SERVICE_ACCOUNT_JSON`: complete service-account credentials JSON as an encrypted Vercel Production environment variable. Keep it private; the existing Google Calendar OAuth client ID/secret cannot replace it.
  - Enable the Earth Engine API, register the Cloud project for its intended purpose, and authorize the service account's Earth Engine access before testing. Usage fees or access restrictions may apply, depending on organization.
- **Data integrity:** no synthetic SMAP or USDA values; 9 km SMAP measurements are not field-level ESP32 measurements; USDA survey pH/texture/drainage are representative published soil attributes, not laboratory test results. Quality-failing SMAP samples are excluded.
- **Caching:** when TigerData is enabled and the database role can create tables, authenticated access automatically creates an independent `cropaganda_soil_cache` table on first successful retrieval. It stores account-keyed, point-keyed JSON (USDA: 24 hours; SMAP: six hours). The table can alternatively be created manually with `sql/cropaganda_soil_cache.sql`. If cache persistence fails, live sourced responses still work.
- **Rotation drafts:** eight crop reference descriptions are adapted from the supplied React prototype, but fixed prices, made-up forecasts, predictive match percentages and synthetic sensor results are deliberately omitted. Saved drafts use the existing account-scoped browser storage. They do **not** automatically modify farm plan, ESP32 records, Google Calendar or SQL history.

Official sources: https://sdmdataaccess.sc.egov.usda.gov/WebServiceHelp.aspx · https://developers.google.com/earth-engine/datasets/catalog/NASA_SMAP_SPL3SMP_E_006 · https://nsidc.org/data/spl3smp_e/versions/6

---

## Cropaganda — Google Calendar and automatic NASA POWER archive (November 2026)

### Fieldy → Farm Calendar → Google Calendar

The Cropaganda dashboard now accepts **calendar action proposals** in Fieldy answers.
Example: "I want to plant strawberries tomorrow." Fieldy may propose a
**Plant strawberries** task for tomorrow (the visitor's local calendar date).
The user must explicitly confirm **Yes, add to both calendars**, or type
**yes** while that proposal is pending. **Nothing is scheduled automatically**.
A refusal dismisses the proposal. The same request ID avoids duplicate Google
events if a confirmation is retried. The farm-calendar side currently saves tasks
**to this browser**; the Google side saves all-day tasks to the user's **primary
Google Calendar**. This is one-way, confirmed event creation, not bidirectional
calendar synchronization or synchronization of all manually added farm tasks.

To enable Google Calendar linking, the Cropaganda project owner must:

1. Open Google Cloud Console. Enable the **Google Calendar API**.
2. Configure the **Google Auth Platform / OAuth consent screen** for Cropaganda.
   Add test users during development, or complete any Google verification needed
   before general public use of the sensitive Calendar events scope.
3. Create an **OAuth 2.0 Client ID** of type **Web application**.
   Add this **exact Authorized redirect URI**:
   `https://cropaganda.garden/api/google/callback`
4. In Vercel project `nasa-hackathon` → Settings → Environment Variables,
   add the client's `GOOGLE_OAUTH_CLIENT_ID` and `GOOGLE_OAUTH_CLIENT_SECRET`
   as Production encrypted secrets; do not commit these values.
   `GOOGLE_TOKEN_ENCRYPTION_KEY` is an independent Fernet key already provisioned
   in Production; **never change it without migrating existing encrypted tokens**.
5. Redeploy. Sign in to Cropaganda through Auth0, select **Connect Google
   Calendar**, grant the `calendar.events` permission, and ask Fieldy to add a task.

Google refresh tokens are encrypted in the account-specific
`cropoganda_google_calendar` SQL table. The table is created by a controlled
CREATE TABLE IF NOT EXISTS on first connection, or manually via the migration
`sql/cropoganda_google_calendar.sql`. Farmers can disconnect the link at any
time. An OAuth connection can only be used by the corresponding authenticated
Auth0 account. Google event creation requires both the account's consent and
per-event confirmation.

### Automatic NASA POWER sync → TigerData

A Vercel Cron job is configured for **09:15 UTC daily**, sending a secret
Authorization header to `GET /api/nasa/cron-sync`. A strong `CRON_SECRET` was
provisioned to Production. The handler refuses any request without that bearer
secret. Only **actual NASA POWER historical daily data** is stored; no synthetic
weather rows are generated.

When a farmer explicitly selects/saves the farm location, Cropaganda stores its
coordinates in TigerData's `cropoganda_farm_locations` table, created if missing.
When they return, an already selected, non-demo location is registered as well.
The daily cron refreshes the most recent 15 days for at most eight registered
farms per invocation, prioritizing the least recently synced farms. It updates
the account-scoped `cropoganda_nasa_daily` table with available real data.
NASA's most recent day may not yet be published. On Hobby Vercel tiers daily Cron
execution is approximate; inspect runtime logs to verify actual successful syncs.

The History tab now presents a **single dropdown of saved UTC dates**, populated
with `GET /api/history/dates` (distinct recorded ESP32 archive dates), followed
by a saved-timestamp selection. No month/year filter or synthetic readings.

Additional migration script:
`sql/cropoganda_google_calendar.sql`.
No ESP32 firmware or device token changes are required for these calendar
and historical browsing features.

---

# Cropaganda — TigerData live monitoring and historical archive

**Website:** https://cropaganda.garden

## Architecture

- **ESP32 upload endpoint stays unchanged:** `POST https://cropaganda.garden/api/device/ingest`. Existing device pairing tokens remain valid.
- **TigerData not yet connected to this deployment:** add the database credentials after provisioning the service. The existing private Vercel Blob feed remains active until that point; its minimum upload interval remains five minutes.
- **When TigerData is configured**, every accepted ESP32 upload **updates the most recent live record immediately**. The Live Sensor Data tab polls every **2 seconds** while visible. This is near-live HTTP polling, not WebSockets; latency is typically up to a few seconds plus upload/network time.
- **Every 10 minutes**, the first actual ESP32 measurement to arrive during each UTC time bucket is retained in `cropoganda_sensor_history`. This is not an invented or averaged value. There is no timestamp without a real upload.
- The **History** tab allows selection of a month, date, and saved timestamp (UTC), and shows the archived sensor values and a stored NASA POWER Daily row for that day and the farm location.
- **NASA POWER historical daily records are stored in TigerData** when a farmer clicks **Download latest NASA data** in the NASA tab (automatically archived during the download), or **Store latest NASA POWER Daily in TigerData** in the History tab. NASA data can lag the current calendar day; it is not a real-time weather forecast.
- Own and view-only shared devices remain account-isolated using verified Auth0 identities. Shared History shows the owner's sensor archive; NASA lookup uses the location and owner's stored regional records.

## Enable TigerData (one-time)

1. Create a TigerData service; copy its **PostgreSQL connection string** with TLS enabled.
2. In the TigerData SQL editor, execute the complete migration file `sql/cropoganda_tigerdata.sql`. This creates four tables and indexes. Do not run unreviewed SQL that drops existing tables.
3. In Vercel **Cropaganda's existing project** (still internally named `nasa-hackathon`), add a **Production encrypted variable**: `TIGERDATA_DATABASE_URL` = the full connection string. Keep it out of GitHub and firmware.
4. Redeploy, then check `https://cropaganda.garden/api/health` for `"tigerdata_configured":true`.
5. Reflash the ESP32 with an upload interval of e.g. **5,000 ms** (only after the DB schema and connection have been verified). TigerData allows a minimum accepted interval of 2 s by default. Set `CROPOGANDA_MIN_SENSOR_SECONDS` in Vercel if another minimum is required. Existing upload tokens do not change.
6. Open NASA POWER Daily and select **Download latest NASA data** to save available daily regional observations to TigerData. Visit the **History** tab to browse archived timestamps.

**Important:** New TigerData snapshots begin when the new DB is enabled. The older Blob snapshot remains as a fallback and is **not automatically backfilled** into the new 10-minute archive. NASA daily observations are updated when explicitly downloaded or synced; a background daily sync scheduler is not yet configured. Device uploads and 2-second dashboard polling increase database operations and Vercel runtime usage. For larger deployments, use a pooled TigerData connection and consider a managed realtime transport.

## Auth0 hosted login wording

Website text is already rebranded **Cropaganda**, but Auth0 Universal Login is a separate hosted service. In Auth0 Dashboard set **Settings → General → Friendly Name** to `Cropaganda`; then rename the linked **Applications → Applications** client to `Cropaganda`. To make the description exactly **Log in to Cropaganda**, under **Branding → Universal Login → Advanced Options → Custom Text**, select the Login prompt and enter `Log in to Cropaganda`. Do not rename the Auth0 tenant's technical hostname or rotate the client ID.

## Compatibility retained

- `FIELDSHIFT_*` environment variable names, `fieldshift_session` cookie, `fieldshift_v9` browser storage prefix, `X-FieldShift-Request` CSRF header, and `fieldshift-*-token-v1` cryptographic salts intentionally retain their existing values, to preserve logins, crop/calendar state, and ESP32 upload and sharing tokens.
- Site address `cropaganda.garden` is **unchanged** and matches the Cropaganda product name.

---

## Shared ESP32 access (read-only) and live forecasts

A farmer with ESP32 uploads can open **Live Sensor Data → Share ESP32 readings** and generate a **viewing token** for their actual device ID. Another verified Auth0 user can paste it under **Enter a viewing token**, then select **Shared ESP32**. Both accounts read the same private snapshot; only the original account's ESP32 upload token authorizes posting readings. A viewing token cannot be used with `/api/device/ingest`.

Viewing tokens expire after 180 days. The owner can select **Revoke all sharing tokens I issued** without stopping ESP32 uploads; recipients may also **Disconnect shared ESP32**. Links are stored privately in Vercel Blob under each recipient and cannot be applied to arbitrary accounts. Each recipient can connect one shared ESP32 at a time. Use the **Show sensor data from** selector to choose an owned or shared feed. Fieldy's Gemini advisor uses the selected feed, with read-only sharing labeled in its context.

**Upcoming weather** no longer offers demo mode. The website always requests the live forecast. If the forecast is unavailable it displays an error; it does not fabricate weather data.

---

## Current production login — Auth0 only

The public `test / test` sample login has been retired. The login page offers only Auth0 sign-in and self-service registration. Set `FIELDSHIFT_SAMPLE_ACCOUNT=0` in the Vercel Production environment. The retired `/auth/demo` route rejects logins, and existing sample sessions are invalidated by authentication middleware. Verified Auth0 accounts retain Gemini, ESP32 pairing, NASA weather, and other existing capabilities.

---

## Cropaganda v14 — Direct Gemini answers and ESP32 cloud ingestion

**Production:** https://cropaganda.garden

### Gemini
The Fieldy AI now answers the **question you type**, using your crop plan, selected location,
upcoming calendar tasks, server-fetched NASA POWER historical weather (or clearly labeled
browser cache when unavailable), live Open-Meteo forecast, official weather alerts, and
real ESP32 readings available for your Auth0 account. Its answer includes assumptions and
source limitations, and estimates are labeled rather than fabricated. 
All email-verified Auth0 users can use the real model. The retired public sample login is disabled in production. The key stays server-side.

### ESP32 — First-time setup
1. Sign in at https://cropaganda.garden with a **verified Auth0 account**.
2. Open **Live Sensor Data → Pair your ESP32**.
3. Choose a device ID (e.g. `esp32-01`), press **Generate pairing token** and **Copy token**.
   Keep this token private. It authorizes *writes only* to your private sensor snapshot.
   Device tokens expire after **180 days**. Generate another after expiration.
4. Open the `esp32/FieldShift_ESP32.ino` sketch from the download package in Arduino IDE.
   Set your Wi-Fi SSID/password, device ID and token. Never commit your Wi-Fi password
   or token to GitHub. Arduino ESP32 Core and WiFi/HTTPClient are required.
5. Start with `VALIDATION_ONLY=true`: it sends sample payloads to
   `POST https://cropaganda.garden/api/device/validate` and **does not store readings**.
   Look for HTTP 200 in Serial Monitor.
6. Wire and calibrate actual sensors, set their corresponding GPIOs, then switch
   `VALIDATION_ONLY=false` to send authenticated readings to
   `POST https://cropaganda.garden/api/device/ingest` over TLS.
7. Refresh Live Sensor Data. The page polls every 30 seconds; private Blob may cache
   updates for up to about a minute. If there is no device upload, sensors display Offline.

**JSON data schema** (send only fields actually measured):

```json
{"device_id":"esp32-01","temperature_c":24.1,"humidity_pct":58,"pressure_hpa":1012.5,"soil_moisture_pct":42,"ph":6.5,"light_pct":75,"rain_wetness_pct":12,"gas_index":21,"altitude_m":16}
```

The paired device sends the token in `Authorization: Bearer <private-token>` and
`Content-Type: application/json`. Unauthorized uploads get 401 and invalid measurements
422. Uploads faster than the backend's minimum interval (default 300 seconds) get
429 with a `Retry-After` response header.

**Storage limitations:** The private Vercel Blob store is persistent and account-scoped,
but is a prototype snapshot (last 72 readings), not a full time-series DB.
Vercel Hobby includes about 2,000 advanced operations/month; a device sending every
five minutes around the clock will exceed that limit. Use a slower interval for
unattended usage, or switch to TigerData/TimescaleDB for frequent real-time data.
The private store's credentials stay in Vercel environment variables.

ESP32 sensor hardware models and pin wiring were not supplied, so the sketch contains
optional *unconnected* ADC examples. Never treat unwired floating ADC values as valid
measurements. The built-in validation mode verifies connectivity without forging field data.

---
## Gemini access — verified Auth0 users (2026-11-14)

Every registered user who has **verified their email** and signed in using Auth0 can request real Gemini advice. The separate public `test / test` sample login remains restricted to fixed sample advice. There is no required `AUTH0_ALLOWED_EMAILS` entry for Gemini. Because there is no durable quota backend yet, monitor paid Gemini usage and set account/project spending safeguards before broad advertising.

---

# Cropaganda v11 — Production login + sample profile

**Live production**: https://cropaganda.garden

- The public home page is a login screen. Real users use Auth0 Universal Login; the temporary **test / test** credentials open a **fictional sample-only** profile using a signed server-side cookie. This is a demonstration, not a secure password.
- Sample account: crop plan, editable calendar, fictional sensor metrics clearly marked synthetic, live NASA POWER historical downloads, live Open-Meteo forecasts and official NWS alerts where supported. Fieldy displays **sample advice only** in this account and makes **no Gemini API call**, so the public test credentials cannot incur AI charges.
- Auth0 users: self-registration uses Auth0 Universal Login. Newly registered users verify their email, then access the dashboard; crop plans/calendar use per-browser storage until TigerData exists. Every signed-in, email-verified Auth0 account can request real Gemini advice. No manual email allowlist is required for Gemini. Do not use browser storage for sensitive farm details.
- ESP32 device upload and TigerData have **not been implemented**. Sensor data outside the sample account is honestly shown as disconnected.
- All `/api/*` endpoints except health and auth-status require a signed session when `AUTH0_ENABLED=1`.

## Required Vercel production environment variables

```
AUTH0_ENABLED=1
AUTH0_ALLOW_SIGNUPS=1
FIELDSHIFT_DEMO=0
FIELDSHIFT_SAMPLE_ACCOUNT=1
APP_BASE_URL=https://cropaganda.garden
AUTH0_DOMAIN=your-auth0-tenant.auth0.com
AUTH0_CLIENT_ID=your-existing-client-id
AUTH0_CLIENT_SECRET=your-existing-secret
AUTH0_SECRET=your-existing-random-cookie-secret-32-chars-plus
GEMINI_API_KEY=your-private-key
```

With `AUTH0_ALLOW_SIGNUPS=1`, all registered Auth0 accounts with verified emails can enter the dashboard and call Gemini; no manual allowlist is required. The public sample user continues to receive fixed advice without Gemini. Configure the Auth0 database connection to allow signups and verify emails. If signups are disabled, `AUTH0_ALLOWED_EMAILS` still controls which verified accounts may sign in.

**Usage and billing warning:** This release has no persistent per-user Gemini quota or rate limiting. Every verified registrant can consume API credits. Configure cost alerts and limits with Google AI Studio / Google Cloud and add durable account-level quotas before scaling. Do not claim that the Auth0 login alone enforces request limits. Never commit .env files or keys.

Set Auth0 Regular Web Application URLs:
- Signup: `https://cropaganda.garden/auth/signup` (Auth0 hosted sign-up)
- Callback: `https://cropaganda.garden/auth/callback`
- Logout: `https://cropaganda.garden/`
- Web Origin: `https://cropaganda.garden`

If Auth0 requests fail, verify these values in Auth0. The separate Auth0 Management API credentials in Vercel are **not** required for user sign-in. Login passwords belong in Auth0, never in the Cropaganda backend. An Auth0 Audience is optional for this server-managed browser session.

## Local run

```
python -m pip install -r requirements.txt
python -m uvicorn app:app --reload --port 8501
```

For local testing, set `AUTH0_ENABLED=0`, `FIELDSHIFT_DEMO=1`, `FIELDSHIFT_SAMPLE_ACCOUNT=1`, and a 32+ character `SESSION_SECRET`. The test profile is a fictional demo, not an Auth0 account.

---

## Live Auth0 setup for cropaganda.garden

The Cropaganda Vercel site uses **https://cropaganda.garden** as its canonical host.
In your existing Auth0 **Regular Web Application**, set:

| Auth0 setting | Value |
|---|---|
| Allowed Callback URLs | `https://cropaganda.garden/auth/callback` |
| Allowed Logout URLs | `https://cropaganda.garden/` |
| Allowed Web Origins | `https://cropaganda.garden` |

Keep the already-configured `AUTH0_DOMAIN`, `AUTH0_CLIENT_ID`, `AUTH0_CLIENT_SECRET`, and `GEMINI_API_KEY` in **Vercel Production Environment Variables**. `APP_BASE_URL=https://cropaganda.garden` is already configured on Vercel.

The app accepts `SESSION_SECRET` or existing `AUTH0_SECRET` (at least 32 characters) for the signed browser session. Never copy or expose its value. Add `AUTH0_ALLOWED_EMAILS` listing only verified email addresses you approve, separated by commas. Then set `AUTH0_ENABLED=1` and `FIELDSHIFT_DEMO=0`, and redeploy **after** the Auth0 callback allowlist is saved.

`AUTH0_AUDIENCE` is optional for the website's OIDC login; add it only if requesting access tokens for your separate protected API. The Auth0 Management API client credentials are **not** needed for ordinary farmer login. Do not paste secrets in GitHub.

**Current limitation:** user-specific farm plans and calendar are saved only in browser storage under an Auth0 user identifier; this is not server-side farm data isolation or cross-device sync. Add TigerData and enforce farm membership in every database query before admitting unrelated farmers.

---

# Cropaganda v9 — Vercel-ready Preview

This edition migrates the Cropaganda v8 three-tab dashboard to **stateless FastAPI** for Vercel's Python runtime. It keeps the original responsive layout and Fieldy mascot, but changes Fieldy's output to compact cards rather than raw technical essays.

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
AUTH0_ALLOW_SIGNUPS=1
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
