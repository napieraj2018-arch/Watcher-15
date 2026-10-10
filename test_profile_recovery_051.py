"""Offline regression checks; synthetic data only, no account access.
Run from the repository root: python3 test_profile_recovery_051.py
Verified against application commit cde1edc7c9cc36c13e15402f4186830dd6a01cb5.
These unit tests do not establish successful Facebook/Instagram authentication.
"""
import ast
import collections
import copy
import json
import pathlib
import sys
import types
import unittest
from urllib.parse import urlsplit

class Failure(RuntimeError):
    pass

sys.modules['steel_runtime'] = types.SimpleNamespace(SteelFailure=Failure)
source = pathlib.Path(__file__).with_name('steel_context_fix.py').read_text()
tree = ast.parse(source)
names = {'native_context', 'safe_route', 'exact_origin', 'merge_profile_state', 'synthetic_fixture_evidence', 'synthetic_fixture_exact_evidence', 'select_coherent_fixture_pair', 'synthetic_fixture_apply_comparison'}
tree.body = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]
ns = {'Path': pathlib.Path, 'json': json, 'deque': collections.deque,
      'time': __import__('time'), 'urlsplit': urlsplit, 'copy': copy}
exec(compile(tree, 'steel_context_fix.py', 'exec'), ns)

def state(value='backup'):
    return {'cookies': [{'name': 'test-cookie', 'domain': 'fixture.test', 'path': '/', 'value': value}],
            'origins': [{'origin': 'https://fixture.test',
                         'localStorage': [{'name': 'test', 'value': value}],
                         'indexedDB': [{'name': 'test-db', 'version': 1, 'stores': []}]}]}

class Context:
    def __init__(self, current=None):
        self.current = current or {'cookies': [], 'origins': []}
        self.states, self.headers, self.handlers = [], [], []
    async def storage_state(self, **kwargs):
        return copy.deepcopy(self.current)
    async def set_storage_state(self, value):
        self.states.append(copy.deepcopy(value))
        self.current = copy.deepcopy(value)
    async def set_extra_http_headers(self, value):
        self.headers.append(value)
    def on(self, event, handler):
        self.handlers.append(event)

def remote(hydrated=True, current=None):
    context = Context(current)
    value = types.SimpleNamespace(
        browser=types.SimpleNamespace(contexts=[context]),
        engine=types.SimpleNamespace(_native_bindings={'r': {'hydrated': hydrated}}),
        remote_id='r')
    return value, context

class Recovery(unittest.IsolatedAsyncioTestCase):
    async def test_hydrated_native_restores_missing_local_storage(self):
        backup = state()
        r, c = remote(current={'cookies': backup['cookies'], 'origins': []})
        await ns['native_context'](r, storage_state=backup)
        self.assertEqual(c.current, backup)

    async def test_restores_missing_indexeddb(self):
        backup = state()
        native = copy.deepcopy(backup)
        native['origins'][0].pop('indexedDB')
        r, c = remote(current=native)
        await ns['native_context'](r, storage_state=backup)
        self.assertEqual(c.current, backup)

    async def test_rotated_native_cookie_is_preserved(self):
        r, c = remote(current={'cookies': state('new')['cookies'], 'origins': []})
        await ns['native_context'](r, storage_state=state())
        self.assertEqual(c.current['cookies'][0]['value'], 'new')

    async def test_current_native_local_storage_is_preserved(self):
        r, c = remote(current=state('new'))
        await ns['native_context'](r, storage_state=state())
        self.assertEqual(c.states, [])

    async def test_matching_state_does_not_reset_context(self):
        r, c = remote(current=state())
        await ns['native_context'](r, storage_state=state())
        self.assertEqual(c.states, [])

    async def test_first_migration_restores_snapshot(self):
        r, c = remote(False)
        await ns['native_context'](r, storage_state=state())
        self.assertEqual(c.current, state())

    async def test_no_snapshot_does_not_clear_context(self):
        r, c = remote(current=state())
        await ns['native_context'](r)
        self.assertEqual(c.states, [])

    async def test_cannot_reimport_during_active_login(self):
        r, c = remote()
        await ns['native_context'](r, storage_state=state())
        with self.assertRaisesRegex(Failure, 'ALREADY_CLAIMED'):
            await ns['native_context'](r, storage_state=state())
        self.assertEqual(len(c.states), 1)

    async def test_invalid_snapshot_rejected(self):
        r, c = remote()
        with self.assertRaisesRegex(Failure, 'INVALID_PROFILE_STATE'):
            await ns['native_context'](r, storage_state=[])
        self.assertEqual(c.states, [])

    async def test_unrecognized_context_options_rejected(self):
        r, c = remote()
        with self.assertRaisesRegex(Failure, 'UNSUPPORTED_CONTEXT_OPTIONS'):
            await ns['native_context'](r, proxy={})

    async def test_missing_context_rejected(self):
        r, c = remote()
        r.browser.contexts = []
        with self.assertRaisesRegex(Failure, 'NATIVE_CONTEXT_MISSING'):
            await ns['native_context'](r)

    async def test_headers_and_event_handlers_preserved(self):
        r, c = remote()
        await ns['native_context'](r, extra_http_headers={'accept-language': 'pl'})
        self.assertEqual(c.headers, [{'accept-language': 'pl'}])
        self.assertEqual(c.handlers, ['request', 'response', 'requestfailed'])

    def test_merge_does_not_mutate_inputs(self):
        native, backup = state('native'), state('backup')
        ns['merge_profile_state'](native, backup)
        self.assertEqual(native, state('native'))
        self.assertEqual(backup, state('backup'))

    def test_merge_adds_missing_origins(self):
        native, backup = state(), state()
        backup['origins'][0]['origin'] = 'https://other-fixture.test'
        self.assertEqual(len(ns['merge_profile_state'](native, backup)['origins']), 2)

    def test_safe_route_redacts_parameters(self):
        self.assertEqual(ns['safe_route']('https://fixture.test/login?token=test-only#password'), 'fixture.test/login')

    def test_origin_rejects_embedded_credentials(self):
        self.assertIsNone(ns['exact_origin']('https://demo:not-a-password@fixture.test'))

    def test_origin_rejects_plain_http(self):
        self.assertIsNone(ns['exact_origin']('http://fixture.test'))

    def test_complete_source_compiles(self):
        compile(source, 'steel_context_fix.py', 'exec')

if __name__ == '__main__':
    unittest.main(verbosity=2)
