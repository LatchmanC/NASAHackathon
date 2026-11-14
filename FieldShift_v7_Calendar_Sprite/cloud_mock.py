"""Local-only simulated cloud SQL service. Replace with TigerData receiver later.

Accepts the *existing v3* Pi upload contract. Exposes authenticated read-only
endpoints for the web dashboard. Never expose this demo service to the Internet.
"""
from __future__ import annotations
import argparse
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

TOKEN = os.getenv('FIELDSHIFT_CLOUD_TOKEN', 'cloud-demo-secret')

@contextmanager
def cloud_db(path):
    conn=sqlite3.connect(path, timeout=15)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def setup(path):
    with cloud_db(path) as c:
        c.execute('CREATE TABLE IF NOT EXISTS cloud_readings (id TEXT PRIMARY KEY, recorded_at TEXT NOT NULL, payload TEXT NOT NULL)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_cloud_time ON cloud_readings(recorded_at DESC)')
        c.execute('CREATE TABLE IF NOT EXISTS station_context (key TEXT PRIMARY KEY, payload TEXT NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)')

def make_handler(db_path):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):
            if os.getenv('FIELDSHIFT_DEBUG_HTTP') == '1':
                super().log_message(*args)
        def reply(self, status, obj):
            body=json.dumps(obj).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Cache-Control','no-store')
            self.send_header('Content-Length',str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def auth(self):
            if self.headers.get('X-Sync-Token') != TOKEN:
                self.reply(401,{'error':'Cloud token required'})
                return False
            return True
        def do_GET(self):
            route=urlparse(self.path)
            if route.path=='/health':
                with cloud_db(db_path) as c:
                    total=c.execute('SELECT COUNT(*) FROM cloud_readings').fetchone()[0]
                    row=c.execute("SELECT value FROM meta WHERE key='last_upload'").fetchone()
                return self.reply(200,{'status':'ok','backend':'local cloud demo','stored':total,
                                       'last_synced_at':row[0] if row else None,'demo_only':True})
            if not self.auth():return
            try:
                if route.path=='/api/readings':
                    q=parse_qs(route.query)
                    limit=max(1,min(int(q.get('limit',['250'])[0]),2000))
                    offset=max(0,int(q.get('offset',['0'])[0]))
                    with cloud_db(db_path) as c:
                        rows=c.execute('SELECT payload FROM cloud_readings ORDER BY recorded_at DESC,id DESC LIMIT ? OFFSET ?',
                                       (limit,offset)).fetchall()
                        total=c.execute('SELECT COUNT(*) FROM cloud_readings').fetchone()[0]
                    return self.reply(200,{'readings':[json.loads(r[0]) for r in rows],
                                           'total':total,'limit':limit,'offset':offset})
                if route.path=='/api/latest':
                    with cloud_db(db_path) as c:
                        r=c.execute('SELECT payload FROM cloud_readings ORDER BY recorded_at DESC,id DESC LIMIT 1').fetchone()
                        last=c.execute("SELECT value FROM meta WHERE key='last_upload'").fetchone()
                    return self.reply(200,{'latest':json.loads(r[0]) if r else None,
                                           'last_synced_at':last[0] if last else None})
                if route.path=='/api/context':
                    with cloud_db(db_path) as c:
                        r=c.execute("SELECT payload FROM station_context WHERE key='current'").fetchone()
                    return self.reply(200,{'station_context':json.loads(r[0]) if r else None})
                return self.reply(404,{'error':'Not found'})
            except (TypeError,ValueError) as e:
                return self.reply(400,{'error':str(e)})
        def do_POST(self):
            if self.path != '/api/upload':return self.reply(404,{'error':'Not found'})
            if not self.auth():return
            try:
                length=int(self.headers.get('Content-Length','0'))
                if length < 2 or length > 1024*1024:raise ValueError('Payload size invalid')
                data=json.loads(self.rfile.read(length))
                rows=data.get('readings',[])
                context=data.get('station_context',{})
                if not isinstance(rows,list) or len(rows)>100:raise ValueError('Max 100 readings per batch')
                if not isinstance(context,dict):raise ValueError('station context must be an object')
                from fieldshift_core import validate_reading
                clean=[]
                for row in rows:
                    item=validate_reading(row)
                    if row.get('id') != item['id']:raise ValueError('Missing/invalid stable reading ID')
                    clean.append(item)
                with cloud_db(db_path) as c:
                    c.executemany('INSERT OR IGNORE INTO cloud_readings (id,recorded_at,payload) VALUES (?,?,?)',
                                  [(x['id'],x['recorded_at'],json.dumps(x)) for x in clean])
                    c.execute('INSERT OR REPLACE INTO station_context(key,payload) VALUES (?,?)',
                              ('current',json.dumps(context)))
                    c.execute('INSERT OR REPLACE INTO meta(key,value) VALUES (?,?)',
                              ('last_upload',datetime.now(timezone.utc).isoformat(timespec='seconds')))
                return self.reply(200,{'acknowledged_ids':[x['id'] for x in clean]})
            except (ValueError,KeyError,TypeError) as e:
                return self.reply(400,{'error':str(e)})
            except Exception as e:
                return self.reply(500,{'error':'Cloud storage failed: '+str(e)[:100]})
    return Handler

def create_cloud_server(port=8766,db_path=None,host='127.0.0.1'):
    path=Path(db_path or (Path(os.getenv('FIELDSHIFT_DATA_DIR',str(Path.home()/'.fieldshift_simple_v5'))) / 'cloud_test.sqlite'))
    path.parent.mkdir(parents=True,exist_ok=True)
    setup(path)
    return ThreadingHTTPServer((host,port),make_handler(str(path)))

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--port',type=int,default=8766)
    args=p.parse_args()
    s=create_cloud_server(port=args.port)
    print(f'Local cloud simulator at http://127.0.0.1:{args.port}',flush=True)
    try:s.serve_forever()
    except KeyboardInterrupt:pass
    finally:s.server_close()
