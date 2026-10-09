"""Offline concurrency regressions for Steel sessions: NO real Steel calls."""
from __future__ import annotations

import asyncio
import os
import unittest
from unittest.mock import patch

from steel_runtime import Engine, SteelFailure


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
