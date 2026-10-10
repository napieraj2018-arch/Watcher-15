"""Real MCPServer 2.3 integration contract: 51 existing + 3 new safe tools.

No network access, no website login and no customer data. It imports the
actual SDK used by the production Docker image, not a fake tool decorator.
"""
import unittest

from mcp.server.mcpserver import MCPServer
from operator_catalog import install, CatalogError
from capability_guard import preflight, OwnershipError
from test_sdk_contract import fake_mcp
from test_capability_guard import DummyManager


class RealMCPCatalog(unittest.IsolatedAsyncioTestCase):
    async def test_real_mcp_v23_exposes_two_read_only_descriptors(self):
        manager=DummyManager()
        mcp=fake_mcp(manager)
        ns={"manager":manager,"mcp":mcp}
        prior=preflight(ns)
        self.assertEqual(prior["tools"],51)

        original_tools={name:tool.fn for name,tool in mcp._tool_manager._tools.items()}
        installed=install(ns)
        self.assertEqual(installed,3)
        self.assertEqual(len(mcp._tool_manager._tools),54)
        for name,fn in original_tools.items():
            self.assertIs(mcp._tool_manager._tools[name].fn,fn)

        listing=await mcp.call_tool("aib_workflow_list",{})
        self.assertIn("anita_reviews_v1",str(listing))
        route=await mcp.call_tool("aib_route_operation",{
            "service":"instagram","operation":"reel","brand":"anita"})
        self.assertIn("create_video_post",str(route))
        self.assertIn("not_checked",str(route))
        self.assertIn("False",str(route))
        self.assertNotIn("Google Sheet",str(listing))

        description=await mcp.call_tool(
            "aib_workflow_describe",{"workflow_id":"anita_reviews_v1"})
        data=str(description)
        self.assertIn("18102998546608585",data)
        self.assertIn("17588627068282939119",data)
        self.assertIn("TENANT_PRIVATE_BACKEND_NOT_ATTACHED_TO_MCP",data)
        self.assertIn("False",data)
        self.assertNotIn("cookie_value",data)

    async def test_bootstrap_order_fails_closed_if_preflight_after_new_tools(self):
        manager=DummyManager()
        mcp=fake_mcp(manager)
        ns={"manager":manager,"mcp":mcp}
        preflight(ns)
        install(ns)
        with self.assertRaisesRegex(OwnershipError,"SESSION_TOOL_CATALOG_MISMATCH"):
            preflight(ns)

    async def test_five_session_owner_guard_then_read_only_workflow_tools(self):
        import re
        from multi_capability_guard import MultiCapabilityGuard
        from test_owner_parallel_mcp import MultiManager
        from mcp.server.mcpserver.exceptions import ToolError

        manager=MultiManager(capacity=5)
        mcp=fake_mcp(manager)
        guard=MultiCapabilityGuard(
            mcp,manager,capacity=5,watchdog_enabled=False)
        self.assertEqual(guard.install(),51)
        old_handlers={k:v.fn for k,v in mcp._tool_manager._tools.items()}
        self.assertEqual(install({"mcp":mcp}),3)
        self.assertEqual(len(mcp._tool_manager._tools),54)
        self.assertTrue(all(mcp._tool_manager._tools[k].fn is fn
                            for k,fn in old_handlers.items()))

        a=await mcp.call_tool("browser_start",{
            "profile":"Synthetic-A","start_url":"https://example.com/"})
        b=await mcp.call_tool("browser_start",{
            "profile":"Synthetic-B","start_url":"https://example.org/"})
        handles=[re.search(r"aib_[A-Za-z0-9_-]{43}",str(x)).group(0)
                 for x in (a,b)]
        self.assertNotEqual(handles[0],handles[1])
        names=str(await mcp.call_tool("browser_sessions",{}))
        self.assertIn("Synthetic-A",names)
        self.assertIn("Synthetic-B",names)
        self.assertNotIn(handles[0],names)
        self.assertNotIn(handles[1],names)

        for handle in handles:
            valid=await mcp.call_tool("browser_status",{"session_id":handle})
            self.assertNotIn("INTERNAL_SYNTHETIC",str(valid))
        with self.assertRaises(ToolError):
            await mcp.call_tool("browser_status",{
                "session_id":"aib_"+"Z"*43})
        router=await mcp.call_tool("aib_route_operation",{
            "service":"gmail","operation":"email_read"})
        self.assertIn("search_emails",str(router))
        self.assertNotIn(handles[0],str(router))
        workflow=await mcp.call_tool("aib_workflow_list",{})
        self.assertIn("anita_reviews_v1",str(workflow))
        desc=await mcp.call_tool("aib_workflow_describe",{
            "workflow_id":"anita_reviews_v1"})
        self.assertIn("autonomous_execution_ready",str(desc))
        self.assertNotIn("INTERNAL_SYNTHETIC",str(workflow)+str(desc))
        self.assertNotIn(handles[0],str(workflow)+str(desc))
        # No call to Steel, real Facebook/Google credentials or live account.

    async def test_unknown_workflow_does_not_leak_path(self):
        manager=DummyManager()
        mcp=fake_mcp(manager)
        install({"mcp":mcp})
        output=await mcp.call_tool(
            "aib_workflow_describe",{"workflow_id":"../../secret-key"})
        text=str(output)
        self.assertIn("CATALOG_WORKFLOW_NOT_FOUND",text)
        self.assertNotIn("secret-key",text)


if __name__=="__main__":
    unittest.main(verbosity=2)
