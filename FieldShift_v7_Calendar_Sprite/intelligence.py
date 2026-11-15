"""Cropaganda v3: source-tagged NASA series, official alerts, charts and cautious farm advice.

NASA observations are REGIONAL, often delayed, and are not a weather forecast.
Synthetic series/alerts are always explicitly tagged demo.
"""
from __future__ import annotations
import json
import math
import os
import random
import statistics
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from fieldshift_core import http_json, utc_now, NASA_URL, VALUE_FIELDS, validate_reading

NASA_FIELDS = ['temperature_c','humidity_pct','pressure_hpa','precipitation_mm','solar_mj_m2_day','soil_wetness_fraction']
LOCAL_NASA_MAP = {
 'temperature_c': ('temperature_c', 'Air temperature', '°C', 'same'),
 'humidity_pct': ('humidity_pct', 'Relative humidity', '%', 'same'),
 'pressure_hpa': ('pressure_hpa', 'Surface pressure', 'hPa', 'same'),
 'rain_wetness_pct': ('precipitation_mm', 'Rain plate vs precipitation', 'index / mm per day', 'dual'),
 'light_pct': ('solar_mj_m2_day', 'Photoresistor vs solar energy', 'index / MJ m⁻² day⁻¹', 'dual'),
 'soil_moisture_pct': ('soil_wetness_fraction', 'Soil moisture index vs regional modeled soil wetness', 'index / fraction', 'dual'),
 'altitude_m': (None, 'Pressure-derived altitude estimate', 'm', 'local'),
 'gas_index': (None, 'Uncalibrated gas sensor index', 'index', 'local')
}


def _clean(v):
    try:
        f=float(v)
        return round(f,4) if math.isfinite(f) and f > -900 else None
    except (ValueError,TypeError):
        return None


def fetch_nasa_daily(location, days=45):
    """Actual NASA POWER daily API with optional separate HY modeled soil wetness."""
    days=max(10,min(int(days),180))
    # POWER daily near-real-time records may lag the current day.
    # Request through three days ago and leave any unavailable values blank.
    end=(datetime.now(timezone.utc).date()-timedelta(days=3))
    start=end-timedelta(days=days-1)
    common={'latitude':location['latitude'],'longitude':location['longitude'],
            'start':start.strftime('%Y%m%d'),'end':end.strftime('%Y%m%d'),
            'format':'JSON','time-standard':'UTC'}
    main=http_json('GET',NASA_URL+'?'+urlencode({**common,'community':'AG',
         'parameters':'T2M,T2M_MAX,T2M_MIN,T2MDEW,RH2M,PS,PRECTOTCORR,ALLSKY_SFC_SW_DWN,WS2M,WS10M'}), timeout=33)
    params=main['properties']['parameter']
    if not params.get('T2M'):
        raise ValueError('NASA POWER returned no daily temperature series.')
    moisture={}
    moisture_status='Unavailable (modeled wetness layer not retrieved)'
    try:
        if os.getenv('FIELDSHIFT_SOIL_LAYER','0') != '1':
            raise RuntimeError('Optional soil layer disabled to keep API responsive')
        hydro=http_json('GET',NASA_URL+'?'+urlencode({**common,'community':'HY','parameters':'GWETTOP'}), timeout=12)
        moisture=hydro['properties']['parameter'].get('GWETTOP',{})
        if moisture:moisture_status='NASA POWER modeled top-layer soil wetness (fraction, not calibrated ESP32 moisture)'
    except Exception:
        pass  # Optional extra query must not prevent climate-data access.
    rows=[]
    for date_str,t in sorted(params['T2M'].items()):
        if not str(date_str).isdigit() or len(str(date_str))!=8:continue
        item={'date':f'{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}',
              'temperature_c':_clean(t),'temperature_max_c':_clean(params.get('T2M_MAX',{}).get(date_str)),
              'temperature_min_c':_clean(params.get('T2M_MIN',{}).get(date_str)),
              'dew_point_c':_clean(params.get('T2MDEW',{}).get(date_str)),
              'wind_2m_ms':_clean(params.get('WS2M',{}).get(date_str)),
              'wind_10m_ms':_clean(params.get('WS10M',{}).get(date_str)),
              'humidity_pct':_clean(params.get('RH2M',{}).get(date_str)),
              'pressure_hpa':_clean(params.get('PS',{}).get(date_str)),
              'precipitation_mm':_clean(params.get('PRECTOTCORR',{}).get(date_str)),
              'solar_mj_m2_day':_clean(params.get('ALLSKY_SFC_SW_DWN',{}).get(date_str)),
              'soil_wetness_fraction':_clean(moisture.get(date_str))}
        if item['pressure_hpa'] is not None:
            item['pressure_hpa']=round(item['pressure_hpa']*10,2)  # kPa to hPa
        rows.append(item)
    if len([r for r in rows if r['temperature_c'] is not None])<8:
        raise RuntimeError('NASA returned fewer than eight usable days. Try again later.')
    return {'source':'NASA POWER DAILY (real regional historical observations/model estimates)',
            'is_real_nasa':True,'demo':False,'latitude':location['latitude'],
            'longitude':location['longitude'],'fetched_at':utc_now(),
            'period':f'{start.isoformat()} through {end.isoformat()}',
            'units':{'temperature_c':'°C','humidity_pct':'%','pressure_hpa':'hPa',
                     'precipitation_mm':'mm/day','solar_mj_m2_day':'MJ/m²/day','soil_wetness_fraction':'0–1 modeled fraction',
                     'temperature_max_c':'°C','temperature_min_c':'°C','dew_point_c':'°C',
                     'wind_2m_ms':'m/s','wind_10m_ms':'m/s'},
            'soil_note':moisture_status,'rows':rows}


def demo_nasa_daily(location, days=35, today=None):
    """Clearly synthetic NASA-LIKE chart fixture; never claim these are NASA observations."""
    today=today or datetime.now(timezone.utc).date()
    rng=random.Random(524)
    rows=[]
    for index in range(days):
        date=today-timedelta(days=days-1-index)
        cyc=math.sin(index/6)
        rain=max(0,round(rng.gauss(2.2,3.0),2))
        rows.append({'date':date.isoformat(), 'temperature_c':round(20+4*cyc+rng.uniform(-1,1),2),
                     'temperature_max_c':round(24+4*cyc+rng.uniform(-1,1),2),
                     'temperature_min_c':round(15+4*cyc+rng.uniform(-1,1),2),
                     'dew_point_c':round(12+2*cyc+rng.uniform(-1,1),2),
                     'wind_2m_ms':round(2.5+rng.uniform(0,1.5),2),
                     'wind_10m_ms':round(4+rng.uniform(0,2),2),
                     'humidity_pct':round(61-7*cyc+rng.uniform(-4,4),1),
                     'pressure_hpa':round(1011.8+rng.uniform(-6,6),2),
                     'precipitation_mm':rain,
                     'solar_mj_m2_day':round(max(0,16+5*cyc-rain*.6),2),
                     'soil_wetness_fraction':round(max(0.1,min(0.9,0.46+0.13*math.sin(index/8)+rng.uniform(-0.03,.03))),3)})
    return {'source':'SYNTHETIC DEMO NASA-LIKE FIXTURE — NOT NASA DATA','is_real_nasa':False,
            'demo':True,'latitude':location['latitude'],'longitude':location['longitude'],
            'period':f'{rows[0]["date"]} through {rows[-1]["date"]}',
            'fetched_at':utc_now(),'soil_note':'SYNTHETIC modeled wetness for chart testing',
            'rows':rows}


def seed_demo_history(db, days=35, today=None):
    """Add one synthetic local reading per day for chart comparison testing; deduplicated."""
    today=today or datetime.now(timezone.utc).date()
    rng=random.Random(815)
    inserted=0
    for idx in range(days):
        day=today-timedelta(days=days-1-idx)
        cyc=math.sin(idx/6)
        # Stable UUID for repeated test runs on the same day.
        rid=str(uuid.uuid5(uuid.NAMESPACE_DNS, f'fieldshift-v3-demo-{day.isoformat()}'))
        r={'id':rid,'device_id':'esp32-history-demo','recorded_at':day.isoformat()+'T12:00:00+00:00',
           'source':'simulated_esp32','temperature_c':round(20.7+4*cyc+rng.uniform(-1.1,1.1),2),
           'humidity_pct':round(60-7*cyc+rng.uniform(-5,5),1),
           'pressure_hpa':round(1012.3+rng.uniform(-6,6),2),
           'altitude_m':round(44330*(1-(1012.3/1013.25)**.1903),1),
           'rain_wetness_pct':round(max(0,min(100,rng.uniform(5,90))),1),
           'light_pct':round(max(0,min(100,64+16*cyc+rng.uniform(-10,10))),1),
           'gas_index':round(18+rng.uniform(-4,4),1),
           'soil_moisture_pct':round(max(10,min(90,44+12*math.sin(idx/8)+rng.uniform(-3,3))),1)}
        inserted+=bool(db.save_reading(r))
    return inserted


def aggregate_local_by_day(readings):
    buckets=defaultdict(lambda: defaultdict(list))
    for record in readings:
        day=str(record.get('recorded_at',''))[:10]
        if len(day)!=10:continue
        for key in VALUE_FIELDS:
            val=record.get(key)
            if val is not None:
                try:buckets[day][key].append(float(val))
                except (TypeError,ValueError):pass
    return {day:{k:round(statistics.mean(v),3) for k,v in fields.items()}
            for day,fields in buckets.items()}


def local_flags(readings):
    """Sensor-derived farm flags only. Not official severe-weather alerts."""
    if not readings:return []
    latest=readings[0]
    flags=[]
    def add(level,label,detail):flags.append({'level':level,'event':label,'description':detail,'source':'LOCAL SENSOR RULE'})
    if latest.get('temperature_c') is not None and latest['temperature_c']>=35:
        add('Warning','High local temperature','Check crop-specific heat stress and irrigation needs; confirm sensor placement.')
    if latest.get('soil_moisture_pct') is not None and latest['soil_moisture_pct']<25:
        add('Advisory','Low soil-moisture index','Recheck calibration and actual root-zone moisture before watering.')
    if latest.get('rain_wetness_pct') is not None and latest['rain_wetness_pct']>=75:
        add('Advisory','Rain plate wet','A wet detector does not measure rainfall amount or predict storms.')
    return flags


def official_alerts(location):
    """US NWS active alert point API; a failed check is never interpreted as 'no warnings'."""
    lat,lon=location['latitude'],location['longitude']
    url='https://api.weather.gov/alerts/active?'+urlencode({'point':f'{lat:.5f},{lon:.5f}'})
    headers={'User-Agent':os.getenv('FIELDSHIFT_NWS_USER_AGENT', 'CropagandaLocalPrototype/0.3 (educational demo)'),
             'Accept':'application/geo+json'}
    try:
        payload=http_json('GET',url,headers=headers,timeout=18)
        features=payload.get('features',[])
        alerts=[]
        for feature in features[:50]:
            p=feature.get('properties') or {}
            alerts.append({'id':str(p.get('id') or feature.get('id') or ''),
               'event':str(p.get('event') or 'Weather alert'),
               'severity':str(p.get('severity') or 'Unknown'),
               'headline':str(p.get('headline') or '')[:500],
               'description':str(p.get('description') or '')[:1500],
               'instruction':str(p.get('instruction') or '')[:1200],
               'effective':p.get('effective'), 'expires':p.get('expires'),
               'sender':str(p.get('senderName') or 'National Weather Service')[:200]})
        return {'status':'live','source':'NATIONAL WEATHER SERVICE (official US active alerts)',
                'fetched_at':utc_now(),'point':[lat,lon],'alerts':alerts,
                'message':('No active official alerts returned for this point at the last successful check.'
                         if not alerts else f'{len(alerts)} active official alert(s) returned.'),
                'warning':'This application is a prototype. Never rely on it as the sole emergency warning source.'}
    except Exception as ex:
        return {'status':'unavailable','source':'NWS alert check unavailable / geographic coverage may be unsupported',
                'fetched_at':utc_now(),'point':[lat,lon],'alerts':[],
                'message':f'COULD NOT VERIFY OFFICIAL ALERTS: {ex}',
                'warning':'No active alerts cannot be concluded. Consult the official meteorological service.'}


def demo_alerts(location):
    return {'status':'demo','source':'SYNTHETIC TRAINING ALERT — NOT AN OFFICIAL WARNING',
            'fetched_at':utc_now(),'point':[location['latitude'],location['longitude']],
            'alerts':[{'id':'simulation-demo-01','event':'DEMO: Heavy Rain Watch',
                       'severity':'Moderate', 'headline':'TEST ONLY — synthetic heavy rain scenario',
                       'description':'This example exists only to demonstrate the alert interface.',
                       'instruction':'TEST ONLY. No real emergency action is indicated.',
                       'effective':utc_now(),'expires':None,'sender':'CROPOGANDA SIMULATOR'}],
            'message':'TRAINING MODE: This is not an active meteorological alert.',
            'warning':'Always consult actual official weather warnings for safety.'}


def empty_alert_status():
    return {'status':'unchecked','source':'none','fetched_at':None,'alerts':[],
            'message':'Official warnings not checked yet. Alert status UNKNOWN.'}


def farm_offline_advice(readings, nasa_daily, alerts, crop='unspecified crop', stage='unknown'):
    lines=['OFFLINE FARM ADVICE — HEURISTIC DEMO, NOT A WEATHER FORECAST',
           f'Crop: {crop or "unspecified"}  |  Growth stage: {stage or "unknown"}']
    if not readings:return '\n'.join(lines+['No local readings available.'])
    r=readings[0]
    lines.append(f"Latest local measurement: {r.get('temperature_c','?')} °C, humidity {r.get('humidity_pct','?')} %, soil index {r.get('soil_moisture_pct','?')}/100.")
    if nasa_daily:
        rows=nasa_daily.get('rows',[])
        vals=[x['temperature_c'] for x in rows if x.get('temperature_c') is not None]
        label='REAL NASA historical' if nasa_daily.get('is_real_nasa') else 'SYNTHETIC NASA-like test'
        if vals:lines.append(f'{label} period mean temperature: {statistics.mean(vals):.1f} °C across {len(vals)} regional daily values.')
    else:lines.append('NASA observations not loaded.')
    alerts=alerts or empty_alert_status()
    lines.append('Official warnings: '+alerts.get('message','not checked'))
    if r.get('soil_moisture_pct') is not None and r['soil_moisture_pct']<30:
        lines.append('Action: inspect soil at root depth, verify probe calibration, then consider irrigation according to crop needs.')
    elif r.get('soil_moisture_pct') is not None:
        lines.append('Action: continue soil monitoring; a moisture index alone does not prove irrigation is needed.')
    if r.get('temperature_c') is not None and r['temperature_c']>=32:
        lines.append('Action: monitor crop-specific heat exposure and irrigation demand.')
    lines.append('Limitation: no verified future storm timing, rainfall probability or yield forecast. Check official forecasts and crop requirements.')
    return '\n\n'.join(lines)


def gemini_farm_advice(readings,nasa_daily,alerts,location,crop,stage,api_key,model='gemini-3.5-flash-lite',question='Give three practical field actions.'):
    if not api_key:raise ValueError('Provide GEMINI_API_KEY or enter your key in the GUI.')
    if not readings:raise ValueError('No local readings available.')
    # Minimize data transmitted. Coordinates are user-set; explicit opt-in occurs when button pressed.
    nasa_rows=(nasa_daily or {}).get('rows',[])
    payload={'location':location,'farmer':{'crop':crop,'growth_stage':stage},
       'local_readings_recent':[{k:r.get(k) for k in ('recorded_at','source',*VALUE_FIELDS)} for r in readings[:24]],
       'regional_nasa':{'source':(nasa_daily or {}).get('source'),
          'is_real_nasa':(nasa_daily or {}).get('is_real_nasa',False),'rows':nasa_rows[-40:]},
       'official_weather_alerts':{'status':(alerts or {}).get('status','unchecked'),
          'fetched_at':(alerts or {}).get('fetched_at'),
          'alerts':[{k:a.get(k) for k in ('event','severity','instruction','expires')} for a in (alerts or {}).get('alerts',[])[:5]]},
       'farmer_question':question[:800]}
    prompt='''You are Cropaganda, a cautious agriculture decision-support assistant. User JSON follows.
Give: 1) Observed local conditions; 2) Regional NASA historical context; 3) Weather alert status (only those explicitly provided); 4) Up to 3 conditional crop management recommendations with why; 5) Uncertainties and missing data.
Rules: Distinguish observed data from synthetic testing fixtures. Never claim demo NASA data is real. Never invent official weather alerts, future storm timings, precipitation probabilities or guaranteed crop outcomes. NASA historical data is NOT a short-term forecast. If alert status is unchecked/unavailable, say official warning status UNKNOWN and refer user to authoritative alerts. A wet rain plate is not mm of rainfall; LDR % is not solar MJ/m²; cheap gas index is not a calibrated gas concentration; cheap soil moisture index is not the same as regional modeled soil wetness. Sea-level-altitude estimate isn't independent data. No instruction to bypass evacuation/official warnings. If no forecast feed is present, do not make a deterministic weather prediction. If evidence is insufficient for a crop-specific recommendation, explicitly say what needs checking.
USER DATA:\n'''+json.dumps(payload,ensure_ascii=False)
    from gemini_client import generate_gemini_reply
    return generate_gemini_reply(api_key, prompt, model)


def draw_comparison_figure(local_readings, nasa_daily, figure):
    """Eight small multiples: overlay only comparable units, dual axes otherwise."""
    figure.clear()
    local_days=aggregate_local_by_day(local_readings)
    regional={r['date']:r for r in (nasa_daily or {}).get('rows',[])}
    keys=list(LOCAL_NASA_MAP)
    axes=figure.subplots(4,2)
    from matplotlib.dates import AutoDateLocator, ConciseDateFormatter
    dates=sorted(set(local_days)|set(regional))
    # Keep relevant last 45 days; avoid old unrelated time spans when restoring older local stores.
    if len(dates)>45:dates=dates[-45:]
    for i,key in enumerate(keys):
        ax=axes[i//2][i%2]
        other,title,unit,mode=LOCAL_NASA_MAP[key]
        ldates=[datetime.fromisoformat(x) for x in dates if local_days.get(x,{}).get(key) is not None]
        lvalues=[local_days[x][key] for x in dates if local_days.get(x,{}).get(key) is not None]
        if lvalues:ax.plot(ldates,lvalues,color='#25a67a',lw=1.75,marker='.',markersize=3,label='ESP32 (daily local)')
        if other:
            ndates=[datetime.fromisoformat(x) for x in dates if regional.get(x,{}).get(other) is not None]
            nvalues=[regional[x][other] for x in dates if regional.get(x,{}).get(other) is not None]
            if nvalues:
                target=ax if mode=='same' else ax.twinx()
                target.plot(ndates,nvalues,color='#579ad6',lw=1.5,linestyle='--',marker='.',markersize=3,
                            label='NASA regional' if (nasa_daily or {}).get('is_real_nasa') else 'SYNTHETIC NASA-like')
                if target is not ax:
                    target.tick_params(axis='y',labelsize=7,colors='#579ad6')
                    target.set_ylabel({'rain_wetness_pct':'NASA mm/day', 'light_pct':'NASA MJ/m²/day',
                                       'soil_moisture_pct':'NASA fraction'}.get(key,'NASA scale'),fontsize=7,color='#579ad6')
        ax.set_title(title,fontsize=9,loc='left',fontweight='semibold')
        ax.grid(True,alpha=.15)
        ax.tick_params(axis='both',labelsize=7)
        ax.set_ylabel(unit if mode=='same' or not other else 'ESP32 index (0–100)',fontsize=7)
        ax.xaxis.set_major_locator(AutoDateLocator(maxticks=5))
        ax.xaxis.set_major_formatter(ConciseDateFormatter(ax.xaxis.get_major_locator()))
        if not lvalues and not (other and any(regional.get(x,{}).get(other) is not None for x in dates)):
            ax.text(.5,.5,'No records for this range',transform=ax.transAxes,ha='center',va='center',fontsize=8,color='gray')
            midpoint=datetime.now(timezone.utc).replace(tzinfo=None)
            ax.set_xlim(midpoint-timedelta(days=3),midpoint+timedelta(days=3))
        elif not other:ax.text(.99,.92,'NASA: no equivalent',transform=ax.transAxes,ha='right',va='top',fontsize=7,color='gray')
    figure.subplots_adjust(left=.07,right=.93,top=.96,bottom=.06,hspace=.65,wspace=.42)
    return figure
