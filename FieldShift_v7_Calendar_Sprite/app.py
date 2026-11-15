"""FieldShift Vercel edition. Stateless FastAPI; private data lives in browser only for preview.
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

ROOT=Path(__file__).resolve().parent
load_dotenv(ROOT/'.env',override=False)
app=FastAPI(title='FieldShift — production demo', docs_url=None, redoc_url=None)
app.mount('/static',StaticFiles(directory=str(ROOT/'public'/'static')),name='static')
SAMPLE_LOCATION={'mode':'coords','label':'Test Farm — San Diego, California','latitude':32.7157,'longitude':-117.1611,'resolution':'sample city-center coordinates'}
SAMPLE_PLAN={'total_area':5,'area_unit':'acres','notes':'Fictional Test Farm — for interface demonstration only','crops':[{'name':'Tomato','area':1.5,'stage':'Planning','planted_on':'','variety':''},{'name':'Corn','area':2,'stage':'Vegetative','planted_on':'2026-10-02','variety':''},{'name':'Potato','area':1,'stage':'Planning','planted_on':'','variety':''}]}

def is_sample(request:Request):
    return request.session.get('user',{}).get('mode')=='sample' if 'session' in request.scope else False

DEFAULT_LOCATION={'mode':'coords','label':'Demo — New York City','latitude':40.7128,'longitude':-74.006,'resolution':'sample coordinates'}
DEFAULT_PLAN={'total_area':5,'area_unit':'acres','notes':'','crops':[{'name':'Tomato','area':1.5,'stage':'Planning','planted_on':'','variety':''},{'name':'Corn','area':2,'stage':'Planning','planted_on':'','variety':''}]}

@app.get('/')
def home(): return FileResponse(ROOT/'public'/'index.html',headers={'Cache-Control':'no-store'})

@app.get('/api/health')
def health(): return {'ok':True,'service':'FieldShift Vercel stateless preview','sensor_connected':False}

@app.get('/api/overview')
def overview(request:Request):
    if is_sample(request):
        now=datetime.now(timezone.utc).isoformat()
        latest={'recorded_at':now,'device_id':'TEST-ESP32-NOT-CONNECTED','temperature_c':24.7,'humidity_pct':53.1,'pressure_hpa':1013.7,'altitude_m':-3.8,'rain_wetness_pct':5.1,'light_pct':62.7,'gas_index':22.2,'soil_moisture_pct':47.4}
        return {'state':'demo','latest':latest,'pi_connected':False,'cloud_connected':False,'last_reading_at':now,'last_cloud_sync':None,'pending_cloud':None,'cloud_record_count':0,'location':SAMPLE_LOCATION,'flags':[], 'sensor_source':'SYNTHETIC_SAMPLE'}
    return {'state':'offline','latest':None,'pi_connected':False,'cloud_connected':False,'last_reading_at':None,'last_cloud_sync':None,'pending_cloud':None,'cloud_record_count':None,'location':DEFAULT_LOCATION,'flags':[], 'sensor_source':'NONE'}

@app.get('/api/recorded')
def recorded(request:Request,limit:int=100,offset:int=0):
    if is_sample(request):
        now=datetime.now(timezone.utc)
        rows=[{'recorded_at':(now-timedelta(hours=i)).isoformat(),'device_id':'TEST-ESP32-NOT-CONNECTED','temperature_c':round(23.7+i*.2,1),'humidity_pct':round(52+i*.6,1),'pressure_hpa':1013.7,'soil_moisture_pct':round(47+i*.7,1),'rain_wetness_pct':5.1,'light_pct':62.7,'gas_index':22.2,'altitude_m':-3.8} for i in range(12)]
        return {'readings':rows[offset:offset+min(limit,100)],'total':len(rows),'storage':'SYNTHETIC SAMPLE ONLY'}
    return {'readings':[],'total':0,'storage':'Awaiting TigerData integration'}

@app.get('/api/charts')
def charts(request:Request):
    if is_sample(request):
        date=datetime.now(timezone.utc).date().isoformat()
        return {'local_days':{date:{'temperature_c':24.7,'humidity_pct':53.1,'pressure_hpa':1013.7,'soil_moisture_pct':47.4}},'nasa':None,'record_count':12,'source':'SYNTHETIC SAMPLE ONLY'}
    return {'local_days':{},'nasa':None,'record_count':0,'source':'No ESP32 connection yet'}

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
def nasa(mode:str='auto',days:int=90,latitude:float=40.7128,longitude:float=-74.006):
    try:lat,lon=valid_lat_lon(latitude,longitude)
    except (ValueError,TypeError) as exc:raise HTTPException(400,str(exc))
    if mode=='auto':return {'nasa_daily':None,'note':'No server-side cache; browser keeps fetched regional history.'}
    if not 14<=days<=120:raise HTTPException(400,'days must be 14–120')
    loc={'latitude':lat,'longitude':lon}
    if mode=='demo': return {'nasa_daily':demo_nasa_daily(loc,days),'note':'Synthetic demonstration data; not NASA observations'}
    if mode!='real': raise HTTPException(400,'Unsupported mode')
    try:
        return {'nasa_daily':fetch_nasa_daily(loc,days=days),'note':'Real historical NASA POWER regional data'}
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
    if mode not in ('live','demo'):raise HTTPException(400,'mode must be live or demo')
    loc={'latitude':lat,'longitude':lon,'label':f'{lat:.3f}, {lon:.3f}'}
    if mode=='demo':
        # Explicit demo option remains available for offline rehearsals.
        return {'mode':'demo','forecast':[], 'forecast_source':'No real forecast selected (demo mode)', 'alert_status':demo_alerts(loc),'location':loc}
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

@app.get('/api/gemini/status')
def gemini_status(request:Request):
    available=bool(os.environ.get('GEMINI_API_KEY','').strip())
    user=request.session.get('user',{}) if 'session' in request.scope else {}
    sample=user.get('mode')=='sample'
    return {'configured':bool(sample or (available and user.get('mode')=='auth0')),
            'model':DEFAULT_GEMINI_MODEL,'mode':'sample' if sample else 'live' if available and user.get('mode')=='auth0' else 'unavailable',
            'note':'Sample advice is a fixed demonstration, not Gemini.' if sample else 'Real Gemini advice requires an approved Auth0 login.'}

class AdviceRequest(BaseModel):
    plan:dict
    question:str=Field(default='',max_length=500)
    model:str=DEFAULT_GEMINI_MODEL
    location:dict=Field(default_factory=dict)
    nasa_excerpt:list[dict]=Field(default_factory=list)
    upcoming_calendar_tasks:list[dict]=Field(default_factory=list)
    weather_mode:str='live'

@app.post('/api/plan/advice')
def farming_advice(req:AdviceRequest,request:Request):
    user=request.session.get('user',{}) if 'session' in request.scope else {}
    if user.get('mode')=='sample':
        p=validate_plan(req.plan)
        crops=[{'name':x['name'],'next_step':'Check crop condition and add a planting date or variety for a better timeline.','timing':'Planning example'} for x in p['crops']]
        return {'advice_structured':{'headline':'Review your sample crop plans before your next field visit.',
           'actions':[{'title':'Check drainage','detail':'Inspect low areas before watering.'},{'title':'Add planting dates','detail':'Enter dates and varieties to improve the growing timeline.'}],
           'crops':crops,'weather_watch':'Download a live forecast in the NASA tab before making decisions.',
           'data_note':'Example guidance only; sensor readings are fictional and no Gemini call was made.'},
           'created_at':datetime.now(timezone.utc).isoformat(),'model':'sample-advice','data_mode':'synthetic','provider':'demo'}
    # Paid model calls are restricted to approved Auth0 accounts only.
    if user.get('mode')!='auth0': raise HTTPException(403,'An approved Auth0 login is required to use Gemini.')
    key=os.environ.get('GEMINI_API_KEY','').strip()
    if not key:raise HTTPException(503,'Gemini has not been configured on this deployment.')
    if req.model!=DEFAULT_GEMINI_MODEL:raise HTTPException(400,'Unsupported model')
    try:p=validate_plan(req.plan);lat,lon=valid_lat_lon(req.location.get('latitude'),req.location.get('longitude'))
    except (ValueError,TypeError) as exc:raise HTTPException(400,str(exc))
    # Weather is fetched server-side; previous UI-provided NASA records are unverified context.
    try:f=forecast(lat,lon)
    except Exception:f=[]
    nasa_rows=[]
    for row in req.nasa_excerpt[-12:]:
        if not isinstance(row,dict):continue
        nasa_rows.append({k:row.get(k) for k in ('date','temperature_c','temperature_max_c','temperature_min_c','precipitation_mm','humidity_pct')})
    context={'location':{'latitude':lat,'longitude':lon,'label':str(req.location.get('label',''))[:100]},'farm':p,
       'current_sensors':'NOT CONNECTED: No ESP32 sensor measurements are available',
       'nasa_recent':'USER-BROWSER CACHED REGIONAL OBSERVATIONS (unverified; not current weather)' if nasa_rows else 'NOT LOADED',
       'nasa_daily_history':nasa_rows,'weather_forecast_source':'Open-Meteo (if available)','forecast':f[:5],
       'tasks':req.upcoming_calendar_tasks[:15], 'question':req.question}
    prompt=('You are Fieldy, a friendly, precise agricultural assistant. Return ONLY a JSON object, no markdown, no headers or disclaimers. '
      'Keys: headline (short friendly sentence), actions (array of 2–4 objects with title and detail), crops (array of objects with name, next_step, timing), weather_watch (one sentence), data_note (one sentence). '
      'Use simple everyday language, practical next actions, max 25 words per field, no more than 4 actions. '
      'Include every crop, no fabricated harvest dates, soil tests, growth percentages, yield or official weather warnings. '
      'If planting dates/cultivars are missing, say what information is needed instead of inventing a date. '
      'NASA POWER is historical regional context, not a forecast; current sensor readings are unavailable. '
      'Explain uncertainties once, only in data_note. Be concise, warm and realistic. '
      'Never claim imminent severe weather unless verified by official sources. Context follows: '+json.dumps(context,ensure_ascii=False,default=str))
    try:
        raw=generate_gemini_reply(key,prompt,model=DEFAULT_GEMINI_MODEL,json_mode=True)
        cleaned=raw.strip().removeprefix('```json').removeprefix('```').removesuffix('```').strip()
        obj=json.loads(cleaned)
        if not isinstance(obj,dict):raise ValueError('Expected structured advice')
        def short(v,n=220):return str(v or '').strip()[:n]
        result={'headline':short(obj.get('headline'),130),
          'actions':[{'title':short(x.get('title'),90),'detail':short(x.get('detail'),210)} for x in (obj.get('actions') or [])[:4] if isinstance(x,dict)],
          'crops':[{'name':short(x.get('name'),70),'next_step':short(x.get('next_step'),180),'timing':short(x.get('timing'),140)} for x in (obj.get('crops') or [])[:30] if isinstance(x,dict)],
          'weather_watch':short(obj.get('weather_watch'),240),'data_note':short(obj.get('data_note'),250)}
        if not result['headline']:raise ValueError('Missing headline')
        return {'advice_structured':result,'created_at':datetime.now(timezone.utc).isoformat(),'model':DEFAULT_GEMINI_MODEL,'data_mode':'live' if f else 'unavailable'}
    except Exception:raise HTTPException(502,'Gemini could not create concise advice. Please try again or check the model and backend logs.')

# Public website has no device upload endpoint: ESP32 uploads and TigerData require user/device auth and durable storage.
from auth0_integration import install_auth
AUTH_SETTINGS=install_auth(app)
