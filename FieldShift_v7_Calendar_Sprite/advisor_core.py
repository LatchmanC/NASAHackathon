"""Fieldy: answer the farmer's actual question using all available sources.

Measurements and forecasts are labelled separately; reasonable guesses are
allowed only as explicitly identified estimates with assumptions.
"""
import json,os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from fastapi import HTTPException
from sensor_store import read_snapshot,age_seconds

def answer_question(req,request,validate_plan,forecast,official_alerts,
                    fetch_nasa_daily,generate_gemini_reply,default_model,valid_lat_lon):
    try:
        user=request.session.get('user',{})
        plan=validate_plan(req.plan)
        lat,lon=valid_lat_lon(req.location.get('latitude'),req.location.get('longitude'))
    except (ValueError,TypeError) as exc:raise HTTPException(400,str(exc))
    question=(req.question or '').strip() or 'Based on my farm, what should I prioritize?'
    if user.get('mode')=='sample':
        return {'advice_structured':{
          'answer':('This is the public sample farm, so this answer is only a demonstration, not a Gemini response. '
                    'You asked: '+question+'\n\nCreate an Auth0 account and verify your email for real Fieldy answers '
                    'using your own farm and available sensor/weather data.'),
          'assumptions':['The public sample account has fictional crop and sensor data.'],
          'source_notes':['No paid Gemini request was made.']},
          'provider':'demo','model':'sample-advice'}
    if user.get('mode')!='auth0' or not user.get('sub') or not user.get('email'):
        raise HTTPException(403,'Verified Auth0 login required')
    key=os.getenv('GEMINI_API_KEY','').strip()
    if not key:raise HTTPException(503,'Gemini key not configured')
    if req.model!=default_model:raise HTTPException(400,'Unsupported model')
    location={'latitude':lat,'longitude':lon,'label':str(req.location.get('label',''))[:100]}
    snapshot=read_snapshot(user['sub'])
    latest=snapshot.get('latest') if snapshot else None
    age=age_seconds(latest)
    def weather_fetch():
        try:return forecast(lat,lon)
        except Exception:return []
    def alerts_fetch():
        try:return official_alerts(location)
        except Exception:return {'status':'unavailable','message':'Official alert service could not be checked'}
    def nasa_fetch():
        try:
            n=fetch_nasa_daily(location,days=21)
            return {'source':'NASA POWER regional historical data (server fetched)',
                    'period':n.get('period'),'rows':(n.get('rows') or [])[-21:]}
        except Exception:
            rows=[{k:row.get(k) for k in ('date','temperature_c','temperature_max_c',
                'temperature_min_c','precipitation_mm','humidity_pct')}
                for row in req.nasa_excerpt[-14:] if isinstance(row,dict)]
            return {'source':'Unverified browser-cached history' if rows else 'unavailable',
                    'rows':rows}
    with ThreadPoolExecutor(max_workers=3) as pool:
        wa=pool.submit(weather_fetch);al=pool.submit(alerts_fetch);na=pool.submit(nasa_fetch)
        weather=wa.result();alerts=al.result();nasa=na.result()
    sensor_status=('recent' if age is not None and age<900 else
                   'stale' if latest else 'not connected')
    context={
        'user_question':question,
        'farm_plan':plan,
        'farm_location':location,
        'calendar_tasks':req.upcoming_calendar_tasks[-30:],
        'esp32_sensor':{'status':sensor_status,'age_minutes':round(age/60,1) if age is not None else None,
                        'readings':latest if age is not None and age<=86400 else None,
                        'source':'Real device uploads, not a forecast, if present'},
        'seven_day_forecast':{'source':'Open-Meteo live weather forecast' if weather else 'unavailable','days':weather},
        'official_weather_alerts':alerts,
        'nasa_historical_weather':nasa,
        'as_of_utc':datetime.now(timezone.utc).isoformat()
    }
    instruction=(
        'You are Fieldy, an expert farming advisor. The FIRST priority is to ANSWER the precise user question '
        'clearly, concretely and thoroughly based on the available data. Do NOT default to a generic crop checklist. '
        'The user might ask about crop layout, harvest dates, soil chemistry, water needs, yield estimates, '
        'weather effects, comparisons, troubleshooting, or math: answer that specific question. '
        'Use available crop sizes, varieties, stages, dates, recent authenticated ESP32 readings and timestamps, '
        'calendar tasks, NASA POWER regional history, live Open-Meteo forecasts, and official alerts where relevant. '
        'If information is incomplete, make a well-reasoned best guess using stated assumptions and general '
        'agronomic knowledge; give ranges or uncertainty instead of declining to estimate. '
        'Clearly distinguish measured data, forecasts, and estimates. Never invent live measurements, '
        'weather warnings, historical observations, or imply stale sensors are current. '
        'If exact dates/varieties are missing, give useful conditional guidance instead of just requesting details. '
        'The response must be JSON ONLY with exactly three fields: '
        'answer (2–7 concise paragraphs directly answering the farmer, plain text with newlines; not markdown), '
        'assumptions (0–4 short strings explaining important estimates), '
        'source_notes (0–4 short strings naming evidence/limitations). '
        'Your answer should be actionable, direct, and not formulaic. Data context: '
        +json.dumps(context,ensure_ascii=False,default=str))
    try:
        raw=generate_gemini_reply(key,instruction,model=default_model,json_mode=True)
        data=json.loads(raw.strip().removeprefix('```json').removeprefix('```').removesuffix('```').strip())
        if not isinstance(data,dict):raise ValueError('Gemini response must be JSON object')
        answer=str(data.get('answer','')).strip()[:7000]
        if not answer:raise ValueError('Empty response')
        return {'advice_structured':{'answer':answer,
                  'assumptions':[str(x)[:250] for x in (data.get('assumptions') or [])[:4] if isinstance(x,str)],
                  'source_notes':[str(x)[:250] for x in (data.get('source_notes') or [])[:4] if isinstance(x,str)]},
                'provider':'gemini','model':default_model,
                'data_sources':{'esp32':sensor_status,'nasa':nasa['source'],'weather':'live' if weather else 'unavailable'}}
    except Exception as exc:
        raise HTTPException(502,'Gemini could not answer. Check model access and server logs.') from exc
