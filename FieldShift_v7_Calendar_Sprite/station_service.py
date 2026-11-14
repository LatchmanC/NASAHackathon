"""Local Pi 5 HTTP gateway. LAN demo only: use authentication + TLS before public deployment."""
from __future__ import annotations
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from fieldshift_core import (StationDB, SensorSimulator, utc_now, http_json,
                             make_location, fetch_nasa_power, demo_nasa_summary)
from intelligence import fetch_nasa_daily, demo_nasa_daily, official_alerts, demo_alerts, empty_alert_status, seed_demo_history

DEFAULT_DEVICE_TOKEN = os.getenv('FIELDSHIFT_DEVICE_TOKEN', 'local-demo-secret')
DEFAULT_CLOUD_TOKEN = os.getenv('FIELDSHIFT_CLOUD_TOKEN', 'cloud-demo-secret')


def make_handler(db, device_token):
    class StationHandler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            if os.getenv('FIELDSHIFT_DEBUG_HTTP') == '1':
                super().log_message(fmt, *args)

        def reply(self, code, value):
            body = json.dumps(value, allow_nan=False).encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def authorized(self):
            if self.headers.get('X-Device-Token') != device_token:
                self.reply(401, {'error': 'device token required'})
                return False
            return True

        def body_json(self):
            length = int(self.headers.get('Content-Length', 0))
            if length <= 0 or length > 1024*1024:
                raise ValueError('JSON payload must be 1–1048576 bytes')
            return json.loads(self.rfile.read(length).decode('utf-8'))

        def do_GET(self):
            url = urlparse(self.path)
            if url.path == '/health':
                return self.reply(200, {'service':'FieldShift Pi 5 gateway', 'status':'ok'})
            if not self.authorized():
                return
            try:
                if url.path == '/api/status':
                    return self.reply(200, {
                        'station':'FieldShift Pi 5 Gateway', 'latest':db.latest(),
                        'counts':db.counts(), 'location':db.get_setting('location'),
                        'nasa':db.get_setting('nasa'), 'outlook':db.get_setting('outlook'),
                        'nasa_daily_meta':{k:v for k,v in (db.get_setting('nasa_daily') or {}).items() if k!='rows'},
                        'alerts':db.get_setting('alerts',empty_alert_status()),
                        'farm':db.get_setting('farm',{'crop':'Tomato','growth_stage':'Vegetative'}),
                        'cloud_url':db.get_setting('cloud_url',''), 'time_utc':utc_now()})
                if url.path == '/api/nasa/daily':
                    return self.reply(200, {'nasa_daily':db.get_setting('nasa_daily')})
                if url.path == '/api/alerts':
                    return self.reply(200, {'alerts':db.get_setting('alerts',empty_alert_status())})
                if url.path == '/api/readings':
                    q = parse_qs(url.query)
                    rows = db.since(q.get('since_seq',['0'])[0], q.get('limit',['400'])[0])
                    return self.reply(200, {'readings':rows,'max_seq':max([r['seq'] for r in rows],default=0)})
                self.reply(404, {'error':'route not found'})
            except (ValueError, TypeError) as e:
                self.reply(400, {'error':str(e)})
            except Exception as e:
                self.reply(500, {'error':str(e)})

        def do_POST(self):
            if not self.authorized():
                return
            url = urlparse(self.path)
            try:
                data = self.body_json()
                if url.path == '/api/ingest':
                    added = db.save_reading(data)
                    return self.reply(200, {'stored': added, 'duplicate':not added,'id':data.get('id')})
                if url.path == '/api/location':
                    loc = make_location(data.get('mode'),data.get('label',''),data.get('latitude'),data.get('longitude'))
                    db.set_setting('location', loc)
                    db.set_setting('nasa',None) # avoid mixing data from previous location
                    db.set_setting('nasa_daily',None)
                    db.set_setting('alerts',empty_alert_status())
                    return self.reply(200, {'location':loc})
                if url.path == '/api/demo/history':
                    count=seed_demo_history(db)
                    return self.reply(200,{'new_synthetic_history_readings':count})
                if url.path == '/api/nasa/daily/demo':
                    demo=demo_nasa_daily(db.get_setting('location'))
                    db.set_setting('nasa_daily',demo)
                    return self.reply(200, {'nasa_daily':demo})
                if url.path == '/api/nasa/daily/fetch':
                    loc=db.get_setting('location')
                    daily=fetch_nasa_daily(loc,data.get('days',45))
                    if db.get_setting('location') != loc:
                        raise ValueError('Location changed during download; data discarded.')
                    db.set_setting('nasa_daily',daily)
                    return self.reply(200, {'nasa_daily':daily})
                if url.path == '/api/alerts/fetch':
                    loc=db.get_setting('location')
                    result=official_alerts(loc)
                    if db.get_setting('location') == loc:db.set_setting('alerts',result)
                    return self.reply(200, {'alerts':result})
                if url.path == '/api/alerts/demo':
                    result=demo_alerts(db.get_setting('location'))
                    db.set_setting('alerts',result)
                    return self.reply(200, {'alerts':result})
                if url.path == '/api/farm':
                    crop=str(data.get('crop',''))[:80].strip()
                    stage=str(data.get('growth_stage',''))[:80].strip()
                    info={'crop':crop or 'unspecified','growth_stage':stage or 'unknown'}
                    db.set_setting('farm',info)
                    return self.reply(200,{'farm':info})
                if url.path == '/api/nasa/demo':
                    demo = demo_nasa_summary(db.get_setting('location'))
                    db.set_setting('nasa',demo)
                    return self.reply(200, {'nasa':demo})
                if url.path == '/api/nasa/fetch':
                    summary = fetch_nasa_power(db.get_setting('location'), data.get('year'))
                    db.set_setting('nasa',summary)
                    return self.reply(200, {'nasa':summary})
                if url.path == '/api/outlook':
                    text = str(data.get('text','')).strip()
                    if not 1 <= len(text) <= 20000:
                        raise ValueError('Outlook text length invalid')
                    obj = {'text':text,'method':data.get('method','analysis'),
                           'model':str(data.get('model',''))[:100], 'created_at':utc_now()}
                    db.set_setting('outlook',obj)
                    return self.reply(200, {'outlook':obj})
                if url.path == '/api/cloud-url':
                    endpoint = str(data.get('url','')).strip()
                    if endpoint and not endpoint.startswith(('http://','https://')):
                        raise ValueError('Cloud endpoint must be an http(s) URL')
                    db.set_setting('cloud_url', endpoint)
                    return self.reply(200, {'cloud_url':endpoint})
                if url.path == '/api/sync':
                    result = db.sync_cloud(db.get_setting('cloud_url',''), DEFAULT_CLOUD_TOKEN)
                    return self.reply(200, result)
                self.reply(404, {'error':'route not found'})
            except (ValueError, TypeError, KeyError) as e:
                self.reply(400, {'error':str(e)})
            except Exception as e:
                self.reply(502, {'error':str(e)})
    return StationHandler


class StationEngine:
    def __init__(self, db=None, host='0.0.0.0', port=8765, simulator=True, interval=4, cloud_period=30):
        self.db = db or StationDB()
        self.server = ThreadingHTTPServer((host, port), make_handler(self.db, DEFAULT_DEVICE_TOKEN))
        self.host, self.port = host, self.server.server_port
        self.simulator = simulator
        self.interval, self.cloud_period = interval, cloud_period
        self.stop_event = threading.Event()
        self.threads = []
        self.last_error = ''
        self.last_sync = 'Not synchronized yet'

    def start(self):
        self._start_thread(self.server.serve_forever, 'ESP32 test receiver')
        if self.simulator:
            self._start_thread(self.simulate_loop, 'ESP32 internal simulator')
        self._start_thread(self.cloud_loop, 'Cloud sync background worker')
        if os.getenv('FIELDSHIFT_ALERTS_ENABLED','1') == '1':
            self._start_thread(self.alert_loop, 'Official NWS alert poller')
        return self

    def _start_thread(self, method, name):
        t = threading.Thread(target=method, name=name, daemon=True)
        t.start()
        self.threads.append(t)

    def simulate_loop(self):
        sim = SensorSimulator('esp32-simulator')
        url = f'http://127.0.0.1:{self.port}/api/ingest'
        while not self.stop_event.is_set():
            try:
                http_json('POST', url, sim.sample(), {'X-Device-Token':DEFAULT_DEVICE_TOKEN}, timeout=5)
                self.last_error = ''
            except Exception as e:
                self.last_error = f'Simulator: {e}'
            self.stop_event.wait(self.interval)

    def alert_loop(self):
        # Never show a demo warning as an official alert. Poll only after a successful position selection.
        while not self.stop_event.is_set():
            try:
                location=self.db.get_setting('location')
                if location:
                    result=official_alerts(location)
                    if self.db.get_setting('location')==location:
                        self.db.set_setting('alerts',result)
            except Exception as e:
                self.db.set_setting('alerts',{'status':'unavailable','alerts':[],
                                             'fetched_at':utc_now(),'message':'Unable to verify official alerts: '+str(e)})
            if self.stop_event.wait(300):break

    def cloud_loop(self):
        while not self.stop_event.wait(self.cloud_period):
            endpoint = self.db.get_setting('cloud_url','')
            if endpoint:
                try:
                    info = self.db.sync_cloud(endpoint, DEFAULT_CLOUD_TOKEN)
                    self.last_sync = str(info)
                except Exception as e:
                    self.last_sync = f'Cloud unavailable: {e}'

    def close(self):
        self.stop_event.set()
        self.server.shutdown()
        self.server.server_close()
