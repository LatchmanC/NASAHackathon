"""Offline regression tests for location picker, TLS and Gemini model."""
import json
import ssl
import unittest
from unittest.mock import MagicMock, patch

from fieldshift_core import http_json, make_location
from gemini_client import DEFAULT_GEMINI_MODEL
from location_catalog import catalog, resolve_preset
from web_server import app

class LocationAndTLS(unittest.TestCase):
    def test_model_default(self):
        self.assertEqual(DEFAULT_GEMINI_MODEL, 'gemini-3.5-flash-lite')

    def test_catalog_has_usable_countries(self):
        countries=catalog()
        self.assertGreaterEqual(len(countries),200)
        for code,region,city in [('US','New York','Albany'),('CA','Ontario','Toronto'),('GY','Demerara-Mahaica','Georgetown')]:
            data=resolve_preset(code,region,city)
            self.assertIn(city,data['label'])
            self.assertEqual(data['mode'],'preset')
            self.assertIsInstance(data['latitude'],float)

    def test_preset_does_not_call_geocoder(self):
        record=resolve_preset('US','New York','New York City')
        with patch('fieldshift_core.geocode',side_effect=AssertionError('Unexpected geocoding request')):
            saved=make_location('preset', record['label'], record['latitude'],record['longitude'])
        self.assertEqual(saved['latitude'],40.7128)

    def test_reject_unlisted_city(self):
        with self.assertRaisesRegex(ValueError,'offline list'):
            resolve_preset('US','New York','NotARealCity123')

    def test_https_uses_verified_context(self):
        response=MagicMock()
        response.read.return_value=b'{"ok":true}'
        contextmgr=MagicMock()
        contextmgr.__enter__.return_value=response
        with patch('fieldshift_core.urlopen',return_value=contextmgr) as mocked:
            self.assertEqual(http_json('GET','https://power.larc.nasa.gov/api/test'),{'ok':True})
        context=mocked.call_args.kwargs.get('context')
        self.assertIsNotNone(context)
        self.assertEqual(context.verify_mode,ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)

    def test_no_tls_context_for_local_http(self):
        response=MagicMock();response.read.return_value=b'{"ok":true}'
        with patch('fieldshift_core.urlopen') as mocked:
            mocked.return_value.__enter__.return_value=response
            http_json('GET','http://127.0.0.1:8765/health')
        self.assertNotIn('context',mocked.call_args.kwargs)

    def test_catalog_web_endpoint(self):
        from fastapi.testclient import TestClient
        with TestClient(app) as client:
            result=client.get('/api/locations/catalog')
            self.assertEqual(result.status_code,200)
            self.assertIn('US',result.json()['countries'])
            result=client.post('/api/location',json={'mode':'preset','country':'US','region':'New York','city':'Imaginary City'})
            self.assertEqual(result.status_code,400)

if __name__=='__main__':unittest.main()
