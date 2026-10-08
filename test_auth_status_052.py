"""Synthetic offline tests. No real account credentials or browser sessions."""
import asyncio
import logging
import os
import json
import sys
import types
import unittest
from unittest.mock import patch
import auth_status_v052 as app


class Locator:
    def __init__(self, count=0, labels=None, text='', change=None):
        self.n, self.labels, self.text, self.change = count, labels, text, change
    async def count(self): return self.n
    async def evaluate_all(self, expression): return self.labels
    async def inner_text(self, **kwargs):
        if self.change: self.change()
        return self.text


class Page:
    def __init__(self, url='https://myaccount.google.com/', password=False, challenge=False,
                 labels=None, body='Demo owner@example.test', closed=False):
        self.url, self.closed = url, closed
        self.items = {
            app.PASSWORD: Locator(int(password)), app.CHALLENGE: Locator(int(challenge)),
            app.GOOGLE_ACCOUNT: Locator(len(labels or []), labels), 'body': Locator(1, text=body)}
    def is_closed(self): return self.closed
    def locator(self, selector): return self.items.get(selector, Locator())


class Context:
    def __init__(self, cookies=None): self.values = cookies or []
    async def cookies(self, origin): return self.values


def session(**kwargs):
    cookies = kwargs.pop('cookies', None)
    return types.SimpleNamespace(page=Page(**kwargs), context=Context(cookies), profile='Fixture')


def config(origin='https://m.facebook.com', profile='Fixture'):
    return {'demo': {'origin': origin, 'profile': profile,
                     'username': 'demo@example.test', 'password': 'SYNTHETIC_TEST_ONLY'}}


class Evidence(unittest.IsolatedAsyncioTestCase):
    async def test_google_identity_verified(self):
        s = session(labels=['Konto Google: Demo (owner@example.test)'])
        self.assertIs((await app.inspect_session(s))['authenticated'], True)
    async def test_google_identity_mismatch_unknown(self):
        s = session(labels=['Account: other@example.test'])
        self.assertIsNone((await app.inspect_session(s))['authenticated'])
    async def test_google_missing_identity_unknown(self):
        self.assertIsNone((await app.inspect_session(session()))['authenticated'])
    async def test_google_password_overrides_identity(self):
        s = session(password=True, labels=['Account: owner@example.test'])
        self.assertEqual((await app.inspect_session(s))['stage'], 'login_form')
    async def test_visible_challenge_stops(self):
        self.assertEqual((await app.inspect_session(session(challenge=True)))['next_action'], 'stop_automatic_login')
    async def test_checkpoint_path_stops(self):
        s = session(url='https://m.facebook.com/checkpoint/123')
        self.assertEqual((await app.inspect_session(s))['stage'], 'verification_required')
    async def test_expired_session(self):
        self.assertEqual((await app.inspect_session(session(closed=True)))['stage'], 'expired')
    async def test_http_not_trusted(self):
        s = session(url='http://myaccount.google.com/', labels=['Account: owner@example.test'])
        self.assertIsNone((await app.inspect_session(s))['authenticated'])
    async def test_lookalike_origin_not_trusted(self):
        s = session(url='https://myaccount.google.com.evil.test/', labels=['Account: owner@example.test'])
        self.assertIsNone((await app.inspect_session(s))['authenticated'])
    async def test_userinfo_origin_not_trusted(self):
        s = session(url='https://demo:fake@myaccount.google.com/', labels=['Account: owner@example.test'])
        self.assertIsNone((await app.inspect_session(s))['authenticated'])
    async def test_nonstandard_port_not_trusted(self):
        s = session(url='https://myaccount.google.com:8443/', labels=['Account: owner@example.test'])
        self.assertIsNone((await app.inspect_session(s))['authenticated'])
    async def test_page_change_does_not_report_success(self):
        s = session(labels=['Account: owner@example.test'])
        s.page.items['body'].change = lambda: setattr(s.page, 'url', 'https://accounts.google.com/')
        self.assertIsNone((await app.inspect_session(s))['authenticated'])
    async def test_google_login_page_not_authenticated(self):
        s = session(url='https://accounts.google.com/v3/signin/identifier')
        self.assertIs((await app.inspect_session(s))['authenticated'], False)
    async def test_facebook_cookie_alone_is_not_success(self):
        s = session(url='https://m.facebook.com/', cookies=[{'name':'c_user','value':'FAKE'}, {'name':'xs','value':'FAKE'}])
        answer = await app.inspect_session(s)
        self.assertIsNone(answer['authenticated'])
        self.assertEqual(answer['next_action'], 'verify_protected_page_without_login')
    async def test_instagram_public_navigation_is_not_success(self):
        s = session(url='https://www.instagram.com/', body='Home Direct Profile')
        self.assertIs((await app.inspect_session(s))['authenticated'], False)
    async def test_read_error_not_logged_out(self):
        s = session(); s.page.locator = lambda _: (_ for _ in ()).throw(RuntimeError('SYNTHETIC_SECRET'))
        answer = await app.inspect_session(s)
        self.assertIsNone(answer['authenticated'])
        self.assertNotIn('SYNTHETIC_SECRET', json.dumps(answer))
    async def test_result_does_not_expose_email(self):
        answer = await app.inspect_session(session(labels=['Account: owner@example.test']))
        self.assertNotIn('owner@example.test', json.dumps(answer))


class ConfigAndLogging(unittest.TestCase):
    def readiness(self, value, profile='Fixture', url='https://m.facebook.com/'):
        with patch.dict(os.environ, {'AI_BROWSER_CREDENTIALS_JSON': value}):
            return app.credential_readiness(profile, url)
    def test_missing_config(self): self.assertEqual(self.readiness('')['status'], 'not_configured')
    def test_invalid_json(self): self.assertEqual(self.readiness('{')['status'], 'invalid_configuration')
    def test_empty_config_not_ready(self): self.assertEqual(self.readiness('{}')['status'], 'no_match_for_current_origin')
    def test_matching_config_ready(self): self.assertEqual(self.readiness(json.dumps(config()))['status'], 'configured_for_current_origin')
    def test_other_profile_not_ready(self): self.assertEqual(self.readiness(json.dumps(config()), profile='Other')['status'], 'no_match_for_current_origin')
    def test_other_origin_not_ready(self): self.assertEqual(self.readiness(json.dumps(config()), url='https://www.instagram.com/')['status'], 'no_match_for_current_origin')
    def test_ambiguous_config_not_ready(self):
        data = config(); data['other'] = data['demo'].copy()
        self.assertEqual(self.readiness(json.dumps(data))['status'], 'ambiguous_configuration')
    def test_empty_password_not_ready(self):
        data = config(); data['demo']['password'] = ''
        self.assertEqual(self.readiness(json.dumps(data))['status'], 'invalid_configuration')
    def test_credentials_never_in_status(self): self.assertNotIn('SYNTHETIC_TEST_ONLY', json.dumps(self.readiness(json.dumps(config()))))
    def test_redirect_origin_not_ready(self): self.assertEqual(self.readiness(json.dumps(config('https://m.facebook.com/other')))['status'], 'invalid_configuration')
    def test_multiple_google_accounts_ambiguous(self): self.assertFalse(app.google_identity_matches(['a@example.test','b@example.test'], 'a@example.test b@example.test'))
    def test_log_path_redacted(self): self.assertEqual(app.redact_log_text('POST /mcp/TEST_ONLY_VALUE HTTP/1.1'), 'POST /mcp/[redacted] HTTP/1.1')
    def test_query_keys_redacted(self):
        text = app.redact_log_text('https://fixture.test/?apiKey=FAKE&code=DEMO&x=1')
        self.assertNotIn('FAKE', text); self.assertNotIn('DEMO', text); self.assertIn('x=1', text)
    def test_uvicorn_format_args_preserved(self):
        args = ('127.0.0.1', 'POST', '/mcp/TEST_ONLY_VALUE', '1.1', 200)
        record = logging.LogRecord('uvicorn.access', logging.INFO, '', 1, '%s %s %s %s %s', args, None)
        self.assertTrue(app.AccessSecretFilter().filter(record)); self.assertEqual(len(record.args), 5)
        self.assertEqual(record.args[-1], 200); self.assertNotIn('TEST_ONLY_VALUE', record.getMessage())


class Lifecycle(unittest.IsolatedAsyncioTestCase):
    async def test_close_and_start_serialized_without_account_writes(self):
        events = []
        class Manager:
            def _session(self, sid): return session()
            async def status(self, sid): return {'session_id': sid}
            async def start(self, *args, **kwargs):
                events.append('start-enter'); await asyncio.sleep(.01); events.append('start-exit')
                return {'session_id': 'test-only'}
            async def stop(self, *args, **kwargs):
                events.append('stop-enter'); await asyncio.sleep(.01); events.append('stop-exit')
                return {'stopped': True}
        manager = Manager()
        modules = {'steel_context_fix':types.SimpleNamespace(), 'steel_runtime':types.SimpleNamespace()}
        with patch.dict(sys.modules, modules), patch.dict(os.environ, {'AI_BROWSER_ENGINE':'steel'}):
            app.install({'manager': manager})
            await asyncio.gather(manager.stop('old'), manager.start('Fixture'))
            self.assertEqual(events, ['stop-enter','stop-exit','start-enter','start-exit'])
            self.assertEqual((await manager.status('test-only'))['controller_revision'], '0.5.2')

if __name__ == '__main__': unittest.main(verbosity=2)
