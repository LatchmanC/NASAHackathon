"""Crop calendar, key handling, and first-tab regression checks."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
import web_server


class FieldShiftV7Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = patch.object(web_server, 'CALENDAR_FILE', Path(self.tmp.name) / 'events.json')
        self.patch.start()
        self.client = TestClient(web_server.app)

    def tearDown(self):
        self.client.close()
        self.patch.stop()
        self.tmp.cleanup()

    def test_calendar_add_list_delete_and_persistence(self):
        self.assertEqual(self.client.get('/api/calendar').json()['events'], [])
        payload = {'date': '2026-11-20', 'kind': 'watering', 'crop': 'Tomato', 'note': 'Check soil first'}
        r = self.client.post('/api/calendar', json=payload)
        self.assertEqual(r.status_code, 200)
        identifier = r.json()['events'][0]['id']
        self.assertEqual(self.client.get('/api/calendar').json()['events'][0]['note'], 'Check soil first')
        # Disk survived the request — the calendar is not solely browser state.
        self.assertTrue(web_server.CALENDAR_FILE.exists())
        self.assertEqual(self.client.delete('/api/calendar/' + identifier).status_code, 200)
        self.assertEqual(self.client.get('/api/calendar').json()['events'], [])

    def test_bad_calendar_event_rejected(self):
        for bad in [
            {'date': '2026-11-40', 'kind': 'harvest'},
            {'date': '2026-11-12', 'kind': 'invalid'},
            {'date': 'not a date', 'kind': 'watering'},
        ]:
            self.assertEqual(self.client.post('/api/calendar', json=bad).status_code, 400)

    def test_frontend_order_and_sprite(self):
        html = self.client.get('/').text
        self.assertLess(html.index('id="tab-crops"'), html.index('id="tab-live"'))
        self.assertLess(html.index('id="tab-live"'), html.index('id="tab-nasa"'))
        self.assertIn('/static/fieldy.svg', html)
        self.assertIn('id="calendar-grid"', html)
        self.assertNotIn('id="gemini-key"', html)
        self.assertEqual(self.client.get('/static/fieldy.svg').status_code, 200)

    def test_secret_not_returned_by_status(self):
        fake_key = 'FAKE_PRIVATE_KEY_SHOULD_NEVER_LEAK'
        with patch.dict(os.environ, {'GEMINI_API_KEY': fake_key}):
            r = self.client.get('/api/gemini/status')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['configured'])
        self.assertNotIn(fake_key, r.text)
        self.assertEqual(r.json()['model'], 'gemini-3.5-flash-lite')

if __name__ == '__main__':
    unittest.main()
