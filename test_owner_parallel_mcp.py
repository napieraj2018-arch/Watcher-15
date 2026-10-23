"""Real MCP SDK 2.3 contract for five owner-only parallel browser profiles.

Synthetic sessions ONLY: no Steel API, no cookies, real login or network.
Tests separate chat capabilities, profile mutex, owner guards, mobile denial,
unmanaged session fail-closed and simultaneous actions in different sessions.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.requests import Request

from multi_capability_guard import MultiCapabilityGuard
from mcp.server.mcpserver.exceptions import ToolError
from capability_guard import OwnershipError
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent
                       / "session_ownership" / "tests"))
from test_sdk_contract import fake_mcp

HANDLE_RE = re.compile(r"aib_[A-Za-z0-9_-]{43}")


class MultiManager:
    def __init__(self, capacity=5):
        self._sessions = {}
        self.max_sessions = capacity
        self.counter = 0
        self.saved = []
        self.broken_save = False

    def _session(self, sid):
        return self._sessions[sid]

    async def start(self, profile, mode="read_only",
                    start_url="about:blank", headless=True):
        if len(self._sessions) >= self.max_sessions:
            raise RuntimeError("SYNTHETIC_MAX_SESSIONS")
        self.counter += 1
        sid = "INTERNAL_SYNTHETIC_SESSION_" + str(self.counter)
        self._sessions[sid] = SimpleNamespace(
            profile=profile, mode=mode,
            page=SimpleNamespace(url=start_url),
        )
        return {"session_id":sid, "profile":profile,
                "mode":mode, "url":start_url}

    async def status(self, sid):
        session = self._session(sid)
        return {"session_id":sid,"mode":session.mode,"profile":session.profile}

    async def flush_profile(self, sid):
        self._session(sid)
        self.saved.append(sid)
        return {"saved":True}

    async def stop(self, sid):
        self._session(sid)
        self._sessions.pop(sid,None)
        self.saved.append(sid)
        return {"session_id":sid,
                "profile_saved":not self.broken_save,
                "full_profile_saved":not self.broken_save}


class MultiMcp(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.manager=MultiManager()
        self.mcp=fake_mcp(self.manager)
        async def mobile(_request):
            return JSONResponse({"unsafe":"legacy endpoint"})
        self.mcp._custom_starlette_routes.append(
            Route("/setup/legacy",mobile,methods=["POST"]))
        self.guard=MultiCapabilityGuard(
            self.mcp,self.manager,capacity=5,watchdog_enabled=False)
        before={name:tool.parameters.copy()
                for name,tool in self.mcp._tool_manager._tools.items()}
        self.assertEqual(self.guard.install(),51)
        after={name:tool.parameters
               for name,tool in self.mcp._tool_manager._tools.items()}
        self.assertEqual(before,after)

    async def begin(self, profile):
        result=await self.mcp.call_tool(
            "browser_start",{"profile":profile,"mode":"read_only",
                             "start_url":"https://example.com/"})
        match=HANDLE_RE.search(str(result))
        self.assertIsNotNone(match)
        return match.group(0)

    async def start_with_remaining(self, profile, remaining):
        async def start_result(**args):
            result = await self.manager.start(**args)
            result["remaining_seconds"] = remaining
            return result
        return await self.guard.start(start_result, {
            "profile": profile, "start_url": "https://example.com/"})

    async def paused_stop(self, outcome="saved", *, watchdog=False):
        """Pause the real guard before removal and before the save receipt."""
        cap = await self.begin("TechnicalClosing")
        lease = self.guard.authorize(cap)
        entered, allow_remove = asyncio.Event(), asyncio.Event()
        removed, allow_receipt = asyncio.Event(), asyncio.Event()

        async def staged_stop(session_id):
            self.manager._session(session_id)
            entered.set()
            await allow_remove.wait()
            self.manager._sessions.pop(session_id)
            removed.set()
            await allow_receipt.wait()
            if outcome == "raise":
                raise RuntimeError("SYNTHETIC_PERSISTENCE_ERROR")
            return {"session_id": session_id, "profile_saved": True,
                    "full_profile_saved": outcome == "saved"}

        if watchdog:
            async def immediate_sleep(_seconds):
                return None
            with patch.object(self.manager, "stop", new=staged_stop), patch(
                    "multi_capability_guard.asyncio.sleep", new=immediate_sleep):
                task = asyncio.create_task(self.guard.watchdog(lease))
                await asyncio.wait_for(entered.wait(), 1.5)
        else:
            task = asyncio.create_task(self.guard.action(
                "browser_stop", staged_stop, {"session_id": cap}))
            await asyncio.wait_for(entered.wait(), 1.5)
        return lease, task, allow_remove, removed, allow_receipt

    async def observe_paused_close(self, lease, allow_remove, removed):
        for after_removal in (False, True):
            if after_removal:
                allow_remove.set()
                await asyncio.wait_for(removed.wait(), 1.5)
            rows = self.guard.safe_sessions()
            self.assertEqual([x["state"] for x in rows], ["closing"])
            self.assertFalse(self.guard.quarantined)
            self.assertFalse(lease.recovery_required)
            self.assertIs(self.guard.leases[lease.internal_session_id], lease)
            with self.assertRaisesRegex(ToolError, "PARALLEL_PROFILE_BUSY"):
                await self.begin("TechnicalClosing")

    async def assert_failed_close_retains_lease(self, lease):
        self.assertTrue(self.guard.quarantined)
        self.assertTrue(lease.recovery_required)
        self.assertIs(self.guard.leases[lease.internal_session_id], lease)
        self.assertEqual([x["state"] for x in self.guard.safe_sessions()],
                         ["missing_session_quarantined"])
        with self.assertRaisesRegex(
                ToolError, "PARALLEL_PROVIDER_RECONCILIATION_REQUIRED"):
            await self.begin("TechnicalBlockedAfterFailure")

    async def paused_start(self, *, outcome="saved", corrupt_profile=False):
        entered, allow_register = asyncio.Event(), asyncio.Event()
        registered, allow_result = asyncio.Event(), asyncio.Event()

        async def staged_start(**args):
            entered.set()
            await allow_register.wait()
            result = await self.manager.start(**args)
            if corrupt_profile:
                self.manager._sessions[result["session_id"]].profile = "PRIVATE_UNEXPECTED_PROFILE"
            registered.set()
            await allow_result.wait()
            if outcome == "raise":
                raise RuntimeError("SYNTHETIC_START_ERROR")
            return result

        task = asyncio.create_task(self.guard.start(staged_start, {
            "profile": "TechnicalStarting", "start_url": "https://example.com/"}))
        await asyncio.wait_for(entered.wait(), 1.5)
        return task, allow_register, registered, allow_result

    async def test_five_different_chat_sessions_and_sixth_is_rejected(self):
        caps=await asyncio.gather(*(
            self.begin("Owner-Profile-"+str(i)) for i in range(1,6)))
        self.assertEqual(len(caps),5)
        self.assertEqual(len(set(caps)),5)
        self.assertEqual(len(self.manager._sessions),5)
        with self.assertRaisesRegex(ToolError,"PARALLEL_CAPACITY_FULL"):
            await self.begin("Owner-Profile-6")
        self.assertEqual(len(self.manager._sessions),5)
        public=await self.mcp.call_tool("browser_sessions",{})
        report=str(public)
        self.assertIn("Owner-Profile-5",report)
        # Production connector requires a bare list return value. The
        # previous {"result": [...], "capacity": 2} structure failed
        # browser_sessionsOutput.result list validation on Render.
        self.assertIsInstance(self.guard.safe_sessions(), list)
        self.assertEqual(len(self.guard.safe_sessions()), 5)
        self.assertNotIn("INTERNAL_SYNTHETIC_SESSION_",report)
        self.assertNotIn(caps[0],report)

    async def test_expired_capability_is_not_reported_as_active(self):
        cap = await self.begin("Owner-Expired-Technical")
        lease = next(iter(self.guard.leases.values()))
        self.guard.clock = lambda: lease.started_at + 851
        listing = self.guard.safe_sessions()
        self.assertEqual(len(listing), 1)
        self.assertEqual(listing[0]["state"], "capability_expired")
        self.assertEqual(listing[0]["session_id"], "[redacted]")
        self.assertNotIn(cap, str(listing))
        with self.assertRaisesRegex(ToolError, "SESSION_CAPABILITY_EXPIRED"):
            await self.mcp.call_tool("browser_status", {"session_id": cap})
        # Cleanup remains available to the owner after capability expiry.
        receipt = await self.mcp.call_tool(
            "browser_stop", {"session_id": cap})
        self.assertIn("full_profile_saved", str(receipt))
        self.assertEqual(self.guard.safe_sessions(), [])

    async def test_engine_quarantine_without_manager_or_lease_is_visible(self):
        self.manager._steel_engine = SimpleNamespace(
            remote={}, _quarantined=True)
        listing = self.guard.safe_sessions()
        self.assertEqual(listing, [{
            "session_id": "[redacted]", "profile": "[redacted]",
            "mode": "unknown", "state": "provider_reconciliation_required"}])
        result = await self.mcp.call_tool("browser_sessions", {})
        self.assertIn("provider_reconciliation_required", str(result))
        self.assertTrue(self.manager._steel_engine._quarantined)
        self.assertEqual(self.manager.saved, [])

    async def test_orphan_remote_reference_cannot_look_idle_or_disclose_id(self):
        private_id = "PRIVATE_PROVIDER_SESSION_ID"
        orphan = SimpleNamespace(_aib_viewer_url="PRIVATE_VIEWER_CAPABILITY")
        self.manager._steel_engine = SimpleNamespace(
            remote={private_id: orphan}, _quarantined=False)
        for _ in range(2):
            listing = self.guard.safe_sessions()
            self.assertEqual(len(listing), 1)
            self.assertEqual(listing[0]["state"], "provider_reconciliation_required")
            self.assertNotIn(private_id, str(listing))
            self.assertNotIn("PRIVATE_VIEWER_CAPABILITY", str(listing))
        # Observation alone must not change release/admission state: this
        # unmatched object could still be in an in-flight start or close.
        self.assertIs(self.manager._steel_engine.remote[private_id], orphan)
        self.assertFalse(self.manager._steel_engine._quarantined)
        self.assertFalse(self.guard.quarantined)
        self.assertEqual(self.manager.saved, [])

    async def test_bound_remote_is_healthy_but_extra_remote_is_reported(self):
        cap = await self.begin("TechnicalHealthy")
        owned = SimpleNamespace(remote_id="PRIVATE_OWNED_PROVIDER_ID")
        self.manager._sessions["INTERNAL_SYNTHETIC_SESSION_1"].browser = owned
        self.manager._steel_engine = SimpleNamespace(
            remote={owned.remote_id: owned}, _quarantined=False)
        self.assertEqual([x["state"] for x in self.guard.safe_sessions()], ["active"])
        self.manager._steel_engine.remote["PRIVATE_ORPHAN_PROVIDER_ID"] = object()
        listing = self.guard.safe_sessions()
        self.assertEqual([x["state"] for x in listing],
                         ["active", "provider_reconciliation_required"])
        self.assertNotIn("PRIVATE_OWNED_PROVIDER_ID", str(listing))
        self.assertNotIn("PRIVATE_ORPHAN_PROVIDER_ID", str(listing))
        self.assertNotIn(cap, str(listing))
        status = await self.mcp.call_tool("browser_status", {"session_id": cap})
        self.assertIn("TechnicalHealthy", str(status))

    async def test_engine_flag_does_not_duplicate_existing_recovery_row(self):
        await self.begin("TechnicalMissing")
        self.manager._sessions.clear()
        self.manager._steel_engine = SimpleNamespace(remote={}, _quarantined=True)
        listing = self.guard.safe_sessions()
        self.assertEqual([x["state"] for x in listing], ["missing_session_quarantined"])

    async def test_unknown_engine_inventory_is_not_an_idle_certificate(self):
        self.manager._steel_engine = SimpleNamespace(_quarantined=False)
        self.assertEqual(self.guard.safe_sessions()[0]["state"],
                         "provider_reconciliation_required")

    async def test_verified_empty_engine_and_manager_remain_empty(self):
        self.manager._steel_engine = SimpleNamespace(remote={}, _quarantined=False)
        self.assertEqual(self.guard.safe_sessions(), [])

    async def test_start_reports_guard_deadline_not_later_provider_deadline(self):
        self.guard.clock = lambda: 100
        async def start_with_late_deadline(**args):
            result = await self.manager.start(**args)
            result["remaining_seconds"] = 870
            return result
        result = await self.guard.start(start_with_late_deadline, {
            "profile": "TechnicalLifecycle", "mode": "read_only",
            "start_url": "https://example.com/"})
        self.assertEqual(result["remaining_seconds"], 780)
        self.assertEqual(870 - result["remaining_seconds"], 90)
        self.assertEqual(result["auto_save_close_in_seconds"], 780)
        self.assertEqual(result["capability_expires_in_seconds"], 850)
        self.assertIs(result["durable_resume_supported"], False)

    async def test_slow_start_keeps_save_margin_in_watchdog_and_diagnostics(self):
        self.guard.clock = lambda: 100
        result = await self.start_with_remaining("TechnicalSlowStart", 700)
        lease = self.guard.authorize(result["session_id"])
        self.assertEqual(result["remaining_seconds"], 610)
        self.assertEqual(result["auto_save_close_in_seconds"], 610)
        self.assertEqual(self.guard.close_deadlines[lease.internal_session_id], 710)

        # Later observations cannot turn a new upstream countdown into a
        # renewal. Both the public inventory and scheduled close use 710.
        self.guard.clock = lambda: 120
        async def renewed_upstream_status(session_id):
            return {"session_id": session_id, "remaining_seconds": 870}
        status = await self.guard.action("browser_status", renewed_upstream_status,
                                        {"session_id": result["session_id"]})
        self.assertEqual(status["auto_save_close_in_seconds"], 590)
        self.assertEqual(self.guard.safe_sessions()[0]["remaining_seconds"], 590)
        sleeps = []
        async def capture_sleep(seconds):
            sleeps.append(seconds)
        with patch("multi_capability_guard.asyncio.sleep", new=capture_sleep):
            await self.guard.watchdog(lease)
        self.assertEqual(sleeps, [590])
        self.assertEqual(self.manager.saved, [lease.internal_session_id])
        self.assertNotIn(lease.internal_session_id, self.guard.close_deadlines)
        self.assertEqual(self.guard.safe_sessions(), [])
        self.assertFalse(self.guard.quarantined)

    async def test_exhausted_start_saves_own_record_without_issuing_capability(self):
        existing = await self.begin("TechnicalOtherChat")
        prior_sid = self.guard.authorize(existing).internal_session_id
        for remaining in (90, 5, 0):
            with self.subTest(remaining=remaining):
                with self.assertRaisesRegex(OwnershipError, "START_SESSION_BUDGET_EXHAUSTED"):
                    await self.start_with_remaining("TechnicalExpiredStart", remaining)
                self.assertEqual(set(self.manager._sessions), {prior_sid})
                self.assertEqual(set(self.guard.leases), {prior_sid})
                self.assertFalse(self.guard.watchdogs)
                self.assertFalse(self.guard.start_cleanups)
                self.assertFalse(self.guard.quarantined)
        self.assertEqual(len(self.manager.saved), 3)
        self.assertNotIn(prior_sid, self.manager.saved)
        await self.begin("TechnicalAfterExhaustedStart")

    async def test_exhausted_start_with_failed_save_stays_quarantined(self):
        self.manager.broken_save = True
        with self.assertRaisesRegex(OwnershipError, "START_SESSION_BUDGET_EXHAUSTED"):
            await self.start_with_remaining("TechnicalUnsavedExpiredStart", 90)
        self.assertEqual(self.guard.leases, {})
        self.assertEqual(self.guard.close_deadlines, {})
        self.assertTrue(self.guard.quarantined)
        self.assertEqual([x["state"] for x in self.guard.safe_sessions()],
                         ["provider_reconciliation_required"])

    async def test_invalid_upstream_countdown_never_extends_default_budget(self):
        self.guard.clock = lambda: 100
        for remaining in (None, "700", True, float("nan"), float("inf"), 2000):
            with self.subTest(remaining=remaining):
                result = await self.start_with_remaining("TechnicalLegacyStart", remaining)
                lease = self.guard.authorize(result["session_id"])
                self.assertEqual(result["auto_save_close_in_seconds"], 780)
                self.assertEqual(self.guard.close_deadlines[lease.internal_session_id], 880)
                await self.mcp.call_tool("browser_stop", {"session_id": result["session_id"]})
                self.assertEqual(self.guard.close_deadlines, {})

    async def test_status_and_inventory_share_actual_countdown_without_renewal(self):
        self.guard.clock = lambda: 100
        cap = await self.begin("TechnicalCountdown")
        lease = self.guard.leases["INTERNAL_SYNTHETIC_SESSION_1"]
        self.guard.clock = lambda: 865  # 15 seconds until automatic saved-close
        async def upstream_status(session_id):
            return {"session_id": session_id, "remaining_seconds": 105}
        result = await self.guard.action("browser_status", upstream_status,
                                        {"session_id": cap})
        listing = self.guard.safe_sessions()[0]
        for observation in (result, listing):
            self.assertEqual(observation["remaining_seconds"], 15)
            self.assertEqual(observation["auto_save_close_in_seconds"], 15)
            self.assertEqual(observation["capability_expires_in_seconds"], 85)
            self.assertIs(observation["durable_resume_supported"], False)
        self.assertEqual(lease.started_at, 100)
        self.assertEqual(self.manager.saved, [])
        self.assertIn("INTERNAL_SYNTHETIC_SESSION_1", self.manager._sessions)

    async def test_lifecycle_never_extends_shorter_provider_deadline(self):
        cap = await self.begin("TechnicalShortProvider")
        async def upstream_status(session_id):
            return {"session_id": session_id, "remaining_seconds": 12}
        result = await self.guard.action("browser_status", upstream_status,
                                        {"session_id": cap})
        self.assertEqual(result["remaining_seconds"], 12)

    async def test_real_mcp_new_tab_status_keeps_original_guard_deadline(self):
        manager = MultiManager()
        mcp = fake_mcp(manager)
        now = [100.0]
        upstream_remaining = [785]

        async def new_tab(session_id):
            result = await manager.status(session_id)
            return {**result, "remaining_seconds": upstream_remaining[0],
                    "tab_count": 2}

        mcp._tool_manager._tools["browser_new_tab"].fn = new_tab
        guard = MultiCapabilityGuard(mcp, manager, capacity=5,
                                     clock=lambda: now[0], watchdog_enabled=False)
        guard.install()
        started = await mcp.call_tool("browser_start", {
            "profile": "TechnicalTabCountdown", "start_url": "https://example.com/"})
        initial = json.loads(started.content[0].text)
        cap = initial["session_id"]
        lease = guard.authorize(cap)
        self.assertEqual(initial["remaining_seconds"], 780)
        deadline = guard.close_deadlines[lease.internal_session_id]

        # Reproduces the live smoke: 85 seconds later a new tab returned the
        # provider's 785s instead of the guard's already-reduced 695s budget.
        for now[0], upstream_remaining[0], expected in (
                (185, 785, 695), (200, 870, 680), (210, 12, 12)):
            with self.subTest(now=now[0], upstream=upstream_remaining[0]):
                response = await mcp.call_tool("browser_new_tab", {"session_id": cap})
                result = json.loads(response.content[0].text)
                self.assertEqual(result["remaining_seconds"], expected)
                self.assertEqual(result["auto_save_close_in_seconds"], 880 - now[0])
                self.assertEqual(result["capability_expires_in_seconds"], 950 - now[0])
                self.assertIs(result["durable_resume_supported"], False)
                self.assertEqual(result["tab_count"], 2)
                self.assertEqual(result["session_id"], cap)
                self.assertEqual(guard.close_deadlines[lease.internal_session_id], deadline)
        self.assertEqual(lease.started_at, 100)
        self.assertEqual(manager.saved, [])

    async def test_ordinary_nonstatus_results_do_not_gain_lifecycle_fields(self):
        cap = await self.begin("TechnicalNonstatusResult")
        for output in ({"ok": True}, {"data": {"remaining_seconds": 15}},
                       [{"title": "Synthetic tab"}]):
            with self.subTest(output=output):
                async def operation(session_id):
                    self.manager._session(session_id)
                    return output
                result = await self.guard.action("browser_tabs", operation,
                                                {"session_id": cap})
                self.assertEqual(result, output)

    async def test_lifecycle_countdown_is_zero_after_watchdog_deadline(self):
        self.guard.clock = lambda: 100
        cap = await self.begin("TechnicalClosePending")
        self.guard.clock = lambda: 881
        result = await self.mcp.call_tool("browser_status", {"session_id": cap})
        self.assertIn("auto_save_close_in_seconds", str(result))
        self.assertEqual(self.guard.safe_sessions()[0]["remaining_seconds"], 0)
        self.assertEqual(self.guard.safe_sessions()[0]["capability_expires_in_seconds"], 69)
        self.assertEqual(self.manager.saved, [])

    async def test_one_writer_per_profile_even_if_slots_available(self):
        cap=await self.begin("Meta - Anita")
        with self.assertRaisesRegex(ToolError,"PARALLEL_PROFILE_BUSY"):
            await self.begin("Meta - Anita")
        other=await self.begin("Google - Architekt")
        self.assertNotEqual(cap,other)
        self.assertEqual(len(self.manager._sessions),2)

    async def test_two_real_mcp_callers_cannot_swap_sessions(self):
        one=await self.begin("Meta - Anita")
        two=await self.begin("Google - Architekt")
        a=await self.mcp.call_tool("browser_status",{"session_id":one})
        b=await self.mcp.call_tool("browser_status",{"session_id":two})
        self.assertIn("Meta - Anita",str(a))
        self.assertIn("Google - Architekt",str(b))
        self.assertNotIn("INTERNAL_SYNTHETIC_SESSION_",str(a)+str(b))
        with self.assertRaises(ToolError):
            await self.mcp.call_tool("browser_status",{
                "session_id":"INTERNAL_SYNTHETIC_SESSION_1"})
        with self.assertRaises(ToolError):
            await self.mcp.call_tool("browser_set_mode",{
                "session_id":"aib_"+"x"*43,"mode":"write"})
        self.assertEqual(self.manager._sessions[
            "INTERNAL_SYNTHETIC_SESSION_1"].mode,"read_only")

    async def test_actions_on_distinct_sessions_actually_overlap(self):
        entered=set()
        both=asyncio.Event()
        release=asyncio.Event()

        async def slow_snapshot(session_id, **kwargs):
            session=manager._session(session_id)
            entered.add(session.profile)
            if len(entered)==2:
                both.set()
            await release.wait()
            return {"session_id":session_id,"profile":session.profile}

        # Fresh real MCP server; replace the synthetic underlying snapshot
        # BEFORE installing the guard, preserving the original tool schema.
        manager=MultiManager()
        mcp=fake_mcp(manager)
        mcp._tool_manager._tools["browser_snapshot"].fn = slow_snapshot
        guard=MultiCapabilityGuard(mcp,manager,capacity=5,
                                   watchdog_enabled=False)
        guard.install()
        first=HANDLE_RE.search(str(await mcp.call_tool("browser_start",{
            "profile":"A","start_url":"https://example.com/"}))).group(0)
        second=HANDLE_RE.search(str(await mcp.call_tool("browser_start",{
            "profile":"B","start_url":"https://example.com/"}))).group(0)
        tasks=[asyncio.create_task(mcp.call_tool(
            "browser_snapshot",{"session_id":x})) for x in (first,second)]
        try:
            await asyncio.wait_for(both.wait(),1.5)
            self.assertEqual(entered,{"A","B"})
        finally:
            release.set()
            await asyncio.gather(*tasks)

    async def test_closed_tab_cannot_break_public_session_catalog(self):
        await self.begin("Meta - Anita")
        class ClosedPage:
            @property
            def url(self):
                raise RuntimeError("Page.title: Target closed")
        self.manager._sessions["INTERNAL_SYNTHETIC_SESSION_1"].page=ClosedPage()
        public=await self.mcp.call_tool("browser_sessions",{})
        self.assertIn("Meta - Anita",str(public))
        self.assertNotIn("Target closed",str(public))
        self.assertIsInstance(self.guard.safe_sessions(), list)

    async def test_audit_returns_list_without_other_chat_history(self):
        first=await self.begin("Meta - Anita")
        await self.begin("Google - Architekt")
        audit_tool=self.mcp._tool_manager._tools["browser_recent_audit"]
        self.assertIsInstance(await audit_tool.fn(session_id=first),list)
        self.assertEqual(await audit_tool.fn(session_id=first),[])
        result=await self.mcp.call_tool(
            "browser_recent_audit",{"session_id":first})
        self.assertNotIn("INTERNAL_SYNTHETIC_SESSION_",str(result))

    async def test_stop_one_keeps_another_and_frees_capacity(self):
        first=await self.begin("Meta - Anita")
        second=await self.begin("Google - Architekt")
        receipt=await self.mcp.call_tool("browser_stop",{"session_id":first})
        self.assertIn("full_profile_saved",str(receipt))
        self.assertEqual(len(self.manager._sessions),1)
        alive=await self.mcp.call_tool("browser_status",{"session_id":second})
        self.assertIn("Google - Architekt",str(alive))
        next_cap=await self.begin("WordPress - Anita")
        self.assertNotEqual(first,next_cap)
        self.assertEqual(len(self.manager._sessions),2)
        with self.assertRaises(ToolError):
            await self.mcp.call_tool("browser_status",{"session_id":first})

    async def test_inventory_during_successful_stop_does_not_quarantine(self):
        cap = await self.begin("TechnicalClosing")
        await self.begin("TechnicalOtherChat")
        remote = SimpleNamespace(remote_id="PRIVATE_CLOSING_PROVIDER_ID")
        self.manager._sessions["INTERNAL_SYNTHETIC_SESSION_1"].browser = remote
        self.manager._steel_engine = SimpleNamespace(
            remote={remote.remote_id: remote}, _quarantined=False)
        entered, allow_remove = asyncio.Event(), asyncio.Event()
        removed, allow_receipt = asyncio.Event(), asyncio.Event()

        async def staged_stop(session_id):
            self.manager._session(session_id)
            entered.set()
            await allow_remove.wait()
            self.manager._sessions.pop(session_id)
            removed.set()
            # Production awaits profile READY and the registry acknowledgement
            # here, after the browser record has already been removed.
            await allow_receipt.wait()
            self.manager._steel_engine.remote.pop(remote.remote_id)
            return {"session_id": session_id, "profile_saved": True,
                    "full_profile_saved": True}

        task = asyncio.create_task(self.guard.action(
            "browser_stop", staged_stop, {"session_id": cap}))
        try:
            await asyncio.wait_for(entered.wait(), 1.5)
            self.assertEqual([x["state"] for x in self.guard.safe_sessions()],
                             ["closing", "active"])
            self.assertFalse(self.guard.quarantined)
            allow_remove.set()
            await asyncio.wait_for(removed.wait(), 1.5)
            rows = self.guard.safe_sessions()
            self.assertEqual([x["state"] for x in rows], ["active", "closing"])
            self.assertNotIn(remote.remote_id, str(rows))
            self.assertFalse(self.guard.quarantined)
            # Closing still reserves its profile and slot, while another
            # independent chat may use capacity that was already available.
            with self.assertRaisesRegex(ToolError, "PARALLEL_PROFILE_BUSY"):
                await self.begin("TechnicalClosing")
            await self.begin("TechnicalThirdChat")
        finally:
            allow_remove.set()
            allow_receipt.set()
            await task
        self.assertFalse(self.guard.quarantined)
        self.assertEqual([x["profile"] for x in self.guard.safe_sessions()],
                         ["TechnicalOtherChat", "TechnicalThirdChat"])
        await self.begin("TechnicalNextChat")

    async def test_inventory_during_failed_save_receipt_keeps_quarantine(self):
        lease, task, allow_remove, removed, allow_receipt = await self.paused_stop("false")
        try:
            await self.observe_paused_close(lease, allow_remove, removed)
        finally:
            allow_remove.set()
            allow_receipt.set()
            result = await task
        self.assertIs(result["full_profile_saved"], False)
        await self.assert_failed_close_retains_lease(lease)

    async def test_inventory_during_stop_exception_keeps_quarantine(self):
        lease, task, allow_remove, removed, allow_receipt = await self.paused_stop("raise")
        try:
            await self.observe_paused_close(lease, allow_remove, removed)
        finally:
            allow_remove.set()
            allow_receipt.set()
            with self.assertRaisesRegex(RuntimeError, "SYNTHETIC_PERSISTENCE_ERROR"):
                await task
        await self.assert_failed_close_retains_lease(lease)

    async def test_cancelled_close_after_record_removal_finishes_saved_receipt(self):
        lease, task, allow_remove, removed, allow_receipt = await self.paused_stop()
        try:
            await self.observe_paused_close(lease, allow_remove, removed)
            task.cancel()
            await asyncio.sleep(0)
            self.assertFalse(task.done())
            self.assertFalse(self.guard.quarantined)
            self.assertFalse(lease.recovery_required)
            self.assertEqual([x["state"] for x in self.guard.safe_sessions()],
                             ["closing"])
            self.assertIn(lease.internal_session_id, self.guard.close_tasks)
            self.assertTrue(self.guard.session_locks[lease.internal_session_id].locked())
        finally:
            allow_remove.set()
            allow_receipt.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
        await asyncio.sleep(0)
        self.assertEqual(self.guard.safe_sessions(), [])
        self.assertFalse(self.guard.quarantined)
        self.assertEqual(self.guard.close_tasks, {})
        self.assertEqual(self.guard.cleanup_tasks, set())
        await self.begin("TechnicalAfterCancelledSavedClose")

    async def test_repeated_close_cancellation_preserves_own_record_and_other_chat(self):
        other = await self.begin("TechnicalOtherChat")
        other_sid = self.guard.authorize(other).internal_session_id
        other_record = self.manager._sessions[other_sid]
        lease, task, allow_remove, removed, allow_receipt = await self.paused_stop()
        sid = lease.internal_session_id
        record = self.manager._sessions[sid]
        try:
            for after_removal in (False, True):
                if after_removal:
                    allow_remove.set()
                    await asyncio.wait_for(removed.wait(), 1.5)
                for _ in range(2):
                    task.cancel()
                    await asyncio.sleep(0)
                self.assertFalse(task.done())
                self.assertTrue(self.guard.session_locks[sid].locked())
                self.assertIs(self.guard.closing[sid], record)
                self.assertIs(self.guard.leases[sid], lease)
                self.assertEqual(len(self.guard.close_tasks), 1)
                self.assertEqual(len(self.guard.cleanup_tasks), 1)
                self.assertFalse(self.guard.quarantined)
                self.assertEqual([x["state"] for x in self.guard.safe_sessions()],
                                 ["active", "closing"])
                result = await self.mcp.call_tool("browser_status", {"session_id": other})
                self.assertIn("TechnicalOtherChat", str(result))
                self.assertIs(self.manager._sessions[other_sid], other_record)
                with self.assertRaisesRegex(ToolError, "PARALLEL_PROFILE_BUSY"):
                    await self.begin(lease.profile)
            await self.begin("TechnicalThirdChatDuringCancelledClose")
        finally:
            allow_remove.set()
            allow_receipt.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertNotIn(sid, self.guard.leases)
        self.assertIs(self.manager._sessions[other_sid], other_record)
        self.assertEqual(self.guard.close_tasks, {})
        self.assertFalse(self.guard.quarantined)
        await self.begin(lease.profile)

    async def test_cancelled_close_with_false_receipt_still_quarantines(self):
        lease, task, allow_remove, removed, allow_receipt = await self.paused_stop("false")
        try:
            await self.observe_paused_close(lease, allow_remove, removed)
            task.cancel()
            await asyncio.sleep(0)
            self.assertFalse(task.done())
            self.assertFalse(self.guard.quarantined)
        finally:
            allow_remove.set()
            allow_receipt.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
        await self.assert_failed_close_retains_lease(lease)

    async def test_cancelled_close_with_failed_receipt_still_quarantines(self):
        lease, task, allow_remove, removed, allow_receipt = await self.paused_stop("raise")
        try:
            await self.observe_paused_close(lease, allow_remove, removed)
            task.cancel()
            await asyncio.sleep(0)
            self.assertFalse(task.done())
        finally:
            allow_remove.set()
            allow_receipt.set()
            with self.assertRaisesRegex(RuntimeError, "SYNTHETIC_PERSISTENCE_ERROR"):
                await task
        await self.assert_failed_close_retains_lease(lease)

    async def test_close_timeout_tracks_finalizer_and_never_clears_uncertainty(self):
        other = await self.begin("TechnicalOtherChat")
        cap = await self.begin("TechnicalSlowClose")
        lease = self.guard.authorize(cap)
        sid = lease.internal_session_id
        removed, cancelled, finish = asyncio.Event(), asyncio.Event(), asyncio.Event()
        stop_calls = []

        async def delayed_receipt(session_id):
            self.assertEqual(self.guard.actor_session.get(), session_id)
            stop_calls.append(session_id)
            self.manager._session(session_id)
            self.manager._sessions.pop(session_id)
            removed.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                await finish.wait()
                return {"session_id": session_id, "profile_saved": True,
                        "full_profile_saved": True}

        with patch("multi_capability_guard.SAVED_CLOSE_TIMEOUT_SECONDS", .03):
            task = asyncio.create_task(self.guard.action(
                "browser_stop", delayed_receipt, {"session_id": cap}))
            try:
                await asyncio.wait_for(removed.wait(), 1.5)
                with self.assertRaisesRegex(OwnershipError, "SESSION_CLOSE_TIMEOUT"):
                    await asyncio.wait_for(task, 1.5)
                await asyncio.wait_for(cancelled.wait(), 1.5)
                self.assertTrue(self.guard.quarantined)
                self.assertTrue(lease.recovery_required)
                self.assertEqual(len(self.guard.close_tasks), 1)
                self.assertEqual(len(self.guard.cleanup_tasks), 1)
                self.assertIn(sid, self.guard.leases)
                for name in ("browser_stop", "profile_flush"):
                    with self.assertRaisesRegex(OwnershipError, "SESSION_CLOSE_IN_PROGRESS"):
                        await self.guard.action(name, delayed_receipt, {"session_id": cap})
                self.assertEqual(stop_calls, [sid])
                with self.assertRaisesRegex(ToolError, "PARALLEL_PROVIDER_RECONCILIATION_REQUIRED"):
                    await self.begin("TechnicalBlockedByCloseTimeout")
                self.assertIn("TechnicalOtherChat", str(await self.mcp.call_tool(
                    "browser_status", {"session_id": other})))
            finally:
                finish.set()
                await asyncio.gather(*tuple(self.guard.cleanup_tasks), return_exceptions=True)
                await asyncio.gather(task, return_exceptions=True)
        self.assertEqual(self.guard.close_tasks, {})
        self.assertEqual(self.guard.cleanup_tasks, set())
        self.assertEqual(stop_calls, [sid])
        self.assertTrue(self.guard.quarantined)
        self.assertTrue(lease.recovery_required)
        self.assertIs(self.guard.leases[sid], lease)
        self.assertEqual([x["state"] for x in self.guard.safe_sessions()],
                         ["active", "missing_session_quarantined"])
        with self.assertRaisesRegex(ToolError, "PARALLEL_PROVIDER_RECONCILIATION_REQUIRED"):
            await self.begin("TechnicalBlockedAfterLateReceipt")

    async def test_real_mcp_cancelled_stop_completes_exact_save_once(self):
        cap = await self.begin("TechnicalMcpCancelledClose")
        lease = self.guard.authorize(cap)
        entered, finish = asyncio.Event(), asyncio.Event()
        original_stop = self.manager.stop

        async def paused_stop(sid):
            result = await original_stop(sid)
            entered.set()
            await finish.wait()
            return result

        with patch.object(self.manager, "stop", new=paused_stop):
            task = asyncio.create_task(self.mcp.call_tool(
                "browser_stop", {"session_id": cap}))
            try:
                await asyncio.wait_for(entered.wait(), 1.5)
                task.cancel()
                await asyncio.sleep(0)
                self.assertFalse(task.done())
                self.assertEqual([x["state"] for x in self.guard.safe_sessions()],
                                 ["closing"])
            finally:
                finish.set()
                with self.assertRaises(asyncio.CancelledError):
                    await task
        self.assertEqual(self.manager.saved, [lease.internal_session_id])
        self.assertEqual(self.guard.safe_sessions(), [])
        self.assertFalse(self.guard.quarantined)

    async def test_late_receipt_after_event_loop_stall_cannot_release_timed_out_lease(self):
        cap = await self.begin("TechnicalLateCloseReceipt")
        lease = self.guard.authorize(cap)
        sid = lease.internal_session_id
        finish = asyncio.Event()
        received = []
        loop = asyncio.get_running_loop()

        async def saved_stop(session_id):
            await finish.wait()
            self.manager._sessions.pop(session_id)
            received.append(session_id)
            return {"session_id": session_id, "profile_saved": True,
                    "full_profile_saved": True}

        # Make both the receipt and timeout callbacks ready in one loop turn.
        # Previously wait_for raised TimeoutError, but its next while test saw
        # a done finalizer that had already freed the slot after the deadline.
        stall = loop.call_later(.01, time.sleep, .06)
        release = loop.call_later(.02, finish.set)
        try:
            with patch("multi_capability_guard.SAVED_CLOSE_TIMEOUT_SECONDS", .03):
                with self.assertRaisesRegex(OwnershipError, "SESSION_CLOSE_TIMEOUT"):
                    await self.guard.action("browser_stop", saved_stop,
                                            {"session_id": cap})
        finally:
            stall.cancel()
            release.cancel()
            finish.set()
            await asyncio.gather(*tuple(self.guard.cleanup_tasks), return_exceptions=True)
        self.assertEqual(received, [sid])
        await self.assert_failed_close_retains_lease(lease)

    async def test_early_receipt_stays_valid_when_only_the_caller_is_delayed(self):
        cap = await self.begin("TechnicalEarlyCloseReceipt")
        lease = self.guard.authorize(cap)
        sid = lease.internal_session_id
        loop = asyncio.get_running_loop()
        stall = None

        async def saved_stop(session_id):
            nonlocal stall
            self.manager._sessions.pop(session_id)
            # The finalizer can synchronously confirm this receipt before the
            # following callback stalls delivery to its awaiting caller.
            stall = loop.call_soon(time.sleep, .06)
            return {"session_id": session_id, "profile_saved": True,
                    "full_profile_saved": True}

        began = loop.time()
        try:
            with patch("multi_capability_guard.SAVED_CLOSE_TIMEOUT_SECONDS", .03):
                result = await self.guard.action("browser_stop", saved_stop,
                                                {"session_id": cap})
        finally:
            if stall is not None:
                stall.cancel()
        self.assertGreater(loop.time() - began, .03)
        self.assertTrue(result["full_profile_saved"])
        self.assertNotIn(sid, self.guard.leases)
        self.assertEqual(self.guard.safe_sessions(), [])
        self.assertFalse(self.guard.quarantined)

    async def test_close_finalizer_does_not_stop_a_replacement_record(self):
        cap = await self.begin("TechnicalReplacedClose")
        lease = self.guard.authorize(cap)
        sid = lease.internal_session_id
        replacement = SimpleNamespace(profile=lease.profile, mode="read_only")
        calls = []
        async def stop(session_id):
            calls.append(session_id)
            return await self.manager.stop(session_id)
        # This callback runs after the action captures its exact record, before
        # the new finalizer task gets its first event-loop turn.
        asyncio.get_running_loop().call_soon(
            self.manager._sessions.__setitem__, sid, replacement)
        with self.assertRaisesRegex(OwnershipError, "SESSION_CHANGED"):
            await self.guard.action("browser_stop", stop, {"session_id": cap})
        self.assertEqual(calls, [])
        self.assertEqual(self.manager.saved, [])
        self.assertIs(self.manager._sessions[sid], replacement)
        self.assertTrue(self.guard.quarantined)
        self.assertTrue(lease.recovery_required)

    async def test_cancelled_queued_close_does_not_start_or_quarantine(self):
        cap = await self.begin("TechnicalQueuedClose")
        lease = self.guard.authorize(cap)
        lock = self.guard.session_locks[lease.internal_session_id]
        async with lock:
            task = asyncio.create_task(self.guard.action(
                "browser_stop", self.manager.stop, {"session_id": cap}))
            await asyncio.sleep(0)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(self.manager.saved, [])
        self.assertEqual(self.guard.close_tasks, {})
        self.assertEqual(self.guard.closing, {})
        self.assertFalse(self.guard.quarantined)
        self.assertEqual([x["state"] for x in self.guard.safe_sessions()], ["active"])

    async def test_inventory_during_watchdog_close_waits_for_full_receipt(self):
        lease, task, allow_remove, removed, allow_receipt = await self.paused_stop(
            watchdog=True)
        try:
            await self.observe_paused_close(lease, allow_remove, removed)
        finally:
            allow_remove.set()
            allow_receipt.set()
            await task
        self.assertEqual(self.guard.safe_sessions(), [])
        self.assertFalse(self.guard.quarantined)
        await self.begin("TechnicalAfterWatchdog")

    async def test_failed_watchdog_receipt_after_inventory_still_blocks(self):
        lease, task, allow_remove, removed, allow_receipt = await self.paused_stop(
            "false", watchdog=True)
        try:
            await self.observe_paused_close(lease, allow_remove, removed)
        finally:
            allow_remove.set()
            allow_receipt.set()
            await task
        await self.assert_failed_close_retains_lease(lease)

    async def test_successful_close_does_not_clear_preexisting_quarantine(self):
        lease, task, allow_remove, removed, allow_receipt = await self.paused_stop()
        try:
            await self.observe_paused_close(lease, allow_remove, removed)
            self.guard.quarantined = True
        finally:
            allow_remove.set()
            allow_receipt.set()
            await task
        self.assertNotIn(lease.internal_session_id, self.guard.leases)
        self.assertTrue(self.guard.quarantined)
        self.assertEqual([x["state"] for x in self.guard.safe_sessions()],
                         ["provider_reconciliation_required"])

    async def test_closing_phase_does_not_hide_provider_quarantine_or_orphan(self):
        lease, task, allow_remove, removed, allow_receipt = await self.paused_stop()
        try:
            await self.observe_paused_close(lease, allow_remove, removed)
            engine = SimpleNamespace(remote={}, _quarantined=True)
            self.manager._steel_engine = engine
            self.assertEqual([x["state"] for x in self.guard.safe_sessions()],
                             ["closing", "provider_reconciliation_required"])
            engine._quarantined = False  # synthetic test case, never production
            engine.remote["PRIVATE_UNRELATED_PROVIDER_ID"] = object()
            rows = self.guard.safe_sessions()
            self.assertEqual([x["state"] for x in rows],
                             ["closing", "provider_reconciliation_required"])
            self.assertNotIn("PRIVATE_UNRELATED_PROVIDER_ID", str(rows))
        finally:
            allow_remove.set()
            allow_receipt.set()
            await task
        self.assertIn("PRIVATE_UNRELATED_PROVIDER_ID", engine.remote)
        self.assertEqual([x["state"] for x in self.guard.safe_sessions()],
                         ["provider_reconciliation_required"])

    async def test_inventory_during_successful_start_does_not_quarantine(self):
        task, allow_register, registered, allow_result = await self.paused_start()
        try:
            self.assertEqual(self.manager._sessions, {})
            self.assertEqual([x["state"] for x in self.guard.safe_sessions()],
                             ["starting"])
            allow_register.set()
            await asyncio.wait_for(registered.wait(), 1.5)
            rows = self.guard.safe_sessions()
            self.assertEqual([x["state"] for x in rows], ["starting"])
            self.assertNotIn("INTERNAL_SYNTHETIC", str(rows))
            self.assertEqual(self.guard.leases, {})
            self.assertFalse(self.guard.quarantined)
        finally:
            allow_register.set()
            allow_result.set()
            result = await task
        self.assertFalse(self.guard.quarantined)
        self.assertIsNone(self.guard.starting)
        self.assertEqual([x["state"] for x in self.guard.safe_sessions()], ["active"])
        self.guard.authorize(result["session_id"])
        await self.begin("TechnicalNextChat")

    async def test_failed_start_saves_its_new_record_and_preserves_original_error(self):
        task, allow_register, registered, allow_result = await self.paused_start(outcome="raise")
        try:
            allow_register.set()
            await asyncio.wait_for(registered.wait(), 1.5)
            self.assertEqual([x["state"] for x in self.guard.safe_sessions()], ["starting"])
            self.assertFalse(self.guard.quarantined)
        finally:
            allow_register.set()
            allow_result.set()
            with self.assertRaisesRegex(RuntimeError, "SYNTHETIC_START_ERROR"):
                await task
        self.assertIsNone(self.guard.starting)
        self.assertFalse(self.guard.quarantined)
        self.assertEqual(self.guard.safe_sessions(), [])
        self.assertEqual(self.guard.leases, {})
        self.assertEqual(self.manager.saved, ["INTERNAL_SYNTHETIC_SESSION_1"])
        await self.begin("TechnicalAfterFailedStart")

    async def test_cancelled_start_saves_only_its_new_record_and_frees_own_slot(self):
        previous = await self.begin("TechnicalOtherChat")
        prior_sid = self.guard.authorize(previous).internal_session_id
        prior_record = self.manager._sessions[prior_sid]
        task, allow_register, registered, allow_result = await self.paused_start()
        try:
            allow_register.set()
            await asyncio.wait_for(registered.wait(), 1.5)
            self.assertEqual([x["state"] for x in self.guard.safe_sessions()],
                             ["active", "starting"])
        finally:
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertIsNone(self.guard.starting)
        self.assertFalse(self.guard.quarantined)
        self.assertEqual(set(self.guard.leases), {prior_sid})
        self.assertEqual(set(self.manager._sessions), {prior_sid})
        self.assertIs(self.manager._sessions[prior_sid], prior_record)
        self.assertEqual(self.manager.saved, ["INTERNAL_SYNTHETIC_SESSION_2"])
        self.assertFalse(self.guard.watchdogs)
        self.assertFalse(self.guard.start_cleanups)
        self.guard.authorize(previous)
        await self.begin("TechnicalStarting")

    async def test_interrupted_start_with_false_save_receipt_remains_quarantined(self):
        self.manager.broken_save = True
        task, allow_register, registered, _ = await self.paused_start()
        allow_register.set()
        await asyncio.wait_for(registered.wait(), 1.5)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(self.guard.quarantined)
        self.assertEqual([x["state"] for x in self.guard.safe_sessions()],
                         ["provider_reconciliation_required"])
        self.assertEqual(self.guard.leases, {})
        with self.assertRaisesRegex(ToolError, "PARALLEL_PROVIDER_RECONCILIATION_REQUIRED"):
            await self.begin("TechnicalBlockedAfterStart")

    async def test_interrupted_start_cleanup_exception_keeps_record_visible(self):
        async def failed_stop(sid):
            self.assertEqual(self.guard.actor_session.get(), sid)
            self.manager._session(sid)
            raise RuntimeError("SYNTHETIC_CLEANUP_ERROR")
        with patch.object(self.manager, "stop", new=failed_stop):
            task, allow_register, registered, _ = await self.paused_start()
            allow_register.set()
            await asyncio.wait_for(registered.wait(), 1.5)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertTrue(self.guard.quarantined)
        self.assertEqual([x["state"] for x in self.guard.safe_sessions()],
                         ["unmanaged_quarantined"])
        self.assertEqual(self.manager.saved, [])

    async def test_second_cancellation_keeps_cleanup_owned_until_full_receipt(self):
        previous = await self.begin("TechnicalOtherChat")
        prior_sid = self.guard.authorize(previous).internal_session_id
        entered, allow_remove = asyncio.Event(), asyncio.Event()
        removed, allow_receipt = asyncio.Event(), asyncio.Event()
        original_stop = self.manager.stop

        async def paused_cleanup(sid):
            self.assertEqual(self.guard.actor_session.get(), sid)
            self.manager._session(sid)
            entered.set()
            await allow_remove.wait()
            receipt = await original_stop(sid)
            removed.set()
            await allow_receipt.wait()
            return receipt

        with patch.object(self.manager, "stop", new=paused_cleanup):
            task, allow_register, registered, _ = await self.paused_start()
            try:
                allow_register.set()
                await asyncio.wait_for(registered.wait(), 1.5)
                task.cancel()
                await asyncio.wait_for(entered.wait(), 1.5)
                for after_removal in (False, True):
                    if after_removal:
                        allow_remove.set()
                        await asyncio.wait_for(removed.wait(), 1.5)
                        task.cancel()  # Cancellation of the same request again.
                        await asyncio.sleep(0)
                    self.assertFalse(task.done())
                    self.assertTrue(self.guard.admission.locked())
                    self.assertEqual(len(self.guard.cleanup_tasks), 1)
                    self.assertEqual(len(self.guard.start_cleanups), 1)
                    self.assertEqual([x["state"] for x in self.guard.safe_sessions()],
                                     ["active", "closing"])
                    self.assertFalse(self.guard.quarantined)
                    self.assertIn(prior_sid, self.manager._sessions)
            finally:
                allow_register.set()
                allow_remove.set()
                allow_receipt.set()
                with self.assertRaises(asyncio.CancelledError):
                    await task
        await asyncio.sleep(0)
        self.assertEqual(self.guard.start_cleanups, {})
        self.assertEqual(self.guard.cleanup_tasks, set())
        self.assertEqual(self.guard.closing, {})
        self.assertEqual(set(self.manager._sessions), {prior_sid})
        self.assertEqual(self.manager.saved, ["INTERNAL_SYNTHETIC_SESSION_2"])
        self.assertFalse(self.guard.quarantined)
        await self.begin("TechnicalAfterTwiceCancelledStart")

    async def test_cleanup_timeout_tracks_pending_finalizer_and_blocks_admission(self):
        entered, cancelled, finish = asyncio.Event(), asyncio.Event(), asyncio.Event()
        original_stop = self.manager.stop

        async def delayed_cleanup(sid):
            self.assertEqual(self.guard.actor_session.get(), sid)
            receipt = await original_stop(sid)
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                await finish.wait()
                # Even a late complete receipt must not clear the flag set
                # when the bounded caller could not establish completion.
                return receipt

        with patch.object(self.manager, "stop", new=delayed_cleanup), patch(
                "multi_capability_guard.START_CLEANUP_TIMEOUT_SECONDS", .03):
            task, allow_register, registered, _ = await self.paused_start()
            try:
                allow_register.set()
                await asyncio.wait_for(registered.wait(), 1.5)
                task.cancel()
                await asyncio.wait_for(entered.wait(), 1.5)
                with self.assertRaises(asyncio.CancelledError):
                    await asyncio.wait_for(asyncio.shield(task), 1.5)
                await asyncio.wait_for(cancelled.wait(), 1.5)
                self.assertTrue(self.guard.quarantined)
                self.assertEqual(self.guard.leases, {})
                self.assertEqual(self.manager._sessions, {})
                self.assertEqual(len(self.guard.cleanup_tasks), 1)
                self.assertEqual(len(self.guard.start_cleanups), 1)
                self.assertEqual([x["state"] for x in self.guard.safe_sessions()],
                                 ["recovery_required"])
                with self.assertRaisesRegex(ToolError, "PARALLEL_PROVIDER_RECONCILIATION_REQUIRED"):
                    await self.begin("TechnicalBlockedDuringFinalizer")
            finally:
                finish.set()
                await asyncio.gather(*tuple(self.guard.cleanup_tasks), return_exceptions=True)
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        self.assertEqual(self.guard.cleanup_tasks, set())
        self.assertEqual(self.guard.start_cleanups, {})
        self.assertTrue(self.guard.quarantined)
        self.assertEqual([x["state"] for x in self.guard.safe_sessions()],
                         ["provider_reconciliation_required"])

    async def test_cleanup_does_not_stop_a_same_id_replacement_object(self):
        replacements = []
        async def replaced_start(**args):
            result = await self.manager.start(**args)
            replacement = SimpleNamespace(profile=args["profile"], mode="read_only")
            replacements.append(replacement)
            # This runs after cleanup captures the original object but before
            # its shielded task can execute manager.stop.
            asyncio.get_running_loop().call_soon(
                self.manager._sessions.__setitem__, result["session_id"], replacement)
            raise RuntimeError("SYNTHETIC_START_ERROR")
        with self.assertRaisesRegex(RuntimeError, "SYNTHETIC_START_ERROR"):
            await self.guard.start(replaced_start, {"profile": "TechnicalReplacement"})
        self.assertIs(self.manager._sessions["INTERNAL_SYNTHETIC_SESSION_1"], replacements[0])
        self.assertEqual(self.manager.saved, [])
        self.assertTrue(self.guard.quarantined)

    async def test_cleanup_does_not_stop_an_ambiguous_delta_or_wrong_profile(self):
        for unexpected in ("extra_record", "wrong_profile"):
            with self.subTest(unexpected=unexpected):
                manager = MultiManager()
                guard = MultiCapabilityGuard(fake_mcp(manager), manager,
                                             capacity=5, watchdog_enabled=False)
                guard.install()
                async def failed_start(**args):
                    result = await manager.start(**args)
                    if unexpected == "extra_record":
                        await manager.start(**args)
                    else:
                        manager._sessions[result["session_id"]].profile = "PRIVATE_UNEXPECTED"
                    raise RuntimeError("SYNTHETIC_START_ERROR")
                with self.assertRaisesRegex(RuntimeError, "SYNTHETIC_START_ERROR"):
                    await guard.start(failed_start, {"profile": "TechnicalAmbiguous"})
                self.assertTrue(guard.quarantined)
                self.assertTrue(manager._sessions)
                self.assertEqual(manager.saved, [])
                self.assertEqual(guard.leases, {})

    async def test_successful_start_cleanup_does_not_clear_existing_quarantine(self):
        task, allow_register, registered, _ = await self.paused_start()
        allow_register.set()
        await asyncio.wait_for(registered.wait(), 1.5)
        self.guard.quarantined = True
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(self.manager._sessions, {})
        self.assertEqual(self.manager.saved, ["INTERNAL_SYNTHETIC_SESSION_1"])
        self.assertTrue(self.guard.quarantined)

    async def test_start_phase_does_not_adopt_an_unexpected_profile(self):
        task, allow_register, registered, allow_result = await self.paused_start(corrupt_profile=True)
        try:
            allow_register.set()
            await asyncio.wait_for(registered.wait(), 1.5)
            rows = self.guard.safe_sessions()
            self.assertIn("unmanaged_quarantined", [x["state"] for x in rows])
            self.assertNotIn("PRIVATE_UNEXPECTED_PROFILE", str(rows))
            self.assertTrue(self.guard.quarantined)
        finally:
            allow_register.set()
            allow_result.set()
            with self.assertRaisesRegex(OwnershipError, "PARALLEL_START_NOT_VERIFIED"):
                await task
        self.assertIsNone(self.guard.starting)
        self.assertEqual(self.guard.leases, {})
        self.assertEqual(self.manager.saved, [])

    async def test_original_sync_inventory_runs_on_guard_event_loop(self):
        manager = MultiManager()
        mcp = fake_mcp(manager)
        tool = mcp._tool_manager._tools["browser_sessions"]
        schema = tool.parameters.copy()
        tool.is_async = False
        tool.fn = lambda: []
        guard = MultiCapabilityGuard(mcp, manager, capacity=5, watchdog_enabled=False)
        guard.install()
        self.assertTrue(tool.is_async)
        self.assertEqual(tool.parameters, schema)
        self.assertEqual(await tool.fn(), [])
        await mcp.call_tool("browser_sessions", {})

    async def test_failed_full_profile_save_quarantines_all_new_starts(self):
        first=await self.begin("Meta - Anita")
        other=await self.begin("Google - Architekt")
        self.manager.broken_save=True
        await self.mcp.call_tool("browser_stop",{"session_id":first})
        with self.assertRaisesRegex(
            ToolError,"PARALLEL_PROVIDER_RECONCILIATION_REQUIRED"):
            await self.begin("WordPress - Anita")
        # Other session may still be used and cleanly stopped.
        result=await self.mcp.call_tool("browser_status",{"session_id":other})
        self.assertIn("Google - Architekt",str(result))

    async def test_broken_start_inventory_redacts_unmanaged_session(self):
        owned = await self.begin("Owner-Technical")
        class ClosedPage:
            @property
            def url(self):
                raise RuntimeError("PRIVATE_CLOSED_PAGE_URL")
        self.manager._sessions["SENSITIVE_PROVIDER_ID"] = SimpleNamespace(
            profile="PRIVATE_ACCOUNT_NAME",
            mode="write",
            page=ClosedPage(),
        )
        catalog = self.guard.safe_sessions()
        self.assertEqual(len(catalog), 2)
        self.assertTrue(self.guard.quarantined)
        self.assertEqual(catalog[0]["state"], "active")
        self.assertEqual(catalog[1], {
            "session_id": "[redacted]",
            "profile": "[redacted]",
            "mode": "unknown",
            "state": "unmanaged_quarantined",
        })
        via_mcp = str(await self.mcp.call_tool("browser_sessions", {}))
        for private in ("SENSITIVE_PROVIDER_ID", "PRIVATE_ACCOUNT_NAME",
                        "PRIVATE_CLOSED_PAGE_URL", owned):
            self.assertNotIn(private, via_mcp)
        with self.assertRaisesRegex(
                ToolError, "UNMANAGED_SESSION_QUARANTINED"):
            await self.begin("Another-Technical")
        # Read-only inspection does not adopt, stop, or erase the orphan.
        self.assertIn("SENSITIVE_PROVIDER_ID", self.manager._sessions)

    async def test_unmanaged_session_fails_closed_not_adopted(self):
        self.manager._sessions["FOREIGN_SESSION"]=SimpleNamespace(
            profile="OTHER",mode="write",page=SimpleNamespace(url="about:blank"))
        with self.assertRaisesRegex(
            ToolError,"UNMANAGED_SESSION_QUARANTINED"):
            await self.begin("Meta - Anita")
        self.assertEqual(self.manager.counter,0)

    async def test_manager_bypass_and_unscoped_old_tools_disabled(self):
        await self.begin("Meta - Anita")
        with self.assertRaisesRegex(
            OwnershipError,"DIRECT_SESSION_START_BLOCKED"):
            await self.manager.start("OTHER")
        with self.assertRaisesRegex(
            OwnershipError,"DIRECT_SESSION_ACCESS_BLOCKED"):
            self.manager._session("INTERNAL_SYNTHETIC_SESSION_1")
        # The new setup endpoint only accepts the exact Facebook login
        # surface; it must not run arbitrary destinations.
        with self.assertRaisesRegex(
            ToolError,"MOBILE_LOGIN_ORIGIN_NOT_ALLOWED"):
            await self.mcp.call_tool("profile_start_setup",{
                "profile":"OTHER","login_url":"https://example.com/"})
        # The unscoped legacy setup endpoint is still HTTP 403, and
        # deletion/unowned operations remain disabled.
        with self.assertRaisesRegex(
            ToolError,"PARALLEL_UNSCOPED_TOOL_DISABLED"):
            await self.mcp.call_tool("profile_delete",{
                "profile":"OTHER","confirmation":"DELETE"})

    async def test_watchdog_closes_orphaned_own_session_without_other_chat(self):
        # An agent can lose its opaque capability when a tool invocation
        # aborts. The watchdog must save/close its own browser independently.
        one=await self.begin("CloudSelfTest")
        two=await self.begin("RepairSelfTest")
        lease=self.guard.leases["INTERNAL_SYNTHETIC_SESSION_1"]
        async def short_sleep(_seconds):
            return None
        with patch("multi_capability_guard.asyncio.sleep",new=short_sleep):
            await self.guard.watchdog(lease)
        self.assertNotIn("INTERNAL_SYNTHETIC_SESSION_1",
                         self.manager._sessions)
        self.assertIn("INTERNAL_SYNTHETIC_SESSION_1",self.manager.saved)
        self.assertIn("INTERNAL_SYNTHETIC_SESSION_2",
                      self.manager._sessions)
        self.assertFalse(self.guard.quarantined)
        result=await self.mcp.call_tool(
            "browser_status",{"session_id":two})
        self.assertIn("RepairSelfTest",str(result))
        with self.assertRaises(ToolError):
            await self.mcp.call_tool(
                "browser_status",{"session_id":one})
        new=await self.begin("ParallelSelfTest03")
        self.assertNotEqual(one,new)

    async def test_watchdog_does_not_free_slot_after_failed_save(self):
        first=await self.begin("CloudSelfTest")
        second=await self.begin("RepairSelfTest")
        self.manager.broken_save=True
        lease=self.guard.leases["INTERNAL_SYNTHETIC_SESSION_1"]
        async def short_sleep(_seconds):
            return None
        with patch("multi_capability_guard.asyncio.sleep",new=short_sleep):
            await self.guard.watchdog(lease)
        self.assertTrue(self.guard.quarantined)
        self.assertTrue(lease.recovery_required)
        self.assertIn("INTERNAL_SYNTHETIC_SESSION_1",
                      self.guard.leases)
        with self.assertRaisesRegex(
                ToolError,"PARALLEL_PROVIDER_RECONCILIATION_REQUIRED"):
            await self.begin("ParallelSelfTest03")
        second_status=await self.mcp.call_tool(
            "browser_status",{"session_id":second})
        self.assertIn("RepairSelfTest",str(second_status))

    async def test_watchdog_missing_remote_session_requires_reconciliation(self):
        await self.begin("CloudSelfTest")
        lease=self.guard.leases["INTERNAL_SYNTHETIC_SESSION_1"]
        # A provider closed without confirmation; do not mark it saved.
        self.manager._sessions.pop("INTERNAL_SYNTHETIC_SESSION_1")
        async def short_sleep(_seconds):
            return None
        with patch("multi_capability_guard.asyncio.sleep",new=short_sleep):
            await self.guard.watchdog(lease)
        self.assertTrue(self.guard.quarantined)
        self.assertTrue(lease.recovery_required)
        self.assertEqual(self.manager.saved,[])
        with self.assertRaisesRegex(
                ToolError,"PARALLEL_PROVIDER_RECONCILIATION_REQUIRED"):
            await self.begin("ParallelSelfTest03")

    async def test_legacy_mobile_http_denied_even_without_sessions(self):
        # The route does not inherit an MCP per-task capability. Never let it
        # bypass the profile boundary, including while browser is idle.
        route=next(x for x in self.mcp._custom_starlette_routes
                   if x.path=="/setup/legacy")
        response=await route.endpoint(Request({
            "type":"http","method":"POST","path":"/setup/legacy",
            "headers":[], "query_string":b"", "scheme":"https",
            "server":("test",443)
        }))
        self.assertEqual(response.status_code,403)


if __name__=="__main__":
    import unittest
    unittest.main(verbosity=2)
