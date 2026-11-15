"""Cropoganda shared Python utilities. Python 3.10+; offline first."""
from __future__ import annotations
import json
from contextlib import contextmanager
import math
import os
import random
import sqlite3
import statistics
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
import ssl
from urllib.parse import urlencode
from urllib.request import Request, urlopen

APP_DIR = Path(os.getenv('FIELDSHIFT_DATA_DIR', str(Path.home() / '.fieldshift_simple_v5')))
DB_PATH = APP_DIR / 'pi5_station.sqlite'
MEASURES = [
    ('temperature_c', 'Air temperature', '°C'),
    ('humidity_pct', 'Humidity', '%'),
    ('pressure_hpa', 'Atmospheric pressure', 'hPa'),
    ('altitude_m', 'Approx. altitude', 'm'),
    ('rain_wetness_pct', 'Rain sensor wetness', '%'),
    ('light_pct', 'Light sensor index', '%'),
    ('gas_index', 'Gas sensor index', '/100'),
    ('soil_moisture_pct', 'Soil moisture index', '%'),
]
VALUE_FIELDS = [x[0] for x in MEASURES]
NASA_URL = 'https://power.larc.nasa.gov/api/temporal/daily/point'
GEO_URL = 'https://geocoding-api.open-meteo.com/v1/search'


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def http_json(method: str, url: str, data=None, headers=None, timeout=12):
    blob = json.dumps(data).encode('utf-8') if data is not None else None
    hdr = {'Accept': 'application/json'}
    if blob is not None:
        hdr['Content-Type'] = 'application/json'
    hdr.update(headers or {})
    req = Request(url=url, data=blob, method=method, headers=hdr)
    # Use verified HTTPS with OS trust roots (truststore), then certifi fallback.
    # Never use unverified contexts, even if geocoding/NASA fails.
    tls_context = None
    if url.lower().startswith('https://'):
        try:
            import truststore
            tls_context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        except ImportError:
            try:
                import certifi
                tls_context = ssl.create_default_context(cafile=certifi.where())
            except ImportError:
                tls_context = ssl.create_default_context()
    try:
        with urlopen(req, timeout=timeout, **({'context':tls_context} if tls_context else {})) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except HTTPError as ex:
        body = ex.read(800).decode('utf-8', errors='replace')
        raise RuntimeError(f'{ex.code} {ex.reason}: {body}') from ex
    except (URLError, ssl.SSLError) as ex:
        if 'CERTIFICATE_VERIFY_FAILED' in str(ex) or 'certificate verify failed' in str(ex):
            raise RuntimeError('HTTPS certificate verification failed. Install/update truststore and certifi '
                '(python -m pip install -U truststore certifi); on macOS also check Python Install Certificates. '
                'If behind an organization proxy, ask IT to install the trusted root CA. '
                'Certificate verification remains enabled.') from ex
        raise RuntimeError(f'Network connection failed: {str(ex)[:180]}') from ex


def valid_lat_lon(lat, lon):
    a, b = float(lat), float(lon)
    if not (math.isfinite(a) and math.isfinite(b) and -90 <= a <= 90 and -180 <= b <= 180):
        raise ValueError('Latitude must be -90 to 90, longitude -180 to 180.')
    return round(a, 6), round(b, 6)


def geocode(place: str):
    place = place.strip()
    if len(place) < 2:
        raise ValueError('Enter a city, town or region name.')
    body = http_json('GET', GEO_URL + '?' + urlencode({'name': place, 'count': 5, 'language': 'en', 'format': 'json'}), timeout=18)
    found = body.get('results', [])
    if not found:
        raise ValueError('No matching location. Enter coordinates instead.')
    # The first match is only an approximation: show it to the user.
    best = found[0]
    area = ', '.join(str(best.get(k)) for k in ('name', 'admin1', 'country') if best.get(k))
    lat, lon = valid_lat_lon(best['latitude'], best['longitude'])
    return {'mode': 'area', 'label': area, 'latitude': lat, 'longitude': lon, 'resolution': 'approximate city/region center'}


def make_location(mode, label='', latitude=None, longitude=None):
    if mode == 'area':
        return geocode(label)
    if mode == 'preset':
        lat, lon = valid_lat_lon(latitude, longitude)
        clean = str(label).strip()
        if not (2 <= len(clean) <= 160):
            raise ValueError('Choose a valid location preset.')
        return {'mode':'preset', 'label':clean, 'latitude':lat, 'longitude':lon,
                'resolution':'approximate city center (use coordinates for farm-level accuracy)'}
    if mode == 'coords':
        lat, lon = valid_lat_lon(latitude, longitude)
        return {'mode': 'coords', 'label': f'Coordinates ({lat:.5f}, {lon:.5f})', 'latitude': lat, 'longitude': lon, 'resolution': 'user-specified coordinates'}
    raise ValueError('Choose area or coords.')


class StationDB:
    def __init__(self, path=DB_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._setup()

    @contextmanager
    def _connect(self):
        c = sqlite3.connect(str(self.path), timeout=15)
        try:
            c.row_factory = sqlite3.Row
            c.execute('PRAGMA busy_timeout = 10000')
            c.execute('PRAGMA journal_mode = WAL')
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    def _setup(self):
        with self._connect() as c:
            c.executescript('''
                CREATE TABLE IF NOT EXISTS readings (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    id TEXT UNIQUE NOT NULL,
                    device_id TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    source TEXT NOT NULL,
                    temperature_c REAL, humidity_pct REAL, pressure_hpa REAL,
                    altitude_m REAL, rain_wetness_pct REAL, light_pct REAL,
                    gas_index REAL, soil_moisture_pct REAL,
                    cloud_synced INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_readings_time ON readings(recorded_at);
                CREATE INDEX IF NOT EXISTS idx_readings_cloud ON readings(cloud_synced, seq);
                CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            ''')
            if not c.execute("SELECT 1 FROM settings WHERE key = 'location'").fetchone():
                sample = {'mode': 'coords', 'label': 'DEMO location — New York City',
                          'latitude': 40.7128, 'longitude': -74.0060,
                          'resolution': 'sample coordinates; change before actual deployment'}
                c.execute('INSERT INTO settings(key,value) VALUES (?,?)', ('location', json.dumps(sample)))

    def set_setting(self, key, value):
        with self._connect() as c:
            c.execute('INSERT OR REPLACE INTO settings(key,value) VALUES (?,?)', (key, json.dumps(value)))

    def get_setting(self, key, default=None):
        with self._connect() as c:
            r = c.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
            return json.loads(r['value']) if r else default

    def save_reading(self, reading):
        clean = validate_reading(reading)
        columns = ['id', 'device_id', 'recorded_at', 'source'] + VALUE_FIELDS
        with self._connect() as c:
            result = c.execute(
                'INSERT OR IGNORE INTO readings(' + ','.join(columns) + ') VALUES (' + ','.join('?' for _ in columns) + ')',
                [clean.get(k) for k in columns]
            )
        return result.rowcount == 1

    def latest(self):
        with self._connect() as c:
            row = c.execute('SELECT * FROM readings ORDER BY seq DESC LIMIT 1').fetchone()
            return dict(row) if row else None

    def recent(self, limit=100):
        with self._connect() as c:
            rows = c.execute('SELECT * FROM readings ORDER BY seq DESC LIMIT ?', (min(int(limit), 100000),)).fetchall()
        return [dict(r) for r in rows]

    def since(self, since_seq=0, limit=400):
        with self._connect() as c:
            rows = c.execute('SELECT * FROM readings WHERE seq > ? ORDER BY seq LIMIT ?',
                             (max(0, int(since_seq)), min(int(limit), 1000))).fetchall()
        return [dict(r) for r in rows]

    def pending(self, limit=100):
        with self._connect() as c:
            rows = c.execute('SELECT * FROM readings WHERE cloud_synced=0 ORDER BY seq LIMIT ?', (limit,)).fetchall()
        return [dict(r) for r in rows]

    def ack_cloud(self, ids):
        if ids:
            with self._connect() as c:
                c.executemany('UPDATE readings SET cloud_synced=1 WHERE id=?', [(i,) for i in ids])

    def counts(self):
        with self._connect() as c:
            r = c.execute('SELECT COUNT(*) AS total, SUM(CASE WHEN cloud_synced=0 THEN 1 ELSE 0 END) AS pending FROM readings').fetchone()
        return {'total': r['total'], 'pending_cloud': r['pending'] or 0}

    def sync_cloud(self, endpoint, token):
        if not endpoint:
            return {'status': 'not_configured', 'uploaded': 0}
        if not endpoint.startswith(('http://','https://')):
            raise ValueError('Cloud URL must begin with http:// or https://')
        pending = self.pending()
        if not pending:
            return {'status': 'up_to_date', 'uploaded': 0}
        headers = {'X-Sync-Token': token}
        reply = http_json('POST', endpoint.rstrip('/') + '/api/upload',
                          data={'readings': pending, 'station_context': {
                              'location': self.get_setting('location'),
                              'nasa': self.get_setting('nasa'),
                              'outlook': self.get_setting('outlook')}}, headers=headers, timeout=20)
        ack = reply.get('acknowledged_ids', [])
        sent = {r['id'] for r in pending}
        if not isinstance(ack, list) or not set(ack).issubset(sent):
            raise ValueError('Invalid cloud acknowledgement: nothing marked synced.')
        self.ack_cloud(ack)
        return {'status': 'ok', 'uploaded': len(ack), 'remaining': self.counts()['pending_cloud']}


def validate_reading(data):
    if not isinstance(data, dict):
        raise ValueError('Reading must be an object.')
    result = {}
    rid = data.get('id') or str(uuid.uuid4())
    if not isinstance(rid, str) or not (8 <= len(rid) <= 100):
        raise ValueError('Invalid reading ID.')
    result['id'] = rid
    result['device_id'] = str(data.get('device_id', 'esp32-001'))[:80]
    ts = str(data.get('recorded_at') or utc_now())
    parsed = datetime.fromisoformat(ts.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Timestamp must include a timezone.')
    result['recorded_at'] = ts
    src = data.get('source', 'esp32')
    if src not in ('esp32', 'simulated_esp32'):
        raise ValueError('Source must be esp32 or simulated_esp32.')
    result['source'] = src
    ranges = {'temperature_c':(-50,85),'humidity_pct':(0,100), 'pressure_hpa':(300,1200),
              'altitude_m':(-500,9000), 'rain_wetness_pct':(0,100), 'light_pct':(0,100),
              'gas_index':(0,100),'soil_moisture_pct':(0,100)}
    for k, (lo, hi) in ranges.items():
        value = data.get(k)
        if value is None:
            result[k] = None
            continue
        v = float(value)
        if not math.isfinite(v) or not lo <= v <= hi:
            raise ValueError(f'{k} must be between {lo} and {hi}.')
        result[k] = round(v, 3)
    if all(result[k] is None for k in VALUE_FIELDS):
        raise ValueError('At least one sensor value must be present.')
    return result


class SensorSimulator:
    """Synthetic data with light/temperature cycles and an occasional rain event."""
    def __init__(self, device_id='esp32-sim-001', seed=17):
        self.device_id = device_id
        self.rng = random.Random(seed)
        self.n = 0
        self.soil = 47.0
        self.pressure = 1014.0

    def sample(self):
        self.n += 1
        cyc = math.sin(self.n / 24.0)
        rain_event = 23 <= (self.n % 135) <= 35
        self.soil += (1.25 if rain_event else -0.13) + self.rng.uniform(-0.5, 0.5)
        self.soil = max(15, min(90, self.soil))
        self.pressure += self.rng.uniform(-0.14, 0.06)
        light = max(0, min(100, 58 + 35 * math.sin(self.n / 40.0) + self.rng.uniform(-3, 3)))
        rain = (65 + self.rng.uniform(-6, 8)) if rain_event else max(0, self.rng.uniform(0, 10))
        # Altitude is a pressure-derived ESTIMATE using an assumed sea-level reference.
        altitude = 44330.0 * (1.0 - (self.pressure / 1013.25) ** 0.1903)
        return validate_reading({
            'id': str(uuid.uuid4()), 'device_id': self.device_id, 'recorded_at': utc_now(),
            'source': 'simulated_esp32',
            'temperature_c': round(23.2 + 3.8 * cyc + self.rng.uniform(-0.3, 0.3), 2),
            'humidity_pct': round(max(20, min(99, 55 - 9 * cyc + (16 if rain_event else 0) + self.rng.uniform(-2, 2))), 2),
            'pressure_hpa': round(self.pressure, 2), 'altitude_m': round(altitude, 1),
            'rain_wetness_pct': round(rain, 1), 'light_pct': round(light, 1),
            'gas_index': round(max(1, min(95, 20 + 4 * math.sin(self.n / 15) + self.rng.uniform(-2, 2))), 1),
            'soil_moisture_pct': round(self.soil, 1),
        })


def demo_nasa_summary(location):
    """Explicitly synthetic fixture; NEVER represent as real NASA observations."""
    return {
        'source': 'DEMO_SYNTHETIC_NOT_NASA', 'is_real_nasa': False,
        'latitude': location['latitude'], 'longitude': location['longitude'],
        'period': 'synthetic reference year, not a real date range',
        'days': 365, 'mean_temperature_c': 16.2, 'total_rain_mm': 1080.0,
        'mean_humidity_pct': 67.1, 'mean_solar_mj_m2_day': 13.1,
        'description': 'Illustrative climate values ONLY, not returned by NASA POWER.'
    }


def fetch_nasa_power(location, year=None):
    """Actual NASA POWER historical measurements; network required."""
    # Using last COMPLETE calendar year improves reproducibility and avoids near-real-time gaps.
    y = int(year or (datetime.now(timezone.utc).year - 1))
    if not 1981 <= y <= datetime.now(timezone.utc).year:
        raise ValueError('NASA POWER year out of range')
    params = {'community':'AG', 'latitude':location['latitude'], 'longitude':location['longitude'],
              'parameters':'T2M,PRECTOTCORR,RH2M,ALLSKY_SFC_SW_DWN', 'start':f'{y}0101',
              'end':f'{y}1231', 'format':'JSON', 'time-standard':'UTC'}
    data = http_json('GET', NASA_URL + '?' + urlencode(params), timeout=80)
    series = data['properties']['parameter']
    def valid_values(key):
        values = []
        for v in series.get(key, {}).values():
            try:
                v = float(v)
                if math.isfinite(v) and v > -900:
                    values.append(v)
            except (ValueError, TypeError):
                pass
        return values
    temp = valid_values('T2M')
    rain = valid_values('PRECTOTCORR')
    humidity = valid_values('RH2M')
    solar = valid_values('ALLSKY_SFC_SW_DWN')
    if len(temp) < 300 or len(rain) < 300:
        raise ValueError('NASA returned too few usable days. Try a different year.')
    return {'source':'NASA POWER Daily API', 'is_real_nasa':True,
            'latitude':location['latitude'], 'longitude':location['longitude'],
            'period':f'{y}-01-01 through {y}-12-31 (historical, not a forecast)',
            'days':len(temp), 'mean_temperature_c':round(statistics.mean(temp),2),
            'total_rain_mm':round(sum(rain),1),
            'mean_humidity_pct':round(statistics.mean(humidity),1) if humidity else None,
            'mean_solar_mj_m2_day':round(statistics.mean(solar),2) if solar else None,
            'description':'Regional historical climate estimates; spatial scale differs from field sensor.'}


def trend_and_signals(recent, nasa):
    """Offline, clearly non-forecast assessment if no Gemini key/network."""
    if not recent:
        return 'No readings available. Start the simulator or connect an ESP32.'
    newest = recent[0]
    notes = []
    def v(k): return newest.get(k)
    if v('rain_wetness_pct') is not None:
        notes.append('Rain plate is currently wet; this is NOT rainfall amount.' if v('rain_wetness_pct') > 45 else 'Rain plate currently appears dry.')
    if v('soil_moisture_pct') is not None:
        notes.append('Soil moisture index is low.' if v('soil_moisture_pct') < 30 else 'Soil moisture index is moderate/high (sensor-specific calibration needed).')
    if v('pressure_hpa') is not None and len(recent) >= 8:
        older = recent[-1].get('pressure_hpa')
        if older is not None:
            delta = v('pressure_hpa') - older
            notes.append(f'Pressure changed {delta:+.1f} hPa across the displayed recent samples. A short trend is not a reliable forecast.')
    if nasa:
        notes.append(('Real NASA historical context' if nasa.get('is_real_nasa') else 'SIMULATED climate context') + f": mean temperature {nasa.get('mean_temperature_c')} °C, annual precipitation {nasa.get('total_rain_mm')} mm.")
    notes.append('No deterministic short-range forecast is possible from these readings alone. For reliable rain/temperature forecasts, integrate an operational forecast feed.')
    return '\n\n'.join('• ' + x for x in notes)


def gemini_weather_outlook(readings, nasa, location, api_key, model='gemini-3.5-flash-lite', question='Give a cautious 0–6 hour weather risk outlook for this field.'):
    """Use the Gemini API only when a key is provided; data is sent to Google."""
    if not api_key:
        raise ValueError('Enter a Gemini API key or set GEMINI_API_KEY.')
    if not readings:
        raise ValueError('No sensor data yet.')
    payload = {
        'location': location,
        'recent_sensor_readings_oldest_to_newest': [
            {k: r.get(k) for k in ('recorded_at','source',*VALUE_FIELDS)} for r in readings[:20][::-1]
        ],
        'nasa_context': nasa if nasa else 'No NASA POWER data available (do not invent it).',
        'user_request': question[:600]
    }
    prompt = '''You are Cropoganda, a cautious agricultural weather-risk ANALYST, not an operational weather forecasting service.
Data is JSON below. Explain possible near-term signals (next 0–6 hours) in plain language.
1. Separate OBSERVED sensor values, NASA HISTORICAL context, and INFERENCES.
2. Explicitly state that NASA POWER historical data is NOT a short-term forecast.
3. If nasa_context.is_real_nasa is false, identify it as SYNTHETIC TEST DATA; never cite it as observed NASA data.
4. Do not invent probabilities, rain timing, 6-hour temperatures, storms, model outputs, or physical measurements.
5. Rain sensor value is a WETNESS INDEX, not precipitation amount. Gas index is UNCALIBRATED, not a safe/unsafe gas concentration. Soil moisture is a calibration-dependent index. Altitude is calculated from pressure and not independent evidence.
6. Offer no more than 3 practical agriculture monitoring suggestions. Include an uncertainty/limitation section.
7. If available evidence is weak, explicitly say no reliable short-range weather prediction can be made.
Return sections: Current conditions; Potential signals; Historical NASA context; Limits/uncertainty; Suggested next checks.
JSON INPUT:\n''' + json.dumps(payload, separators=(',',':'))
    from gemini_client import generate_gemini_reply
    return generate_gemini_reply(api_key, prompt, model)
