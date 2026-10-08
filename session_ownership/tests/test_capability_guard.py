"""Offline regression tests for the staged MCP capability guard."""
import asyncio
import json
import types
import unittest
from unittest.mock import patch

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from capability_guard import CapabilityGuard, OwnershipError, TOOLS, OWNED

class DummyTool:
    def __init__(self,fn,asynchronous=True):
        self.fn,self.is_async=fn,asynchronous

class DummyManager:
    def __init__(self):
        self._sessions={}
        self.calls=[]
        self.bad_save=False
    def _session(self,sid):
        self.calls.append(('get',sid))
        return self._sessions[sid]
    async def start(self,profile,mode='read_only',start_url='about:blank',headless=True):
        if self._sessions:raise RuntimeError("FAKE_BROWSER_BUSY")
        sid="TEST_INTERNAL_ID_NOT_REAL"
        self._sessions[sid]=types.SimpleNamespace(
          mode=mode,profile=profile,page=types.SimpleNamespace(url=start_url))
        return {"session_id":sid,"profile":profile,"mode":mode,"url":start_url}
    async def status(self,sid):
        self._session(sid)
        return {"session_id":sid,"mode":self._sessions[sid].mode}
    async def flush_profile(self,sid):
        self._session(sid)
        return {"saved":True}
    async def stop(self,sid):
        self._session(sid)
        if self.bad_save:
            return {"session_id":sid,"profile_saved":False,"full_profile_saved":False}
        self._sessions.pop(sid,None)
        return {"session_id":sid,"profile_saved":True,"full_profile_saved":True}

class Fixture:
    def __init__(self):
        self.manager=DummyManager()
        self.counts={name:0 for name in TOOLS}
        self.tools={}
        for name in TOOLS:
            if name=='browser_start':
                async def fn(**kw):
                    self.counts['browser_start']+=1
                    return await self.manager.start(**kw)
            elif name=='browser_sessions':
                async def fn(**kw):
                    return {"result":[{"session_id":sid,"url":s.page.url,"profile":s.profile,
                                      "mode":s.mode} for sid,s in self.manager._sessions.items()]}
            elif name=='browser_recent_audit':
                async def fn(**kw):
                    return {"result":[{"session_id":next(iter(self.manager._sessions),"none"),
                                       "details":{"url":"https://m.facebook.com/?wtsid=SECRET"}}]}
            elif name=='browser_stop':
                async def fn(session_id):
                    return await self.manager.stop(session_id)
            elif name=='browser_status':
                async def fn(session_id):
                    return await self.manager.status(session_id)
            elif name=='browser_snapshot':
                async def fn(session_id,**kw):
                    s=self.manager._session(session_id)
                    return {"session_id":session_id,"url":s.page.url}
            elif name=='profile_flush':
                async def fn(session_id):
                    return await self.manager.flush_profile(session_id)
            elif name=='browser_set_mode':
                async def fn(session_id,mode):
                    self.counts['browser_set_mode']+=1
                    s=self.manager._session(session_id);s.mode=mode
                    return {"session_id":session_id,"mode":mode}
            elif name=='profile_start_setup':
                async def fn(**kw):return {"setup_id":"TEST_SETUP"}
            elif name=='profile_cancel_setup':
                async def fn(**kw):return {"cancelled":True}
            elif name=='profile_delete':
                async def fn(**kw):return {"deleted":True}
            elif name=='profile_login_window':
                async def fn(profile,login_url):
                    return await self.manager.start(profile=profile,mode='write',start_url=login_url)
            elif name=='profile_list':
                async def fn():return {"result":[{"name":"TEST"}]}
            elif name=='browser_staged_files':
                async def fn():return {"result":[{"file_id":"TEST"}]}
            elif name in OWNED:
                async def fn(session_id,**kw):
                    self.manager._session(session_id)
                    return {"session_id":session_id,"ok":True}
            else:
                raise AssertionError(name)
            self.tools[name]=DummyTool(fn)
        async def setup(req):return JSONResponse({"change":"THIS_IS_TEST"})
        async def health(req):return JSONResponse({"status":"ok"})
        self.routes=[Route("/setup/{id}/save",endpoint=setup,methods=["POST"]),
                     Route("/health/context",endpoint=health,methods=["GET"])]
        self.mcp=types.SimpleNamespace(
          _tool_manager=types.SimpleNamespace(_tools=self.tools),
          _custom_starlette_routes=self.routes)
        self.guard=CapabilityGuard(self.mcp,self.manager,
                                   clock=lambda:100,watchdog_enabled=False)

class GuardTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.f=Fixture()
        self.f.guard.install()
    async def open(self):
        return await self.f.tools["browser_start"].fn(
          profile="Meta - Maciej - Monitoring",mode="read_only",
          start_url="https://m.facebook.com/")
    async def test_catalog(self):
        self.assertEqual(len(TOOLS),51)
    async def test_opaque_capability(self):
        result=await self.open()
        self.assertTrue(result["session_id"].startswith("aib_"))
        self.assertNotIn("TEST_INTERNAL_ID",json.dumps(result))
    async def test_authorized_snapshot(self):
        cap=(await self.open())["session_id"]
        result=await self.f.tools["browser_snapshot"].fn(session_id=cap)
        self.assertEqual(result["session_id"],cap)
    async def test_second_actor_cannot_read(self):
        await self.open()
        with self.assertRaisesRegex(OwnershipError,"SESSION_NOT_OWNED"):
            await self.f.tools["browser_snapshot"].fn(session_id="aib_"+"x"*43)
    async def test_second_actor_cannot_escalate(self):
        await self.open()
        with self.assertRaisesRegex(OwnershipError,"SESSION_NOT_OWNED"):
            await self.f.tools["browser_set_mode"].fn(session_id="aib_"+"x"*43,mode="write")
        self.assertEqual(self.f.counts["browser_set_mode"],0)
    async def test_raw_sid_rejected(self):
        await self.open()
        with self.assertRaises(OwnershipError):
            await self.f.tools["browser_stop"].fn(session_id="TEST_INTERNAL_ID_NOT_REAL")
    async def test_double_start_denied(self):
        await self.open()
        with self.assertRaisesRegex(OwnershipError,"BROWSER_BUSY"):
            await self.open()
    async def test_start_parallel_is_serialized(self):
        results=await asyncio.gather(self.open(),self.open(),return_exceptions=True)
        self.assertEqual(sum(isinstance(x,dict) for x in results),1)
        self.assertEqual(sum(isinstance(x,OwnershipError) for x in results),1)
    async def test_public_sessions_hide_raw_ids(self):
        await self.open()
        result=await self.f.tools["browser_sessions"].fn()
        self.assertEqual(result["result"][0]["session_id"],"[redacted]")
    async def test_public_audit_hides_raw_ids_and_query(self):
        await self.open()
        result=await self.f.tools["browser_recent_audit"].fn()
        self.assertEqual(result["result"][0]["session_id"],"[redacted]")
        self.assertNotIn("SECRET",json.dumps(result))
    async def test_direct_manager_get_denied(self):
        await self.open()
        with self.assertRaisesRegex(OwnershipError,"DIRECT_SESSION_ACCESS_BLOCKED"):
            self.f.manager._session("TEST_INTERNAL_ID_NOT_REAL")
    async def test_direct_manager_stop_denied(self):
        await self.open()
        with self.assertRaisesRegex(OwnershipError,"DIRECT_SESSION_ACCESS_BLOCKED"):
            await self.f.manager.stop("TEST_INTERNAL_ID_NOT_REAL")
    async def test_direct_manager_start_denied(self):
        await self.open()
        with self.assertRaises(OwnershipError):
            await self.f.manager.start("OTHER")
    async def test_background_autosave_works(self):
        await self.open()
        self.assertTrue((await self.f.manager.flush_profile("TEST_INTERNAL_ID_NOT_REAL"))["saved"])
    async def test_background_status_works(self):
        await self.open()
        self.assertEqual((await self.f.manager.status("TEST_INTERNAL_ID_NOT_REAL"))["mode"],"read_only")
    async def test_authorized_mode_change(self):
        cap=(await self.open())["session_id"]
        result=await self.f.tools["browser_set_mode"].fn(session_id=cap,mode="write")
        self.assertEqual(result["session_id"],cap)
    async def test_stop_and_new_capability(self):
        cap=(await self.open())["session_id"]
        result=await self.f.tools["browser_stop"].fn(session_id=cap)
        self.assertEqual(result["session_id"],cap)
        self.assertIsNone(self.f.guard.lease)
        newcap=(await self.open())["session_id"]
        self.assertNotEqual(newcap,cap)
    async def test_bad_save_never_releases_owner(self):
        cap=(await self.open())["session_id"]
        self.f.manager.bad_save=True
        await self.f.tools["browser_stop"].fn(session_id=cap)
        self.assertTrue(self.f.guard.lease.recovery_required)
        with self.assertRaises(OwnershipError):
            await self.open()
    async def test_missing_session_tombstone(self):
        await self.open()
        self.f.manager._sessions.clear()
        with self.assertRaises(OwnershipError):
            await self.open()
        self.assertTrue(self.f.guard.lease.recovery_required)
    async def test_manual_setup_blocked_during_lease(self):
        await self.open()
        with self.assertRaises(OwnershipError):
            await self.f.tools["profile_start_setup"].fn(profile="X",login_url="https://x.example/")
    async def test_delete_blocked_during_lease(self):
        await self.open()
        with self.assertRaises(OwnershipError):
            await self.f.tools["profile_delete"].fn(profile="X",confirmation="X")
    async def test_staged_files_require_ownership(self):
        with self.assertRaises(OwnershipError):
            await self.f.tools["browser_staged_files"].fn()
    async def test_mobile_save_route_blocked_during_lease(self):
        await self.open()
        with TestClient(Starlette(routes=self.f.routes)) as client:
            response=client.post("/setup/abc/save")
        self.assertEqual(response.status_code,409)
    async def test_mobile_save_route_allowed_when_idle(self):
        with TestClient(Starlette(routes=self.f.routes)) as client:
            response=client.post("/setup/abc/save")
        self.assertEqual(response.status_code,200)
    async def test_health_available_during_lease(self):
        await self.open()
        with TestClient(Starlette(routes=self.f.routes)) as client:
            response=client.get("/health/context")
        self.assertEqual(response.status_code,200)
    async def test_unsupported_tool_catalog_fails_closed(self):
        fixture=Fixture()
        fixture.tools["browser_stealth"]=DummyTool(lambda:None,False)
        with self.assertRaisesRegex(OwnershipError,"SESSION_TOOL_CATALOG_MISMATCH"):
            fixture.guard.install()
    async def test_missing_tool_catalog_fails_closed(self):
        fixture=Fixture()
        del fixture.tools["browser_set_mode"]
        with self.assertRaisesRegex(OwnershipError,"SESSION_TOOL_CATALOG_MISMATCH"):
            fixture.guard.install()
    async def test_expired_capability_cannot_read(self):
        cap=(await self.open())["session_id"]
        self.f.guard.clock=lambda:1200
        with self.assertRaisesRegex(OwnershipError,"SESSION_CAPABILITY_EXPIRED"):
            await self.f.tools["browser_snapshot"].fn(session_id=cap)
    async def test_expired_owner_can_close_and_save(self):
        cap=(await self.open())["session_id"]
        self.f.guard.clock=lambda:1200
        self.assertTrue((await self.f.tools["browser_stop"].fn(session_id=cap))["full_profile_saved"])
    async def test_login_window_returns_capability(self):
        fixture=Fixture()
        fixture.guard.install()
        r=await fixture.tools["profile_login_window"].fn(profile="X",login_url="https://m.facebook.com/")
        self.assertTrue(r["session_id"].startswith("aib_"))
    async def test_unreviewed_tool_without_browser_prefix_is_blocked(self):
        fixture=Fixture()
        fixture.tools["admin_reconfigure"]=DummyTool(lambda: None,False)
        with self.assertRaisesRegex(OwnershipError,"SESSION_TOOL_CATALOG_MISMATCH"):
            fixture.guard.install()

    async def test_invalid_route_does_not_partially_wrap_mobile(self):
        fixture=Fixture()
        first=fixture.routes[0].endpoint
        fixture.routes.append(types.SimpleNamespace(path=None,endpoint=None))
        with self.assertRaisesRegex(OwnershipError,"HTTP_ROUTE_NOT_SUPPORTED"):
            fixture.guard.install()
        self.assertIs(fixture.routes[0].endpoint,first)

    async def test_original_tool_metadata_unmodified(self):
        tool=self.f.tools["browser_start"]
        self.assertTrue(tool.is_async)
        self.assertEqual(self.f.counts["browser_start"],0)

if __name__=="__main__":
    unittest.main(verbosity=2)
