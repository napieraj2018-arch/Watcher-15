"""Real MCPServer 2.3 integration contract: 51 existing + 2 new safe tools.

No network access, no website login and no customer data. It imports the
actual SDK used by the production Docker image, not a fake tool decorator.
"""
import unittest

from mcp.server.mcpserver import MCPServer
from operator_catalog import install, CatalogError
from session_ownership.capability_guard import preflight, OwnershipError
from session_ownership.tests.test_sdk_contract import fake_mcp
from session_ownership.tests.test_capability_guard import DummyManager


class RealMCPCatalog(unittest.IsolatedAsyncioTestCase):
    async def test_real_mcp_v23_exposes_two_read_only_descriptors(self):
        manager=DummyManager()
        mcp=fake_mcp(manager)
        ns={"manager":manager,"mcp":mcp}
        prior=preflight(ns)
        self.assertEqual(prior["tools"],51)

        original_tools={name:tool.fn for name,tool in mcp._tool_manager._tools.items()}
        installed=install(ns)
        self.assertEqual(installed,2)
        self.assertEqual(len(mcp._tool_manager._tools),53)
        for name,fn in original_tools.items():
            self.assertIs(mcp._tool_manager._tools[name].fn,fn)

        listing=await mcp.call_tool("aib_workflow_list",{})
        self.assertIn("anita_reviews_v1",str(listing))
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
