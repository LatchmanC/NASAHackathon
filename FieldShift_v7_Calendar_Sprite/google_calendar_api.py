"""Google Calendar linking for Cropaganda.
Auth0 signs in the farmer; Google OAuth separately grants event creation.
Refresh tokens are encrypted at rest and never returned to the browser.
"""
from __future__ import annotations
import hashlib, hmac, os, secrets
from datetime import date, timedelta
from urllib.parse import urlencode
import httpx
from cryptography.fernet import Fernet
from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from device_api import _owner
from tigerdata_store import _connection, _key

GOOGLE_SCOPE='https://www.googleapis.com/auth/calendar.events'
KINDS={'planting':'Plant','watering':'Water','harvest':'Harvest','fertilizing':'Fertilize',
       'inspection':'Inspect','other':'Farm task'}

def oauth_ready():
    return all(os.getenv(key,'').strip() for key in
        ('GOOGLE_OAUTH_CLIENT_ID','GOOGLE_OAUTH_CLIENT_SECRET','GOOGLE_TOKEN_ENCRYPTION_KEY'))

def fernet():
    try:return Fernet(os.environ['GOOGLE_TOKEN_ENCRYPTION_KEY'].encode())
    except (KeyError,ValueError) as exc:
        raise HTTPException(503,'Google Calendar token encryption is not configured') from exc

def _db_setup(conn):
    with conn.cursor() as cur:
        cur.execute("""CREATE TABLE IF NOT EXISTS cropoganda_google_calendar (
            account_key TEXT PRIMARY KEY,
            encrypted_refresh_token TEXT NOT NULL,
            connected_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )""")

def _saved_refresh_token(owner):
    with _connection() as conn:
        _db_setup(conn)
        with conn.cursor() as cur:
            cur.execute('SELECT encrypted_refresh_token FROM cropoganda_google_calendar WHERE account_key=%s',(_key(owner),))
            record=cur.fetchone()
        return fernet().decrypt(record[0].encode()).decode() if record else None

def _store_refresh_token(owner,token):
    with _connection() as conn:
        _db_setup(conn)
        ciphertext=fernet().encrypt(token.encode()).decode()
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO cropoganda_google_calendar(account_key,encrypted_refresh_token)
                           VALUES (%s,%s) ON CONFLICT(account_key) DO UPDATE
                           SET encrypted_refresh_token=EXCLUDED.encrypted_refresh_token,
                               connected_at=now()""",(_key(owner),ciphertext))

def _delete_refresh_token(owner):
    with _connection() as conn:
        _db_setup(conn)
        with conn.cursor() as cur:
            cur.execute('DELETE FROM cropoganda_google_calendar WHERE account_key=%s',(_key(owner),))

def _redirect_uri():
    return os.getenv('APP_BASE_URL','https://cropaganda.garden').rstrip('/')+'/api/google/callback'

def _exchange(params):
    try:
        response=httpx.post('https://oauth2.googleapis.com/token',data=params,timeout=16)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError,ValueError) as exc:
        raise HTTPException(502,'Google authorization could not be completed') from exc

class AddEvent(BaseModel):
    confirmed:bool
    request_id:str=Field(min_length=12,max_length=100,pattern=r'^[A-Za-z0-9_-]+$')
    date:str=Field(pattern=r'^\d{4}-\d{2}-\d{2}$')
    kind:str=Field(pattern=r'^(planting|watering|harvest|fertilizing|inspection|other)$')
    crop:str=Field(default='',max_length=70)
    note:str=Field(default='',max_length=240)

def install_google_calendar_routes(app):
    @app.get('/api/google/status')
    def status(request:Request):
        owner=_owner(request)
        configured=oauth_ready()
        if not configured:
            return {'configured':False,'connected':False,
                    'message':'Google Calendar OAuth credentials have not been configured.'}
        try: connected=bool(_saved_refresh_token(owner))
        except Exception as exc:raise HTTPException(503,'Google Calendar connection status unavailable') from exc
        return {'configured':True,'connected':connected,
                'message':'Connected to Google Calendar' if connected else 'Connect Google Calendar to sync confirmed farm tasks.'}

    @app.get('/api/google/connect')
    def connect(request:Request):
        _owner(request)
        if not oauth_ready():raise HTTPException(503,'Google Calendar OAuth is not configured')
        nonce=secrets.token_urlsafe(32)
        request.session['cropoganda_google_state']=nonce
        params={
            'client_id':os.environ['GOOGLE_OAUTH_CLIENT_ID'],'redirect_uri':_redirect_uri(),
            'response_type':'code','scope':GOOGLE_SCOPE,
            'access_type':'offline','prompt':'consent','state':nonce}
        return RedirectResponse('https://accounts.google.com/o/oauth2/v2/auth?'+urlencode(params),status_code=302)

    @app.get('/api/google/callback')
    def callback(request:Request,code:str='',state:str='',error:str=''):
        # Callback must remain tied to the same signed-in Auth0 session.
        try:owner=_owner(request)
        except HTTPException:return RedirectResponse('/?error=google_session',status_code=303)
        nonce=request.session.pop('cropoganda_google_state',None)
        if not nonce or not state or not hmac.compare_digest(nonce,state) or error or not code:
            return RedirectResponse('/dashboard.html?google_calendar=failed',status_code=303)
        if not oauth_ready():
            return RedirectResponse('/dashboard.html?google_calendar=unconfigured',status_code=303)
        try:
            token=_exchange({'code':code,'client_id':os.environ['GOOGLE_OAUTH_CLIENT_ID'],
                             'client_secret':os.environ['GOOGLE_OAUTH_CLIENT_SECRET'],
                             'redirect_uri':_redirect_uri(),'grant_type':'authorization_code'})
            refresh=token.get('refresh_token')
            granted=token.get('scope','')
            if not refresh or (granted and GOOGLE_SCOPE not in granted.split()):
                raise ValueError('Missing Google Calendar refresh token or scope')
            _store_refresh_token(owner,refresh)
            return RedirectResponse('/dashboard.html?google_calendar=connected',status_code=303)
        except Exception:
            return RedirectResponse('/dashboard.html?google_calendar=failed',status_code=303)

    @app.post('/api/google/disconnect')
    def disconnect(request:Request):
        owner=_owner(request)
        if oauth_ready():_delete_refresh_token(owner)
        return {'disconnected':True}

    @app.post('/api/google/events')
    def insert_event(request:Request,event:AddEvent):
        owner=_owner(request)
        if not event.confirmed:
            raise HTTPException(403,'Explicit farmer confirmation required')
        if not oauth_ready():
            raise HTTPException(503,'Google Calendar OAuth has not been configured')
        try:
            day=date.fromisoformat(event.date)
        except ValueError as exc:raise HTTPException(400,'Invalid calendar date') from exc
        if day < date.today()-timedelta(days=366) or day > date.today()+timedelta(days=1825):
            raise HTTPException(400,'Calendar date out of supported range')
        try:refresh=_saved_refresh_token(owner)
        except Exception as exc:raise HTTPException(503,'Google Calendar connection unavailable') from exc
        if not refresh:
            raise HTTPException(409,'Connect Google Calendar before confirming a farm event')
        token=_exchange({'client_id':os.environ['GOOGLE_OAUTH_CLIENT_ID'],
                         'client_secret':os.environ['GOOGLE_OAUTH_CLIENT_SECRET'],
                         'refresh_token':refresh,'grant_type':'refresh_token'}).get('access_token')
        if not token:raise HTTPException(502,'Google Calendar access token could not be refreshed')
        summary=KINDS[event.kind]+(' '+event.crop.strip() if event.crop.strip() else ' farm task')
        nextday=(day+timedelta(days=1)).isoformat()
        uid=hashlib.sha256((owner+':'+event.request_id).encode()).hexdigest()
        event_id='c'+uid[:40]
        payload={'id':event_id,'summary':summary,
                 'description':('Cropaganda farm calendar'+(' — '+event.note if event.note else '')),
                 'start':{'date':event.date},'end':{'date':nextday}}
        try:
            r=httpx.post('https://www.googleapis.com/calendar/v3/calendars/primary/events',
                         headers={'Authorization':'Bearer '+token},
                         params={'sendUpdates':'none'},json=payload,timeout=18)
        except httpx.HTTPError as exc:raise HTTPException(502,'Google Calendar could not be reached') from exc
        if r.status_code==409:
            return {'created':True,'already_exists':True,'event_id':event_id}
        if not r.is_success:
            raise HTTPException(502,'Google Calendar rejected the event; please reconnect if access expired')
        return {'created':True,'event_id':event_id,'google_url':r.json().get('htmlLink')}
