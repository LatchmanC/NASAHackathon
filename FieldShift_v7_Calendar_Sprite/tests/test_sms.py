"""Text-message (Twilio) tests. Offline: no real Twilio, Blob, or Gemini calls."""
import os
import unittest
from unittest.mock import patch

os.environ.update({'TWILIO_ACCOUNT_SID': 'ACtest', 'TWILIO_AUTH_TOKEN': 'secret-token',
                   'TWILIO_FROM_NUMBER': '+16413216713', 'FIELDSHIFT_SMS_TO': '+16204136430',
                   'APP_BASE_URL': 'https://farm.example', 'CRON_SECRET': 'cron-secret',
                   'GEMINI_API_KEY': 'fake-key'})

from fastapi.testclient import TestClient
from twilio.request_validator import RequestValidator
import app as server
import sms

URL = 'https://farm.example/api/twilio/sms'
LINK = {'owner': 'auth0|farmer', 'location': {'latitude': 40.7, 'longitude': -74.0, 'label': 'Test Farm'},
        'calendar': [{'date': '2099-01-02', 'kind': 'watering', 'crop': 'Corn', 'note': 'Field 2'}]}
READING = {'recorded_at': '2026-11-14T22:00:00+00:00', 'temperature_c': 21.5, 'humidity_pct': 60,
           'soil_moisture_pct': 41, 'rain_wetness_pct': 3, 'light_pct': 50, 'pressure_hpa': 1012}


def signed(client, params, signature=None):
    sig = signature or RequestValidator('secret-token').compute_signature(URL, params)
    return client.post('/api/twilio/sms', data=params, headers={'X-Twilio-Signature': sig})


class SmsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(server.app)

    def test_forged_webhook_rejected(self):
        r = signed(self.client, {'From': '+16204136430', 'Body': 'STATUS'}, signature='forged')
        self.assertEqual(r.status_code, 403)

    def test_unknown_number_refused(self):
        r = signed(self.client, {'From': '+19999999999', 'Body': 'STATUS'})
        self.assertIn('not registered', r.text)

    @patch('sms.read_link', return_value=LINK)
    @patch('sms.read_snapshot', return_value={'latest': READING})
    def test_status_and_tasks(self, *_):
        r = signed(self.client, {'From': '+16204136430', 'Body': 'status'})
        self.assertEqual(r.status_code, 200)
        self.assertIn('Soil moisture 41%', r.text)
        self.assertIn('Test Farm', r.text)
        r = signed(self.client, {'From': '+16204136430', 'Body': 'TASKS'})
        self.assertIn('Watering Corn: Field 2', r.text)

    @patch('sms.read_link', return_value=LINK)
    @patch('sms.read_snapshot', return_value={'latest': READING})
    def test_question_goes_to_fieldy(self, *_):
        with patch.object(sms, 'ask_fieldy', return_value='Water early tomorrow.') as ask:
            r = signed(self.client, {'From': '+16204136430', 'Body': 'Should I water my corn?'})
        self.assertIn('Water early tomorrow.', r.text)
        self.assertEqual(ask.call_args[0][0], 'Should I water my corn?')

    def test_fieldy_timeout_is_handled(self):
        import time
        def slow_gemini(*a, **k):
            time.sleep(12)
        start = time.time()
        text = sms.ask_fieldy('hi', READING, {'owner': 'x', 'calendar': []}, slow_gemini, 'm', lambda *a: [])
        self.assertLess(time.time() - start, 11.5)        # must stay under Twilio's 15 s
        self.assertIn('could not answer', text)

    def test_stop_handled_by_twilio(self):
        r = signed(self.client, {'From': '+16204136430', 'Body': 'STOP'})
        self.assertNotIn('<Message>', r.text)

    def test_alert_only_on_new_crossing(self):
        dry = {**READING, 'soil_moisture_pct': 18}
        with patch('sms.read_link', return_value=LINK), patch('sms.send_sms', return_value={'sent': True}) as send:
            sms.on_new_reading('auth0|farmer', dry, READING)      # crosses -> text
            sms.on_new_reading('auth0|farmer', dry, dry)          # still dry -> no repeat
            sms.on_new_reading('auth0|someone-else', dry, READING)  # not the linked farm -> no text
        self.assertEqual(send.call_count, 1)
        self.assertIn('Low soil moisture', send.call_args[0][1])

    def test_alert_never_breaks_upload(self):
        with patch('sms.read_link', side_effect=RuntimeError('blob down')):
            self.assertEqual(sms.on_new_reading('auth0|farmer', READING, None), [])

    def test_cron_requires_secret(self):
        self.assertEqual(self.client.get('/api/sms/cron-reminders').status_code, 401)
        with patch('sms.read_link', return_value={**LINK, 'calendar': []}):
            r = self.client.get('/api/sms/cron-reminders', headers={'Authorization': 'Bearer cron-secret'})
        self.assertEqual(r.status_code, 200)

    def test_cron_sends_tomorrows_tasks(self):
        from datetime import date
        with patch('sms.farm_today', return_value=date(2099, 1, 1)), \
             patch('sms.read_link', return_value=LINK), \
             patch('sms.send_sms', return_value={'sent': True}) as send:
            self.client.get('/api/sms/cron-reminders', headers={'Authorization': 'Bearer cron-secret'})
        self.assertIn('Watering Corn: Field 2', send.call_args[0][1])

    def test_dashboard_buttons_need_login(self):
        self.assertEqual(self.client.post('/api/sms/test', headers={'X-FieldShift-Request': '1'}).status_code in (401, 403), True)

    def test_status_hides_numbers(self):
        with patch('sms.read_link', return_value=None):
            s = self.client.get('/api/sms/status').json()
        self.assertNotIn('+16204136430', str(s))
        self.assertTrue(s['configured'])


class SmsWithLoginEnabled(unittest.TestCase):
    """With the public sample login on, Twilio and Vercel Cron must still reach their routes."""
    def test_webhook_and_cron_bypass_session(self):
        with patch.dict(os.environ, {'FIELDSHIFT_SAMPLE_ACCOUNT': '1', 'SESSION_SECRET': 'x' * 40}):
            import importlib
            import auth0_integration
            importlib.reload(auth0_integration)
            app = importlib.reload(server).app
            client = TestClient(app)
            self.assertEqual(client.get('/api/overview').status_code, 401)      # private API stays private
            r = signed(client, {'From': '+19999999999', 'Body': 'hi'})
            self.assertEqual(r.status_code, 200)                                # Twilio gets through
            self.assertEqual(client.get('/api/sms/cron-reminders').status_code, 401)  # needs CRON_SECRET, not session
        importlib.reload(auth0_integration)
        importlib.reload(server)


if __name__ == '__main__':
    unittest.main()
