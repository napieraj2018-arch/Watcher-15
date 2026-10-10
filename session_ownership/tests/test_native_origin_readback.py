"""Offline canary scoping/cleanup regressions; no provider or real credentials."""
import asyncio
import copy
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from native_origin_readback import (
    FLAG, ERROR, URL, ReliabilityError, observe_native_origin, wrap_native_context,
)


class CanaryReadback(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {FLAG: '1', 'AI_BROWSER_PORTABLE_PRIORITY_PROFILES': ''})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.page = SimpleNamespace(
            url=URL, route=AsyncMock(), goto=AsyncMock(), close=AsyncMock(),
            evaluate=AsyncMock(return_value={
                'cookie_present': True, 'storage_present': True, 'pair_matches': True}))
        self.context = SimpleNamespace(new_page=AsyncMock(return_value=self.page),
                                       set_storage_state=AsyncMock())
        self.binding = {'profile': 'SteelSelfTest', 'hydrated': True}
        self.remote = SimpleNamespace(engine=SimpleNamespace(_native_bindings={'r': self.binding}),
                                      remote_id='r', browser=SimpleNamespace(contexts=[self.context]))
        self.applied = AsyncMock()
        async def original(remote, **options):
            return await self.applied(remote, **options)
        self.wrapped = wrap_native_context(original)

    async def test_canary_reads_before_existing_restore_and_preserves_arguments(self):
        self.applied.side_effect = lambda *a, **kw: self.page.close.assert_awaited_once()
        state = {'cookies': [], 'origins': []}
        untouched = copy.deepcopy(state)
        await self.wrapped(self.remote, storage_state=state, viewport={'width': 1200, 'height': 800})
        self.applied.assert_awaited_once_with(self.remote, storage_state=state,
                                             viewport={'width': 1200, 'height': 800})
        self.context.set_storage_state.assert_not_awaited()
        self.assertEqual(state, untouched)
        self.assertEqual(self.binding['synthetic_native_origin_readback']['status'], 'observed')

    async def test_real_profiles_not_probed_even_when_flag_enabled(self):
        for profile in ('Meta - Anita', 'Meta - Maciej - Monitoring', 'Google - Architekt',
                        'Default', 'steelselFTest', ''):
            self.binding['profile'] = profile
            await self.wrapped(self.remote, storage_state={})
        self.context.new_page.assert_not_awaited()
        self.assertNotIn('synthetic_native_origin_readback', self.binding)

    async def test_default_and_invalid_flag_do_not_probe(self):
        for value in ('', '0', 'true', 'yes', ' 1'):
            with patch.dict(os.environ, {FLAG: value}):
                await self.wrapped(self.remote, storage_state={})
        self.context.new_page.assert_not_awaited()

    async def test_first_import_is_not_probed(self):
        self.binding['hydrated'] = False
        await self.wrapped(self.remote, storage_state={})
        self.context.new_page.assert_not_awaited()

    async def test_claimed_session_is_not_probed(self):
        self.remote._native_context_claimed = True
        await self.wrapped(self.remote, storage_state={})
        self.context.new_page.assert_not_awaited()

    async def test_unsupported_or_absent_state_does_not_add_navigation(self):
        for options in ({}, {'storage_state': None}, {'storage_state': []},
                        {'storage_state': {}, 'unknown_argument': 1}):
            await self.wrapped(self.remote, **options)
        self.context.new_page.assert_not_awaited()

    async def test_read_failure_cannot_restore_or_leak_error(self):
        self.page.evaluate.side_effect = RuntimeError('PRIVATE PROVIDER DETAIL')
        with self.assertRaisesRegex(ReliabilityError, '^' + ERROR + '$'):
            await self.wrapped(self.remote, storage_state={})
        self.applied.assert_not_awaited()
        self.page.close.assert_awaited_once()

    async def test_navigation_failure_closes_only_created_page(self):
        self.page.goto.side_effect = RuntimeError('PRIVATE URL')
        with self.assertRaisesRegex(ReliabilityError, ERROR):
            await self.wrapped(self.remote, storage_state={})
        self.page.close.assert_awaited_once()
        self.applied.assert_not_awaited()

    async def test_cancellation_closes_probe_and_is_not_converted_to_success(self):
        self.page.goto.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await self.wrapped(self.remote, storage_state={})
        self.page.close.assert_awaited_once()
        self.applied.assert_not_awaited()

    async def test_close_failure_cannot_continue_restore(self):
        self.page.close.side_effect = RuntimeError('PRIVATE CLOSE DETAIL')
        with self.assertRaisesRegex(ReliabilityError, ERROR):
            await self.wrapped(self.remote, storage_state={})
        self.applied.assert_not_awaited()

    async def test_foreign_redirect_cannot_be_read(self):
        self.page.url = 'https://www.facebook.com/'
        with self.assertRaisesRegex(ReliabilityError, ERROR):
            await self.wrapped(self.remote, storage_state={})
        self.page.evaluate.assert_not_awaited()
        self.applied.assert_not_awaited()

    async def test_canary_page_route_never_contacts_network(self):
        await observe_native_origin(self.context)
        handler = self.page.route.call_args.args[1]
        for url, method, kind, allowed in (
                (URL, 'GET', 'document', True), (URL, 'POST', 'document', False),
                (URL, 'GET', 'fetch', False), (URL + '?private=1', 'GET', 'document', False),
                ('https://www.instagram.com/', 'GET', 'document', False)):
            route = SimpleNamespace(request=SimpleNamespace(url=url, method=method, resource_type=kind),
                                    fulfill=AsyncMock(), abort=AsyncMock())
            await handler(route)
            if allowed:
                route.fulfill.assert_awaited_once()
                route.abort.assert_not_awaited()
            else:
                route.abort.assert_awaited_once()
                route.fulfill.assert_not_awaited()

    async def test_portable_priority_conflict_denies_before_any_probe(self):
        with patch.dict(os.environ, {'AI_BROWSER_PORTABLE_PRIORITY_PROFILES': 'SteelSelfTest'}):
            with self.assertRaisesRegex(ReliabilityError, 'NATIVE_READBACK_POLICY_CONFLICT'):
                await self.wrapped(self.remote, storage_state={})
        self.context.new_page.assert_not_awaited()
        self.applied.assert_not_awaited()

    async def test_wrapper_idempotent(self):
        self.assertIs(wrap_native_context(self.wrapped), self.wrapped)

    async def test_unreviewed_contract_fails_closed(self):
        async def bad(other):
            pass
        with self.assertRaisesRegex(ReliabilityError, 'CONTRACT_INVALID'):
            wrap_native_context(bad)


if __name__ == '__main__':
    unittest.main(verbosity=2)
