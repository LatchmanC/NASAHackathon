"""Cropaganda text messages (Twilio) - Vercel/stateless edition.

Features
  1. Alerts       - when the ESP32 uploads a reading that NEWLY crosses a rule (low soil
                    moisture, heat, frost, wet rain plate), the linked farm gets a text.
  2. Reminders    - a daily Vercel Cron (and a dashboard button) texts tomorrow's calendar tasks.
  3. Text Fieldy  - texting any question to the Cropaganda number gets a Gemini answer.
  4. STATUS/TASKS - texting STATUS returns the latest readings; TASKS the upcoming calendar.

Vercel environment variables (Project Settings -> Environment Variables):
  TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN   from the Twilio Console (keep the token secret)
  TWILIO_FROM_NUMBER                      the Cropaganda Twilio number, e.g. +16413216713
  FIELDSHIFT_SMS_TO                       farmer phone number(s), comma-separated, e.g. +16204136430
                                          Only these numbers can text in or receive texts.
  APP_BASE_URL                            already used by Auth0, e.g. https://cropaganda.garden
  CRON_SECRET                             any long random string (protects the daily reminder route)
Optional:
  FIELDSHIFT_TZ=America/New_York          farm time zone for "tomorrow"
  FIELDSHIFT_SMS_ALLOW_SAMPLE=1           let the public test/test account press the demo buttons

Storage: the linked farm (Auth0 owner, location, calendar) is one private Vercel Blob
(sms/v1/link.json). Sensor readings come from the existing sensor_store snapshots.
"""
from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from xml.sax.saxutils import escape

from fastapi import HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from sensor_store import configured as blob_configured, read_snapshot

LINK_PATH = 'sms/v1/link.json'
SMS_MAX = 900                     # ~6 SMS segments
TASK_KINDS = {'planting', 'watering', 'harvest', 'fertilizing', 'inspection', 'other'}


# ------------------------------------------------------------------ settings
def env(name, default=''):
    return os.environ.get(name, default).strip()


def configured():
    return bool(env('TWILIO_ACCOUNT_SID') and env('TWILIO_AUTH_TOKEN') and env('TWILIO_FROM_NUMBER'))


def farmer_numbers():
    return [n.strip() for n in env('FIELDSHIFT_SMS_TO').split(',') if n.strip()]


def mask(number):
    n = str(number or '')
    return n[:2] + '•' * max(0, len(n) - 6) + n[-4:] if len(n) > 6 else n


def farm_today():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(env('FIELDSHIFT_TZ', 'America/New_York'))).date()
    except Exception:
        return datetime.now(timezone.utc).date()


# ------------------------------------------------------------------ linked farm (private Blob)
def read_link():
    if not blob_configured():
        return None
    from vercel.blob import sync as blob
    from vercel.blob.errors import BlobNotFoundError
    try:
        data = blob.get_blob(LINK_PATH, access='private')
        if data is None or len(data.body) > 300000:
            return None
        doc = json.loads(data.body)
        return doc if isinstance(doc, dict) and doc.get('owner') else None
    except BlobNotFoundError:
        return None
    except Exception:
        return None


def write_link(doc):
    if not blob_configured():
        raise HTTPException(503, 'Cloud storage (Vercel Blob) is not configured')
    from vercel.blob import sync as blob
    blob.put_blob(LINK_PATH, json.dumps(doc, separators=(',', ':')).encode(), access='private',
                  content_type='application/json', allow_overwrite=True, cache_control_max_age=60)


def clean_tasks(tasks):
    out = []
    for t in (tasks or [])[:200]:
        if not isinstance(t, dict):
            continue
        date, kind = str(t.get('date', ''))[:10], str(t.get('kind', '')).lower()
        try:
            datetime.strptime(date, '%Y-%m-%d')
        except ValueError:
            continue
        if kind in TASK_KINDS:
            out.append({'date': date, 'kind': kind, 'crop': str(t.get('crop', ''))[:70],
                        'note': str(t.get('note', ''))[:240]})
    return sorted(out, key=lambda x: x['date'])


def clean_location(loc):
    try:
        lat, lon = float(loc.get('latitude')), float(loc.get('longitude'))
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            return {'latitude': lat, 'longitude': lon, 'label': str(loc.get('label', ''))[:100]}
    except (TypeError, ValueError, AttributeError):
        pass
    return None


# ------------------------------------------------------------------ sending
def send_sms(to, body):
    body = (body or '').strip()[:SMS_MAX]
    if not configured():
        return {'to': mask(to), 'sent': False, 'error': 'Twilio is not configured on the server'}
    try:
        from twilio.rest import Client
        msg = Client(env('TWILIO_ACCOUNT_SID'), env('TWILIO_AUTH_TOKEN')).messages.create(
            to=to, from_=env('TWILIO_FROM_NUMBER'), body=body)
        return {'to': mask(to), 'sent': True, 'status': msg.status}
    except Exception as exc:
        return {'to': mask(to), 'sent': False, 'error': (getattr(exc, 'msg', None) or str(exc))[:200]}


def send_to_farmers(body):
    if not farmer_numbers():
        raise HTTPException(400, 'Set FIELDSHIFT_SMS_TO in Vercel first')
    return [send_sms(n, body) for n in farmer_numbers()]


def twiml(message=None):
    if not message:
        return Response('<?xml version="1.0" encoding="UTF-8"?><Response></Response>', media_type='application/xml')
    return Response('<?xml version="1.0" encoding="UTF-8"?><Response><Message>'
                    f'{escape(message[:SMS_MAX])}</Message></Response>', media_type='application/xml')


# ------------------------------------------------------------------ message text
def fmt(v, unit='', digits=0):
    try:
        return f'{float(v):.{digits}f}{unit}'
    except (TypeError, ValueError):
        return 'n/a'


ALERT_RULES = [
    # (name, test, advice)
    ('Low soil moisture', lambda r: r.get('soil_moisture_pct') is not None and r['soil_moisture_pct'] < 25,
     'Check root-zone moisture and consider watering.'),
    ('Frost risk', lambda r: r.get('temperature_c') is not None and r['temperature_c'] <= 2,
     'Temperature near freezing. Consider protecting sensitive crops.'),
    ('High heat', lambda r: r.get('temperature_c') is not None and r['temperature_c'] >= 35,
     'Watch for heat stress; check irrigation.'),
    ('Rain detected', lambda r: r.get('rain_wetness_pct') is not None and r['rain_wetness_pct'] >= 75,
     'Rain plate is wet. You may be able to skip watering.'),
]


def triggered(reading):
    return [(name, advice) for name, test, advice in ALERT_RULES if reading and test(reading)]


def alert_text(name, advice, r, demo=False):
    tag = ' [DEMO]' if demo else ''
    return (f'Cropaganda alert{tag}: {name}. Soil {fmt(r.get("soil_moisture_pct"), "%")}, '
            f'temp {fmt(r.get("temperature_c"), "C", 1)}, rain plate {fmt(r.get("rain_wetness_pct"), "%")}. '
            f'{advice} Reply STATUS for readings.')


def status_text(latest, label=''):
    if not latest:
        return 'Cropaganda: no sensor readings yet. Is the ESP32 online and paired?'
    when = str(latest.get('recorded_at', ''))[:16].replace('T', ' ')
    head = f'Cropaganda status{" - " + label if label else ""}'
    return (f'{head}\nTemp {fmt(latest.get("temperature_c"), "C", 1)} | Humidity {fmt(latest.get("humidity_pct"), "%")}\n'
            f'Soil moisture {fmt(latest.get("soil_moisture_pct"), "%")} | Rain plate {fmt(latest.get("rain_wetness_pct"), "%")}\n'
            f'Light {fmt(latest.get("light_pct"), "%")} | Pressure {fmt(latest.get("pressure_hpa"), " hPa")}\n'
            f'Reading at {when} UTC')


def task_line(t):
    return (t['kind'].title() + (f' {t["crop"]}' if t.get('crop') else '')
            + (f': {t["note"]}' if t.get('note') else ''))


def tasks_text(tasks, today):
    upcoming = [t for t in tasks if t['date'] >= today][:6]
    if not upcoming:
        return 'Cropaganda: no upcoming tasks on the farm calendar.'
    return 'Cropaganda upcoming tasks:\n' + '\n'.join(f'{t["date"][5:]}: {task_line(t)}' for t in upcoming)


def reminder_text(tasks_tomorrow):
    return 'Cropaganda reminder - tomorrow:\n' + '\n'.join('- ' + task_line(t) for t in tasks_tomorrow[:8])


HELP_TEXT = ('Cropaganda by text:\nSTATUS - latest field readings\nTASKS - upcoming calendar tasks\n'
             'Or text any farming question and Fieldy will answer.')


# ------------------------------------------------------------------ hooks used by other modules
def on_new_reading(owner, reading, previous):
    """Called by /api/device/ingest after a reading is saved. Texts only on a NEW crossing,
    so a dry field doesn't text every 5 minutes. Never raises (uploads must not fail)."""
    try:
        if not configured() or not farmer_numbers():
            return []
        link = read_link()
        if not link or link.get('owner') != owner:
            return []
        before = {name for name, _ in triggered(previous or {})}
        sent = []
        for name, advice in triggered(reading):
            if name not in before:
                sent += send_to_farmers(alert_text(name, advice, reading))
        return sent
    except Exception as exc:
        print('SMS alert failed:', type(exc).__name__, flush=True)
        return []


# ------------------------------------------------------------------ routes
class LinkRequest(BaseModel):
    location: dict = Field(default_factory=dict)
    calendar: list[dict] = Field(default_factory=list)


def _user(request: Request, allow_sample=False):
    try:
        user = request.session.get('user', {})
    except AssertionError:
        user = {}
    if not isinstance(user, dict) or not user.get('sub'):
        raise HTTPException(401, 'Please sign in to Cropaganda.')
    if user.get('mode') == 'auth0' and user.get('email'):
        return user
    if allow_sample and user.get('mode') == 'sample' and env('FIELDSHIFT_SMS_ALLOW_SAMPLE') == '1':
        return user
    raise HTTPException(403, 'Verified Auth0 login required for text messages')


def install_sms_routes(app, generate_gemini_reply, default_model, forecast):

    @app.get('/api/sms/status')
    def sms_status(request: Request):
        try:
            user = request.session.get('user', {})
        except AssertionError:
            user = {}
        link = read_link()
        return {'configured': configured(), 'from_number': mask(env('TWILIO_FROM_NUMBER')),
                'recipients': [mask(n) for n in farmer_numbers()],
                'linked': bool(link), 'linked_to_me': bool(link and link.get('owner') == user.get('sub')),
                'tasks_synced': len(link.get('calendar', [])) if link else 0,
                'cron_ready': bool(env('CRON_SECRET'))}

    @app.post('/api/sms/link')
    def sms_link(req: LinkRequest, request: Request):
        """Link the signed-in farm to the Cropaganda number and sync its location + calendar."""
        user = _user(request)
        link = read_link()
        if link and link.get('owner') != user['sub'] and not req.calendar and not req.location:
            raise HTTPException(409, 'Another account is linked')
        doc = {'owner': user['sub'], 'linked_at': datetime.now(timezone.utc).isoformat(),
               'location': clean_location(req.location), 'calendar': clean_tasks(req.calendar)}
        write_link(doc)
        return {'linked': True, 'tasks_synced': len(doc['calendar'])}

    @app.post('/api/sms/sync')
    def sms_sync(req: LinkRequest, request: Request):
        """Browser calls this after calendar/location changes, only if this account is linked."""
        user = _user(request)
        link = read_link()
        if not link or link.get('owner') != user['sub']:
            return {'synced': False}
        link['calendar'] = clean_tasks(req.calendar)
        link['location'] = clean_location(req.location) or link.get('location')
        write_link(link)
        return {'synced': True, 'tasks_synced': len(link['calendar'])}

    @app.post('/api/sms/test')
    def sms_test(request: Request):
        _user(request, allow_sample=True)
        return {'results': send_to_farmers('Cropaganda test: text messages are working!\n' + HELP_TEXT)}

    @app.post('/api/sms/demo-alert')
    def sms_demo_alert(request: Request):
        """Demo button: send an alert from the latest real reading, or a clearly-labeled demo reading."""
        user = _user(request, allow_sample=True)
        snap = read_snapshot(user['sub']) if user.get('mode') == 'auth0' else None
        latest = (snap or {}).get('latest')
        hits = triggered(latest) if latest else []
        if hits:
            name, advice = hits[0]
            return {'results': send_to_farmers(alert_text(name, advice, latest)), 'demo': False}
        sample = {'soil_moisture_pct': 18, 'temperature_c': 24.5, 'rain_wetness_pct': 4}
        name, advice = triggered(sample)[0]
        return {'results': send_to_farmers(alert_text(name, advice, sample, demo=True)), 'demo': True}

    @app.post('/api/sms/remind-now')
    def sms_remind_now(req: LinkRequest, request: Request):
        """Dashboard button: text tomorrow's tasks now (uses the browser's calendar)."""
        _user(request, allow_sample=True)
        tomorrow = (farm_today() + timedelta(days=1)).isoformat()
        tasks = [t for t in clean_tasks(req.calendar) if t['date'] == tomorrow]
        if not tasks:
            return {'results': [], 'message': f'No tasks on the calendar for tomorrow ({tomorrow}).'}
        return {'results': send_to_farmers(reminder_text(tasks))}

    @app.get('/api/sms/cron-reminders')
    def sms_cron(request: Request):
        """Vercel Cron calls this once a day (see vercel.json). Protected by CRON_SECRET."""
        secret = env('CRON_SECRET')
        if not secret or request.headers.get('authorization') != f'Bearer {secret}':
            raise HTTPException(401, 'Unauthorized')
        link = read_link()
        if not link or not configured() or not farmer_numbers():
            return {'sent': 0, 'reason': 'not linked or Twilio not configured'}
        tomorrow = (farm_today() + timedelta(days=1)).isoformat()
        tasks = [t for t in link.get('calendar', []) if t['date'] == tomorrow]
        if not tasks:
            return {'sent': 0, 'reason': f'no tasks for {tomorrow}'}
        return {'results': send_to_farmers(reminder_text(tasks))}

    @app.post('/api/twilio/sms')
    async def twilio_incoming(request: Request):
        """Twilio calls this when someone texts the Cropaganda number."""
        raw = await request.body()
        if len(raw) > 20000:
            raise HTTPException(413, 'Too large')
        from urllib.parse import parse_qsl
        form = dict(parse_qsl(raw.decode('utf-8', 'replace'), keep_blank_values=True))
        url = env('APP_BASE_URL').rstrip('/') + '/api/twilio/sms'
        token = env('TWILIO_AUTH_TOKEN')
        from twilio.request_validator import RequestValidator
        if not token or not RequestValidator(token).validate(url, form, request.headers.get('X-Twilio-Signature', '')):
            raise HTTPException(403, 'Invalid Twilio signature')

        sender, body = form.get('From', ''), (form.get('Body', '') or '').strip()
        if sender not in farmer_numbers():
            return twiml('This number is not registered with Cropaganda.')
        word = body.upper()
        if word in ('STOP', 'STOPALL', 'UNSUBSCRIBE', 'CANCEL', 'END', 'QUIT', 'START', 'UNSTOP'):
            return twiml(None)          # Twilio handles opt-out keywords
        if word in ('', 'HELP', 'INFO', '?'):
            return twiml(HELP_TEXT)

        link = read_link()
        if not link:
            return twiml('Cropaganda: no farm is linked yet. Sign in to the dashboard and press "Link my farm to texts".')
        snap = read_snapshot(link['owner'])
        latest = (snap or {}).get('latest')
        loc = link.get('location') or {}
        if word in ('STATUS', 'S', 'READINGS'):
            return twiml(status_text(latest, loc.get('label', '')))
        if word in ('TASKS', 'TASK', 'CALENDAR'):
            return twiml(tasks_text(link.get('calendar', []), farm_today().isoformat()))
        return twiml(ask_fieldy(body, latest, link, generate_gemini_reply, default_model, forecast))


def ask_fieldy(question, latest, link, generate_gemini_reply, default_model, forecast):
    """Gemini answer that fits inside Twilio's 15 s webhook limit."""
    key = env('GEMINI_API_KEY')
    if not key:
        return 'Fieldy is not set up yet (no Gemini key on the server).'
    loc = link.get('location') or {}
    upcoming = [t for t in link.get('calendar', []) if t['date'] >= farm_today().isoformat()][:10]
    pool = ThreadPoolExecutor(2)          # never "with": that would wait for slow calls
    weather = []
    if loc:
        try:
            weather = pool.submit(forecast, loc['latitude'], loc['longitude']).result(timeout=3.5)[:5]
        except Exception:
            weather = []
    context = {'location': loc, 'latest_esp32_reading': latest, 'forecast_next_days': weather,
               'upcoming_calendar_tasks': upcoming, 'today': farm_today().isoformat()}
    prompt = ("You are Fieldy, Cropaganda's farming assistant, replying by TEXT MESSAGE. "
              'Plain text only, no markdown or bullet symbols, at most 600 characters. '
              'Be practical and cautious; use only the data below, never invent weather warnings, '
              'soil chemistry or yields, and say so if data is missing. '
              f'Farmer question: {question[:500]}\nDATA: ' + json.dumps(context, default=str))
    try:
        # Twilio waits ~15 s for a reply; give Gemini 10 s of it.
        answer = pool.submit(generate_gemini_reply, key, prompt, default_model).result(timeout=10)
        return answer[:SMS_MAX]
    except Exception as exc:
        name = 'timeout' if type(exc).__name__ == 'TimeoutError' else type(exc).__name__
        return f'Fieldy could not answer right now ({name}). Please try again in a minute.'
    finally:
        pool.shutdown(wait=False)
