"""Read-only ESP32 sharing regression tests with fake storage."""
import os
import unittest
from unittest.mock import patch
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware
from device_api import install_device_routes,resolve_device_data,signer
import device_api

class SharedDeviceTests(unittest.TestCase):
    def setUp(self):
        self.records={'owner':{'schema':1,'latest':{'device_id':'esp32-01','temperature_c':23.5,
                      'recorded_at':'2026-11-14T20:00:00+00:00'},'readings':[],
                      'share_version':'v1'}}
        self.links={}
        self.settings_patch=patch('auth0_integration.settings',return_value={'session_secret':'s'*64})
        self.settings_patch.start()
        self.config_patch=patch.object(device_api,'configured',return_value=True)
        self.config_patch.start()
        self.read_patch=patch.object(device_api,'read_snapshot',side_effect=lambda sub:self.records.get(sub))
        self.read_patch.start()
        self.link_read=patch.object(device_api,'read_shared_link',side_effect=lambda sub:self.links.get(sub))
        self.link_read.start()
        self.link_save=patch.object(device_api,'save_shared_link',side_effect=self.store_link)
        self.link_save.start()
        self.revoke_patch=patch.object(device_api,'revoke_shared_viewers',side_effect=self.revoke)
        self.revoke_patch.start()
        a=FastAPI()
        @a.get('/login/{user}')
        def login(user:str,request:Request):
            request.session['user']={'mode':'auth0','sub':user,'email':user+'@example.com'}
            return {'ok':True}
        install_device_routes(a)
        a.add_middleware(SessionMiddleware,secret_key='testing-session-key'*3)
        self.client=TestClient(a)
        self.client.get('/login/owner')
    def tearDown(self):
        for attr in ('revoke_patch','link_save','link_read','read_patch','config_patch','settings_patch'):
            getattr(self,attr).stop()
    def store_link(self,sub,token=None):
        self.links[sub]={'schema':1,'token':token} if token else None
    def revoke(self,owner):
        self.records[owner]['share_version']='rotated'

    def test_share_token_is_not_upload_token_and_is_read_only(self):
        token_response=self.client.post('/api/device/share/token',json={'device_id':'esp32-01'})
        self.assertEqual(token_response.status_code,200,token_response.text)
        token=token_response.json()['token']
        self.assertEqual(token_response.json()['permission'],'read-only')
        self.assertNotEqual(token,signer().dumps({'sub':'owner','device_id':'esp32-01'}))
        self.client.get('/login/viewer')
        joined=self.client.post('/api/device/share/join',json={'token':token})
        self.assertEqual(joined.status_code,200,joined.text)
        snap,mode=resolve_device_data('viewer')
        self.assertEqual(mode,'shared')
        self.assertEqual(snap['latest']['temperature_c'],23.5)
        self.assertEqual(self.client.get('/api/device/share/status').json()['device_id'],'esp32-01')
        self.assertEqual(self.client.post('/api/device/validate',headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'},
            json={'device_id':'esp32-01','temperature_c':25}).status_code,401)

    def test_invalid_upload_token_cannot_be_imported_as_viewer(self):
        self.client.get('/login/viewer')
        write_token=signer().dumps({'sub':'owner','device_id':'esp32-01'})
        self.assertEqual(self.client.post('/api/device/share/join',json={'token':write_token}).status_code,400)
        self.assertEqual(self.client.post('/api/device/share/join',json={'token':'bad-token'*5}).status_code,400)
        self.assertNotIn('viewer',self.links)

    def test_revoke_all_disables_existing_links(self):
        token=self.client.post('/api/device/share/token',json={'device_id':'esp32-01'}).json()['token']
        self.client.get('/login/viewer')
        self.assertEqual(self.client.post('/api/device/share/join',json={'token':token}).status_code,200)
        self.assertEqual(resolve_device_data('viewer')[1],'shared')
        self.client.get('/login/owner')
        self.assertEqual(self.client.post('/api/device/share/revoke').status_code,200)
        self.assertEqual(resolve_device_data('viewer')[1],'none')
        self.client.get('/login/viewer')
        self.assertFalse(self.client.get('/api/device/share/status').json()['connected'])
        self.assertEqual(self.client.post('/api/device/share/join',json={'token':token}).status_code,403)

    def test_disconnect_and_select_view(self):
        token=self.client.post('/api/device/share/token',json={'device_id':'esp32-01'}).json()['token']
        self.client.get('/login/viewer')
        self.client.post('/api/device/share/join',json={'token':token})
        self.assertEqual(resolve_device_data('viewer','shared')[1],'shared')
        self.assertEqual(resolve_device_data('viewer','own')[1],'none')
        self.assertEqual(self.client.post('/api/device/share/disconnect').status_code,200)
        self.assertEqual(resolve_device_data('viewer','auto')[1],'none')
        self.assertEqual(self.client.get('/api/device/share/status').json()['connected'],False)
        self.assertRaises(Exception,resolve_device_data,'viewer','invalid')

    def test_only_owner_can_generate_and_only_known_device(self):
        self.assertEqual(self.client.post('/api/device/share/token',json={'device_id':'other'}).status_code,409)
        self.client.get('/login/viewer')
        self.assertEqual(self.client.post('/api/device/share/token',json={'device_id':'esp32-01'}).status_code,409)

if __name__=='__main__':unittest.main()
