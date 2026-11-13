"""Synthetic regression tests. No real account, network or production data."""
import asyncio
import base64
import copy
import hashlib
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import test_security  # existing test-only configuration
import server
import production_runtime as prod
import completion_runtime as final


class InputChecks(unittest.TestCase):
    def test_operation_id_is_bounded_and_exact(self):
        for value in ['', 'null', '[]', '{}', '{"operation_id":"short"}',
                      '{"operation_id":"operation-valid","target":"pages/1"}',
                      json.dumps({'operation_id': 'x' * 81}),
                      json.dumps({'operation_id': 'operation/invalid'})]:
            with self.subTest(value=value), self.assertRaises(server.HTTPException):
                final.operation_key(value)
        op, key = final.operation_key('{"operation_id":"operation-valid"}')
        self.assertEqual(op, 'operation-valid')
        self.assertRegex(key, r'^wp-op-[a-f0-9]{32}$')

    def test_guessed_creation_and_changed_target_are_rejected(self):
        for state in [dict(path='pages', phase='submitted'),
                      dict(path='media', phase='acknowledged', target='media/1'),
                      dict(path='pages', phase='acknowledged', target='posts/1'),
                      dict(path='pages/1', phase='submitted', target='pages/2'),
                      dict(path='pages/1?secret=value', phase='submitted')]:
            with self.subTest(state=state), self.assertRaises(server.HTTPException):
                final.readback_target(state)

    def test_invalid_record_does_not_become_an_operation(self):
        for record in [None, {}, {'checkpoint': {}, 'revision': 1},
                       {'checkpoint': {'account': 'other'}, 'revision': True}]:
            with self.subTest(record=record), self.assertRaises(server.HTTPException):
                final.checked_state(record)


class Recovery(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.operation = 'completion-fixture-operation'
        self.args = {'action': 'wordpress_reconcile', 'name': prod.WP_PROFILE,
                     'text': json.dumps({'operation_id': self.operation})}
        _, self.task = final.operation_key(self.args['text'])
        self.desired = {'title': 'expected title'}
        raw = json.dumps(self.desired, ensure_ascii=False).encode()
        digest = hashlib.sha256(raw).hexdigest()
        self.block_id = 'wp-b-' + 'b' * 32
        self.reference = {'chunks': [self.block_id], 'sha256': digest, 'bytes': len(raw)}
        self.state = {'phase': 'submitted', 'path': 'pages/1', 'account': 'edycjanapieraj',
                      'request_hash': 'a' * 64, 'desired_backup': self.reference}
        self.db = {
            self.task: {'checkpoint': copy.deepcopy(self.state), 'revision': 3},
            self.block_id: {'checkpoint': {'encoding': 'base64-json-chunk', 'offset': 0,
                              'sha256': digest, 'data': base64.b64encode(raw).decode()}, 'revision': 1},
        }
        self.writes = []
        self.calls = []
        self.after = {'id': 1, 'title': {'raw': 'expected title'}, 'status': 'draft'}
        self.identity = {'id': 1, 'slug': 'edycjanapieraj'}
        self.page = SimpleNamespace(url=prod.WP_ORIGIN + '/wp-admin/')
        self.w = SimpleNamespace(lock=asyncio.Lock(), context=object(),
                    profile=prod.WP_PROFILE, human=False, assert_lease=AsyncMock(),
                    page=lambda: self.page, last_activity=0)

        def checkpoint(ident, payload=None, revision=None):
            if payload is None:
                if ident not in self.db:
                    raise server.HTTPException(404, 'missing')
                return copy.deepcopy(self.db[ident])
            old = self.db.get(ident)
            if not old or old['revision'] != revision:
                raise server.HTTPException(409, 'CAS conflict')
            self.writes.append(ident)
            self.db[ident] = {'checkpoint': copy.deepcopy(payload), 'revision': revision + 1}
            return {'id': ident, 'revision': revision + 1}

        async def rest(page, path, method='GET', body=None, upload=None):
            self.calls.append((path, method))
            self.assertEqual(method, 'GET', 'Recovery must never replay a WordPress write')
            if path.startswith('users/me'):
                return {'data': copy.deepcopy(self.identity)}
            return {'data': copy.deepcopy(self.after)}

        self.backup = AsyncMock(return_value={'chunks': ['wp-b-'+'c'*32], 'sha256': 'd'*64, 'bytes': 100})
        self.patches = [patch.object(server, 'workspace', self.w),
                       patch.object(server, 'db_checkpoint', checkpoint),
                       patch.object(prod, 'rest', rest),
                       patch.object(prod, 'backup_document', self.backup)]
        for item in self.patches:
            item.start()

    async def asyncTearDown(self):
        for item in reversed(self.patches):
            item.stop()

    async def test_submitted_update_is_resolved_by_get_only(self):
        result = await final.completion_action(self.args, automated=True)
        self.assertTrue(result['verified'])
        self.assertFalse(result['external_write_replayed'])
        self.assertEqual(self.db[self.task]['checkpoint']['phase'], 'verified')
        self.assertEqual(self.db[self.task]['revision'], 4)
        self.assertEqual(self.writes, [self.task])
        self.assertEqual(len(self.calls), 2)
        self.backup.assert_awaited_once()

    async def test_second_reconciliation_never_writes_again(self):
        await final.completion_action(self.args, automated=True)
        result = await final.completion_action(self.args, automated=True)
        self.assertTrue(result['already_confirmed'])
        self.assertEqual(self.writes, [self.task])
        self.assertEqual([m for p, m in self.calls], ['GET', 'GET', 'GET'])

    async def test_mismatch_keeps_uncertain_operation_unchanged(self):
        self.after['title']['raw'] = 'different edit'
        with self.assertRaises(server.HTTPException) as error:
            await final.completion_action(self.args, automated=True)
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(self.db[self.task]['checkpoint']['phase'], 'submitted')
        self.assertEqual(self.writes, [])
        self.backup.assert_not_awaited()

    async def test_owner_handoff_is_respected(self):
        self.w.human = True
        with self.assertRaises(server.HTTPException):
            await final.completion_action(self.args, automated=True)
        self.assertEqual(self.calls, [])

    async def test_wrong_live_account_is_rejected(self):
        self.identity['slug'] = 'other-account'
        with self.assertRaises(server.HTTPException) as error:
            await final.completion_action(self.args, automated=True)
        self.assertEqual(error.exception.status_code, 403)
        self.assertEqual(self.writes, [])
        self.assertEqual(len(self.calls), 1)

    async def test_closed_profile_is_not_auto_opened(self):
        self.w.context = None
        with self.assertRaises(server.HTTPException):
            await final.completion_action(self.args, automated=True)
        self.assertEqual(self.calls, [])

    async def test_wrong_profile_is_not_switched(self):
        self.w.profile = 'another-owner-task'
        with self.assertRaises(server.HTTPException):
            await final.completion_action(self.args, automated=True)
        self.assertEqual(self.calls, [])

    async def test_wrong_requested_profile_is_rejected(self):
        with self.assertRaises(server.HTTPException) as error:
            await final.completion_action({**self.args, 'name': 'other'}, automated=True)
        self.assertEqual(error.exception.status_code, 403)
        self.assertEqual(self.calls, [])

    async def test_expired_owner_context_is_rejected(self):
        with self.assertRaises(server.HTTPException):
            await final.completion_action(self.args, owner_context=object())
        self.assertEqual(self.calls, [])

    async def test_non_admin_page_is_not_navigated(self):
        self.page.url = prod.WP_ORIGIN + '/wp-login.php'
        with self.assertRaises(server.HTTPException):
            await final.completion_action(self.args, automated=True)
        self.assertEqual(self.calls, [])

    async def test_lease_failure_stops_all_website_requests(self):
        self.w.assert_lease.side_effect = server.HTTPException(409, 'lease lost')
        with self.assertRaises(server.HTTPException):
            await final.completion_action(self.args, automated=True)
        self.assertEqual(self.calls, [])

    async def test_prepared_is_not_falsely_marked_submitted(self):
        self.db[self.task]['checkpoint']['phase'] = 'prepared'
        with self.assertRaises(server.HTTPException):
            await final.completion_action(self.args, automated=True)
        self.assertEqual(self.writes, [])
        self.assertEqual(len(self.calls), 1)

    async def test_unknown_creation_is_not_guessed_or_replayed(self):
        self.db[self.task]['checkpoint']['path'] = 'pages'
        with self.assertRaises(server.HTTPException):
            await final.completion_action(self.args, automated=True)
        self.assertEqual(self.writes, [])
        self.assertEqual(len(self.calls), 1)

    async def test_acknowledged_creation_with_known_id_can_be_read_back(self):
        self.db[self.task]['checkpoint'].update(path='pages', phase='acknowledged', target='pages/1')
        result = await final.completion_action(self.args, automated=True)
        self.assertTrue(result['verified'])
        self.assertEqual(result['target'], 'pages/1')

    async def test_corrupted_backup_hash_prevents_confirmation(self):
        self.db[self.block_id]['checkpoint']['data'] = base64.b64encode(b'{"title":"changed"}').decode()
        with self.assertRaises(server.HTTPException):
            await final.completion_action(self.args, automated=True)
        self.assertEqual(self.writes, [])
        self.assertEqual(len(self.calls), 1)

    async def test_bad_chunk_offset_prevents_confirmation(self):
        self.db[self.block_id]['checkpoint']['offset'] = 1
        with self.assertRaises(server.HTTPException):
            await final.completion_action(self.args, automated=True)
        self.assertEqual(self.writes, [])

    async def test_empty_or_malformed_backup_is_not_a_vacuous_success(self):
        for ref in [None, {}, {'chunks': [], 'bytes': 0, 'sha256': '0'*64}]:
            with self.subTest(ref=ref), self.assertRaises(server.HTTPException):
                await final.read_desired(ref)

    async def test_cas_conflict_preserves_other_writer(self):
        original = server.db_checkpoint
        def conflict(ident, payload=None, revision=None):
            if payload is not None:
                raise server.HTTPException(409, 'CAS conflict')
            return original(ident)
        with patch.object(server, 'db_checkpoint', conflict):
            with self.assertRaises(server.HTTPException):
                await final.completion_action(self.args, automated=True)
        self.assertEqual(self.db[self.task]['checkpoint']['phase'], 'submitted')
        self.assertEqual(self.writes, [])

    async def test_status_does_not_return_backup_content_or_visit_website(self):
        result = await final.completion_action({**self.args, 'action': 'wordpress_operation_status'})
        self.assertEqual(result['phase'], 'submitted')
        self.assertTrue(result['requires_readback'])
        self.assertNotIn('desired_backup', result)
        self.assertNotIn('expected title', json.dumps(result))
        self.assertEqual(self.calls, [])
        self.assertEqual(self.writes, [])

    async def test_runtime_status_does_not_claim_background_execution(self):
        result = await final.completion_action({'action': 'runtime_status'})
        self.assertFalse(result['background_execution'])
        self.assertEqual(result['file_limit_bytes'], 8000000)
        self.assertIn('wordpress_reconcile', result['capabilities'])
        self.assertEqual(self.calls, [])

    async def test_existing_actions_are_forwarded_without_retry(self):
        previous = AsyncMock(return_value={'original': True})
        with patch.object(final, '_previous_action', previous):
            result = await final.completion_action({'action': 'snapshot', 'name': 'fixture'}, automated=True)
        previous.assert_awaited_once_with({'action': 'snapshot', 'name': 'fixture'}, automated=True, owner_context=None)
        self.assertEqual(result, {'original': True})


if __name__ == '__main__':
    unittest.main()
