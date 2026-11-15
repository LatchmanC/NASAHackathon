"""Signup and Gemini approval tests; fake Auth0 provider, no network or secrets."""
import os
import sys
import types
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.testclient import TestClient
from auth0_integration import install_auth, settings
from app import gemini_approved

class FakeRemote:
    claims={'sub':'auth0|new123','email':'newuser@example.com','email_verified':True,'name':'New Farmer'}
    async def authorize_redirect(self,request,redirect_uri,**kwargs):
        args='&'.join(f'{k}={v}' for k,v in kwargs.items())
        return RedirectResponse('/fake-provider?'+args+'&redirect_uri='+redirect_uri,status_code=302)
    async def authorize_access_token(self,request):
        return {'userinfo':self.claims.copy()}
class FakeOAuth:
    def __init__(self): self.auth0=FakeRemote()
    def register(self,**kwargs):pass

class SignupTests(unittest.TestCase):
    def setUp(self):
        fake_root=types.ModuleType('authlib');fake_root.__path__=[]
        fake_integrations=types.ModuleType('authlib.integrations');fake_integrations.__path__=[]
        fake_mod=types.ModuleType('authlib.integrations.starlette_client');fake_mod.OAuth=FakeOAuth
        self.mods=patch.dict(sys.modules,{'authlib':fake_root,'authlib.integrations':fake_integrations,'authlib.integrations.starlette_client':fake_mod})
        self.mods.start()
        self.env=patch.dict(os.environ,{'AUTH0_ENABLED':'1','AUTH0_ALLOW_SIGNUPS':'1','FIELDSHIFT_DEMO':'0',
            'AUTH0_DOMAIN':'example.us.auth0.com','AUTH0_CLIENT_ID':'fake-id','AUTH0_CLIENT_SECRET':'fake-client-secret',
            'AUTH0_SECRET':'z'*64,'AUTH0_ALLOWED_EMAILS':'approved@example.com',
            'APP_BASE_URL':'https://cropaganda.garden'},clear=True)
        self.env.start()
        a=FastAPI()
        @a.get('/api/private')
        def private(): return {'ok':True}
        install_auth(a)
        self.client=TestClient(a,base_url='https://cropaganda.garden',follow_redirects=False)
    def tearDown(self):self.env.stop();self.mods.stop()
    def test_signup_opens_auth0_signup_screen(self):
        r=self.client.get('/auth/signup')
        self.assertEqual(r.status_code,302)
        self.assertIn('screen_hint=signup',r.headers['location'])
        self.assertIn('prompt=login',r.headers['location'])
    def test_verified_unlisted_user_can_join(self):
        self.assertEqual(self.client.get('/api/private').status_code,401)
        r=self.client.get('/auth/callback')
        self.assertEqual(r.status_code,303)
        self.assertEqual(r.headers['location'],'/dashboard.html')
        user=self.client.get('/api/auth/me').json()
        self.assertTrue(user['authenticated'])
        self.assertEqual(user['user']['email'],'newuser@example.com')
        self.assertTrue(gemini_approved(user['user']))
        self.assertEqual(self.client.get('/api/private').status_code,200)
    def test_unverified_user_cannot_join(self):
        FakeRemote.claims={**FakeRemote.claims,'email_verified':False}
        try:
            self.assertEqual(self.client.get('/auth/callback').status_code,403)
            self.assertEqual(self.client.get('/api/private').status_code,401)
        finally:FakeRemote.claims={**FakeRemote.claims,'email_verified':True}
    def test_can_disable_signups_without_blocking_preapproved(self):
        with patch.dict(os.environ,{'AUTH0_ALLOW_SIGNUPS':'0'}):
            a=FastAPI();install_auth(a)
            c=TestClient(a,base_url='https://cropaganda.garden',follow_redirects=False)
            self.assertEqual(c.get('/auth/signup').headers['location'],'/?error=signup_unavailable')
            self.assertEqual(c.get('/auth/callback').status_code,403)
    def test_gemini_for_every_verified_auth0_session_not_sample(self):
        # The Auth0 callback issues sessions only for email_verified=True.
        self.assertTrue(gemini_approved({'mode':'auth0','sub':'auth0|new123','email':'newuser@example.com'}))
        self.assertTrue(gemini_approved({'mode':'auth0','sub':'auth0|old123','email':'approved@example.com'}))
        self.assertFalse(gemini_approved({'mode':'sample','sub':'sample:test','email':'approved@example.com'}))
        self.assertFalse(gemini_approved({'mode':'auth0','sub':'','email':'newuser@example.com'}))
        self.assertFalse(gemini_approved({'mode':'auth0','sub':'auth0|fake','email':''}))
    def test_retired_sample_cookie_cannot_access_private_api(self):
        # A cookie created before retirement must stop working when demo is disabled.
        with patch.dict(os.environ, {'FIELDSHIFT_SAMPLE_ACCOUNT':'1'}):
            older=FastAPI()
            install_auth(older)
            client=TestClient(older,base_url='https://cropaganda.garden',follow_redirects=False)
            login=client.post('/auth/demo',data={'username':'test','password':'test'})
            self.assertEqual(login.status_code,303)
            old_cookie=client.cookies.get('fieldshift_session')
            self.assertTrue(old_cookie)
        self.client.cookies.set('fieldshift_session',old_cookie)
        self.assertEqual(self.client.get('/api/private').status_code,401)
        self.assertFalse(self.client.get('/api/auth/me').json()['authenticated'])

    def test_settings_exposes_signup(self):
        self.assertTrue(settings()['signup_enabled'])
        with patch.dict(os.environ,{'AUTH0_ALLOW_SIGNUPS':'0'}):
            self.assertFalse(settings()['signup_enabled'])
if __name__=='__main__':unittest.main()
