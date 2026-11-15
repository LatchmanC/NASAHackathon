"""Offline regression tests: no Google or NASA requests, no demo sensor records."""
import json
import os
import unittest
from datetime import date,timedelta
from types import SimpleNamespace
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from google_calendar_api import AddEvent,oauth_ready,install_google_calendar_routes
from farm_sync import install_farm_sync_routes
from advisor_core import answer_question

class GoogleCalendarSecurityTests(unittest.TestCase):
    def test_requires_explicit_confirmation_input(self):
        with self.assertRaises(ValidationError):
            AddEvent(request_id='ab'*15,date='2026-11-15',kind='planting',
                     crop='Strawberries')
        event=AddEvent(confirmed=True,request_id='ab'*15,
                       date='2026-11-15',kind='planting',crop='Strawberries')
        self.assertEqual(event.date,'2026-11-15')
        with self.assertRaises(ValidationError):
            AddEvent(confirmed=True,request_id='ab'*15,
                     date='2026/11/15',kind='planting')

    def test_google_calendar_is_not_ready_without_owner_credentials(self):
        with patch.dict(os.environ, {'GOOGLE_OAUTH_CLIENT_ID':'',
            'GOOGLE_OAUTH_CLIENT_SECRET':''},clear=False):
            self.assertFalse(oauth_ready())

    def test_daily_nasa_cron_is_fail_closed(self):
        app=FastAPI()
        install_farm_sync_routes(app)
        client=TestClient(app)
        with patch.dict(os.environ, {'CRON_SECRET':'test-only-secret'}):
            self.assertEqual(client.get('/api/nasa/cron-sync').status_code,401)
            self.assertEqual(client.get('/api/nasa/cron-sync',headers={
                'Authorization':'Bearer wrong'}).status_code,401)

    def test_proposal_never_writes_to_calendar_until_confirmed(self):
        import advisor_core
        plan={'total_area':2,'area_unit':'acres',
              'crops':[{'name':'Strawberries','area':1,'stage':'Planning'}]}
        day=date(2026,11,14)
        req=SimpleNamespace(plan=plan,
            question='I want to plant strawberries tomorrow',
            client_today=day.isoformat(),model='fake-model',
            location={'latitude':40.5,'longitude':-73.5},
            sensor_view='own',nasa_excerpt=[],upcoming_calendar_tasks=[],
            soil_view={},chat_history=[])
        request=SimpleNamespace(session={'user':{
            'sub':'auth0|test','mode':'auth0','email':'test@example.com'}})
        raw=json.dumps({'answer':'Good plan. Would you like it on both calendars?',
                        'assumptions':[],'source_notes':[],
                        'calendar_proposal':{'kind':'planting','crop':'Strawberries',
                            'date':'2026-11-18','note':'Prepare soil'}})
        with patch.dict(os.environ, {'GEMINI_API_KEY':'test-placeholder'}),\
             patch.object(advisor_core,'resolve_device_data',return_value=(None,'none')):
            result=answer_question(req,request,lambda p:p,
                lambda lat,lon:[],lambda loc:{'status':'unavailable'},
                lambda loc,days: {'period':'test','rows':[]},
                lambda key,instruction,model,json_mode:raw,
                'fake-model',lambda lat,lon:(lat,lon))
        self.assertEqual(result['calendar_proposal']['date'],
                         (day+timedelta(days=1)).isoformat())
        self.assertEqual(result['calendar_proposal']['kind'],'planting')
        self.assertNotIn('event_created',result)

if __name__=='__main__':
    unittest.main()
