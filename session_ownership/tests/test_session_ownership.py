"""Synthetic unit tests; they never call Steel, Meta, Render or user accounts."""
import asyncio
import unittest
from session_ownership import SessionCoordinator, LeaseError


class FakeBrowser:
    def __init__(self):
        self.session = None
        self.started = 0
        self.closed = 0
        self.stop_status = {"profile_saved": True, "full_profile_saved": True}
        self.concurrent = 0
        self.max_concurrent = 0

    async def sessions(self):
        return [dict(self.session)] if self.session else []

    async def start(self, *, profile, mode, start_url):
        self.started += 1
        self.session = {"session_id": "synthetic-session", "profile": profile,
                        "mode": mode, "url": start_url}
        return dict(self.session)

    async def stop(self, session_id):
        self.closed += 1
        if self.stop_status.get("profile_saved") and self.stop_status.get("full_profile_saved"):
            self.session = None
        return dict(self.stop_status)

    async def navigate(self, session_id, url):
        self.concurrent += 1
        self.max_concurrent = max(self.max_concurrent, self.concurrent)
        await asyncio.sleep(.002)
        self.session["url"] = url
        self.concurrent -= 1
        return {"url": url}

    async def snapshot(self, session_id, **kwargs):
        return {"url": self.session["url"], "passwords": None}

    async def status(self, session_id):
        return dict(self.session)


class TestSessionOwnership(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.b = FakeBrowser()
        self.t = [100]
        self.c = SessionCoordinator(self.b, clock=lambda: self.t[0])
        self.options = dict(profile="Meta - Maciej - Monitoring",
            start_url="https://business.facebook.com/latest/home",
            allowed_origins=("https://business.facebook.com", "https://m.facebook.com"))

    async def acquire(self):
        return await self.c.open(**self.options)

    async def test_one_owner(self):
        result = await self.acquire()
        self.assertEqual(result["mode"], "read_only")
        self.assertEqual(self.b.started, 1)

    async def test_second_owner_blocked(self):
        results = await asyncio.gather(self.acquire(), self.acquire(), return_exceptions=True)
        self.assertEqual(sum(isinstance(x, dict) for x in results), 1)
        self.assertEqual(sum(isinstance(x, LeaseError) for x in results), 1)

    async def test_existing_live_session_not_stolen(self):
        self.b.session = {"session_id":"other", "profile":"Other", "mode":"write", "url":"https://m.facebook.com"}
        with self.assertRaisesRegex(LeaseError, "BROWSER_BUSY"): await self.acquire()
        self.assertEqual(self.b.closed, 0)

    async def test_duplicate_open_blocked(self):
        await self.acquire()
        with self.assertRaisesRegex(LeaseError, "BROWSER_BUSY"): await self.acquire()

    async def test_read_navigation(self):
        token = (await self.acquire())["lease_token"]
        result = await self.c.run(token, "navigate", url="https://m.facebook.com/groups/123/")
        self.assertEqual(result["url"], "https://m.facebook.com/groups/123/")

    async def test_outside_origin_rejected(self):
        token = (await self.acquire())["lease_token"]
        for dest in ("https://evil.example.test", "https://business.facebook.com.evil.test/"):
            with self.subTest(dest=dest), self.assertRaises(LeaseError):
                await self.c.run(token, "navigate", url=dest)

    async def test_non_https_rejected(self):
        token = (await self.acquire())["lease_token"]
        with self.assertRaises(LeaseError):
            await self.c.run(token, "navigate", url="http://m.facebook.com/")

    async def test_query_or_fragment_rejected(self):
        token = (await self.acquire())["lease_token"]
        for dest in ("https://m.facebook.com/?key=FAKE", "https://m.facebook.com/#FAKE"):
            with self.subTest(dest=dest), self.assertRaises(LeaseError):
                await self.c.run(token, "navigate", url=dest)

    async def test_write_actions_not_enabled(self):
        token = (await self.acquire())["lease_token"]
        for action in ("click", "fill", "publish", "set_mode"):
            with self.subTest(action=action), self.assertRaisesRegex(LeaseError, "SEPARATE_AUTHORIZATION"):
                await self.c.run(token, action)

    async def test_other_token_denied(self):
        await self.acquire()
        with self.assertRaisesRegex(LeaseError, "LEASE_NOT_OWNED"):
            await self.c.run("A" * 43, "snapshot")

    async def test_other_token_cannot_close(self):
        await self.acquire()
        with self.assertRaisesRegex(LeaseError, "LEASE_NOT_OWNED"):
            await self.c.close("A" * 43)
        self.assertEqual(self.b.closed, 0)

    async def test_expiration(self):
        token = (await self.acquire())["lease_token"]
        self.t[0] += 601
        with self.assertRaisesRegex(LeaseError, "LEASE_EXPIRED"):
            await self.c.run(token, "snapshot")

    async def test_expired_but_live_not_stolen(self):
        await self.acquire()
        self.t[0] += 601
        self.assertEqual((await self.c.reconcile())["status"], "expired_but_live_needs_manual_resolution")
        with self.assertRaisesRegex(LeaseError, "BROWSER_BUSY"): await self.acquire()

    async def test_expired_and_empty_releases(self):
        await self.acquire()
        self.t[0] += 601
        self.b.session = None
        self.assertEqual((await self.c.reconcile())["status"], "expired_and_empty_released")
        self.assertIsNone(self.c.lease)

    async def test_stop_requires_full_profile_saved(self):
        token = (await self.acquire())["lease_token"]
        self.b.stop_status = {"profile_saved": True, "full_profile_saved": False}
        with self.assertRaisesRegex(LeaseError, "PERSISTENCE_NOT_CONFIRMED"):
            await self.c.close(token)
        self.assertIsNotNone(self.c.lease)

    async def test_close_success(self):
        token = (await self.acquire())["lease_token"]
        self.assertTrue((await self.c.close(token))["released"])
        self.assertEqual(self.b.closed, 1)
        self.assertIsNone(self.c.lease)

    async def test_calls_serial(self):
        token = (await self.acquire())["lease_token"]
        await asyncio.gather(*(self.c.run(token, "navigate", url="https://m.facebook.com/page"+str(x)) for x in range(8)))
        self.assertEqual(self.b.max_concurrent, 1)

    async def test_unexpected_mode_change_detected(self):
        token = (await self.acquire())["lease_token"]
        self.b.session["mode"] = "write"
        with self.assertRaisesRegex(LeaseError, "SESSION_PRIVILEGE_CHANGED"):
            await self.c.run(token, "snapshot")

    async def test_unexpected_session_change_detected(self):
        token = (await self.acquire())["lease_token"]
        self.b.session["session_id"] = "someone-else"
        with self.assertRaisesRegex(LeaseError, "SESSION_CHANGED_OUTSIDE"):
            await self.c.run(token, "status")

    async def test_redirect_not_trusted(self):
        token = (await self.acquire())["lease_token"]
        old = self.b.navigate
        async def redirect(sid, url):
            await old(sid, url)
            self.b.session["url"] = "https://other.example.test"
            return {"url": self.b.session["url"]}
        self.b.navigate = redirect
        with self.assertRaisesRegex(LeaseError, "REDIRECT_OUTSIDE"):
            await self.c.run(token, "navigate", url="https://m.facebook.com/")
        with self.assertRaisesRegex(LeaseError, "CURRENT_ORIGIN_NOT_ALLOWED"):
            await self.c.run(token, "snapshot")

    async def test_close_does_not_stop_elevated_session(self):
        token = (await self.acquire())["lease_token"]
        self.b.session["mode"] = "write"
        with self.assertRaisesRegex(LeaseError, "SESSION_CHANGED_OUTSIDE"):
            await self.c.close(token)
        self.assertEqual(self.b.closed, 0)

    async def test_renew_checks_identity(self):
        token = (await self.acquire())["lease_token"]
        self.b.session["session_id"] = "someone-else"
        with self.assertRaisesRegex(LeaseError, "SESSION_CHANGED_OUTSIDE"):
            await self.c.renew(token)

    async def test_renew_valid(self):
        token = (await self.acquire())["lease_token"]
        self.t[0] += 570
        self.assertTrue((await self.c.renew(token))["renewed"])
        self.t[0] += 20
        self.assertEqual((await self.c.run(token, "status"))["mode"], "read_only")

    async def test_invalid_duration(self):
        with self.assertRaisesRegex(LeaseError, "INVALID_LEASE_DURATION"):
            await self.c.open(**{**self.options,"lease_seconds":10000})

    async def test_invalid_profile(self):
        with self.assertRaisesRegex(LeaseError, "INVALID_PROFILE"):
            await self.c.open(**{**self.options,"profile":"../wrong"})

    async def test_capability_rotated(self):
        first = (await self.acquire())["lease_token"]
        await self.c.close(first)
        second = (await self.acquire())["lease_token"]
        self.assertNotEqual(first, second)
        with self.assertRaisesRegex(LeaseError, "LEASE_NOT_OWNED"):
            await self.c.run(first, "status")

    async def test_snapshot_limit(self):
        token = (await self.acquire())["lease_token"]
        with self.assertRaisesRegex(LeaseError, "INVALID_OUTPUT_LIMIT"):
            await self.c.run(token, "snapshot", max_text_chars=100000)

    async def test_wrong_start_origin(self):
        with self.assertRaisesRegex(LeaseError, "DESTINATION_NOT_ALLOWED"):
            await self.c.open(**{**self.options,"start_url":"https://www.instagram.com/"})

    async def test_unknown_argument(self):
        token = (await self.acquire())["lease_token"]
        with self.assertRaisesRegex(LeaseError, "INVALID_ARGUMENT"):
            await self.c.run(token, "snapshot", leaked="bad")

if __name__ == "__main__":
    unittest.main(verbosity=2)
