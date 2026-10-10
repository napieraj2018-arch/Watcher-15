"""Real MCP SDK 2.3 contract for five owner-only parallel browser profiles.

Synthetic sessions ONLY: no Steel API, no cookies, real login or network.
Tests separate chat capabilities, profile mutex, owner guards, mobile denial,
unmanaged session fail-closed and simultaneous actions in different sessions.
"""
from __future__ import annotations

import asyncio
import re
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
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
        self.mcp=fake_mcp(self.manager, sessions_as_list=True)
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
        # Real output is a list; the SDK adds result by itself. Returning
        # a nested capacity object fails Pydantic browser_sessionsOutput.
        self.assertNotIn("capacity",report)
        self.assertNotIn("INTERNAL_SYNTHETIC_SESSION_",report)
        self.assertNotIn(caps[0],report)

    async def test_browser_sessions_real_typed_sdk_contract_even_when_empty(self):
        # The actual provider tool declares list[dict], NOT dict. This
        # failed on the live service even though mock-only tests passed.
        empty=await self.mcp.call_tool("browser_sessions",{})
        self.assertNotIn("INTERNAL_SYNTHETIC_SESSION_",str(empty))
        self.assertNotIn("Error executing tool",str(empty))
        await self.begin("Meta - Anita")
        await self.begin("Google - Architekt")
        listed=await self.mcp.call_tool("browser_sessions",{})
        self.assertIn("Meta - Anita",str(listed))
        self.assertIn("Google - Architekt",str(listed))
        self.assertNotIn("INTERNAL_SYNTHETIC_SESSION_",str(listed))
        self.assertNotIn("aib_",str(listed))

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
        mcp=fake_mcp(manager, sessions_as_list=True)
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
        with self.assertRaisesRegex(
            ToolError,"PARALLEL_UNSCOPED_TOOL_DISABLED"):
            await self.mcp.call_tool("profile_start_setup",{
                "profile":"OTHER","login_url":"https://example.com/"})
        with self.assertRaisesRegex(
            ToolError,"PARALLEL_UNSCOPED_TOOL_DISABLED"):
            await self.mcp.call_tool("profile_delete",{
                "profile":"OTHER","confirmation":"DELETE"})

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
