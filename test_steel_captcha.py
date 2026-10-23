"""Provider CAPTCHA configuration/progress contract; no network or accounts."""
import asyncio
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import steel_runtime as app
from test_steel_singleflight import FakeChromium, FakeEngine, FakeCDPBrowser


class CaptchaCreateContract(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            'STEEL_API_KEY': 'synthetic-only', 'AI_BROWSER_CAPTCHA_AUTOMATION': '1'})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    async def test_unset_configuration_disables_feature_without_status_request(self):
        with patch.dict(os.environ):
            os.environ.pop('AI_BROWSER_CAPTCHA_AUTOMATION', None)
            engine = FakeEngine()
        remote = await engine.launch(FakeChromium())
        try:
            self.assertIs(engine.last_create_body['solveCaptcha'], False)
            self.assertEqual(remote.captcha_configuration(), {
                'requested': False, 'provider_confirmed': False, 'availability': 'disabled'})
            # FakeEngine rejects any CAPTCHA status GET: disabled is local.
            self.assertEqual((await remote.captcha_status('https://example.test/'))['status'], 'disabled')
            self.assertEqual(engine.creates, 1)
        finally:
            await remote.close()

    async def test_explicit_opt_in_never_changes_proxy_or_profile_device(self):
        engine = FakeEngine()
        original = engine.request
        async def request(method, path, body=None, timeout=25):
            result = await original(method, path, body, timeout)
            if path == '/sessions':
                result['solveCaptcha'] = True
            return result
        engine.request = request
        remote = await engine.launch(FakeChromium())
        self.assertEqual(remote.captcha_configuration(), {
            'requested': True, 'provider_confirmed': True, 'availability': 'enabled'})
        self.assertIs(engine.last_create_body['solveCaptcha'], True)
        self.assertIs(engine.last_create_body['useProxy'], False)
        self.assertNotIn('stealthConfig', engine.last_create_body)
        self.assertEqual(engine.last_create_body['deviceConfig'], {'device': 'mobile'})
        await remote.close()

    async def test_absent_provider_flag_is_unconfirmed(self):
        engine = FakeEngine()
        remote = await engine.launch(FakeChromium())
        self.assertFalse(remote.captcha_configuration()['provider_confirmed'])
        self.assertEqual(remote.captcha_configuration()['availability'], 'provider_unconfirmed')
        await remote.close()

    async def test_explicit_provider_disable_is_reported(self):
        engine = FakeEngine()
        original = engine.request
        async def request(method, path, body=None, timeout=25):
            result = await original(method, path, body, timeout)
            if path == '/sessions':
                result['solveCaptcha'] = False
            return result
        engine.request = request
        remote = await engine.launch(FakeChromium())
        self.assertEqual(remote.captcha_configuration()['availability'], 'provider_disabled')
        self.assertEqual((await remote.captcha_status('https://example.test'))['status'], 'disabled')
        await remote.close()

    async def test_operator_can_disable_feature(self):
        with patch.dict(os.environ, {'AI_BROWSER_CAPTCHA_AUTOMATION': '0'}):
            engine = FakeEngine()
        remote = await engine.launch(FakeChromium())
        self.assertIs(engine.last_create_body['solveCaptcha'], False)
        self.assertEqual(remote.captcha_configuration()['availability'], 'disabled')
        await remote.close()

    async def test_invalid_configuration_fails_before_provider_access(self):
        for value in ('', 'yes', 'true', 'false', '01', ' 1', '1 ', '2'):
            with self.subTest(value=value), patch.dict(os.environ, {
                    'AI_BROWSER_CAPTCHA_AUTOMATION': value}), \
                    patch.object(app.httpx, 'AsyncClient') as client:
                with self.assertRaisesRegex(app.SteelFailure, '^STEEL_CAPTCHA_CONFIG_INVALID$'):
                    app.Engine()
                client.assert_not_called()

    async def test_exact_payment_rejection_drops_feature_once_same_requested_id(self):
        engine = FakeEngine()
        original = engine.request
        requests = []
        async def request(method, path, body=None, timeout=25):
            if path == '/sessions':
                requests.append(dict(body))
                if len(requests) == 1:
                    raise app.SteelCaptchaNotAvailable('STEEL_CAPTCHA_ACCOUNT_ACCESS_REQUIRED')
            return await original(method, path, body, timeout)
        engine.request = request
        remote = await engine.launch(FakeChromium())
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[0]['sessionId'], requests[1]['sessionId'])
        self.assertEqual({**requests[0], 'solveCaptcha': False}, requests[1])
        self.assertFalse(engine._quarantined)
        self.assertEqual(remote.captcha_configuration()['availability'], 'account_access_required')
        self.assertFalse((await remote.captcha_status('https://example.test'))['enabled'])
        await remote.close()

    async def test_other_errors_never_retry_create(self):
        for message in ('STEEL_CONNECTION_FAILED', 'STEEL_HTTP_400', 'STEEL_HTTP_403',
                        'STEEL_HTTP_429', 'STEEL_HTTP_500', 'STEEL_INVALID_RESPONSE'):
            with self.subTest(message=message):
                engine = FakeEngine()
                original = engine.request
                count = 0
                async def request(method, path, body=None, timeout=25):
                    nonlocal count
                    if path == '/sessions':
                        count += 1
                        raise app.SteelFailure(message)
                    return await original(method, path, body, timeout)
                engine.request = request
                with self.assertRaises(app.SteelFailure):
                    await engine.launch(FakeChromium())
                self.assertEqual(count, 1)
                self.assertTrue(engine._quarantined)

    async def test_second_create_is_never_repeated_on_failure(self):
        engine = FakeEngine()
        original = engine.request
        count = 0
        async def request(method, path, body=None, timeout=25):
            nonlocal count
            if path == '/sessions':
                count += 1
                if count == 1:
                    raise app.SteelCaptchaNotAvailable('STEEL_CAPTCHA_ACCOUNT_ACCESS_REQUIRED')
                raise app.SteelFailure('STEEL_CONNECTION_FAILED')
            return await original(method, path, body, timeout)
        engine.request = request
        with self.assertRaises(app.SteelFailure):
            await engine.launch(FakeChromium())
        self.assertEqual(count, 2)
        self.assertTrue(engine._quarantined)

    async def test_only_exact_transport_402_produces_safe_option_rejection(self):
        # Real request() with a local HTTPX transport, no network.
        client_type = httpx.AsyncClient
        calls = []
        async def respond(request):
            calls.append(request)
            return httpx.Response(402, json={'message': 'SYNTHETIC_PRIVATE_PROVIDER_MESSAGE'})
        transport = httpx.MockTransport(respond)
        with patch.object(app.httpx, 'AsyncClient',
                          side_effect=lambda **kw: client_type(transport=transport, **kw)):
            engine = app.Engine()
            with self.assertRaises(app.SteelCaptchaNotAvailable) as caught:
                await engine.request('POST', '/sessions', {'solveCaptcha': True, 'useProxy': False})
            self.assertNotIn('SYNTHETIC_PRIVATE', str(caught.exception))
            for method, path, body in (
                ('GET', '/sessions/id/captchas/status', None),
                ('POST', '/sessions', {'solveCaptcha': False, 'useProxy': False}),
                ('POST', '/sessions', {'solveCaptcha': True, 'useProxy': True}),
                ('POST', '/sessions/id/release', {}),
            ):
                with self.assertRaises(app.SteelFailure) as other:
                    await engine.request(method, path, body)
                self.assertNotIsInstance(other.exception, app.SteelCaptchaNotAvailable)

    async def test_transport_403_with_release_404_never_retries_or_clears_quarantine(self):
        client_type = httpx.AsyncClient
        calls = []

        async def respond(request):
            calls.append(request)
            if request.method == 'POST' and request.url.path == '/v1/sessions':
                return httpx.Response(403, json={
                    'message': 'SYNTHETIC_PRIVATE_PROVIDER_MESSAGE'})
            if request.method == 'POST' and request.url.path.endswith('/release'):
                return httpx.Response(404, json={'message': 'Session not found'})
            raise AssertionError('Unexpected provider request')

        transport = httpx.MockTransport(respond)
        with patch.object(app.httpx, 'AsyncClient',
                          side_effect=lambda **kw: client_type(transport=transport, **kw)):
            engine, chromium = app.Engine(), FakeChromium()
            with self.assertRaisesRegex(app.SteelFailure, '^STEEL_HTTP_403$') as caught:
                await engine.launch(chromium)
            self.assertNotIsInstance(caught.exception, app.SteelCaptchaNotAvailable)
            self.assertEqual(len(calls), 2)
            create = json.loads(calls[0].content)
            self.assertIs(create['solveCaptcha'], True)
            self.assertIs(create['useProxy'], False)
            self.assertEqual(calls[1].url.path,
                             '/v1/sessions/' + create['sessionId'] + '/release')
            self.assertEqual(chromium.attempts, 0)
            self.assertTrue(engine._quarantined)
            self.assertEqual(engine.remote, {})
            with self.assertRaisesRegex(app.SteelFailure, '^STEEL_SESSION_QUARANTINED$'):
                await engine.launch(chromium)
            self.assertEqual(len(calls), 2)


class CaptchaProgress(unittest.IsolatedAsyncioTestCase):
    def remote(self, data=None, error=None):
        engine = SimpleNamespace(request=AsyncMock(return_value=data, side_effect=error))
        remote = app.RemoteBrowser(engine, FakeCDPBrowser(), 'synthetic-provider-id')
        remote._captcha_requested = remote._captcha_enabled = True
        remote._captcha_availability = 'provider_unconfirmed'
        return remote

    async def test_current_page_progress_only_no_raw_private_data(self):
        url = 'https://example.test/challenge?token=SYNTHETIC_PRIVATE'
        remote = self.remote([{'url': url, 'pageId': 'PRIVATE_PAGE',
                               'isSolvingCaptcha': True, 'tasks': [{'secret': 'PRIVATE_TASK'}]},
                              {'url': 'https://other.test/', 'isSolvingCaptcha': False}])
        result = await remote.captcha_status(url)
        self.assertEqual(result['status'], 'solving')
        self.assertFalse(result['completion_confirmed'])
        self.assertNotIn('PRIVATE', json.dumps(result))
        self.assertNotIn('PRIVATE', repr(remote._captcha_cache))
        remote.engine.request.assert_awaited_once_with(
            'GET', '/sessions/synthetic-provider-id/captchas/status', timeout=5)

    async def test_not_running_does_not_mean_solved(self):
        remote = self.remote([{'url': 'https://example.test/', 'isSolvingCaptcha': False}])
        result = await remote.captcha_status('https://example.test/')
        self.assertEqual(result['status'], 'not_running')
        self.assertFalse(result['completion_confirmed'])

    async def test_other_query_never_matches_current_login(self):
        remote = self.remote([{'url': 'https://example.test/?flow=other', 'isSolvingCaptcha': True}])
        self.assertEqual((await remote.captcha_status('https://example.test/?flow=current'))['status'], 'not_reported')

    async def test_other_fragment_never_matches_or_reuses_current_flow_cache(self):
        remote = self.remote([{'url': 'https://example.test/#flow=current', 'isSolvingCaptcha': True}])
        self.assertEqual((await remote.captcha_status('https://example.test/#flow=current'))['status'], 'solving')
        self.assertEqual((await remote.captcha_status('https://example.test/#flow=other'))['status'], 'not_reported')
        self.assertEqual(remote.engine.request.await_count, 2)
        self.assertNotIn('flow=', repr(remote._captcha_cache))

    async def test_no_detected_challenge_is_not_solved(self):
        result = await self.remote([]).captcha_status('https://example.test/')
        self.assertEqual(result['status'], 'not_reported')
        self.assertFalse(result['completion_confirmed'])

    async def test_duplicate_matching_tabs_are_ambiguous(self):
        row = {'url': 'https://example.test/', 'isSolvingCaptcha': True}
        result = await self.remote([row, row]).captcha_status(row['url'])
        self.assertEqual(result['status'], 'unavailable')

    async def test_malformed_response_never_claims_solving(self):
        for data in ({'isSolvingCaptcha': True}, 'PRIVATE_ERROR',
                     [{'url': 'https://example.test/', 'isSolvingCaptcha': 'true'}], [None] * 51):
            with self.subTest(type=type(data).__name__):
                result = await self.remote(data).captcha_status('https://example.test/')
                self.assertEqual(result['status'], 'unavailable')

    async def test_provider_error_sanitized_no_write(self):
        remote = self.remote(error=RuntimeError('SYNTHETIC_PRIVATE_ERROR'))
        result = await remote.captcha_status('https://example.test/')
        self.assertEqual(result['status'], 'unavailable')
        self.assertNotIn('PRIVATE', json.dumps(result))
        self.assertEqual(remote.engine.request.await_count, 1)

    async def test_disabled_or_closed_does_not_contact_provider(self):
        remote = self.remote([])
        remote._captcha_enabled = False
        self.assertEqual((await remote.captcha_status('https://example.test/'))['status'], 'disabled')
        remote._captcha_enabled, remote.closed = True, True
        self.assertEqual((await remote.captcha_status('https://example.test/'))['status'], 'unavailable')
        remote.engine.request.assert_not_awaited()

    async def test_invalid_origin_does_not_contact_provider(self):
        remote = self.remote([])
        for url in ('http://example.test', 'https://user:pass@example.test/',
                    'https://example.test:8443/', 'data:text/plain,secret', None):
            self.assertEqual((await remote.captcha_status(url))['status'], 'unavailable')
        remote.engine.request.assert_not_awaited()

    async def test_cache_is_bounded_per_page_and_defensive_copy(self):
        remote = self.remote([])
        first = await remote.captcha_status('https://example.test/')
        first['status'] = 'tampered'
        self.assertEqual((await remote.captcha_status('https://example.test/'))['status'], 'not_reported')
        self.assertEqual(remote.engine.request.await_count, 1)
        await remote.captcha_status('https://example.test/next')
        self.assertEqual(remote.engine.request.await_count, 2)

    async def test_parallel_reads_are_single_flight(self):
        remote = self.remote([])
        await asyncio.gather(*(remote.captcha_status('https://example.test/') for _ in range(5)))
        self.assertEqual(remote.engine.request.await_count, 1)

    async def test_cancellation_propagates_without_retry(self):
        remote = self.remote(error=asyncio.CancelledError())
        with self.assertRaises(asyncio.CancelledError):
            await remote.captcha_status('https://example.test/')
        self.assertEqual(remote.engine.request.await_count, 1)
        self.assertIsNone(remote._captcha_cache)


if __name__ == '__main__':
    unittest.main(verbosity=2)
