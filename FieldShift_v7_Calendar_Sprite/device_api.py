"""ESP32 private bearer-token pairing and HTTPS ingestion routes."""
import os
from datetime import datetime, timezone
from fastapi import HTTPException, Request
from pydantic import BaseModel, Field
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from sensor_store import (SensorPayload,configured,read_snapshot,save_snapshot,age_seconds,
                          read_shared_link,save_shared_link,revoke_shared_viewers)

def signer():
    from auth0_integration import settings
    secret=settings()['session_secret']
    if len(secret)<32:raise HTTPException(503,'Pairing unavailable')
    return URLSafeTimedSerializer(secret_key=secret,salt='fieldshift-device-token-v1')

class PairRequest(BaseModel):
    device_id:str=Field(default='esp32-01',pattern=r'^[A-Za-z0-9_-]{1,40}

def _owner(request):
    try:user=request.session.get('user',{})
    except AssertionError:user={}
    if not isinstance(user,dict) or user.get('mode')!='auth0' or not user.get('sub'):
        raise HTTPException(403,'Verified Auth0 login required for device pairing')
    return user['sub']

def install_device_routes(app):
    @app.post('/api/device/token')
    def token(req:PairRequest,request:Request):
        owner=_owner(request)
        if not configured():raise HTTPException(503,'Sensor cloud storage unavailable')
        return {'device_id':req.device_id,'token':signer().dumps({'sub':owner,'device_id':req.device_id}),
                'upload_url':'https://cropaganda.garden/api/device/ingest',
                'expires_days':180,'min_interval_seconds':max(60,int(os.getenv('FIELDSHIFT_MIN_SENSOR_SECONDS','300')))}

    async def _read_payload(request):
        raw_token=request.headers.get('authorization','')
        if not raw_token.startswith('Bearer '):raise HTTPException(401,'Device token required')
        try:claims=signer().loads(raw_token[7:],max_age=180*86400)
        except (BadSignature,SignatureExpired):raise HTTPException(401,'Device token invalid or expired')
        if not isinstance(claims,dict) or not claims.get('sub') or not claims.get('device_id'):
            raise HTTPException(401,'Device token scope invalid')
        if 'application/json' not in request.headers.get('content-type','').lower():
            raise HTTPException(415,'JSON content type required')
        raw=await request.body()
        if len(raw)>4096:raise HTTPException(413,'Device payload too large')
        try:payload=SensorPayload.model_validate_json(raw)
        except ValueError:raise HTTPException(422,'Invalid sensor payload or measurement range')
        if payload.device_id!=claims['device_id']:raise HTTPException(403,'Device ID not paired to this token')
        return claims,payload

    @app.post('/api/device/validate')
    async def validate(request:Request):
        claims,payload=await _read_payload(request)
        return {'valid':True,'stored':False,
                'checked_metrics':len(payload.model_dump(exclude_none=True))-1,
                'message':'Connection and token valid; test values were NOT stored'}

    @app.post('/api/device/ingest')
    async def ingest(request:Request):
        claims,payload=await _read_payload(request)
        old=read_snapshot(claims['sub'])
        last=old.get('latest') if old else None
        age=age_seconds(last)
        interval=max(60,min(86400,int(os.getenv('FIELDSHIFT_MIN_SENSOR_SECONDS','300'))))
        if age is not None and age<interval:
            wait=max(1,int(interval-age)+1)
            raise HTTPException(429,f'Wait {wait} seconds before next cloud upload',headers={'Retry-After':str(wait)})
        row={'device_id':payload.device_id,'recorded_at':datetime.now(timezone.utc).isoformat()}
        row.update(payload.model_dump(exclude_none=True,exclude={'device_id'}))
        snap=save_snapshot(claims['sub'],row,old)
        # Text the linked farm if this reading NEWLY crosses an alert rule (never fails the upload).
        from sms import on_new_reading
        on_new_reading(claims['sub'],row,last)
        return {'accepted':True,'received_at':row['recorded_at'],'stored_records':len(snap['readings']),
                'min_interval_seconds':interval}

    @app.post('/api/device/share/token')
    def generate_view_token(req:PairRequest,request:Request):
        owner=_owner(request)
        snapshot=read_snapshot(owner)
        if not snapshot or not snapshot.get('latest'):
            raise HTTPException(409,'An ESP32 must upload a reading before it can be shared')
        if snapshot['latest'].get('device_id')!=req.device_id:
            raise HTTPException(409,'Device ID does not match your last uploaded ESP32')
        code=share_signer().dumps({'scope':'view','sub':owner,'device_id':req.device_id,
                                    'version':snapshot.get('share_version','v1')})
        return {'token':code,'device_id':req.device_id,'expires_days':180,
                'permission':'read-only','note':'Sharing tokens cannot upload sensor measurements'}

    @app.post('/api/device/share/join')
    def join_shared_device(req:JoinRequest,request:Request):
        viewer=_owner(request)
        claims=share_claims(req.token)
        if claims['sub']==viewer:
            raise HTTPException(400,'This device already belongs to your account')
        shared=read_snapshot(claims['sub'])
        if (not shared or not shared.get('latest') or
            shared.get('share_version','v1')!=claims['version'] or
            shared['latest'].get('device_id')!=claims['device_id']):
            raise HTTPException(403,'This sharing token has been revoked or the device is unavailable')
        save_shared_link(viewer,req.token)
        return {'connected':True,'device_id':claims['device_id'],
                'permission':'read-only','message':'Shared ESP32 added to your dashboard'}

    @app.post('/api/device/share/disconnect')
    def disconnect_shared_device(request:Request):
        save_shared_link(_owner(request),None)
        return {'disconnected':True}

    @app.post('/api/device/share/revoke')
    def revoke_all_shared_viewers(request:Request):
        revoke_shared_viewers(_owner(request))
        return {'revoked':True,'message':'All earlier sharing tokens have been invalidated'}

    @app.get('/api/device/share/status')
    def shared_device_status(request:Request):
        viewer=_owner(request)
        snapshot,mode=resolve_device_data(viewer,view='shared')
        return {'connected':bool(mode=='shared' and snapshot),
                'device_id':snapshot['latest'].get('device_id') if mode=='shared' and snapshot else None,
                'permission':'read-only' if mode=='shared' else None}

    @app.get('/api/device/status')
    def status(request:Request):
        owner=_owner(request)
        snapshot=read_snapshot(owner)
        latest=snapshot.get('latest') if snapshot else None
        age=age_seconds(latest)
        return {'configured':configured(),'online':age is not None and age<15*60,
                'last_seen':latest.get('recorded_at') if latest else None,
                'device_id':latest.get('device_id') if latest else None,
                'age_seconds':round(age) if age is not None else None}
)

class JoinRequest(BaseModel):
    token:str=Field(min_length=30,max_length=4096)

def share_signer():
    """Separate salt ensures viewing tokens cannot authorize ESP32 writes."""
    from auth0_integration import settings
    return URLSafeTimedSerializer(settings()['session_secret'],salt='fieldshift-view-token-v1')

def share_claims(token):
    try:
        claims=share_signer().loads(token,max_age=180*86400)
    except (BadSignature,SignatureExpired,ValueError,TypeError):
        raise HTTPException(400,'Invalid or expired sharing token')
    if (not isinstance(claims,dict) or claims.get('scope')!='view' or
        not isinstance(claims.get('sub'),str) or not claims['sub'] or
        not isinstance(claims.get('device_id'),str) or not claims['device_id'] or
        not isinstance(claims.get('version'),str)):
        raise HTTPException(400,'Invalid sharing token scope')
    return claims

def resolve_device_data(account,view='auto'):
    """Read own measurements or an explicitly linked view-only shared feed."""
    if view not in ('auto','own','shared'):
        raise HTTPException(400,'Invalid sensor view')
    own=read_snapshot(account) if view!='shared' else None
    if view=='own' or (view=='auto' and own and own.get('latest')):
        return own, 'own'
    link=read_shared_link(account)
    if link:
        try:
            claims=share_claims(link['token'])
        except HTTPException:
            claims=None
        if claims and claims['sub']!=account:
            shared=read_snapshot(claims['sub'])
            if (shared and shared.get('latest') and
                shared.get('share_version','v1')==claims['version'] and
                shared['latest'].get('device_id')==claims['device_id']):
                return shared,'shared'
    return (own,'own') if own and own.get('latest') else (None,'none')


def _owner(request):
    try:user=request.session.get('user',{})
    except AssertionError:user={}
    if not isinstance(user,dict) or user.get('mode')!='auth0' or not user.get('sub'):
        raise HTTPException(403,'Verified Auth0 login required for device pairing')
    return user['sub']

def install_device_routes(app):
    @app.post('/api/device/token')
    def token(req:PairRequest,request:Request):
        owner=_owner(request)
        if not configured():raise HTTPException(503,'Sensor cloud storage unavailable')
        return {'device_id':req.device_id,'token':signer().dumps({'sub':owner,'device_id':req.device_id}),
                'upload_url':'https://cropaganda.garden/api/device/ingest',
                'expires_days':180,'min_interval_seconds':max(60,int(os.getenv('FIELDSHIFT_MIN_SENSOR_SECONDS','300')))}

    async def _read_payload(request):
        raw_token=request.headers.get('authorization','')
        if not raw_token.startswith('Bearer '):raise HTTPException(401,'Device token required')
        try:claims=signer().loads(raw_token[7:],max_age=180*86400)
        except (BadSignature,SignatureExpired):raise HTTPException(401,'Device token invalid or expired')
        if not isinstance(claims,dict) or not claims.get('sub') or not claims.get('device_id'):
            raise HTTPException(401,'Device token scope invalid')
        if 'application/json' not in request.headers.get('content-type','').lower():
            raise HTTPException(415,'JSON content type required')
        raw=await request.body()
        if len(raw)>4096:raise HTTPException(413,'Device payload too large')
        try:payload=SensorPayload.model_validate_json(raw)
        except ValueError:raise HTTPException(422,'Invalid sensor payload or measurement range')
        if payload.device_id!=claims['device_id']:raise HTTPException(403,'Device ID not paired to this token')
        return claims,payload

    @app.post('/api/device/validate')
    async def validate(request:Request):
        claims,payload=await _read_payload(request)
        return {'valid':True,'stored':False,
                'checked_metrics':len(payload.model_dump(exclude_none=True))-1,
                'message':'Connection and token valid; test values were NOT stored'}

    @app.post('/api/device/ingest')
    async def ingest(request:Request):
        claims,payload=await _read_payload(request)
        old=read_snapshot(claims['sub'])
        last=old.get('latest') if old else None
        age=age_seconds(last)
        interval=max(60,min(86400,int(os.getenv('FIELDSHIFT_MIN_SENSOR_SECONDS','300'))))
        if age is not None and age<interval:
            wait=max(1,int(interval-age)+1)
            raise HTTPException(429,f'Wait {wait} seconds before next cloud upload',headers={'Retry-After':str(wait)})
        row={'device_id':payload.device_id,'recorded_at':datetime.now(timezone.utc).isoformat()}
        row.update(payload.model_dump(exclude_none=True,exclude={'device_id'}))
        snap=save_snapshot(claims['sub'],row,old)
        # Text the linked farm if this reading NEWLY crosses an alert rule (never fails the upload).
        from sms import on_new_reading
        on_new_reading(claims['sub'],row,last)
        return {'accepted':True,'received_at':row['recorded_at'],'stored_records':len(snap['readings']),
                'min_interval_seconds':interval}

    @app.get('/api/device/status')
    def status(request:Request):
        owner=_owner(request)
        snapshot=read_snapshot(owner)
        latest=snapshot.get('latest') if snapshot else None
        age=age_seconds(latest)
        return {'configured':configured(),'online':age is not None and age<15*60,
                'last_seen':latest.get('recorded_at') if latest else None,
                'device_id':latest.get('device_id') if latest else None,
                'age_seconds':round(age) if age is not None else None}
