"""Auth0 settings tests use fictitious values; do not call the real provider."""
import os
import unittest
from unittest.mock import patch
from auth0_integration import settings

EXAMPLE = {
    'AUTH0_ENABLED':'1',
    'AUTH0_DOMAIN':'example.us.auth0.com',
    'AUTH0_CLIENT_ID':'example-public-client',
    'AUTH0_CLIENT_SECRET':'example-fake-secret',
    'AUTH0_SECRET':'x'*48,
    'AUTH0_ALLOWED_EMAILS':'farmer@example.com',
    'APP_BASE_URL':'https://cropaganda.garden',
}

class AuthSettingsTests(unittest.TestCase):
    def test_existing_auth0_secret(self):
        with patch.dict(os.environ, EXAMPLE, clear=True):
            s=settings()
            self.assertTrue(s['enabled'])
            self.assertEqual(s['session_secret'],'x'*48)
            self.assertEqual(s['base'],'https://cropaganda.garden')

    def test_session_secret_override(self):
        with patch.dict(os.environ, {**EXAMPLE,'SESSION_SECRET':'y'*64}, clear=True):
            self.assertEqual(settings()['session_secret'],'y'*64)

    def test_requires_explicit_allowlist(self):
        with patch.dict(os.environ, {**EXAMPLE,'AUTH0_ALLOWED_EMAILS':''}, clear=True):
            with self.assertRaisesRegex(RuntimeError,'AUTH0_ALLOWED_EMAILS'):
                settings()

    def test_rejects_insecure_public_origin(self):
        with patch.dict(os.environ, {**EXAMPLE,'APP_BASE_URL':'http://cropaganda.garden'}, clear=True):
            with self.assertRaises(RuntimeError):
                settings()

    def test_production_cannot_disable_auth(self):
        with patch.dict(os.environ, {'AUTH0_ENABLED':'0','FIELDSHIFT_DEMO':'0'}, clear=True):
            with self.assertRaisesRegex(RuntimeError,'Refusing'):
                settings()

if __name__=='__main__': unittest.main()
