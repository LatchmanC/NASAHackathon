#!/usr/bin/env python3
"""Optional TigerData cloud receiver using same /api/upload payload as the local SQLite demo.

Must sit behind a hardened HTTPS reverse proxy with proper auth, rate limits, TLS
and secure secrets before deployment. Localhost binding by default.
"""
import argparse
import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timezone

TOKEN=os.getenv('FIELDSHIFT_CLOUD_TOKEN','')
DATABASE_URL=os.getenv('TIGER_DATABASE_URL','')


def store_batch(readings, context):
    if not DATABASE_URL:
        raise RuntimeError('TIGER_DATABASE_URL has not been set')
    try:import psycopg
    except ImportError as e:
        raise RuntimeError('psycopg not installed. Run: pip install "psycopg[binary]"') from e
    from fieldshift_core import validate_reading
    # Normalize and validate all records before starting a database transaction.
    clean=[]
    for raw in readings:
        r=validate_reading(raw)
        if raw['id']!=r['id']:raise ValueError('Missing reading ID: refusing non-idempotent cloud write')
        clean.append(r)
    columns=['recorded_at','id','device_id','source','temperature_c','humidity_pct',
             'pressure_hpa','altitude_m','rain_wetness_pct','light_pct','gas_index','soil_moisture_pct']
    values=[tuple(r.get(col) for col in columns) for r in clean]
    sql='''INSERT INTO sensor_readings
      (recorded_at, reading_id, device_id, source, temperature_c, humidity_pct,
       pressure_hpa, altitude_m, rain_wetness_pct, light_pct, gas_index, soil_moisture_pct)
      VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
      ON CONFLICT (recorded_at, reading_id) DO NOTHING'''
    with psycopg.connect(DATABASE_URL,connect_timeout=12) as conn:
        with conn.cursor() as cur:
            if values:cur.executemany(sql,values)
            cur.execute('''INSERT INTO station_context(station_id, context_json, updated_at)
                VALUES (%s, %s::jsonb, now()) ON CONFLICT(station_id)
                DO UPDATE SET context_json=EXCLUDED.context_json, updated_at=now()''',
                ('fieldshift-pi5',json.dumps(context)))
    return [r['id'] for r in clean]


def query_cloud(limit=250,offset=0,latest_only=False):
    if not DATABASE_URL:
        raise RuntimeError('TIGER_DATABASE_URL missing')
    import psycopg
    cols='recorded_at, reading_id, device_id, source, temperature_c, humidity_pct, pressure_hpa, altitude_m, rain_wetness_pct, light_pct, gas_index, soil_moisture_pct'
    with psycopg.connect(DATABASE_URL, connect_timeout=12) as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT COUNT(*) FROM sensor_readings')
            total=cur.fetchone()[0]
            cur.execute(f'SELECT {cols} FROM sensor_readings ORDER BY recorded_at DESC, reading_id DESC LIMIT %s OFFSET %s', (1 if latest_only else limit, 0 if latest_only else offset))
            labels=['recorded_at','id','device_id','source','temperature_c','humidity_pct','pressure_hpa','altitude_m','rain_wetness_pct','light_pct','gas_index','soil_moisture_pct']
            rows=[]
            for row in cur.fetchall():
                record=dict(zip(labels,row))
                record['recorded_at']=record['recorded_at'].isoformat()
                rows.append(record)
            cur.execute('SELECT MAX(updated_at) FROM station_context')
            timestamp=cur.fetchone()[0]
    return rows,total,timestamp.isoformat() if timestamp else None


class Handler(BaseHTTPRequestHandler):
    def respond(self,status,data):
        blob=json.dumps(data).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(blob)))
        self.send_header('Cache-Control','no-store')
        self.end_headers();self.wfile.write(blob)
    def do_GET(self):
        route=urlparse(self.path)
        if route.path=='/health':
            return self.respond(200,{'status':'ok','backend':'TigerData','database_configured':bool(DATABASE_URL)})
        if not TOKEN or not hmac.compare_digest(self.headers.get('X-Sync-Token',''),TOKEN):
            return self.respond(401,{'error':'not authorized'})
        try:
            if route.path=='/api/latest':
                rows,total,synced=query_cloud(latest_only=True)
                return self.respond(200,{'latest':rows[0] if rows else None,'last_synced_at':synced,'stored':total})
            if route.path=='/api/readings':
                q=parse_qs(route.query)
                limit=max(1,min(2000,int(q.get('limit',['250'])[0])))
                offset=max(0,int(q.get('offset',['0'])[0]))
                rows,total,synced=query_cloud(limit,offset)
                return self.respond(200,{'readings':rows,'total':total,'limit':limit,'offset':offset})
            return self.respond(404,{'error':'not found'})
        except (TypeError,ValueError) as e:
            return self.respond(400,{'error':str(e)})
        except Exception as e:
            print('TigerData query failed:',str(e)[:150],flush=True)
            return self.respond(503,{'error':'TigerData query unavailable'})
    def do_POST(self):
        if self.path!='/api/upload':return self.respond(404,{'error':'not found'})
        if not TOKEN or not hmac.compare_digest(self.headers.get('X-Sync-Token',''),TOKEN):
            return self.respond(401,{'error':'not authorized'})
        try:
            length=int(self.headers.get('Content-Length','0'))
            if length<2 or length>1048576:raise ValueError('Payload size invalid')
            incoming=json.loads(self.rfile.read(length))
            readings=incoming.get('readings',[])
            context=incoming.get('station_context',{})
            if not isinstance(readings,list) or len(readings)>100:raise ValueError('Maximum 100 records per batch')
            if not isinstance(context,dict):raise ValueError('station_context must be an object')
            ids=store_batch(readings,context)
            self.respond(200,{'acknowledged_ids':ids})
        except (ValueError,TypeError,KeyError) as e:self.respond(400,{'error':str(e)})
        except Exception as e:
            print('TigerData upload failed:',repr(e),flush=True)
            self.respond(503,{'error':'Database unavailable or not configured. Pi will retry later.'})


def main():
    p=argparse.ArgumentParser(description='TigerData receiver (localhost demo; deploy behind HTTPS)')
    p.add_argument('--host',default='127.0.0.1')
    p.add_argument('--port',type=int,default=8780)
    args=p.parse_args()
    if not TOKEN:raise SystemExit('Set a strong FIELDSHIFT_CLOUD_TOKEN before starting')
    print('TigerData receiver at http://%s:%d'%(args.host,args.port),flush=True)
    srv=ThreadingHTTPServer((args.host,args.port),Handler)
    try:srv.serve_forever()
    except KeyboardInterrupt:pass
    finally:srv.server_close()

if __name__=='__main__':main()
