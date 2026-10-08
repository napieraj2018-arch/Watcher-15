"""MCP 2.3 integration smoke test using 51 in-memory synthetic tools."""
import unittest
from starlette.responses import JSONResponse

from mcp.server.mcpserver import MCPServer
from capability_guard import CapabilityGuard, TOOLS, OWNED
from test_capability_guard import DummyManager

def fake_mcp(manager):
    server=MCPServer("synthetic-session-guard-test")
    @server.custom_route("/health/context",methods=["GET"])
    async def health(request):
        return JSONResponse({"ok":True})

    async def start(profile:str,mode:str="read_only",start_url:str="about:blank")->dict:
        return await manager.start(profile,mode=mode,start_url=start_url)
    async def status(session_id:str)->dict:
        return await manager.status(session_id)
    async def sessions()->dict:
        return {"result":[{"session_id":sid,"profile":s.profile,"mode":s.mode,"url":s.page.url}
                          for sid,s in manager._sessions.items()]}
    async def audit()->dict:
        return {"result":[]}
    async def noop(session_id:str)->dict:
        manager._session(session_id)
        return {"session_id":session_id,"ok":True}
    async def mode(session_id:str,mode:str)->dict:
        obj=manager._session(session_id)
        obj.mode=mode
        return {"session_id":session_id,"mode":mode}
    async def stop(session_id:str)->dict:
        return await manager.stop(session_id)
    async def flush(session_id:str)->dict:
        return await manager.flush_profile(session_id)
    async def setup(profile:str,login_url:str)->dict:
        return {"setup_id":"SYNTHETIC"}
    async def login_window(profile:str,login_url:str)->dict:
        return await manager.start(profile,mode="write",start_url=login_url)
    async def cancel(setup_id:str)->dict:
        return {"cancelled":True}
    async def delete(profile:str,confirmation:str)->dict:
        return {"deleted":True}
    async def list_profiles()->dict:
        return {"result":[]}
    async def staged_files()->dict:
        return {"result":[]}

    for name in TOOLS:
        if name=="browser_start": fn=start
        elif name=="browser_status": fn=status
        elif name=="browser_sessions": fn=sessions
        elif name=="browser_recent_audit": fn=audit
        elif name=="browser_set_mode": fn=mode
        elif name=="browser_stop": fn=stop
        elif name=="profile_flush": fn=flush
        elif name=="profile_start_setup": fn=setup
        elif name=="profile_login_window": fn=login_window
        elif name=="profile_cancel_setup": fn=cancel
        elif name=="profile_delete": fn=delete
        elif name=="profile_list": fn=list_profiles
        elif name=="browser_staged_files": fn=staged_files
        elif name in OWNED: fn=noop
        else: raise AssertionError(name)
        server.add_tool(fn,name=name)
    return server

class SDKContractTest(unittest.IsolatedAsyncioTestCase):
    async def test_51_tools_installed_and_schema_preserved(self):
        manager=DummyManager()
        mcp=fake_mcp(manager)
        before={n:t.parameters.copy() for n,t in mcp._tool_manager._tools.items()}
        guard=CapabilityGuard(mcp,manager,watchdog_enabled=False)
        self.assertEqual(guard.install(),51)
        after={n:t.parameters for n,t in mcp._tool_manager._tools.items()}
        self.assertEqual(before,after)
    async def test_mcp_server_tool_call_uses_capability_not_raw_sid(self):
        manager=DummyManager()
        mcp=fake_mcp(manager)
        guard=CapabilityGuard(mcp,manager,watchdog_enabled=False)
        guard.install()
        result=await mcp.call_tool("browser_start",{
            "profile":"Meta - Maciej - Monitoring","mode":"read_only",
            "start_url":"https://m.facebook.com/"})
        text=str(result)
        self.assertNotIn("TEST_INTERNAL_ID_NOT_REAL",text)
        self.assertIn("aib_",text)
        # Actual SDK dispatch uses original input schema plus wrapped function.
        self.assertEqual(manager._sessions["TEST_INTERNAL_ID_NOT_REAL"].mode,"read_only")

if __name__=="__main__":
    unittest.main(verbosity=2)
