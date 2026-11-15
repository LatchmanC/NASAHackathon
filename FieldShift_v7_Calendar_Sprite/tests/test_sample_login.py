import os
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from auth0_integration import install_auth, settings

class SampleLoginTests(unittest.TestCase):
    def setUp(self):
        self.patch=patch.dict(os.environ,{
            'AUTH0_ENABLED':'0','FIELDSHIFT_DEMO':'1','FIELDSHIFT_SAMPLE_ACCOUNT':'1',
            'SESSION_SECRET':'supersecure-unit-test-secret-'+('x'*50),
            'APP_BASE_URL':'http://127.0.0.1:8501'
        },clear=True)
        self.patch.start()
        a=FastAPI()
        @a.get('/api/private')
        def private():return {'ok':True}
        @a.post('/api/private')
        def mutate():return {'ok':True}
        self.settings=install_auth(a)
        self.client=TestClient(a,base_url='http://127.0.0.1:8501',follow_redirects=False)
    def tearDown(self):self.patch.stop()
    def test_no_session_cannot_call_api(self):
        self.assertEqual(self.client.get('/api/private').status_code,401)
        self.assertFalse(self.client.get('/api/auth/me').json()['authenticated'])
    def test_test_profile_can_sign_in(self):
        r=self.client.post('/auth/demo',data={'username':'test','password':'test'})
        self.assertEqual(r.status_code,303)
        self.assertEqual(r.headers['location'],'/dashboard.html')
        profile=self.client.get('/api/auth/me').json()
        self.assertTrue(profile['authenticated'])
        self.assertEqual(profile['user']['mode'],'sample')
        self.assertNotIn('email',profile['user'])
        self.assertEqual(self.client.get('/api/private').status_code,200)
        self.assertEqual(self.client.post('/api/private').status_code,403)
        self.assertEqual(self.client.post('/api/private',headers={'X-FieldShift-Request':'1'}).status_code,200)
        self.assertEqual(self.client.get('/auth/logout').status_code,303)
        self.assertEqual(self.client.get('/api/private').status_code,401)
    def test_demo_button_signs_in_without_credentials(self):
        r=self.client.post('/auth/demo',data={'demo':'1'})
        self.assertEqual(r.status_code,303)
        self.assertEqual(r.headers['location'],'/dashboard.html')
        profile=self.client.get('/api/auth/me').json()
        self.assertEqual(profile['user']['mode'],'sample')
        self.assertEqual(profile['user']['name'],'Demo Farmer')
        self.assertNotIn('email',profile['user'])

    def test_cross_site_demo_form_rejected(self):
        r=self.client.post('/auth/demo',data={'demo':'1'},
                           headers={'origin':'https://evil.example',
                                    'sec-fetch-site':'cross-site'})
        self.assertEqual(r.status_code,403)
        self.assertFalse(self.client.get('/api/auth/me').json()['authenticated'])

    def test_bad_password_rejected(self):
        self.assertEqual(self.client.post('/auth/demo',data={'username':'test','password':'wrong'}).headers['location'],'/?error=invalid')
        self.assertEqual(self.client.get('/api/private').status_code,401)
    def test_cross_origin_post_rejected(self):
        r=self.client.post('/auth/demo',data={'username':'test','password':'test'},headers={'origin':'https://evil.example'})
        self.assertEqual(r.status_code,403)
        self.assertEqual(self.client.get('/api/private').status_code,401)
    def test_retired_sample_login_is_disabled(self):
        with patch.dict(os.environ, {'FIELDSHIFT_SAMPLE_ACCOUNT':'0'}):
            a=FastAPI()
            install_auth(a)
            c=TestClient(a,base_url='http://127.0.0.1:8501',follow_redirects=False)
            r=c.post('/auth/demo',data={'username':'test','password':'test'})
            self.assertEqual(r.status_code,404)
            self.assertFalse(c.get('/api/auth/me').json()['sample_available'])

    def test_auth_disabled_in_production_refused(self):
        with patch.dict(os.environ,{'AUTH0_ENABLED':'0','FIELDSHIFT_DEMO':'0'}):
            with self.assertRaises(RuntimeError):settings()

if __name__=='__main__':unittest.main()
