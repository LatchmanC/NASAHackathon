"""FieldShift identity boundary: Auth0 for real users, isolated public sample account.

The test/test credentials are deliberately PUBLIC DEMO CREDENTIALS, not an
Auth0 password and never grant the right to call Gemini or read real farm data.
Private data endpoints require a verified Auth0 session. Public signup is optional; Gemini is available to verified Auth0 accounts.
"""
from __future__ import annotations
import hmac
import os
import re
from urllib.parse import quote, parse_qs, urlsplit, urlencode
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse, HTMLResponse
from starlette.middleware.sessions import SessionMiddleware


def settings():
    enabled = os.getenv('AUTH0_ENABLED','0') == '1'
    sample = os.getenv('FIELDSHIFT_SAMPLE_ACCOUNT','0') == '1'
    signup = enabled and os.getenv('AUTH0_ALLOW_SIGNUPS','0') == '1'
    demo = os.getenv('FIELDSHIFT_DEMO','1') == '1'
    base = os.getenv('APP_BASE_URL','http://127.0.0.1:8501').rstrip('/')
    if not enabled and not demo:
        raise RuntimeError('Refusing to start publicly without Auth0.')
    domain=os.getenv('AUTH0_DOMAIN','').strip()
    if enabled and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{1,251}[A-Za-z0-9]',domain):
        raise RuntimeError('AUTH0_DOMAIN must be a bare tenant domain')
    client_id=os.getenv('AUTH0_CLIENT_ID','').strip()
    client_secret=os.getenv('AUTH0_CLIENT_SECRET','').strip()
    secret=(os.getenv('SESSION_SECRET','').strip() or os.getenv('AUTH0_SECRET','').strip())
    allowed={p.strip().casefold() for p in os.getenv('AUTH0_ALLOWED_EMAILS','').split(',') if p.strip()}
    if enabled and (not client_id or not client_secret):
        raise RuntimeError('Configure AUTH0_CLIENT_ID and AUTH0_CLIENT_SECRET')
    if (enabled or sample) and len(secret)<32:
        raise RuntimeError('SESSION_SECRET or AUTH0_SECRET must be >=32 characters')
    parsed=urlsplit(base)
    local=parsed.hostname in ('127.0.0.1','localhost')
    if enabled and ((parsed.scheme!='https' and not(local and parsed.scheme=='http')) or parsed.query or parsed.fragment or parsed.path not in ('','/')):
        raise RuntimeError('APP_BASE_URL must be an HTTPS origin')
    return {'enabled':enabled,'sample_enabled':sample,'demo':demo,'base':base,'domain':domain,
            'client_id':client_id,'client_secret':client_secret,'session_secret':secret,
            'allowed':allowed,'signup_enabled':signup,'https_only':parsed.scheme=='https'}


def install_auth(app: FastAPI):
    conf=settings()
    oauth=None
    if conf['enabled']:
        from authlib.integrations.starlette_client import OAuth
        oauth=OAuth()
        oauth.register(name='auth0',client_id=conf['client_id'],client_secret=conf['client_secret'],
                       server_metadata_url=f"https://{conf['domain']}/.well-known/openid-configuration",
                       client_kwargs={'scope':'openid profile email'})

    @app.middleware('http')
    async def require_session(request:Request,call_next):
        path=request.url.path
        # The Vercel public/ folder is served separately. ALL private APIs must
        # independently validate the signed session cookie.
        public=path.startswith('/static/') or path in ('/','/api/health','/api/auth/me','/auth/login','/auth/callback','/auth/logout','/auth/demo','/auth/signup','/api/device/ingest','/api/device/validate','/api/twilio/sms','/api/sms/cron-reminders')
        if not conf['enabled'] and not conf['sample_enabled']:
            return await call_next(request)
        user=request.session.get('user')
        # Retire any signed sample sessions when the public demo account is disabled.
        if isinstance(user,dict) and user.get('mode')=='sample' and not conf['sample_enabled']:
            request.session.clear()
            user=None
        if not public and (not isinstance(user,dict) or not user.get('sub')):
            if path.startswith('/api/'):
                return JSONResponse({'detail':'Please sign in to FieldShift.'},status_code=401)
            return RedirectResponse('/',status_code=303)
        if path.startswith('/api/') and path not in ('/api/device/ingest','/api/device/validate','/api/twilio/sms') and request.method in ('POST','PUT','PATCH','DELETE'):
            if request.headers.get('X-FieldShift-Request')!='1':
                return JSONResponse({'detail':'Request protection header missing'},status_code=403)
            origin=request.headers.get('origin')
            if origin and origin.rstrip('/')!=conf['base']:
                return JSONResponse({'detail':'Origin mismatch'},status_code=403)
        return await call_next(request)

    @app.get('/api/auth/me')
    async def me(request:Request):
        user=request.session.get('user') if (conf['enabled'] or conf['sample_enabled']) else None
        if not isinstance(user,dict) or not user.get('sub'):
            return {'auth_enabled':conf['enabled'],'authenticated':False,'sample_available':conf['sample_enabled'],'signup_available':conf['signup_enabled']}
        safe={k:v for k,v in user.items() if k in ('sub','name','email','mode')}
        return {'auth_enabled':conf['enabled'],'authenticated':True,'user':safe,
                'signup_available':conf['signup_enabled'],
                'scope':'sample_only' if user.get('mode')=='sample' else 'verified_auth0_profile'}

    @app.post('/auth/demo')
    async def demo_login(request:Request):
        if not conf['sample_enabled']:
            return JSONResponse({'detail':'Sample login is not enabled'},status_code=404)
        # This is NOT a privileged user account. The example password is public.
        origin=request.headers.get('origin')
        if origin and origin.rstrip('/')!=conf['base']:
            return JSONResponse({'detail':'Origin mismatch'},status_code=403)
        if not request.headers.get('content-type','').startswith('application/x-www-form-urlencoded'):
            return JSONResponse({'detail':'Form content type required'},status_code=415)
        body=await request.body()
        if len(body)>500:
            return JSONResponse({'detail':'Form too large'},status_code=413)
        form=parse_qs(body.decode('utf-8','replace'),keep_blank_values=True)
        username=form.get('username',[''])[0]
        password=form.get('password',[''])[0]
        if not (hmac.compare_digest(username,'test') and hmac.compare_digest(password,'test')):
            return RedirectResponse('/?error=invalid',status_code=303)
        request.session.clear()
        request.session['user']={'sub':'sample:test','name':'Test Farmer','mode':'sample'}
        return RedirectResponse('/dashboard.html',status_code=303)

    @app.get('/auth/login')
    async def login(request:Request):
        if not conf['enabled']:
            return RedirectResponse('/?error=auth0_not_configured',status_code=303)
        user=request.session.get('user')
        if user and user.get('mode')!='sample':
            return RedirectResponse('/dashboard.html',status_code=303)
        request.session.clear()
        args={'audience':os.environ['AUTH0_AUDIENCE']} if os.getenv('AUTH0_AUDIENCE') else {}
        return await oauth.auth0.authorize_redirect(request,f"{conf['base']}/auth/callback",**args)

    @app.get('/auth/signup')
    async def signup(request:Request):
        # Auth0 Universal Login handles registration and stores passwords.
        if not conf['signup_enabled']:
            return RedirectResponse('/?error=signup_unavailable',status_code=303)
        request.session.clear()
        args={'screen_hint':'signup','prompt':'login'}
        if os.getenv('AUTH0_AUDIENCE'):
            args['audience']=os.environ['AUTH0_AUDIENCE']
        return await oauth.auth0.authorize_redirect(request,f"{conf['base']}/auth/callback",**args)

    @app.get('/auth/callback')
    async def callback(request:Request):
        if not conf['enabled']:
            return RedirectResponse('/',status_code=303)
        try:
            token=await oauth.auth0.authorize_access_token(request)
            claims=token.get('userinfo') or {}
        except Exception:
            request.session.clear()
            return HTMLResponse('<h2>Sign-in could not be completed.</h2><p>Check the Auth0 callback configuration, then <a href="/">try again</a>.</p>',status_code=400)
        email=str(claims.get('email','')).strip().casefold()
        if not email or claims.get('email_verified') is not True or not claims.get('sub'):
            request.session.clear()
            return HTMLResponse('<h2>Verify your email address</h2><p>Please verify your email through Auth0, then <a href="/auth/login">sign in again</a>.</p>',status_code=403)
        if not conf['signup_enabled'] and email not in conf['allowed']:
            request.session.clear()
            return HTMLResponse('<h2>Account approval required</h2><p>This account is not currently authorized for FieldShift. <a href="/">Return to login</a>.</p>',status_code=403)
        request.session.clear()
        request.session['user']={'sub':str(claims['sub'])[:200], 'email':email,
                                 'name':str(claims.get('name') or email)[:100], 'mode':'auth0'}
        return RedirectResponse('/dashboard.html',status_code=303)

    @app.get('/auth/logout')
    async def logout(request:Request):
        user=request.session.get('user') if (conf['enabled'] or conf['sample_enabled']) else None
        request.session.clear()
        if not conf['enabled'] or not user or user.get('mode')=='sample':
            return RedirectResponse('/',status_code=303)
        query=urlencode({'returnTo':f"{conf['base']}/",'client_id':conf['client_id']},quote_via=quote)
        return RedirectResponse(f"https://{conf['domain']}/v2/logout?{query}",status_code=303)

    if conf['enabled'] or conf['sample_enabled']:
        app.add_middleware(SessionMiddleware,secret_key=conf['session_secret'],
                           session_cookie='fieldshift_session',same_site='lax',
                           https_only=conf['https_only'],max_age=60*60*8)
    return conf
