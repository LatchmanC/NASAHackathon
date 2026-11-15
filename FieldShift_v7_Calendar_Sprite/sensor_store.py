"""Isolated, bounded ESP32 telemetry stored as private Vercel Blob snapshots.

This is a starter receiver, NOT a high-frequency time-series database.
"""
import os, math, json, hashlib, secrets
from datetime import datetime, timezone
from fastapi import HTTPException
from pydantic import BaseModel, Field, model_validator
from tigerdata_store import enabled as tiger_enabled, live_snapshot as tiger_live, record as tiger_record, new_share_version as tiger_revoke

METRIC_BOUNDS={'temperature_c':(-60,85),'humidity_pct':(0,100),'pressure_hpa':(300,1200),
               'altitude_m':(-1000,10000),'rain_wetness_pct':(0,100),'light_pct':(0,100),
               'gas_index':(0,100),'soil_moisture_pct':(0,100),'ph':(0,14)}
class SensorPayload(BaseModel):
    device_id:str=Field(min_length=1,max_length=40,pattern=r'^[A-Za-z0-9_-]+$')
    temperature_c:float|None=None
    humidity_pct:float|None=None
    pressure_hpa:float|None=None
    altitude_m:float|None=None
    rain_wetness_pct:float|None=None
    light_pct:float|None=None
    gas_index:float|None=None
    soil_moisture_pct:float|None=None
    ph:float|None=None
    @model_validator(mode='after')
    def check(self):
        count=0
        for name,(lo,hi) in METRIC_BOUNDS.items():
            val=getattr(self,name)
            if val is not None:
                if not math.isfinite(val) or not lo<=val<=hi:raise ValueError(f'{name} must be between {lo} and {hi}')
                count+=1
        if not count:raise ValueError('Supply at least one actual sensor reading')
        return self

def configured():
    return bool(os.getenv('BLOB_READ_WRITE_TOKEN') or os.getenv('BLOB_STORE_ID')) or tiger_enabled()

def path_for(owner):
    if not isinstance(owner,str) or not owner or len(owner)>300:raise ValueError('Owner required')
    return 'esp32/v1/'+hashlib.sha256(owner.encode()).hexdigest()+'/snapshot.json'

def read_snapshot(owner):
    # TigerData holds the immediate/live reading. Retain the private Blob fallback
    # for deployments not yet connected to TigerData and earlier demo-era data.
    if tiger_enabled():
        live=tiger_live(owner)
        if live is not None:return live
    if not configured():return None
    from vercel.blob import sync as blob
    from vercel.blob.errors import BlobNotFoundError
    try:
        data=blob.get_blob(path_for(owner),access='private')
        if data is None:return None
        if len(data.body)>2000000:raise ValueError('Oversized stored snapshot')
        doc=json.loads(data.body)
        if not isinstance(doc,dict) or doc.get('schema')!=1:raise ValueError('Bad storage version')
        return doc
    except BlobNotFoundError:return None
    except Exception as e:raise HTTPException(503,'Sensor storage could not be reached') from e

def save_snapshot(owner, reading, old):
    if tiger_enabled():
        return tiger_record(owner,reading)
    if not configured():raise HTTPException(503,'Sensor storage is not configured')
    from vercel.blob import sync as blob
    latest={k:v for k,v in reading.items() if k in METRIC_BOUNDS or k in ('device_id','recorded_at')}
    rows=([latest]+(old.get('readings',[]) if old else []))[:72]
    doc={'schema':1,'latest':latest,'last_updated':latest['recorded_at'],'readings':rows,
         'share_version':(old.get('share_version','v1') if old else 'v1')}
    try:
        blob.put_blob(path_for(owner),json.dumps(doc,separators=(',',':')).encode(),
            access='private',content_type='application/json',allow_overwrite=True,cache_control_max_age=60)
    except Exception as e:raise HTTPException(503,'Sensor reading could not be saved') from e
    return doc

def age_seconds(latest):
    if not latest or not latest.get('recorded_at'):return None
    try:return max(0,(datetime.now(timezone.utc)-datetime.fromisoformat(latest['recorded_at'].replace('Z','+00:00'))).total_seconds())
    except (ValueError,TypeError):return None

def daily_averages(rows):
    data={}
    for row in rows:
        day=str(row.get('recorded_at',''))[:10]
        if len(day)!=10:continue
        d=data.setdefault(day,{})
        for key in METRIC_BOUNDS:
            val=row.get(key)
            if isinstance(val,(int,float)) and math.isfinite(val):d.setdefault(key,[]).append(val)
    return {day:{key:round(sum(vals)/len(vals),2) for key,vals in d.items()} for day,d in data.items()}



def share_path_for(viewer):
    """The recipient's own private Blob key, never exposed to clients."""
    return path_for(viewer).removesuffix('/snapshot.json')+'/shared_link.json'


def read_shared_link(viewer):
    if not configured():
        return None
    from vercel.blob import sync as blob
    from vercel.blob.errors import BlobNotFoundError
    try:
        value=blob.get_blob(share_path_for(viewer),access='private')
        if value is None:
            return None
        if len(value.body)>5000:
            raise ValueError('Oversized shared-device link')
        link=json.loads(value.body)
        return link if isinstance(link,dict) and link.get('schema')==1 and link.get('token') else None
    except BlobNotFoundError:
        return None
    except Exception as exc:
        raise HTTPException(503,'Shared device connection could not be loaded') from exc


def save_shared_link(viewer,token=None):
    """Save or disconnect a single view-only device link for this Auth0 account."""
    if not configured():
        raise HTTPException(503,'Sensor storage is not configured')
    from vercel.blob import sync as blob
    doc={'schema':1,'token':token if token else None}
    try:
        blob.put_blob(share_path_for(viewer),json.dumps(doc).encode(),
                      access='private',content_type='application/json',
                      allow_overwrite=True,cache_control_max_age=60)
    except Exception as exc:
        raise HTTPException(503,'Shared device connection could not be saved') from exc
    return doc


def revoke_shared_viewers(owner):
    """Rotate the owner's share version without invalidating ESP32 upload tokens."""
    current=read_snapshot(owner)
    if not current or not current.get('latest'):
        raise HTTPException(409,'Upload a reading from your ESP32 before managing sharing')
    from vercel.blob import sync as blob
    current=dict(current)
    current['share_version']=tiger_revoke(owner) if tiger_enabled() else secrets.token_urlsafe(18)
    try:
        blob.put_blob(path_for(owner),json.dumps(current,separators=(',',':')).encode(),
                      access='private',content_type='application/json',
                      allow_overwrite=True,cache_control_max_age=60)
    except Exception as exc:
        raise HTTPException(503,'Could not revoke shared access') from exc
    return current
