"""Offline concurrency regressions for Steel sessions: NO real Steel calls."""
from __future__ import annotations

import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import steel_context_fix
import steel_runtime
from steel_runtime import Engine, RemoteBrowser, SteelFailure, install


class FakeCDPBrowser:
    def __init__(self):
        self.close_count = 0

    async def close(self):
        self.close_count += 1


class FakeChromium:
    def __init__(self):
        self.attempts = 0
        self.fail_next = False
        self.connections = []

    async def connect_over_cdp(self, endpoint, timeout):
        self.attempts += 1
        # The synthetic key is never logged or sent to a network service.
        assert endpoint.startswith("wss://connect.steel.dev?")
        assert timeout == 25000
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("Synthetic remote error: do not disclose")
        result = FakeCDPBrowser()
        self.connections.append(result)
        return result


class FakeEngine(Engine):
    def __init__(self):
        super().__init__()
        self.creates = 0
        self.releases = 0
        self.last_create_body = None
        self.block_create = False
        self.block_release = False
        self.return_wrong_id = False
        self.fail_release = False
        self.fail_create = False
        self.create_entered = asyncio.Event()
        self.create_continue = asyncio.Event()
        self.release_entered = asyncio.Event()
        self.release_continue = asyncio.Event()

    async def request(self, method, path, body=None, timeout=25):
        # Replaces ALL I/O. No API, browser or paid provider is contacted.
        if method == "POST" and path == "/sessions":
            self.creates += 1
            self.last_create_body = body
            if self.fail_create:
                raise SteelFailure('STEEL_CONNECTION_FAILED')
            if self.block_create:
                self.create_entered.set()
                await self.create_continue.wait()
            return {"id": "mismatched-id" if self.return_wrong_id else body["sessionId"]}
        if method == "POST" and path.endswith("/release"):
            self.releases += 1
            if self.fail_release:
                raise SteelFailure('STEEL_HTTP_503')
            if self.block_release:
                self.release_entered.set()
                await self.release_continue.wait()
            return {}
        raise AssertionError("Unexpected request to provider stub")


class SteelSingleFlight(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.key = patch.dict(os.environ, {"STEEL_API_KEY": "synthetic-key-not-a-secret"})
        self.key.start()

    def tearDown(self):
        self.key.stop()

    async def test_steel_session_explicitly_allows_human_mouse_keyboard(self):
        engine, chrome = FakeEngine(), FakeChromium()
        browser = await engine.launch(chrome)
        try:
            request = engine.last_create_body
            self.assertEqual(request["debugConfig"]["interactive"], True)
            self.assertEqual(request["debugConfig"]["systemCursor"], True)
            self.assertEqual(request["dimensions"], {"width": 508, "height": 1074})
            self.assertIs(request["headless"], False)
            self.assertIs(request["solveCaptcha"], True)
        finally:
            await browser.close()

    async def test_two_simultaneous_starts_create_only_one_remote(self):
        engine, chrome = FakeEngine(), FakeChromium()
        engine.block_create = True
        first = asyncio.create_task(engine.launch(chrome))
        await asyncio.wait_for(engine.create_entered.wait(), timeout=2)
        second = asyncio.create_task(engine.launch(chrome))
        await asyncio.sleep(0.03)
        self.assertEqual(engine.creates, 1, "A second provider POST is billable")
        engine.create_continue.set()
        remote = await asyncio.wait_for(first, timeout=2)
        with self.assertRaisesRegex(SteelFailure, "STEEL_SESSION_LIMIT_1"):
            await asyncio.wait_for(second, timeout=2)
        self.assertEqual(engine.creates, 1)
        self.assertEqual(chrome.attempts, 1)
        await remote.close()

    async def test_close_in_progress_blocks_new_session(self):
        engine, chrome = FakeEngine(), FakeChromium()
        remote = await engine.launch(chrome)
        engine.block_release = True
        closer = asyncio.create_task(remote.close())
        await asyncio.wait_for(engine.release_entered.wait(), timeout=2)
        self.assertTrue(remote.closed)
        self.assertIn(remote.remote_id, engine.remote)
        with self.assertRaisesRegex(SteelFailure, "STEEL_SESSION_LIMIT_1"):
            await asyncio.wait_for(engine.launch(chrome), timeout=2)
        self.assertEqual(engine.creates, 1)
        engine.release_continue.set()
        await asyncio.wait_for(closer, timeout=2)
        self.assertEqual(engine.remote, {})

    async def test_normal_close_allows_new_session(self):
        engine, chrome = FakeEngine(), FakeChromium()
        first = await engine.launch(chrome)
        await first.close()
        second = await engine.launch(chrome)
        self.assertEqual(engine.creates, 2)
        self.assertNotEqual(first.remote_id, second.remote_id)
        await second.close()
        self.assertEqual(engine.releases, 2)

    async def test_failed_cdp_connect_releases_provider_and_unlocks(self):
        engine, chrome = FakeEngine(), FakeChromium()
        chrome.fail_next = True
        with self.assertRaises(SteelFailure) as caught:
            await engine.launch(chrome)
        self.assertEqual(str(caught.exception), "STEEL_CDP_CONNECTION_FAILED")
        self.assertNotIn("Synthetic remote error", str(caught.exception))
        self.assertEqual(engine.releases, 1)
        self.assertEqual(engine.remote, {})
        second = await engine.launch(chrome)
        await second.close()
        self.assertEqual(engine.creates, 2)

    async def test_mismatched_provider_id_quarantines_even_if_release_acknowledged(self):
        engine, chrome = FakeEngine(), FakeChromium()
        engine.return_wrong_id = True
        with self.assertRaisesRegex(SteelFailure, "STEEL_SESSION_ID_MISMATCH"):
            await engine.launch(chrome)
        self.assertEqual(engine.remote, {})
        self.assertEqual(engine.releases, 1)
        self.assertTrue(engine._quarantined)
        engine.return_wrong_id = False
        with self.assertRaisesRegex(SteelFailure, "STEEL_SESSION_QUARANTINED"):
            await engine.launch(chrome)
        self.assertEqual(engine.creates, 1)

    async def test_uncertain_release_blocks_a_replacement_and_leaves_reference(self):
        engine, chrome = FakeEngine(), FakeChromium()
        remote = await engine.launch(chrome)
        engine.fail_release = True
        with self.assertRaisesRegex(SteelFailure, "STEEL_REMOTE_RELEASE_UNCONFIRMED"):
            await remote.close()
        self.assertTrue(engine._quarantined)
        self.assertIn(remote.remote_id, engine.remote)
        self.assertEqual(engine.releases, 2)
        with self.assertRaisesRegex(SteelFailure, "STEEL_SESSION_QUARANTINED"):
            await engine.launch(chrome)
        self.assertEqual(engine.creates, 1)

    async def test_uncertain_release_does_not_retry_on_second_close(self):
        engine, chrome = FakeEngine(), FakeChromium()
        remote = await engine.launch(chrome)
        engine.fail_release = True
        with self.assertRaises(SteelFailure):
            await remote.close()
        with self.assertRaisesRegex(SteelFailure, "STEEL_REMOTE_RELEASE_UNCONFIRMED"):
            await remote.close()
        self.assertEqual(engine.releases, 2)
        self.assertTrue(engine._quarantined)
        self.assertIn(remote.remote_id, engine.remote)

    async def test_ambiguous_create_is_quarantined_even_if_cleanup_acknowledges(self):
        engine, chrome = FakeEngine(), FakeChromium()
        engine.fail_create = True
        with self.assertRaisesRegex(SteelFailure, "STEEL_CONNECTION_FAILED"):
            await engine.launch(chrome)
        self.assertTrue(engine._quarantined)
        self.assertEqual(engine.releases, 1)
        engine.fail_create = False
        with self.assertRaisesRegex(SteelFailure, "STEEL_SESSION_QUARANTINED"):
            await engine.launch(chrome)
        self.assertEqual(engine.creates, 1)

    async def test_cdp_error_and_failed_release_quarantine(self):
        engine, chrome = FakeEngine(), FakeChromium()
        engine.fail_release = True
        chrome.fail_next = True
        with self.assertRaisesRegex(SteelFailure, "STEEL_CDP_CONNECTION_FAILED"):
            await engine.launch(chrome)
        self.assertTrue(engine._quarantined)
        self.assertEqual(engine.releases, 2)
        with self.assertRaisesRegex(SteelFailure, "STEEL_SESSION_QUARANTINED"):
            await engine.launch(chrome)
        self.assertEqual(engine.creates, 1)

    async def test_simultaneous_close_is_idempotent(self):
        engine, chrome = FakeEngine(), FakeChromium()
        remote = await engine.launch(chrome)
        await asyncio.gather(remote.close(), remote.close())
        self.assertEqual(engine.releases, 1)
        self.assertEqual(chrome.connections[0].close_count, 1)
        self.assertEqual(engine.remote, {})


class SteelInstalledCreatePreflight(unittest.IsolatedAsyncioTestCase):
    """Use the real context wrapper; all registry/provider I/O stays synthetic."""

    async def asyncSetUp(self):
        self.engine, self.chrome = FakeEngine(), FakeChromium()
        self.profile_id = "00000000-0000-4000-8000-000000000001"
        self.registry_read = AsyncMock(return_value={
            "profile_id": self.profile_id, "hydrated": True})
        self.registry_write = AsyncMock(return_value={"ok": True})
        self.provider_read = AsyncMock(return_value={"status": "READY"})
        provider_request = self.engine.request

        async def request(method, path, body=None, timeout=25):
            if method == "GET" and path == "/profiles/" + self.profile_id:
                return await self.provider_read()
            result = await provider_request(method, path, body, timeout)
            if method == "POST" and path == "/sessions":
                result["profileId"] = self.profile_id
            return result

        async def registry_request(method, *args):
            return await (self.registry_read if method == "GET"
                          else self.registry_write)(*args)

        self.engine.request = request
        sessions = {}

        async def start(profile):
            remote = await self.engine.launch(self.chrome)
            sid = "synthetic-" + remote.remote_id
            sessions[sid] = SimpleNamespace(
                browser=remote, profile=profile,
                page=SimpleNamespace(url="https://example.org/", is_closed=lambda: False,
                    locator=lambda _selector: SimpleNamespace(count=AsyncMock(return_value=0))))
            return {"session_id": sid}

        async def stop(sid):
            await sessions[sid].browser.close()
            sessions.pop(sid)
            return {"profile_saved": False}

        self.manager = SimpleNamespace(
            _steel_engine=self.engine, _sessions=sessions,
            _session=lambda sid: sessions[sid], start=start, stop=stop,
            status=AsyncMock(side_effect=lambda sid: {"session_id": sid}),
            flush_profile=AsyncMock(return_value={"ok": True}))
        mcp = SimpleNamespace(
            tool=lambda: lambda fn: fn,
            custom_route=lambda *_args, **_kwargs: lambda fn: fn)
        for patcher in (
            patch.dict(os.environ, {"AI_BROWSER_ENGINE": "steel",
                                   "STEEL_API_KEY": "synthetic-key-not-a-secret"}),
            patch.object(RemoteBrowser, "new_context", RemoteBrowser.new_context),
            patch.object(steel_runtime, "VERSION", steel_runtime.VERSION),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        with patch.object(steel_context_fix, "ProfileRegistry", return_value=SimpleNamespace(
                request=registry_request)), patch("builtins.print"):
            steel_context_fix.install({
                "manager": self.manager, "mcp": mcp, "_SETUP_HTML": "",
                "_setup_record": lambda _request: None})

    def assert_no_create(self):
        self.assertEqual(self.engine.creates, 0)
        self.assertEqual(self.engine.releases, 0)
        self.assertEqual(self.chrome.attempts, 0)
        self.assertFalse(self.engine._quarantined)
        self.registry_write.assert_not_awaited()

    async def test_missing_profile_context_cannot_quarantine_or_release(self):
        with self.assertRaisesRegex(steel_context_fix.ReliabilityError, "^PROFILE_CONTEXT_REQUIRED$"):
            await self.engine.launch(self.chrome)
        self.assert_no_create()
        self.registry_read.assert_not_awaited()

    async def test_registry_error_preserves_code_and_allows_later_explicit_start(self):
        failure = steel_context_fix.ReliabilityError("PROFILE_REGISTRY_UNAVAILABLE")
        self.registry_read.side_effect = failure
        with self.assertRaises(steel_context_fix.ReliabilityError) as caught:
            await self.manager.start("SyntheticPreflight")
        self.assertIs(caught.exception, failure)
        self.assert_no_create()

        # No automatic retry. A later caller may start once the read recovers.
        self.registry_read.side_effect = None
        result = await self.manager.start("SyntheticPreflight")
        try:
            self.assertEqual(self.engine.creates, 1)
            self.assertEqual(self.chrome.attempts, 1)
        finally:
            await self.manager.stop(result["session_id"])
        self.assertEqual(self.engine.remote, {})

    async def test_not_ready_profile_cannot_quarantine_or_release(self):
        self.provider_read.return_value = {"status": "FAILED"}
        with self.assertRaisesRegex(steel_context_fix.ReliabilityError, "^NATIVE_PROFILE_NOT_READY$"):
            await self.manager.start("SyntheticPreflight")
        self.assert_no_create()

    async def test_ready_read_network_error_cannot_quarantine_or_release(self):
        self.provider_read.side_effect = SteelFailure("STEEL_HTTP_503")
        with self.assertRaisesRegex(SteelFailure, "^STEEL_HTTP_503$"):
            await self.manager.start("SyntheticPreflight")
        self.assert_no_create()

    async def assert_cancelled_read_did_not_create(self, read):
        entered = asyncio.Event()

        async def blocked(*_args):
            entered.set()
            await asyncio.Event().wait()

        read.side_effect = blocked
        task = asyncio.create_task(self.manager.start("SyntheticPreflight"))
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(task.cancelled(), "Cancellation must not become an ordinary error")
        self.assert_no_create()

    async def test_cancelled_registry_read_has_no_provider_side_effect(self):
        await self.assert_cancelled_read_did_not_create(self.registry_read)

    async def test_cancelled_ready_read_has_no_provider_side_effect(self):
        await self.assert_cancelled_read_did_not_create(self.provider_read)

    async def assert_quarantined_without_create_retry(self):
        self.assertTrue(self.engine._quarantined)
        self.assertEqual(self.engine.creates, 1)
        self.assertGreaterEqual(self.engine.releases, 1)
        reads = self.registry_read.await_count
        with self.assertRaisesRegex(SteelFailure, "^STEEL_SESSION_QUARANTINED$"):
            await self.manager.start("SyntheticPreflight")
        self.assertEqual(self.engine.creates, 1)
        self.assertEqual(self.registry_read.await_count, reads)

    async def test_cancellation_inside_actual_create_still_quarantines(self):
        self.engine.block_create = True
        task = asyncio.create_task(self.manager.start("SyntheticPreflight"))
        await asyncio.wait_for(self.engine.create_entered.wait(), 2)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        await self.assert_quarantined_without_create_retry()

    async def test_actual_create_error_still_quarantines(self):
        self.engine.fail_create = True
        with self.assertRaisesRegex(SteelFailure, "^STEEL_CONNECTION_FAILED$"):
            await self.manager.start("SyntheticPreflight")
        await self.assert_quarantined_without_create_retry()

    async def test_registry_write_after_create_still_quarantines(self):
        self.registry_write.side_effect = steel_context_fix.ReliabilityError("PROFILE_REGISTRY_UNAVAILABLE")
        with self.assertRaisesRegex(steel_context_fix.ReliabilityError, "^NATIVE_PROFILE_BINDING_FAILED$"):
            await self.manager.start("SyntheticPreflight")
        await self.assert_quarantined_without_create_retry()

    async def test_existing_quarantine_and_remote_reference_cannot_be_cleared(self):
        other = RemoteBrowser(self.engine, FakeCDPBrowser(), "synthetic-other")
        self.engine.remote[other.remote_id] = other
        self.engine._quarantined = True
        with self.assertRaisesRegex(SteelFailure, "^STEEL_SESSION_QUARANTINED$"):
            await self.manager.start("SyntheticPreflight")
        self.assertTrue(self.engine._quarantined)
        self.assertIs(self.engine.remote[other.remote_id], other)
        self.assertFalse(other.closed)
        self.assertEqual(self.engine.creates, 0)
        self.assertEqual(self.engine.releases, 0)
        self.registry_read.assert_not_awaited()


class SteelCloseCancellation(unittest.IsolatedAsyncioTestCase):
    """Exercise cancellation stages without a provider or browser connection."""

    async def asyncSetUp(self):
        self.engine = FakeEngine()
        self.browser = FakeCDPBrowser()
        self.remote = RemoteBrowser(self.engine, self.browser, "synthetic-owned")
        self.other_browser = FakeCDPBrowser()
        self.other = RemoteBrowser(self.engine, self.other_browser, "synthetic-other")
        self.engine.remote.update({
            self.remote.remote_id: self.remote,
            self.other.remote_id: self.other,
        })
        self.engine.release = AsyncMock(wraps=self.engine.release)

    def assert_other_untouched(self):
        self.assertIs(self.engine.remote.get(self.other.remote_id), self.other)
        self.assertEqual(self.other_browser.close_count, 0)
        self.assertFalse(self.other.closed)

    async def cancel_during_cdp_close(self, close=None):
        entered = asyncio.Event()
        original_close = self.browser.close

        async def blocked_close():
            await original_close()
            entered.set()
            await asyncio.Event().wait()

        self.browser.close = blocked_close
        task = asyncio.create_task((close or self.remote.close)())
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

    async def test_cancel_before_release_allows_one_first_release_on_later_closes(self):
        await self.cancel_during_cdp_close()
        self.engine.release.assert_not_awaited()
        self.assertIn(self.remote.remote_id, self.engine.remote)
        self.assertTrue(self.engine._quarantined)

        await asyncio.gather(self.remote.close(), self.remote.close())

        self.engine.release.assert_awaited_once_with(self.remote.remote_id)
        self.assertEqual(self.browser.close_count, 1)
        self.assertNotIn(self.remote.remote_id, self.engine.remote)
        self.assertTrue(self.engine._quarantined, "Close must not clear quarantine")
        self.assert_other_untouched()

    async def test_installed_stop_finally_releases_after_cancelled_cdp_close(self):
        async def original_stop(sid):
            await manager._sessions[sid].browser.close()

        manager = SimpleNamespace(
            portable_profiles=True,
            _sessions={
                "owned-session": SimpleNamespace(browser=self.remote),
                "other-session": SimpleNamespace(browser=self.other),
            },
            _ensure_playwright=AsyncMock(),
            start=AsyncMock(),
            stop=AsyncMock(side_effect=original_stop),
            status=AsyncMock(return_value={}),
        )
        original_stop_mock = manager.stop
        mcp = SimpleNamespace(custom_route=lambda *_args, **_kwargs: lambda fn: fn)
        ns = {"manager": manager, "mcp": mcp, "_SETUP_HTML": "",
              "_setup_record": lambda _request: None}
        with patch.dict(os.environ, {
                "AI_BROWSER_ENGINE": "steel",
                "AI_BROWSER_PARALLEL_SESSIONS": "1",
                "AI_BROWSER_SESSION_GUARD": "0",
        }), patch("steel_runtime.Engine", return_value=self.engine), patch("builtins.print"):
            install(ns)

        # Run the real installed wrapper: old_stop enters the cancelled close;
        # its finally block must finish the never-started provider release.
        await self.cancel_during_cdp_close(lambda: manager.stop("owned-session"))

        original_stop_mock.assert_awaited_once_with("owned-session")
        self.engine.release.assert_awaited_once_with(self.remote.remote_id)
        self.assertEqual(self.browser.close_count, 1)
        self.assertNotIn(self.remote.remote_id, self.engine.remote)
        self.assertTrue(self.engine._quarantined)
        self.assert_other_untouched()

    async def test_cancel_during_release_never_resubmits_the_release(self):
        self.engine.block_release = True
        task = asyncio.create_task(self.remote.close())
        await asyncio.wait_for(self.engine.release_entered.wait(), 2)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

        with self.assertRaisesRegex(SteelFailure, "^STEEL_REMOTE_RELEASE_UNCONFIRMED$"):
            await self.remote.close()

        self.engine.release.assert_awaited_once_with(self.remote.remote_id)
        self.assertEqual(self.engine.releases, 1)
        self.assertIn(self.remote.remote_id, self.engine.remote)
        self.assertTrue(self.engine._quarantined)
        self.assert_other_untouched()

    async def test_cancel_waiting_for_close_lock_leaves_session_active(self):
        await self.remote.close_lock.acquire()
        try:
            task = asyncio.create_task(self.remote.close())
            await asyncio.sleep(0)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        finally:
            self.remote.close_lock.release()

        self.engine.release.assert_not_awaited()
        self.assertEqual(self.browser.close_count, 0)
        self.assertFalse(self.remote.closed)
        self.assertFalse(self.engine._quarantined)
        self.assertIs(self.engine.remote[self.remote.remote_id], self.remote)
        self.assert_other_untouched()

    async def test_unexpected_release_exception_is_redacted_and_not_retried(self):
        self.engine.release.side_effect = RuntimeError("synthetic private provider detail")
        for _ in range(2):
            with self.assertRaisesRegex(SteelFailure, "^STEEL_REMOTE_RELEASE_UNCONFIRMED$"):
                await self.remote.close()

        self.engine.release.assert_awaited_once_with(self.remote.remote_id)
        self.assertIn(self.remote.remote_id, self.engine.remote)
        self.assertTrue(self.engine._quarantined)
        self.assert_other_untouched()

    async def test_failed_release_after_cancel_stays_unconfirmed(self):
        await self.cancel_during_cdp_close()
        self.engine.fail_release = True
        for _ in range(2):
            with self.assertRaisesRegex(SteelFailure, "^STEEL_REMOTE_RELEASE_UNCONFIRMED$"):
                await self.remote.close()

        self.engine.release.assert_awaited_once_with(self.remote.remote_id)
        self.assertEqual(self.engine.releases, 2, "Existing bounded release policy is unchanged")
        self.assertIn(self.remote.remote_id, self.engine.remote)
        self.assertTrue(self.engine._quarantined)
        self.assert_other_untouched()

    async def test_cdp_exception_does_not_prevent_provider_release(self):
        self.browser.close = AsyncMock(side_effect=RuntimeError("synthetic CDP failure"))
        await self.remote.close()

        self.engine.release.assert_awaited_once_with(self.remote.remote_id)
        self.assertNotIn(self.remote.remote_id, self.engine.remote)
        self.assertFalse(self.engine._quarantined)
        self.assert_other_untouched()

    async def test_close_does_not_remove_a_replaced_remote_reference(self):
        replacement = object()
        self.engine.remote[self.remote.remote_id] = replacement
        await self.remote.close()

        self.engine.release.assert_awaited_once_with(self.remote.remote_id)
        self.assertIs(self.engine.remote[self.remote.remote_id], replacement)
        self.assert_other_untouched()


if __name__ == "__main__":
    unittest.main(verbosity=2)
