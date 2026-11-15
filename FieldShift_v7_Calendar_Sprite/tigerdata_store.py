"""Cropoganda TigerData/TimescaleDB persistence.
Live rows update on every accepted ESP32 upload; historical rows are recorded
only once per ten-minute UTC bucket. Never expose database credentials to JS.
Install sql/cropoganda_tigerdata.sql before setting TIGERDATA_DATABASE_URL.
"""
from __future__ import annotations
import hashlib
import os
import secrets
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

HISTORY_ZONE=ZoneInfo('America/New_York')

def _eastern_bounds(day):
    d=_day(day)
    start=datetime(d.year,d.month,d.day,tzinfo=HISTORY_ZONE).astimezone(timezone.utc)
    following=d+timedelta(days=1)
    stop=datetime(following.year,following.month,following.day,tzinfo=HISTORY_ZONE).astimezone(timezone.utc)
    return start,stop
from fastapi import HTTPException

def enabled():
    return bool(os.getenv('TIGERDATA_DATABASE_URL','').strip())

def _key(owner):
    if not isinstance(owner,str) or not owner or len(owner)>300:
        raise ValueError('Invalid account')
    return hashlib.sha256(owner.encode('utf-8')).hexdigest()

def _connection():
    if not enabled():
        raise HTTPException(503,'TigerData is not configured')
    try:
        import psycopg
        return psycopg.connect(os.environ['TIGERDATA_DATABASE_URL'],connect_timeout=6,sslmode='require')
    except Exception as exc:
        raise HTTPException(503,'Could not connect to TigerData') from exc

def _json(v):
    import json
    return json.loads(v) if isinstance(v,(str,bytes)) else v

def live_snapshot(owner):
    key=_key(owner)
    try:
        with _connection() as conn, conn.cursor() as cur:
            cur.execute("""SELECT l.device_id,l.observed_at,l.readings,
                                  COALESCE(s.version,'v1')
                           FROM cropoganda_live l
                           LEFT JOIN cropoganda_share_state s ON l.account_key=s.account_key
                           WHERE l.account_key=%s""",(key,))
            latest=cur.fetchone()
            if not latest:return None
            cur.execute("""SELECT readings FROM cropoganda_sensor_history
                           WHERE account_key=%s ORDER BY bucket_at DESC LIMIT 72""",(key,))
            rows=[_json(row[0]) for row in cur.fetchall()]
        return {'schema':1,'latest':_json(latest[2]),'last_updated':latest[1].isoformat(),
                'readings':rows,'share_version':latest[3]}
    except HTTPException:raise
    except Exception as exc:
        raise HTTPException(503,'TigerData live readings unavailable; run the SQL schema setup') from exc

def record(owner,reading):
    from psycopg.types.json import Jsonb
    key=_key(owner)
    raw=datetime.fromisoformat(reading['recorded_at'].replace('Z','+00:00'))
    recorded=raw.astimezone(timezone.utc)
    bucket=datetime.fromtimestamp(int(recorded.timestamp())//600*600,tz=timezone.utc)
    try:
        with _connection() as conn, conn.cursor() as cur:
            cur.execute("""INSERT INTO cropoganda_live(account_key,device_id,observed_at,readings)
                           VALUES (%s,%s,%s,%s)
                           ON CONFLICT(account_key) DO UPDATE
                           SET device_id=EXCLUDED.device_id,observed_at=EXCLUDED.observed_at,
                               readings=EXCLUDED.readings
                           WHERE cropoganda_live.observed_at <= EXCLUDED.observed_at""",
                        (key,reading['device_id'],recorded,Jsonb(reading)))
            # The first real ESP32 reading received in each 10-minute window is retained.
            cur.execute("""INSERT INTO cropoganda_sensor_history
                           (account_key,bucket_at,observed_at,device_id,readings)
                           VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                        (key,bucket,recorded,reading['device_id'],Jsonb(reading)))
            cur.execute("""INSERT INTO cropoganda_share_state(account_key,version)
                           VALUES (%s,'v1') ON CONFLICT DO NOTHING""",(key,))
        return {'schema':1,'latest':reading,'last_updated':reading['recorded_at'],
                'readings':[reading],'share_version':'v1'}
    except HTTPException:raise
    except Exception as exc:
        raise HTTPException(503,'Could not save ESP32 reading to TigerData') from exc

def new_share_version(owner):
    version=secrets.token_urlsafe(18)
    try:
        with _connection() as conn, conn.cursor() as cur:
            cur.execute("""INSERT INTO cropoganda_share_state(account_key,version)
                           VALUES (%s,%s) ON CONFLICT(account_key) DO UPDATE
                           SET version=EXCLUDED.version""",(_key(owner),version))
        return version
    except HTTPException:raise
    except Exception as exc:
        raise HTTPException(503,'Could not revoke shared access in TigerData') from exc

def available_dates(owner):
    """Only show dates with actual archived ESP32 measurements."""
    try:
        with _connection() as conn,conn.cursor() as cur:
            cur.execute("""SELECT DISTINCT (bucket_at AT TIME ZONE 'America/New_York')::date AS day
                           FROM cropoganda_sensor_history WHERE account_key=%s
                           ORDER BY day DESC LIMIT 1200""",(_key(owner),))
            return [row[0].isoformat() for row in cur.fetchall()]
    except HTTPException:raise
    except Exception as exc:
        raise HTTPException(503,'Could not list saved TigerData dates') from exc

def dates(owner,year,month):
    if not (2020<=year<=2100 and 1<=month<=12):
        raise HTTPException(400,'Invalid month')
    start,_=_eastern_bounds(f'{year:04d}-{month:02d}-01')
    if month==12:
        stop,_=_eastern_bounds(f'{year+1:04d}-01-01')
    else:
        stop,_=_eastern_bounds(f'{year:04d}-{month+1:02d}-01')
    try:
        with _connection() as conn,conn.cursor() as cur:
            cur.execute("""SELECT (bucket_at AT TIME ZONE 'America/New_York')::date,count(*)
                           FROM cropoganda_sensor_history
                           WHERE account_key=%s AND bucket_at>=%s AND bucket_at<%s
                           GROUP BY 1 ORDER BY 1""",(_key(owner),start,stop))
            return [{'date':d.isoformat(),'count':c} for d,c in cur.fetchall()]
    except HTTPException:raise
    except Exception as exc:raise HTTPException(503,'Could not load TigerData dates') from exc

def times(owner,day):
    start,stop=_eastern_bounds(day)
    try:
        with _connection() as conn,conn.cursor() as cur:
            cur.execute("""SELECT bucket_at,observed_at,device_id
                           FROM cropoganda_sensor_history
                           WHERE account_key=%s AND bucket_at>=%s AND bucket_at<%s
                           ORDER BY bucket_at""",(_key(owner),start,stop))
            return [{'bucket_at':b.isoformat(),'recorded_at':o.isoformat(),'device_id':dev}
                    for b,o,dev in cur.fetchall()]
    except HTTPException:raise
    except Exception as exc:raise HTTPException(503,'Could not load TigerData snapshots') from exc

def archived_reading(owner,day,bucket):
    _day(day)
    try:
        b=datetime.fromisoformat(bucket.replace('Z','+00:00')).astimezone(timezone.utc)
    except (ValueError,TypeError,AttributeError) as exc:
        raise HTTPException(400,'Invalid snapshot time') from exc
    if b.astimezone(HISTORY_ZONE).date().isoformat()!=day:
        raise HTTPException(400,'Snapshot time does not match selected date')
    try:
        with _connection() as conn,conn.cursor() as cur:
            cur.execute("""SELECT readings FROM cropoganda_sensor_history
                           WHERE account_key=%s AND bucket_at=%s""",(_key(owner),b))
            found=cur.fetchone()
        return _json(found[0]) if found else None
    except HTTPException:raise
    except Exception as exc:raise HTTPException(503,'Could not load selected sensor snapshot') from exc

def _day(s):
    try:
        d=datetime.strptime(s,'%Y-%m-%d').date()
        if not (2020<=d.year<=2100):raise ValueError('Invalid year')
        return d
    except (ValueError,TypeError):
        raise HTTPException(400,'Invalid date')

def save_nasa(owner,lat,lon,rows):
    from psycopg.types.json import Jsonb
    key=_key(owner)
    saved=0
    try:
        with _connection() as conn,conn.cursor() as cur:
            for row in rows[:120]:
                if not isinstance(row,dict) or not row.get('date'):continue
                try: day=_day(str(row['date']))
                except HTTPException:continue
                cur.execute("""INSERT INTO cropoganda_nasa_daily
                               (account_key,day,latitude,longitude,observations,stored_at)
                               VALUES (%s,%s,%s,%s,%s,now())
                               ON CONFLICT(account_key,day,latitude,longitude)
                               DO UPDATE SET observations=EXCLUDED.observations,stored_at=now()""",
                            (key,day,lat,lon,Jsonb(row)))
                saved+=1
        return saved
    except HTTPException:raise
    except Exception as exc:raise HTTPException(503,'Could not store NASA POWER history') from exc

def nasa_day(owner,day,lat,lon):
    d=_day(day)
    try:
        with _connection() as conn,conn.cursor() as cur:
            cur.execute("""SELECT observations,stored_at FROM cropoganda_nasa_daily
                           WHERE account_key=%s AND day=%s
                             AND abs(latitude-%s)<0.0001 AND abs(longitude-%s)<0.0001
                           ORDER BY stored_at DESC LIMIT 1""",(_key(owner),d,lat,lon))
            found=cur.fetchone()
        return {'observations':_json(found[0]),'stored_at':found[1].isoformat()} if found else None
    except HTTPException:raise
    except Exception as exc:raise HTTPException(503,'Could not load NASA POWER history') from exc
