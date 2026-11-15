# Cropoganda text messages (Twilio) on Vercel

| Feature | How it works |
|---|---|
| **Alerts** | When the ESP32 uploads a reading that **newly** crosses a rule, the linked farm gets a text: low soil moisture (<25%), frost (≤2°C), heat (≥35°C), rain plate wet (≥75%). A field that stays dry doesn't re-text every upload. |
| **Reminders** | Vercel Cron runs once a day (`vercel.json`, 23:00 UTC ≈ 6pm New York) and texts tomorrow's calendar tasks. The **Text tomorrow's tasks** button does it on demand. |
| **Text Fieldy** | Text any question to the Cropoganda number → Gemini answers by text, using the farm's latest ESP32 reading, location forecast and calendar. |
| **STATUS / TASKS** | Text `STATUS` → latest readings. `TASKS` → upcoming calendar. `HELP` → commands. `STOP` is handled by Twilio. |

**Dashboard → Crop Management → 📱 Text alerts** has the buttons: *Link my farm to texts*, *Send test text*, *Send test alert*, *Text tomorrow's tasks*.

## 1. Vercel environment variables

Project → Settings → Environment Variables (then **redeploy**):

| Name | Value |
|---|---|
| `TWILIO_ACCOUNT_SID` | from the Twilio Console home page |
| `TWILIO_AUTH_TOKEN` | from the Twilio Console home page. **Secret.** |
| `TWILIO_FROM_NUMBER` | the Cropoganda number, e.g. `+16413216713` |
| `FIELDSHIFT_SMS_TO` | the farmer / Dev Phone number(s), comma-separated, e.g. `+16204136430` |
| `CRON_SECRET` | any long random string (Vercel sends it to the daily reminder route) |
| `APP_BASE_URL` | already set for Auth0. Must be the exact public URL, e.g. `https://cropaganda.garden` |

Optional: `FIELDSHIFT_TZ` (default `America/New_York`), `FIELDSHIFT_SMS_ALLOW_SAMPLE=1` (lets the public test/test account press the demo buttons).

Only numbers in `FIELDSHIFT_SMS_TO` can text in or receive texts. Everyone else gets "not registered".

## 2. Point the Twilio number at Vercel

Twilio Console → Phone Numbers → Active numbers → **the Cropoganda number** (not the Dev Phone's) → Messaging configuration → **A message comes in**:
- Webhook: `https://YOUR-DOMAIN/api/twilio/sms` (same domain as `APP_BASE_URL`)
- HTTP **POST** → Save

Every request is checked with Twilio's signature. If texts get no reply, check that the webhook URL and `APP_BASE_URL` match **exactly** (https, no trailing slash).

## 3. Link the farm

Sign in with Auth0 → Crop Management → **Link my farm to texts**. This saves (privately, in Vercel Blob) which account the texts are about, plus the farm location and calendar. Calendar/location changes re-sync automatically.

## 4. Demo with the Twilio Dev Phone

`twilio dev-phone` → pick the Dev Phone number → destination = Cropoganda number.
- Press **Send test alert** → alert appears in the Dev Phone
- Type `STATUS` in the Dev Phone → readings come back
- Type a question → Fieldy answers (takes a few seconds)

## Notes

- Fieldy gets 10 s for an answer because Twilio only waits ~15 s for a reply. If Gemini is slow, the farmer gets "try again in a minute".
- Vercel Hobby crons run once per day, sometime within the scheduled hour.
- Tests: `python -m unittest discover -s tests` (`tests/test_sms.py`, offline).
