"""FieldShift Simple: local-only farmer web dashboard and Python backend.

The browser talks to THIS Python backend; device/cloud tokens and Gemini SDK
never need to be exposed by browser JavaScript. Bind to 127.0.0.1 in demo.
"""
from __future__ import annotations
import json
import math
import os
import statistics
import time
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from fieldshift_core import http_json, valid_lat_lon, make_location, MEASURES, VALUE_FIELDS
from intelligence import (fetch_nasa_daily, demo_nasa_daily,
                          aggregate_local_by_day, official_alerts,
                          demo_alerts, local_flags)
from gemini_client import generate_gemini_reply, DEFAULT_GEMINI_MODEL
from location_catalog import catalog, resolve_preset

BASE=Path(__file__).resolve().parent
# Backend-only local credentials. Never expose the key to browser JavaScript.
load_dotenv(BASE / ".env", override=False)
DATA_DIR=Path(os.environ.get('FIELDSHIFT_DATA_DIR',str(Path.home()/'.fieldshift_simple_v5')))
DATA_DIR.mkdir(parents=True,exist_ok=True)
PLAN_FILE=DATA_DIR/'farm_plan.json'
CALENDAR_FILE=DATA_DIR/'calendar_events.json'
STATION_URL=os.environ.get('FIELDSHIFT_ESP32_URL', 'http://127.0.0.1:8765').rstrip('/')
CLOUD_URL=os.environ.get('FIELDSHIFT_CLOUD_URL','http://127.0.0.1:8766').rstrip('/')
DEVICE_HEADERS={'X-Device-Token':os.environ.get('FIELDSHIFT_DEVICE_TOKEN','local-demo-secret')}
CLOUD_HEADERS={'X-Sync-Token':os.environ.get('FIELDSHIFT_CLOUD_TOKEN','cloud-demo-secret')}
DEMO_ENV=os.environ.get('FIELDSHIFT_DEMO','1')=='1'
DEFAULT_LOCATION={'mode':'coords','label':'Demo — New York City','latitude':40.7128,'longitude':-74.006,'resolution':'sample coordinates'}
CACHE={}

app=FastAPI(title='FieldShift farmer dashboard',docs_url=None,redoc_url=None)
app.mount('/static',StaticFiles(directory=str(BASE/'web'/'static')),name='static')

@app.get('/')
def home():return FileResponse(BASE/'web'/'index.html')

@app.get('/api/health')
def health():return {'ok':True,'service':'FieldShift web app','demo':DEMO_ENV}

def from_pi(path, *, data=None, timeout=5):
    return http_json('POST' if data is not None else 'GET',STATION_URL+path,data,DEVICE_HEADERS,timeout=timeout)

def from_cloud(path, *, timeout=5):
    return http_json('GET',CLOUD_URL+path,headers=CLOUD_HEADERS,timeout=timeout)

def safe_status():
    try:return from_pi('/api/status',timeout=3)
    except Exception:return None

def safe_cloud():
    try:
        h=http_json('GET',CLOUD_URL+'/health',timeout=3)
        l=from_cloud('/api/latest',timeout=3)
        return {**h,**l}
    except Exception:return None

def timestamp_age(value):
    if not value:return None
    try:
        parsed=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        if not parsed.tzinfo:return None
        return max(0,(datetime.now(timezone.utc)-parsed.astimezone(timezone.utc)).total_seconds())
    except (TypeError,ValueError):return None

@app.get('/api/overview')
def overview():
    pi=safe_status(); cloud=safe_cloud()
    station_latest=pi.get('latest') if pi else None
    cloud_latest=cloud.get('latest') if cloud else None
    age=timestamp_age(station_latest.get('recorded_at')) if station_latest else None
    # "Connected" requires reachable Pi and an up-to-date sensor packet.
    live=bool(pi and station_latest and age is not None and age < 150)
    latest=station_latest if pi and station_latest else cloud_latest
    state=('live' if live else ('stale' if pi else ('cloud_only' if cloud else 'offline')))
    return {'state':state,'latest':latest,'pi_connected':pi is not None,
            'cloud_connected':cloud is not None,'last_reading_at':latest.get('recorded_at') if latest else None,
            'last_cloud_sync':cloud.get('last_synced_at') if cloud else None,
            'pending_cloud':(pi.get('counts') or {}).get('pending_cloud') if pi else None,
            'cloud_record_count':cloud.get('stored') if cloud else None,
            'location':(pi or {}).get('location') or DEFAULT_LOCATION,
            'flags':local_flags([latest] if latest else []),
            'sensor_source':('SIMULATED' if latest and latest.get('source')=='simulated_esp32' else 'REAL' if latest else 'NONE')}

@app.get('/api/recorded')
def recorded(limit:int=250,offset:int=0):
    if not (1<=limit<=1000 and 0<=offset<=10**7):raise HTTPException(400,'Invalid pagination')
    try:return {**from_cloud(f'/api/readings?limit={limit}&offset={offset}'), 'storage':'cloud demo (SQLite)'}
    except Exception as e:raise HTTPException(503,f'Cloud database not reachable: {str(e)[:140]}')

@app.get('/api/local')
def local_readings(limit:int=1000):
    if not 1<=limit<=1000:raise HTTPException(400,'Invalid limit')
    pi=safe_status()
    if not pi:raise HTTPException(503,'Local receiver is unavailable')
    total=(pi.get('counts') or {}).get('total') or 0
    start=max(0,total-limit)
    try:return from_pi(f'/api/readings?since_seq={start}&limit={limit}')
    except Exception as e:raise HTTPException(503,str(e)[:140])

@app.get('/api/locations/catalog')
def get_location_catalog():
    return {'countries': catalog(), 'note':'Bundled offline city centers; GPS coordinates are more precise.'}

@app.post('/api/location')
def set_location(payload:dict):
    try:
        mode=payload.get('mode')
        if mode=='coords':
            lat,lon=valid_lat_lon(payload.get('latitude'),payload.get('longitude'))
            data={'mode':'coords','latitude':lat,'longitude':lon}
        elif mode=='preset':
            resolved = resolve_preset(payload.get('country'), payload.get('region'), payload.get('city'))
            data = {'mode':'preset', 'label':resolved['label'],
                    'latitude':resolved['latitude'],'longitude':resolved['longitude']}
        elif mode=='area':
            label=str(payload.get('label','')).strip()
            if not 2<=len(label)<=120:raise ValueError('Enter a city/region name')
            data={'mode':'area','label':label}
        else:raise ValueError('Select an area or coordinates')
        # The Pi stores the selected location and clears NASA series from old location.
        return from_pi('/api/location',data=data,timeout=25)
    except Exception as e:raise HTTPException(400,str(e)[:200])

@app.get('/api/nasa')
def nasa(mode:str='cached',days:int=45):
    status=safe_status()
    loc=(status or {}).get('location') or DEFAULT_LOCATION
    if mode=='auto':
        # Once-per-day refresh on tab access, only if actual NASA data has been requested.
        # Synthetic demo series are not silently replaced with live observations.
        if not status:
            return {'nasa_daily':None,'note':'ESP32 station unavailable; cannot update NASA cache.'}
        try:
            cached_record=from_pi('/api/nasa/daily',timeout=3)
            existing=cached_record.get('nasa_daily') or {}
            fetched=str(existing.get('fetched_at',''))[:10]
            today=datetime.now(timezone.utc).date().isoformat()
            if existing.get('is_real_nasa') and fetched!=today:
                try:return from_pi('/api/nasa/daily/fetch',data={'days':max(30,min(days,180))},timeout=95)
                except Exception as exc:
                    return {'nasa_daily':existing,'note':'Daily refresh failed; showing cached NASA observations: '+str(exc)[:130]}
            return cached_record
        except Exception as e:raise HTTPException(503,str(e)[:200])
    if mode=='cached':
        if not status:return {'nasa':None,'note':'ESP32 station unavailable. NASA history not cached.'}
        try:return from_pi('/api/nasa/daily',timeout=3)
        except Exception as e:raise HTTPException(503,str(e))
    if mode=='demo':
        if not status:raise HTTPException(503,'ESP32 station required to save NASA demo series')
        return from_pi('/api/nasa/daily/demo',data={},timeout=12)
    if mode=='real':
        if not status:raise HTTPException(503,'ESP32 station required for NASA retrieval')
        try:return from_pi('/api/nasa/daily/fetch',data={'days':max(14,min(days,180))},timeout=95)
        except Exception as e:raise HTTPException(502,f'NASA retrieval failed: {str(e)[:300]}')
    raise HTTPException(400,'Unsupported mode')

@app.get('/api/charts')
def charts():
    try:cloud=from_cloud('/api/readings?limit=1800',timeout=7)
    except Exception:cloud=None
    if cloud is None:
        try:local=local_readings(1000);records=local['readings'];source='Local receiver fallback (cloud unreachable)'
        except Exception:records=[];source='Not available'
    else:
        records=cloud['readings'];source='Cloud synchronized history'
    daily=aggregate_local_by_day(records)
    nasa_data=None
    try:nasa_data=from_pi('/api/nasa/daily',timeout=4).get('nasa_daily')
    except Exception:pass
    return {'source':source,'local_days':daily,'nasa':nasa_data,'record_count':len(records),
            'measures':[{'key':k,'label':n,'unit':u} for k,n,u in MEASURES]}


def demo_forecast():
    today=datetime.now(timezone.utc).date()
    sample=[(22,15,30,1.1,12,'Partly cloudy'),(23,16,50,4.5,19,'Clouds and showers'),
            (20,13,75,8.2,24,'Rain'),(21,12,20,0.2,15,'Clear'),(24,17,10,0,10,'Sunny')]
    return [{'date':(today+timedelta(days=i)).isoformat(),'high_c':hi,'low_c':lo,
             'rain_chance_pct':chance,'precipitation_mm':rain,'wind_kmh':wind,
             'summary':desc} for i,(hi,lo,chance,rain,wind,desc) in enumerate(sample)]


def real_forecast(lat,lon):
    url='https://api.open-meteo.com/v1/forecast?'+urlencode({
        'latitude':lat,'longitude':lon,'timezone':'auto','forecast_days':7,
        'daily':'temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,wind_speed_10m_max,weather_code'})
    raw=http_json('GET',url,timeout=18)
    day=raw.get('daily') or {}
    codes={0:'Clear',1:'Mostly clear',2:'Partly cloudy',3:'Overcast',
           45:'Fog',48:'Fog',51:'Drizzle',53:'Drizzle',55:'Drizzle',
           61:'Rain',63:'Rain',65:'Heavy rain',71:'Snow',73:'Snow',75:'Heavy snow',
           80:'Showers',81:'Showers',82:'Heavy showers',95:'Thunderstorm',96:'Thunderstorm',99:'Thunderstorm'}
    result=[]
    for i,date in enumerate(day.get('time',[])):
        def at(key):
            v=day.get(key)
            return v[i] if isinstance(v,list) and len(v)>i else None
        result.append({'date':date,'high_c':at('temperature_2m_max'),
                       'low_c':at('temperature_2m_min'),'rain_chance_pct':at('precipitation_probability_max'),
                       'precipitation_mm':at('precipitation_sum'),'wind_kmh':at('wind_speed_10m_max'),
                       'summary':codes.get(at('weather_code'),'Mixed conditions')})
    if not result:raise RuntimeError('Forecast provider returned no days')
    return result


def cached(key,ttl,func):
    now=time.monotonic()
    if key in CACHE and now-CACHE[key][0]<ttl:return CACHE[key][1]
    result=func();CACHE[key]=(now,result)
    return result

@app.get('/api/weather')
def weather(mode:str='demo'):
    if mode not in ('demo','live'):raise HTTPException(400,'mode must be demo or live')
    status=safe_status()
    location=(status or {}).get('location') or DEFAULT_LOCATION
    lat,lon=location['latitude'],location['longitude']
    if mode=='demo':
        return {'mode':'demo','forecast':demo_forecast(),
                'alert_status':demo_alerts(location),'location':location,
                'forecast_source':'SYNTHETIC weather forecast — NOT operational weather data'}
    errors=[]
    try:
        forecast=cached(('forecast',lat,lon),600,lambda:real_forecast(lat,lon))
    except Exception as e:
        errors.append('Forecast unavailable: '+str(e)[:130]);forecast=[]
    try:
        alert_status=cached(('alerts',lat,lon),180,lambda:official_alerts(location))
    except Exception as e:
        errors.append('Alerts unavailable: '+str(e)[:130]);
        alert_status={'status':'unavailable','alerts':[],'message':str(e)}
    return {'mode':'live','forecast':forecast,'alert_status':alert_status,
            'location':location,'errors':errors,
            'forecast_source':'Open-Meteo model forecast (not NASA POWER)'}

DEFAULT_PLAN={'total_area':5,'area_unit':'acres','notes':'','crops':[
    {'name':'Tomato','area':1.5,'stage':'Planning','planted_on':'','variety':''},
    {'name':'Corn','area':2.0,'stage':'Planning','planted_on':'','variety':''}]}

def get_plan():
    if PLAN_FILE.exists():
        try:
            value=json.loads(PLAN_FILE.read_text(encoding='utf8'))
            if isinstance(value,dict):return value
        except (OSError,ValueError):pass
    return DEFAULT_PLAN

@app.get('/api/plan')
def read_plan():return get_plan()


def validate_plan(plan):
    if not isinstance(plan,dict):raise ValueError('Farm plan must be an object')
    unit=plan.get('area_unit','acres')
    if unit not in ('acres','hectares'):raise ValueError('Area unit must be acres or hectares')
    total=float(plan.get('total_area',0))
    if not math.isfinite(total) or not 0<total<1e8:raise ValueError('Enter a valid total area')
    raw=plan.get('crops')
    if not isinstance(raw,list) or not 1<=len(raw)<=30:raise ValueError('Choose 1–30 crops')
    cleaned=[];sum_area=0
    for r in raw:
        if not isinstance(r,dict):raise ValueError('Invalid crop row')
        name=str(r.get('name','')).strip()[:70]
        area=float(r.get('area',0))
        if not name or not math.isfinite(area) or area<=0:raise ValueError('Every crop needs a name and positive area')
        stage=str(r.get('stage','Planning'))[:50].strip()
        date=str(r.get('planted_on','')).strip()[:10]
        if date:
            try:datetime.strptime(date,'%Y-%m-%d')
            except ValueError:raise ValueError('Planting dates must use YYYY-MM-DD')
        cleaned.append({'name':name,'area':area,'stage':stage,'planted_on':date,
                        'variety':str(r.get('variety',''))[:80]})
        sum_area+=area
    if sum_area>total+1e-6:raise ValueError(f'Crop area ({sum_area:g}) exceeds farm area ({total:g})')
    return {'total_area':total,'area_unit':unit,'crops':cleaned,
            'notes':str(plan.get('notes',''))[:1500], 'unallocated_area':round(total-sum_area,4)}

@app.post('/api/plan')
def save_plan(payload:dict):
    try:
        plan=validate_plan(payload)
        PLAN_FILE.write_text(json.dumps(plan,indent=2),encoding='utf8')
        return {'saved':True,'plan':plan,'storage':'Local dashboard file (not yet in TigerData)'}
    except (ValueError,TypeError) as e:raise HTTPException(400,str(e))

# Farmer-managed calendar tasks. Automatically derived crop planting markers
# are not saved here; the frontend reads their dates from farm_plan.json.
CALENDAR_TYPES={'planting','watering','harvest','fertilizing','inspection','other'}

def load_calendar_events():
    if not CALENDAR_FILE.exists():return []
    try:
        events=json.loads(CALENDAR_FILE.read_text(encoding='utf8'))
        return events if isinstance(events,list) else []
    except (OSError,ValueError):return []

def write_calendar_events(events):
    pending=CALENDAR_FILE.with_suffix('.tmp')
    pending.write_text(json.dumps(events,ensure_ascii=False,indent=2),encoding='utf8')
    pending.replace(CALENDAR_FILE)

@app.get('/api/calendar')
def list_calendar_events():
    return {'events':load_calendar_events(),'storage':'local JSON file'}

@app.post('/api/calendar')
def add_calendar_event(payload:dict):
    try:
        raw=str(payload.get('date',''))
        day=datetime.strptime(raw,'%Y-%m-%d').date()
        if not 1900<=day.year<=2200 or day.isoformat()!=raw:raise ValueError('Invalid calendar date')
        kind=str(payload.get('kind','')).strip().lower()
        if kind not in CALENDAR_TYPES:raise ValueError('Choose a valid task type')
        crop=str(payload.get('crop','')).strip()[:70]
        note=str(payload.get('note','')).strip()[:240]
        events=load_calendar_events()
        if len(events)>=500:raise ValueError('Calendar supports up to 500 manual tasks')
        events.append({'id':str(uuid.uuid4()),'date':raw,'kind':kind,'crop':crop,'note':note})
        events.sort(key=lambda row:(row['date'],row['id']))
        write_calendar_events(events)
        return {'saved':True,'events':events}
    except (ValueError,TypeError) as exc:raise HTTPException(400,str(exc))

@app.delete('/api/calendar/{event_id}')
def delete_calendar_event(event_id:str):
    # A strict UUID prevents ambiguous or malformed deletion requests.
    try:uuid.UUID(event_id)
    except ValueError:raise HTTPException(400,'Invalid task ID')
    events=load_calendar_events()
    new_events=[item for item in events if item.get('id')!=event_id]
    if len(new_events)==len(events):raise HTTPException(404,'Task not found')
    write_calendar_events(new_events)
    return {'deleted':True,'events':new_events}

@app.get('/api/gemini/status')
def gemini_status():
    # Only report whether credentials exist. Never return the credential itself.
    return {'configured':bool(os.environ.get('GEMINI_API_KEY','').strip()),
            'model':DEFAULT_GEMINI_MODEL,'key_source':'server environment'}

class AdviceRequest(BaseModel):
    plan:dict
    model:str=DEFAULT_GEMINI_MODEL
    question:str=''
    weather_mode:str='live'

@app.post('/api/plan/advice')
def farming_advice(req:AdviceRequest):
    try:plan=validate_plan(req.plan)
    except (ValueError,TypeError) as e:raise HTTPException(400,str(e))
    api_key=os.environ.get('GEMINI_API_KEY','').strip()
    if not api_key:raise HTTPException(400,'Set GEMINI_API_KEY on the server (run python configure_gemini.py).')
    overview_data=overview()
    charts_data=charts()
    daily=charts_data.get('local_days') or {}
    nasa=charts_data.get('nasa') or {}
    ns_rows=nasa.get('rows',[])
    f=weather(req.weather_mode)
    # Avoid sending unbounded raw readings or secret keys to Gemini.
    context={'location':overview_data.get('location'),
             'latest_station_reading':overview_data.get('latest'),
             'sensor_source':overview_data.get('sensor_source'),
             'local_daily_history':{d:daily[d] for d in sorted(daily)[-12:]},
             'nasa_source':nasa.get('source') if nasa else 'Not loaded',
             'nasa_is_real':bool(nasa.get('is_real_nasa')),
             'nasa_daily_recent':ns_rows[-12:],
             'weather_forecast_source':f.get('forecast_source'),
             'weather_forecast_mode':f.get('mode'),
             'weather_forecast':f.get('forecast',[])[:7],
             'official_alert_status':f.get('alert_status'),
             'crop_allocation':plan,
             'upcoming_calendar_tasks':[e for e in load_calendar_events() if e.get('date','')>=datetime.now().date().isoformat()][:30],
             'farmer_question':req.question[:500]}
    prompt=('You are FieldShift, a cautious agricultural decision-support assistant. '\
      'Use only the provided observations, location, forecasts and crop information. '\
      'DO NOT invent soil chemistry, weather warnings, growth stage, crop maturity dates, or yield. '\
      'Separate measured ESP32 data, historical/regional NASA data, forecast model data, and assumptions. '\
      'When source is simulated, explicitly say so and do not claim operational accuracy. '\
      'If a planting date, cultivar, or actual growing degree days are missing, progress estimates must be qualitative '\
      'or clearly conditional, never a fabricated percentage. '\
      'State the weather forecast source and that NASA POWER is not a short-term weather forecast. '\
      'Official alerts must be reported as the provider states; NEVER originate a severe warning. '\
      'Respond clearly in sections: Farm snapshot; Crop-by-crop planting windows; Harvest timing/estimated progress; '\
      'Next 7-day actions; Weather risks; Assumptions and uncertainties. '\
      'Emphasize that outputs require farmer judgment and local agricultural guidance. '\
      '\nJSON DATA:\n'+json.dumps(context,default=str))
    try:
        text=generate_gemini_reply(api_key,prompt,model=req.model)
        return {'advice':text,'model':req.model,'created_at':datetime.now(timezone.utc).isoformat(),
                'data_mode':f['mode'],'nasa_real':bool(nasa.get('is_real_nasa'))}
    except Exception as e:raise HTTPException(502,f'Gemini request failed: {type(e).__name__}: {str(e)[:300]}')

if __name__=='__main__':
    import uvicorn
    uvicorn.run('web_server:app',host='127.0.0.1',port=8501,log_level='warning')
