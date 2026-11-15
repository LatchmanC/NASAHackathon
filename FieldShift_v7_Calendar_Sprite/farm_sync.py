"""Daily NASA POWER sync: only real regional rows, no sample data.
User-specific farm coordinates are persisted in TigerData for Vercel Cron.
"""
from __future__ import annotations
import hmac,os
from fastapi import HTTPException,Request
from pydantic import BaseModel,Field
from device_api import _owner
from fieldshift_core import valid_lat_lon
from intelligence import fetch_nasa_daily
from tigerdata_store import _connection,_key,enabled
from psycopg.types.json import Jsonb

class FarmLocation(BaseModel):
    latitude:float
    longitude:float
    label:str=Field(default='',max_length=130)

def _setup(conn):
    with conn.cursor() as cur:
        cur.execute("""CREATE TABLE IF NOT EXISTS cropoganda_farm_locations(
            account_key TEXT PRIMARY KEY,
            latitude DOUBLE PRECISION NOT NULL,
            longitude DOUBLE PRECISION NOT NULL,
            label TEXT NOT NULL DEFAULT '',
            last_nasa_sync_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )""")

def _archive_for_account_key(key,lat,lon,rows,conn):
    stored=0
    with conn.cursor() as cur:
        for r in rows[:21]:
            if not isinstance(r,dict):continue
            day=r.get('date','')
            if not isinstance(day,str) or len(day)!=10:continue
            try:
                import datetime
                datetime.date.fromisoformat(day)
            except (ValueError,TypeError):continue
            cur.execute("""INSERT INTO cropoganda_nasa_daily
                (account_key,day,latitude,longitude,observations,stored_at)
                VALUES (%s,%s,%s,%s,%s,now())
                ON CONFLICT(account_key,day,latitude,longitude)
                DO UPDATE SET observations=EXCLUDED.observations,stored_at=now()""",
                (key,day,lat,lon,Jsonb(r)))
            stored+=1
    return stored

def install_farm_sync_routes(app):
    @app.post('/api/farm/location')
    def save_location(req:FarmLocation,request:Request):
        account=_owner(request)
        if not enabled():raise HTTPException(503,'TigerData not configured')
        try:lat,lon=valid_lat_lon(req.latitude,req.longitude)
        except (ValueError,TypeError) as exc:
            raise HTTPException(400,'Invalid farm coordinates') from exc
        with _connection() as conn:
            _setup(conn)
            with conn.cursor() as cur:
                cur.execute("""INSERT INTO cropoganda_farm_locations
                    (account_key,latitude,longitude,label,last_nasa_sync_at)
                    VALUES (%s,%s,%s,%s,NULL)
                    ON CONFLICT(account_key) DO UPDATE
                    SET latitude=EXCLUDED.latitude,longitude=EXCLUDED.longitude,
                        label=EXCLUDED.label,updated_at=now(),
                        last_nasa_sync_at=CASE
                          WHEN cropoganda_farm_locations.latitude=EXCLUDED.latitude
                           AND cropoganda_farm_locations.longitude=EXCLUDED.longitude
                          THEN cropoganda_farm_locations.last_nasa_sync_at
                          ELSE NULL END""",( _key(account),lat,lon,req.label ))
        return {'saved':True,'nasa_auto_sync_registered':True,'label':req.label}

    @app.get('/api/nasa/cron-sync')
    def sync_daily(request:Request):
        expected=os.getenv('CRON_SECRET','')
        provided=request.headers.get('authorization','')
        if not expected or not hmac.compare_digest(provided,'Bearer '+expected):
            raise HTTPException(401,'Unauthorized scheduled task')
        if not enabled():raise HTTPException(503,'TigerData not configured')
        with _connection() as conn:
            _setup(conn)
            with conn.cursor() as cur:
                cur.execute("""SELECT account_key,latitude,longitude
                               FROM cropoganda_farm_locations
                               ORDER BY last_nasa_sync_at ASC NULLS FIRST,
                                        updated_at ASC LIMIT 8""")
                farms=cur.fetchall()
        result={'registered_checked':len(farms),'farms_updated':0,'daily_rows_saved':0,'errors':0}
        # NASA may publish the most recent day after a delay. Re-fetch two weeks
        # each day; do not invent today's daily observations.
        by_location={}
        for account_key,lat,lon in farms:
            loc=(round(lat,5),round(lon,5))
            if loc not in by_location:
                try:
                    real=fetch_nasa_daily({'latitude':lat,'longitude':lon},days=15)
                    if not real.get('is_real_nasa'):
                        raise ValueError('No authenticated NASA POWER records')
                    by_location[loc]=real.get('rows') or []
                except Exception:
                    by_location[loc]=None
            rows=by_location[loc]
            if rows is None:
                result['errors']+=1
                continue
            try:
                with _connection() as conn:
                    saved=_archive_for_account_key(account_key,lat,lon,rows,conn)
                    with conn.cursor() as cur:
                        cur.execute("""UPDATE cropoganda_farm_locations
                                       SET last_nasa_sync_at=now()
                                       WHERE account_key=%s""",(account_key,))
                result['farms_updated']+=1
                result['daily_rows_saved']+=saved
            except Exception:
                result['errors']+=1
        return {'ok':result['errors']==0,**result,'source':'NASA POWER Daily (real only)'}
