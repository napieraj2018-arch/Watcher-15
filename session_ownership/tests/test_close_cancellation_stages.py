"""Cancellation-stage regressions. Only local stubs; no provider calls or secrets."""
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from steel_runtime import RemoteBrowser, SteelFailure


class CloseCancellationStages(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.browser = SimpleNamespace(close=AsyncMock())
        self.engine = SimpleNamespace(
            remote={}, _quarantined=False,
            release=AsyncMock(return_value=True),
            confirm_terminal=AsyncMock(return_value=False))
        self.remote = RemoteBrowser(self.engine, self.browser, 'technical-own-session')
        self.engine.remote[self.remote.remote_id] = self.remote
        self.other = object()
        self.engine.remote['technical-other-session'] = self.other

    async def cancel_during_cdp_close(self):
        entered = asyncio.Event()
        async def pending_close():
            entered.set()
            await asyncio.Event().wait()
        self.browser.close.side_effect = pending_close
        task = asyncio.create_task(self.remote.close())
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(self.engine._quarantined)
        self.assertIn(self.remote.remote_id, self.engine.remote)
        self.engine.release.assert_not_awaited()
        self.engine.confirm_terminal.assert_not_awaited()

    def assert_other_untouched(self):
        self.assertIs(self.engine.remote['technical-other-session'], self.other)

    async def test_cancel_before_release_allows_first_authorized_release(self):
        await self.cancel_during_cdp_close()
        await self.remote.close()
        self.engine.release.assert_awaited_once_with(self.remote.remote_id)
        self.engine.confirm_terminal.assert_not_awaited()
        self.browser.close.assert_awaited_once()
        self.assertTrue(self.remote._release_confirmed)
        self.assertNotIn(self.remote.remote_id, self.engine.remote)
        self.assertTrue(self.engine._quarantined, 'Recovery does not clear global quarantine')
        self.assert_other_untouched()

    async def test_two_authorized_retries_after_cancel_issue_one_release(self):
        await self.cancel_during_cdp_close()
        await asyncio.gather(self.remote.close(), self.remote.close())
        self.engine.release.assert_awaited_once_with(self.remote.remote_id)
        self.engine.confirm_terminal.assert_not_awaited()
        self.assert_other_untouched()

    async def test_failed_first_release_after_cancel_remains_unconfirmed(self):
        await self.cancel_during_cdp_close()
        self.engine.release.return_value = False
        with self.assertRaisesRegex(SteelFailure, '^STEEL_REMOTE_RELEASE_UNCONFIRMED$'):
            await self.remote.close()
        self.engine.release.assert_awaited_once()
        self.assertIn(self.remote.remote_id, self.engine.remote)
        self.assertTrue(self.engine._quarantined)
        self.assertFalse(self.remote._release_confirmed)
        self.assert_other_untouched()

    async def test_cancel_during_release_never_repeats_release(self):
        self.engine.release.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await self.remote.close()
        self.assertTrue(self.engine._quarantined)
        self.engine.confirm_terminal.return_value = True
        await self.remote.close()
        self.engine.release.assert_awaited_once_with(self.remote.remote_id)
        self.engine.confirm_terminal.assert_awaited_once_with(self.remote.remote_id)
        self.assertNotIn(self.remote.remote_id, self.engine.remote)
        self.assertTrue(self.engine._quarantined)
        self.assert_other_untouched()

    async def test_unknown_release_result_only_readbacks_on_retry(self):
        self.engine.release.return_value = False
        with self.assertRaises(SteelFailure):
            await self.remote.close()
        self.engine.confirm_terminal.return_value = True
        await self.remote.close()
        self.engine.release.assert_awaited_once()
        self.engine.confirm_terminal.assert_awaited_once_with(self.remote.remote_id)
        self.assertTrue(self.engine._quarantined)
        self.assert_other_untouched()

    async def test_release_exception_redacted_and_not_repeated(self):
        self.engine.release.side_effect = RuntimeError('synthetic private diagnostic')
        with self.assertRaisesRegex(SteelFailure, '^STEEL_REMOTE_RELEASE_UNCONFIRMED$'):
            await self.remote.close()
        with self.assertRaisesRegex(SteelFailure, '^STEEL_REMOTE_RELEASE_UNCONFIRMED$'):
            await self.remote.close()
        self.engine.release.assert_awaited_once()
        self.engine.confirm_terminal.assert_awaited_once()
        self.assert_other_untouched()

    async def test_cdp_exception_does_not_prevent_release(self):
        self.browser.close.side_effect = RuntimeError('synthetic CDP failure')
        await self.remote.close()
        self.engine.release.assert_awaited_once()
        self.assertFalse(self.engine._quarantined)
        self.assert_other_untouched()

    async def test_cancel_waiting_for_lock_does_not_change_lifecycle(self):
        await self.remote.close_lock.acquire()
        task = asyncio.create_task(self.remote.close())
        await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.remote.close_lock.release()
        self.assertFalse(self.remote.closed)
        self.assertFalse(self.engine._quarantined)
        self.browser.close.assert_not_awaited()
        self.engine.release.assert_not_awaited()
        self.assert_other_untouched()

    async def test_cancel_during_readback_cannot_resubmit_release(self):
        self.engine.release.return_value = False
        with self.assertRaises(SteelFailure):
            await self.remote.close()
        self.engine.confirm_terminal.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await self.remote.close()
        self.engine.confirm_terminal.side_effect = None
        self.engine.confirm_terminal.return_value = True
        await self.remote.close()
        self.engine.release.assert_awaited_once()
        self.assertEqual(self.engine.confirm_terminal.await_count, 2)
        self.assertTrue(self.engine._quarantined)
        self.assert_other_untouched()

    async def test_success_is_idempotent(self):
        for _ in range(3):
            await self.remote.close()
        self.engine.release.assert_awaited_once()
        self.engine.confirm_terminal.assert_not_awaited()
        self.browser.close.assert_awaited_once()
        self.assertFalse(self.engine._quarantined)
        self.assert_other_untouched()


if __name__ == '__main__':
    unittest.main(verbosity=2)
