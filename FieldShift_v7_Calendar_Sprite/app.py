"""Cropoganda Vercel edition. Stateless FastAPI; private data lives in browser only for preview.
No ESP32 feed/SQL until the actual device and TigerData integration is configured.
"""
from __future__ import annotations
import json, math, os, re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlencode
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from fieldshift_core import http_json, valid_lat_lon
from intelligence import fetch_nasa_daily, demo_nasa_daily, official_alerts, demo_alerts
from location_catalog import catalog, resolve_preset
from gemini_client import generate_gemini_reply, DEFAULT_GEMINI_MODEL
from sensor_store import configured as sensor_configured, read_snapshot, age_seconds, daily_averages
from device_api import resolve_device_data
from device_api import install_device_routes
from history_api import install_history_routes
from tigerdata_store import enabled as tiger_enabled, save_nasa as tiger_save_nasa
from advisor_core import answer_question

ROOT=Path(__file__).resolve().parent
load_dotenv(ROOT/'.env',override=False)
app=FastAPI(title='Cropoganda — farm intelligence', docs_url=None, redoc_url=None)
# Vercel serves public/static separately from Python functions.
static_dir = ROOT / 'public' / 'static'
if static_dir.is_dir():
    app.mount('/static', StaticFiles(directory=str(static_dir)), name='static')
SAMPLE_LOCATION={'mode':'coords','label':'Test Farm — San Diego, California','latitude':32.7157,'longitude':-117.1611,'resolution':'sample city-center coordinates'}
SAMPLE_PLAN={'total_area':5,'area_unit':'acres','notes':'Fictional Test Farm — for interface demonstration only','crops':[{'name':'Tomato','area':1.5,'stage':'Planning','planted_on':'','variety':''},{'name':'Corn','area':2,'stage':'Vegetative','planted_on':'2026-10-02','variety':''},{'name':'Potato','area':1,'stage':'Planning','planted_on':'','variety':''}]}

def is_sample(request:Request):
    return request.session.get('user',{}).get('mode')=='sample' if 'session' in request.scope else False

DEFAULT_LOCATION={'mode':'coords','label':'Demo — New York City','latitude':40.7128,'longitude':-74.006,'resolution':'sample coordinates'}
DEFAULT_PLAN={'total_area':5,'area_unit':'acres','notes':'','crops':[{'name':'Tomato','area':1.5,'stage':'Planning','planted_on':'','variety':''},{'name':'Corn','area':2,'stage':'Planning','planted_on':'','variety':''}]}

@app.get('/')
def home(): return FileResponse(ROOT/'public'/'index.html',headers={'Cache-Control':'no-store'})

@app.get('/api/health')
def health(): return {'ok':True,'service':'Cropoganda','sensor_storage_configured':sensor_configured(),'tigerdata_configured':tiger_enabled()}

@app.get('/api/overview')
def overview(request:Request,view:str='auto'):
    if is_sample(request):
        now=datetime.now(timezone.utc).isoformat()
        latest={'recorded_at':now,'device_id':'TEST-ESP32-NOT-CONNECTED','temperature_c':24.7,'humidity_pct':53.1,'pressure_hpa':1013.7,'altitude_m':-3.8,'rain_wetness_pct':5.1,'light_pct':62.7,'gas_index':22.2,'soil_moisture_pct':47.4}
        return {'state':'demo','latest':latest,'pi_connected':False,'cloud_connected':False,'last_reading_at':now,'last_cloud_sync':None,'pending_cloud':None,'cloud_record_count':0,'location':SAMPLE_LOCATION,'flags':[], 'sensor_source':'SYNTHETIC_SAMPLE'}
    user=request.session.get('user',{}) if 'session' in request.scope else {}
    snap,access=resolve_device_data(user['sub'],view) if user.get('mode')=='auth0' else (None,'none')
    latest=snap.get('latest') if snap else None
    age=age_seconds(latest)
    fresh=age is not None and age<15*60
    return {'state':'live' if fresh else 'stale' if latest else 'offline',
            'latest':latest,'pi_connected':bool(fresh),'cloud_connected':sensor_configured(),
            'last_reading_at':latest.get('recorded_at') if latest else None,
            'last_cloud_sync':snap.get('last_updated') if snap else None,'pending_cloud':None,
            'cloud_record_count':len(snap.get('readings',[])) if snap else 0,
            'location':DEFAULT_LOCATION,'flags':[],
            'sensor_source':'ESP32_SHARED_READONLY' if latest and access=='shared' else ('ESP32_TIGERDATA' if tiger_enabled() else 'ESP32_PRIVATE_BLOB') if latest else 'NONE',
            'sensor_access_mode':access}

@app.get('/api/recorded')
def recorded(request:Request,limit:int=100,offset:int=0,view:str='auto'):
    if is_sample(request):
        now=datetime.now(timezone.utc)
        rows=[{'recorded_at':(now-timedelta(hours=i)).isoformat(),'device_id':'TEST-ESP32-NOT-CONNECTED','temperature_c':round(23.7+i*.2,1),'humidity_pct':round(52+i*.6,1),'pressure_hpa':1013.7,'soil_moisture_pct':round(47+i*.7,1),'rain_wetness_pct':5.1,'light_pct':62.7,'gas_index':22.2,'altitude_m':-3.8} for i in range(12)]
        return {'readings':rows[offset:offset+min(limit,100)],'total':len(rows),'storage':'SYNTHETIC SAMPLE ONLY'}
    user=request.session.get('user',{}) if 'session' in request.scope else {}
    snap,access=resolve_device_data(user['sub'],view) if user.get('mode')=='auth0' else (None,'none')
    rows=snap.get('readings',[]) if snap else []
    offset=max(0,offset);limit=max(1,min(100,limit))
    return {'readings':rows[offset:offset+limit],'total':len(rows),
            'storage':('Shared read-only ESP32 history' if access=='shared' else 'Private Blob bounded history') if sensor_configured() else 'Cloud storage unavailable'}

@app.get('/api/charts')
def charts(request:Request,view:str='auto'):
    if is_sample(request):
        date=datetime.now(timezone.utc).date().isoformat()
        return {'local_days':{date:{'temperature_c':24.7,'humidity_pct':53.1,'pressure_hpa':1013.7,'soil_moisture_pct':47.4}},'nasa':None,'record_count':12,'source':'SYNTHETIC SAMPLE ONLY'}
    user=request.session.get('user',{}) if 'session' in request.scope else {}
    snap,access=resolve_device_data(user['sub'],view) if user.get('mode')=='auth0' else (None,'none')
    rows=snap.get('readings',[]) if snap else []
    return {'local_days':daily_averages(rows),'nasa':None,'record_count':len(rows),
            'source':('Shared ESP32 measurements' if access=='shared' else 'ESP32 measurements') if rows else 'No authenticated device readings'}

@app.get('/api/locations/catalog')
def locations(): return {'countries':catalog(),'note':'Preset city centers; precise locations require GPS coordinates.'}

@app.post('/api/location')
def location_api(payload:dict):
    try:
        if payload.get('mode')=='preset': result=resolve_preset(payload.get('country'),payload.get('region'),payload.get('city'))
        elif payload.get('mode')=='coords':
            lat,lon=valid_lat_lon(payload.get('latitude'),payload.get('longitude'))
            result={'mode':'coords','label':f'{lat:.4f}, {lon:.4f}','latitude':lat,'longitude':lon,'resolution':'explicit coordinates'}
        else:raise ValueError('Invalid location mode')
        return {'location':result,'saved':False,'storage':'browser only'}
    except (ValueError,TypeError) as exc:raise HTTPException(400,str(exc))

@app.get('/api/nasa')
def nasa(request:Request,mode:str='auto',days:int=90,latitude:float=40.7128,longitude:float=-74.006):
    try:lat,lon=valid_lat_lon(latitude,longitude)
    except (ValueError,TypeError) as exc:raise HTTPException(400,str(exc))
    if mode=='auto':return {'nasa_daily':None,'note':'No server-side cache; browser keeps fetched regional history.'}
    if not 14<=days<=120:raise HTTPException(400,'days must be 14–120')
    loc={'latitude':lat,'longitude':lon}
    if mode=='demo': return {'nasa_daily':demo_nasa_daily(loc,days),'note':'Synthetic demonstration data; not NASA observations'}
    if mode!='real': raise HTTPException(400,'Unsupported mode')
    try:
        history=fetch_nasa_daily(loc,days=days)
        stored=0
        note='Real historical NASA POWER regional data'
        if tiger_enabled():
            user=request.session.get('user',{}) if 'session' in request.scope else {}
            if user.get('mode')=='auth0' and user.get('sub') and history.get('is_real_nasa'):
                try:
                    stored=tiger_save_nasa(user['sub'],lat,lon,history.get('rows') or [])
                    note+=' · '+str(stored)+' daily rows stored in TigerData'
                except HTTPException:
                    note+=' · TigerData history storage unavailable'
        return {'nasa_daily':history,'note':note,'tigerdata_stored_days':stored}
    except Exception as exc:
        raise HTTPException(502,'NASA POWER could not be retrieved: '+str(exc)[:180])

WEATHER_CODES={0:'Clear',1:'Mostly clear',2:'Partly cloudy',3:'Overcast',45:'Fog',48:'Fog',51:'Drizzle',53:'Drizzle',55:'Drizzle',61:'Rain',63:'Rain',65:'Heavy rain',71:'Snow',73:'Snow',75:'Heavy snow',80:'Showers',81:'Showers',82:'Heavy showers',95:'Thunderstorm',96:'Thunderstorm',99:'Thunderstorm'}

def forecast(lat,lon):
    u='https://api.open-meteo.com/v1/forecast?'+urlencode({'latitude':lat,'longitude':lon,'timezone':'auto','forecast_days':7,'daily':'temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,wind_speed_10m_max,weather_code'})
    data=http_json('GET',u,timeout=13).get('daily',{})
    records=[]
    for i,day in enumerate(data.get('time',[])):
        def v(k): return data.get(k,[None]*7)[i]
        records.append({'date':day,'high_c':v('temperature_2m_max'),'low_c':v('temperature_2m_min'),'rain_chance_pct':v('precipitation_probability_max'),'precipitation_mm':v('precipitation_sum'),'wind_kmh':v('wind_speed_10m_max'),'summary':WEATHER_CODES.get(v('weather_code'),'Mixed weather')})
    return records

@app.get('/api/weather')
def weather(mode:str='live',latitude:float=40.7128,longitude:float=-74.006):
    try: lat,lon=valid_lat_lon(latitude,longitude)
    except (ValueError,TypeError) as exc:raise HTTPException(400,str(exc))
    if mode!='live':raise HTTPException(400,'Only live weather forecasts are supported')
    loc={'latitude':lat,'longitude':lon,'label':f'{lat:.3f}, {lon:.3f}'}
    errors=[]
    try: upcoming=forecast(lat,lon)
    except Exception as ex:upcoming=[];errors.append('Forecast unavailable: '+str(ex)[:120])
    try: alerts=official_alerts(loc)
    except Exception as ex:alerts={'status':'unavailable','alerts':[],'message':'Official alert service could not be checked'};errors.append('Weather alert service unavailable')
    return {'mode':'live','forecast':upcoming,'forecast_source':'Open-Meteo forecast — separate from NASA POWER', 'alert_status':alerts,'location':loc,'errors':errors}

@app.get('/api/plan')
def plan(request:Request):return SAMPLE_PLAN if is_sample(request) else DEFAULT_PLAN

def validate_plan(p):
    if not isinstance(p,dict):raise ValueError('Invalid plan')
    unit=p.get('area_unit','acres')
    if unit not in ('acres','hectares'):raise ValueError('Invalid area unit')
    try:total=float(p.get('total_area',0))
    except (ValueError,TypeError):raise ValueError('Invalid farm area')
    if not math.isfinite(total) or not 0<total<1e8:raise ValueError('Enter a valid farm area')
    crops=p.get('crops')
    if not isinstance(crops,list) or not 1<=len(crops)<=30:raise ValueError('Enter 1–30 crops')
    used=0;clean=[]
    for row in crops:
        if not isinstance(row,dict):raise ValueError('Invalid crop')
        name=str(row.get('name','')).strip()[:70]
        try: area=float(row.get('area',0))
        except (ValueError,TypeError):raise ValueError('Invalid crop area')
        if not name or not math.isfinite(area) or area<=0:raise ValueError('Each crop requires a name and positive area')
        planted=str(row.get('planted_on','')).strip()[:10]
        if planted:
            try:datetime.strptime(planted,'%Y-%m-%d')
            except ValueError:raise ValueError('Planting date must use YYYY-MM-DD')
        used+=area
        clean.append({'name':name,'area':area,'stage':str(row.get('stage','Planning'))[:50],'variety':str(row.get('variety',''))[:80],'planted_on':planted})
    if used>total+1e-6:raise ValueError('Total crop allocations exceed farm area')
    return {'total_area':total,'area_unit':unit,'notes':str(p.get('notes',''))[:1500],'crops':clean,'unallocated_area':round(total-used,3)}

@app.post('/api/plan')
def plan_validate(payload:dict):
    try:p=validate_plan(payload)
    except ValueError as exc:raise HTTPException(400,str(exc))
    return {'saved':False,'plan':p,'storage':'Browser-only in Vercel preview'}

@app.get('/api/calendar')
def calendar(): return {'events':[],'storage':'browser only'}

def gemini_approved(user:dict)->bool:
    """All signed-in Auth0 accounts may use Gemini; the Auth0 callback
    only creates these signed sessions after verifying the email address.
    Public sample sessions never qualify.
    """
    return (user.get('mode') == 'auth0'
            and bool(user.get('sub'))
            and bool(user.get('email')))

@app.get('/api/gemini/status')
def gemini_status(request:Request):
    available=bool(os.environ.get('GEMINI_API_KEY','').strip())
    user=request.session.get('user',{}) if 'session' in request.scope else {}
    sample=user.get('mode')=='sample'
    eligible=gemini_approved(user)
    return {'configured':bool(sample or (available and eligible)),
            'model':DEFAULT_GEMINI_MODEL,
            'mode':'sample' if sample else 'live' if available and eligible else 'unavailable',
            'note':('Fixed sample guidance; no Gemini request.' if sample else
                    'Gemini is ready for your verified Auth0 account.' if available and eligible else
                    'Gemini API key is not configured.' if eligible else
                    'Sign in using your verified Auth0 account.')}


class AdviceRequest(BaseModel):
    plan:dict
    question:str=Field(default='',max_length=2500)
    model:str=DEFAULT_GEMINI_MODEL
    location:dict=Field(default_factory=dict)
    nasa_excerpt:list[dict]=Field(default_factory=list)
    upcoming_calendar_tasks:list[dict]=Field(default_factory=list)
    weather_mode:str='live'
    sensor_view:str='auto'

@app.post('/api/plan/advice')
def farming_advice(req:AdviceRequest,request:Request):
    return answer_question(req,request,validate_plan,forecast,official_alerts,
                           fetch_nasa_daily,generate_gemini_reply,DEFAULT_GEMINI_MODEL,valid_lat_lon)

# ESP32 uses authenticated, account-isolated private Blob uploads. TigerData is a future upgrade.
from auth0_integration import install_auth
AUTH_SETTINGS=install_auth(app)
install_device_routes(app)
install_history_routes(app)

# Text messages (Twilio): alerts, reminders, STATUS and Fieldy by SMS. See sms.py / TWILIO_SETUP.md
from sms import install_sms_routes
install_sms_routes(app, generate_gemini_reply, DEFAULT_GEMINI_MODEL, forecast)
