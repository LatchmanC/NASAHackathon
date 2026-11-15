"""Offline tests for the Cropoganda 10-minute History API."""
import os
import unittest
from unittest.mock import patch
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware
from history_api import install_history_routes
import history_api

class ArchiveAPITests(unittest.TestCase):
    def setUp(self):
        self.app=FastAPI()
        @self.app.get('/_login')
        def login(request:Request):
            request.session['user']={'mode':'auth0','sub':'auth0|owner',
                                     'email':'owner@example.com'}
            return {'ok':True}
        install_history_routes(self.app)
        self.app.add_middleware(SessionMiddleware,secret_key='test'*24)
        self.client=TestClient(self.app)
        self.client.get('/_login')
    def test_unconfigured_is_explicit(self):
        with patch.object(history_api.tiger,'enabled',return_value=False):
            r=self.client.get('/api/history/status')
            self.assertEqual(r.status_code,200)
            self.assertFalse(r.json()['configured'])
            self.assertEqual(self.client.get('/api/history/days?year=2026&month=11').status_code,503)
    def test_saved_times_are_read_only(self):
        stamp='2026-11-14T20:00:00+00:00'
        with patch.object(history_api.tiger,'enabled',return_value=True),\
             patch.object(history_api,'selected_account',return_value=('auth0|owner','own')),\
             patch.object(history_api.tiger,'dates',return_value=[{'date':'2026-11-14','count':1}]),\
             patch.object(history_api.tiger,'times',return_value=[{'bucket_at':stamp,'recorded_at':stamp,'device_id':'esp32-01'}]),\
             patch.object(history_api.tiger,'archived_reading',return_value={'device_id':'esp32-01','temperature_c':22.3}),\
             patch.object(history_api.tiger,'nasa_day',return_value={'observations':{'temperature_c':19.1},'stored_at':stamp}):
            days=self.client.get('/api/history/days?year=2026&month=11').json()
            self.assertEqual(days['days'][0]['count'],1)
            entries=self.client.get('/api/history/snapshots?day=2026-11-14').json()
            self.assertEqual(entries['snapshots'][0]['device_id'],'esp32-01')
            selected=self.client.get('/api/history/entry',params={'day':'2026-11-14',
                'bucket':stamp,'latitude':40,'longitude':-73}).json()
            self.assertEqual(selected['sensor']['temperature_c'],22.3)
            self.assertEqual(selected['nasa']['observations']['temperature_c'],19.1)
    def test_nasa_sync_uses_verified_nasa_only(self):
        with patch.object(history_api.tiger,'enabled',return_value=True),\
             patch.object(history_api,'fetch_nasa_daily',return_value={'is_real_nasa':True,'rows':[{'date':'2026-11-12','temperature_c':21.1}], 'period':'2026-11-12 through 2026-11-12'}),\
             patch.object(history_api.tiger,'save_nasa',return_value=1) as store:
            r=self.client.post('/api/history/sync-nasa',json={'location':{'latitude':40,'longitude':-73},'days':90})
            self.assertEqual(r.status_code,200,r.text)
            self.assertEqual(r.json()['stored_days'],1)
            self.assertEqual(store.call_args.args[0],'auth0|owner')
    def test_rejects_anonymous_reader(self):
        fresh=TestClient(self.app)
        self.assertEqual(fresh.get('/api/history/status').status_code,403)

if __name__=='__main__':
    unittest.main()
