"""Auth0 Universal Login for the FieldShift web dashboard.

- Auth0 OIDC is used for *human* login only.
- All signed-in users in this prototype share ONE farm. AUTH0_ALLOWED_EMAILS
  makes that explicit by restricting access to approved, verified addresses.
- Device uploads use a separate credential and are never granted browser sessions.
- Set AUTH0_ENABLED=1 before exposing the dashboard publicly.
"""
from __future__ import annotations

import os
import re
from urllib.parse import quote, urlsplit, urlencode

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware


def settings():
    enabled = os.environ.get('AUTH0_ENABLED', '0') == '1'
    base = os.environ.get('APP_BASE_URL', 'http://127.0.0.1:8501').rstrip('/')
    demo = os.environ.get('FIELDSHIFT_DEMO', '1') == '1'
    if not enabled:
        if not demo:
            raise RuntimeError('Refusing to start publicly without Auth0. Set AUTH0_ENABLED=1.')
        return {'enabled': False, 'base': base}
    domain = os.environ.get('AUTH0_DOMAIN', '').strip()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{1,251}[A-Za-z0-9]', domain):
        raise RuntimeError('AUTH0_DOMAIN must be a bare domain such as tenant.us.auth0.com')
    client_id = os.environ.get('AUTH0_CLIENT_ID', '').strip()
    client_secret = os.environ.get('AUTH0_CLIENT_SECRET', '').strip()
    # Existing Auth0 SDK setups often use AUTH0_SECRET for cookie signing.
    # Support either name without accessing or copying secret values.
    session_secret = (os.environ.get('SESSION_SECRET', '').strip()
                      or os.environ.get('AUTH0_SECRET', '').strip())
    allowed = {part.strip().casefold() for part in os.environ.get('AUTH0_ALLOWED_EMAILS','').split(',') if part.strip()}
    if not client_id or not client_secret or len(session_secret) < 32:
        raise RuntimeError('Configure AUTH0_CLIENT_ID, AUTH0_CLIENT_SECRET and SESSION_SECRET or AUTH0_SECRET (>=32 chars)')
    if not allowed:
        raise RuntimeError('Set AUTH0_ALLOWED_EMAILS for this single-farm prototype.')
    parsed = urlsplit(base)
    local = parsed.hostname in {'127.0.0.1', 'localhost'}
    if (parsed.scheme != 'https' and not (local and parsed.scheme == 'http')) or parsed.query or parsed.fragment or parsed.path not in ('', '/'):
        raise RuntimeError('APP_BASE_URL must be an HTTPS origin (localhost HTTP only for development).')
    return {'enabled': True, 'domain': domain, 'client_id':client_id,
            'client_secret':client_secret, 'session_secret':session_secret,
            'allowed':allowed, 'base':base, 'https_only': parsed.scheme == 'https'}


def install_auth(app: FastAPI):
    """Adds a same-origin session gate, login routes, and a minimal account API."""
    conf = settings()
    oauth = None
    if conf['enabled']:
        from authlib.integrations.starlette_client import OAuth
        oauth = OAuth()
        oauth.register(
            name='auth0',
            client_id=conf['client_id'],
            client_secret=conf['client_secret'],
            server_metadata_url=f"https://{conf['domain']}/.well-known/openid-configuration",
            client_kwargs={'scope': 'openid profile email'},
        )

    @app.middleware('http')
    async def require_session(request: Request, call_next):
        if not conf['enabled']:
            return await call_next(request)
        path = request.url.path
        if path.startswith('/static/') or path in ('/api/health','/auth/login','/auth/callback','/auth/logout'):
            return await call_next(request)
        user = request.session.get('user')
        if not isinstance(user, dict) or not user.get('sub'):
            if path.startswith('/api/'):
                return JSONResponse({'detail': 'Sign in to FieldShift first'}, status_code=401)
            return RedirectResponse('/auth/login', status_code=303)
        if path.startswith('/api/') and request.method.upper() in ('POST','PUT','PATCH','DELETE'):
            # Custom header makes browser cross-site POSTs fail CORS preflight;
            # origin is checked independently to guard against same-site abuse.
            if request.headers.get('X-FieldShift-Request') != '1':
                return JSONResponse({'detail':'Missing request protection header'},status_code=403)
            origin = request.headers.get('origin')
            if origin and origin.rstrip('/') != conf['base']:
                return JSONResponse({'detail':'Origin mismatch'},status_code=403)
        return await call_next(request)

    @app.get('/api/auth/me')
    async def who_am_i(request: Request):
        if not conf['enabled']:
            return {'auth_enabled':False,'authenticated':False,'mode':'local_demo'}
        return {'auth_enabled':True,'authenticated':True,'user':request.session['user'],
                'scope':'single_farm_allowlist'}

    @app.get('/auth/login')
    async def login(request: Request):
        if not conf['enabled']:
            return RedirectResponse('/', status_code=303)
        if request.session.get('user'):
            return RedirectResponse('/', status_code=303)
        return await oauth.auth0.authorize_redirect(request, f"{conf['base']}/auth/callback", **({'audience':os.environ['AUTH0_AUDIENCE']} if os.environ.get('AUTH0_AUDIENCE') else {}))

    @app.get('/auth/callback')
    async def callback(request: Request):
        if not conf['enabled']:
            return RedirectResponse('/',status_code=303)
        try:
            token = await oauth.auth0.authorize_access_token(request)
            claims = token.get('userinfo') or {}
        except Exception:
            request.session.clear()
            return JSONResponse({'detail':'Unable to complete login. Check Auth0 callback settings.'},status_code=400)
        email = str(claims.get('email','')).strip().casefold()
        if not email or claims.get('email_verified') is not True or email not in conf['allowed'] or not claims.get('sub'):
            request.session.clear()
            return JSONResponse({'detail':'This verified account has not been authorized for this farm.'},status_code=403)
        # Signed cookie stores small, non-sensitive profile only, NEVER tokens.
        request.session.clear()
        request.session['user'] = {'sub':str(claims['sub'])[:200],
                                   'email':email,
                                   'name':str(claims.get('name') or email)[:100]}
        return RedirectResponse('/',status_code=303)

    @app.get('/auth/logout')
    async def logout(request: Request):
        if not conf['enabled']:
            return RedirectResponse('/',status_code=303)
        request.session.clear()
        query = urlencode({'returnTo':f"{conf['base']}/",'client_id':conf['client_id']},quote_via=quote)
        return RedirectResponse(f"https://{conf['domain']}/v2/logout?{query}",status_code=303)

    # Must wrap the guard so request.session is populated before it runs.
    if conf['enabled']:
        app.add_middleware(SessionMiddleware,secret_key=conf['session_secret'],
                           session_cookie='fieldshift_session',same_site='lax',
                           https_only=conf['https_only'],max_age=60*60*8)
    return conf
