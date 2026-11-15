"""Offline tests; no NASA/Gemini network calls or credentials required."""
import json
import os
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from types import SimpleNamespace
import app as server


class HostedPreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client=TestClient(server.app)

    def test_stateless_preview(self):
        for u in ['/', '/static/app.js', '/api/health','/api/overview','/api/locations/catalog','/api/calendar','/api/plan','/api/recorded','/api/nasa?mode=auto','/api/gemini/status']:
            self.assertEqual(self.client.get(u).status_code,200,u)
        overview=self.client.get('/api/overview').json()
        self.assertEqual(overview['state'],'offline')
        self.assertIsNone(overview['latest'])

    def test_plan_validation(self):
        good={'total_area':5,'area_unit':'acres','crops':[{'name':'Potatoes','area':2,'stage':'Planning'}]}
        self.assertEqual(self.client.post('/api/plan',json=good).status_code,200)
        bad={**good,'total_area':1}
        self.assertEqual(self.client.post('/api/plan',json=bad).status_code,400)

    def test_unprotected_gemini_is_blocked(self):
        resp=self.client.post('/api/plan/advice',json={'plan':{'total_area':5,'area_unit':'acres','crops':[{'name':'Corn','area':2}]},'location':{'latitude':40,'longitude':-73}})
        self.assertEqual(resp.status_code,403)

    def test_all_verified_auth0_sessions_are_eligible(self):
        from app import gemini_approved, gemini_status
        request=SimpleNamespace(scope={'session':{}},session={'user':{'mode':'auth0','sub':'auth0|new-user','email':'newuser@example.com'}})
        with patch.dict(os.environ, {'GEMINI_API_KEY':'fictional-api-key'}, clear=False):
            self.assertTrue(gemini_approved(request.session['user']))
            result=gemini_status(request)
            self.assertTrue(result['configured'])
            self.assertEqual(result['mode'], 'live')

    def test_sample_account_does_not_call_paid_model(self):
        body={'plan':{'total_area':5,'area_unit':'acres','crops':[{'name':'Corn','area':2}]},
              'location':{'latitude':40,'longitude':-73}}
        request=SimpleNamespace(scope={'session':{}},session={'user':{'mode':'sample','sub':'sample:test'}})
        with patch.object(server, 'generate_gemini_reply') as generate:
            result=server.farming_advice(server.AdviceRequest(**body), request)
            self.assertEqual(result['provider'],'demo')
            generate.assert_not_called()

    def test_model_parser_with_fake_provider(self):
        fake={'answer':'Estimated watering interval 3–4 days, depending on moisture and rain.','assumptions':['Drainage typical'],'source_notes':['Uses weather forecast.']}
        body={'plan':{'total_area':5,'area_unit':'acres','crops':[{'name':'Corn','area':2}]},'location':{'latitude':40,'longitude':-73},'question':'Help with corn'}
        # Mock only the provider functions. Real authentication enforcement is tested in v8.
        with patch.dict(os.environ,{'AUTH0_ENABLED':'1','GEMINI_API_KEY':'test-not-real'}),patch.object(server,'read_snapshot',return_value=None),patch.object(server,'forecast',return_value=[]),patch.object(server,'official_alerts',return_value={'status':'unavailable'}),patch.object(server,'fetch_nasa_daily',return_value={'period':'test','rows':[]}),patch.object(server,'generate_gemini_reply',return_value=json.dumps(fake)) as generate:
            request=SimpleNamespace(scope={'session':{}},session={'user':{'mode':'auth0','sub':'auth0|new-user','email':'newuser@example.com'}})
            result=server.farming_advice(server.AdviceRequest(**body),request)
            self.assertEqual(result['advice_structured']['answer'],fake['answer'])
            self.assertEqual(result['provider'],'gemini')
            self.assertEqual(generate.call_args.kwargs.get('json_mode'),True)


if __name__=='__main__':unittest.main()
