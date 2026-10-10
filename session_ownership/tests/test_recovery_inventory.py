"""Read-only recovery inventory regressions; no providers or real profiles."""
import asyncio
import hashlib
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from capability_guard import Lease, OwnershipError
from multi_capability_guard import MultiCapabilityGuard


class RecoveryInventory(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.manager = SimpleNamespace(_sessions={}, stop=AsyncMock())
        self.guard = MultiCapabilityGuard(
            None, self.manager, capacity=5, watchdog_enabled=False, clock=lambda: 100)

    def bind(self, name="PRIVATE_FIXTURE_ACCOUNT", present=True):
        sid = "INTERNAL_PRIVATE_" + name
        cap = "aib_" + "x" * 43
        lease = Lease(sid, hashlib.sha256(cap.encode()).digest(), name, 100)
        self.guard.leases[sid] = lease
        self.guard.by_profile[name] = sid
        self.guard.session_locks[sid] = asyncio.Lock()
        if present:
            self.manager._sessions[sid] = SimpleNamespace(profile=name, mode="read_only")
        return sid, cap, lease

    def assert_redacted(self, listing, *private):
        text = json.dumps(listing)
        for value in private:
            self.assertNotIn(value, text)
        self.assertIsInstance(listing, list)

    async def test_clean_idle_remains_empty(self):
        self.assertEqual(self.guard.safe_sessions(), [])
        self.assertFalse(self.guard.quarantined)

    async def test_missing_owned_session_cannot_look_idle(self):
        sid, cap, lease = self.bind(present=False)
        listing = self.guard.safe_sessions()
        self.assertEqual(len(listing), 1)
        self.assertEqual(listing[0], {
            "session_id": "[redacted]", "profile": "[redacted]",
            "mode": "unknown", "state": "missing_session_quarantined"})
        self.assertTrue(self.guard.quarantined)
        self.assertTrue(lease.recovery_required)
        self.assert_redacted(listing, sid, cap, lease.profile)
        self.assertIn(sid, self.guard.leases)
        self.manager.stop.assert_not_awaited()
        with self.assertRaisesRegex(OwnershipError, "PARALLEL_PROVIDER_RECONCILIATION_REQUIRED"):
            await self.guard.start(AsyncMock(), {"profile": "NewTechnicalProfile"})

    async def test_failed_save_after_manager_removal_still_visible(self):
        sid, cap, lease = self.bind()
        async def failed_stop(session_id):
            self.manager._sessions.pop(session_id)
            return {"profile_saved": False, "full_profile_saved": False}
        await self.guard.action("browser_stop", failed_stop, {"session_id": cap})
        self.assertEqual(self.manager._sessions, {})
        self.assertEqual(self.guard.safe_sessions()[0]["state"], "missing_session_quarantined")
        self.assertIn(sid, self.guard.leases)
        self.assertTrue(lease.recovery_required)

    async def test_missing_record_does_not_hide_or_touch_healthy_chat(self):
        sid, cap, lease = self.bind("MISSING_PRIVATE_ACCOUNT", present=False)
        other_sid, _, _ = self.bind("TechnicalHealthy")
        listing = self.guard.safe_sessions()
        self.assertEqual(len(listing), 2)
        self.assertEqual(listing[0]["state"], "active")
        self.assertEqual(listing[1]["state"], "missing_session_quarantined")
        self.assertIn(other_sid, self.manager._sessions)
        self.assert_redacted(listing, sid, other_sid, cap, lease.profile)
        self.manager.stop.assert_not_awaited()

    async def test_quarantine_without_any_local_record_cannot_look_idle(self):
        self.guard.quarantined = True
        listing = self.guard.safe_sessions()
        self.assertEqual(listing, [{
            "session_id": "[redacted]", "profile": "[redacted]", "mode": "unknown",
            "state": "provider_reconciliation_required"}])
        self.assertTrue(self.guard.quarantined)
        self.assertEqual(self.manager._sessions, {})
        self.manager.stop.assert_not_awaited()

    async def test_sticky_quarantine_reported_next_to_active_session(self):
        self.bind("TechnicalHealthy")
        self.guard.quarantined = True
        listing = self.guard.safe_sessions()
        self.assertEqual([x["state"] for x in listing],
                         ["active", "provider_reconciliation_required"])
        self.assertEqual(len(self.manager._sessions), 1)

    async def test_unmanaged_and_missing_each_preserved_without_extra_sentinel(self):
        sid, cap, lease = self.bind(present=False)
        self.manager._sessions["FOREIGN_PROVIDER_HANDLE"] = SimpleNamespace(
            profile="FOREIGN_PRIVATE_ACCOUNT", mode="write")
        listing = self.guard.safe_sessions()
        self.assertEqual([x["state"] for x in listing],
                         ["unmanaged_quarantined", "missing_session_quarantined"])
        self.assert_redacted(listing, sid, cap, lease.profile,
                             "FOREIGN_PROVIDER_HANDLE", "FOREIGN_PRIVATE_ACCOUNT")
        self.assertIn("FOREIGN_PROVIDER_HANDLE", self.manager._sessions)

    async def test_repeated_inspection_does_not_release_or_duplicate_records(self):
        sid, _, _ = self.bind(present=False)
        first = self.guard.safe_sessions()
        for _ in range(3):
            self.assertEqual(self.guard.safe_sessions(), first)
        self.assertEqual(len(self.guard.leases), 1)
        self.assertIn(sid, self.guard.session_locks)
        self.manager.stop.assert_not_awaited()

    async def test_verified_complete_returns_clean_idle(self):
        sid, cap, _ = self.bind()
        async def success(session_id):
            self.manager._sessions.pop(session_id)
            return {"profile_saved": True, "full_profile_saved": True}
        await self.guard.action("browser_stop", success, {"session_id": cap})
        self.assertEqual(self.guard.safe_sessions(), [])
        self.assertNotIn(sid, self.guard.leases)
        self.assertFalse(self.guard.quarantined)


if __name__ == "__main__":
    unittest.main(verbosity=2)
