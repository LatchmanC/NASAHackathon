"""Cropoganda History endpoints: recorded ESP32 snapshots and NASA POWER daily.
All requests require verified Auth0 sessions; shared viewers have read-only scope.
"""
from __future__ import annotations
from fastapi import HTTPException, Request
from pydantic import BaseModel, Field
from device_api import _owner, resolve_device_data, share_claims
from sensor_store import read_shared_link
from fieldshift_core import valid_lat_lon
from intelligence import fetch_nasa_daily
import tigerdata_store as tiger

class NasaSyncRequest(BaseModel):
    location:dict=Field(default_factory=dict)
    days:int=Field(default=90,ge=14,le=120)

def selected_account(request,view):
    subject=_owner(request)
    snapshot,access=resolve_device_data(subject,view=view)
    if access!='shared':
        return subject,access
    link=read_shared_link(subject)
    if not link or not link.get('token'):
        raise HTTPException(403,'No shared device is authorized')
    claim=share_claims(link['token'])
    # resolve_device_data has already verified the token, owner, version and device ID.
    return claim['sub'],access

def install_history_routes(app):
    @app.get('/api/history/status')
    def status(request:Request):
        _owner(request)
        return {'configured':tiger.enabled(),
                'archive_interval_minutes':10,'date_basis':'America/New_York',
                'live_mode':'TigerData live row' if tiger.enabled() else 'Legacy Vercel Blob (slower)',
                'note':'Connect TigerData and run the SQL schema to enable cloud history.' if not tiger.enabled()
                       else 'Live readings updated on every accepted device upload; the first reading in each UTC 10-minute window is archived, grouped into Eastern local dates.'}

    @app.get('/api/history/dates')
    def available_dates(request:Request,view:str='auto'):
        if not tiger.enabled():
            raise HTTPException(503,'TigerData is not connected')
        account,access=selected_account(request,view)
        return {'dates':tiger.available_dates(account),'sensor_access':access,'date_basis':'America/New_York'}

    @app.get('/api/history/days')
    def days(request:Request,year:int,month:int,view:str='auto'):
        if not tiger.enabled():
            raise HTTPException(503,'TigerData is not connected')
        account,access=selected_account(request,view)
        return {'days':tiger.dates(account,year,month),'sensor_access':access,
                'date_basis':'America/New_York'}

    @app.get('/api/history/snapshots')
    def snapshots(request:Request,day:str,view:str='auto'):
        if not tiger.enabled():
            raise HTTPException(503,'TigerData is not connected')
        account,access=selected_account(request,view)
        return {'snapshots':tiger.times(account,day),'day':day,
                'sensor_access':access,'date_basis':'America/New_York'}

    @app.get('/api/history/entry')
    def entry(request:Request,day:str,bucket:str,latitude:float,longitude:float,view:str='auto'):
        if not tiger.enabled():
            raise HTTPException(503,'TigerData is not connected')
        try:lat,lon=valid_lat_lon(latitude,longitude)
        except (TypeError,ValueError) as exc:raise HTTPException(400,str(exc)) from exc
        account,access=selected_account(request,view)
        sensor=tiger.archived_reading(account,day,bucket)
        if not sensor:
            raise HTTPException(404,'No sensor snapshot saved for this timestamp')
        nasa=tiger.nasa_day(account,day,lat,lon)
        return {'day':day,'bucket_at':bucket,'sensor':sensor,
                'nasa':nasa,'sensor_access':access,
                'nasa_source':'NASA POWER regional historical daily observations' if nasa else 'not stored for this day/location',
                'date_basis':'America/New_York'}

    @app.post('/api/history/sync-nasa')
    def sync_nasa(request:Request,req:NasaSyncRequest):
        if not tiger.enabled():
            raise HTTPException(503,'TigerData is not connected')
        # A viewer cannot write records into somebody else's farm.
        subject=_owner(request)
        try:
            lat,lon=valid_lat_lon(req.location.get('latitude'),req.location.get('longitude'))
        except (ValueError,TypeError) as exc:
            raise HTTPException(400,'Select a valid farm location') from exc
        try:
            result=fetch_nasa_daily({'latitude':lat,'longitude':lon},days=req.days)
        except Exception as exc:
            raise HTTPException(502,'NASA POWER daily observations are currently unavailable') from exc
        if not result.get('is_real_nasa'):
            raise HTTPException(502,'NASA returned no confirmed historical records')
        rows=result.get('rows') or []
        count=tiger.save_nasa(subject,lat,lon,rows)
        return {'stored_days':count,'location':{'latitude':lat,'longitude':lon},
                'period':result.get('period'),'source':'NASA POWER daily','date_basis':'America/New_York'}
