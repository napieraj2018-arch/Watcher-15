"""Offline preflight contract tests: synthetic routes and sessions only."""
import unittest
from capability_guard import preflight, OwnershipError, TOOLS
from test_capability_guard import Fixture, DummyTool

class ReadOnlyPreflight(unittest.TestCase):
    def test_inspection_only(self):
        f=Fixture()
        start_fn=f.tools["browser_start"].fn
        session_before=dict(f.manager._sessions)
        mobile_before=[route.endpoint for route in f.routes]
        out=preflight({"mcp":f.mcp,"manager":f.manager})
        self.assertEqual(out["tools"],len(TOOLS))
        self.assertEqual(out["changed"],False)
        self.assertEqual(out["mode"],"read_only_preflight")
        self.assertEqual(out["mobile_and_support_routes"],len(mobile_before))
        self.assertIs(f.tools["browser_start"].fn,start_fn)
        self.assertEqual([r.endpoint for r in f.routes],mobile_before)
        self.assertEqual(f.manager._sessions,session_before)
        self.assertFalse(f.guard.installed)

    def test_unknown_tool_rejected(self):
        f=Fixture()
        f.tools["stealth_admin_tool"]=DummyTool("stealth_admin_tool")
        with self.assertRaisesRegex(OwnershipError,"SESSION_TOOL_CATALOG_MISMATCH"):
            preflight({"mcp":f.mcp,"manager":f.manager})

    def test_missing_tool_rejected(self):
        f=Fixture()
        del f.tools["browser_stop"]
        with self.assertRaisesRegex(OwnershipError,"SESSION_TOOL_CATALOG_MISMATCH"):
            preflight({"mcp":f.mcp,"manager":f.manager})

    def test_invalid_route_rejected_without_mutation(self):
        f=Fixture()
        handler=f.routes[0].endpoint
        f.routes[0].endpoint=None
        with self.assertRaisesRegex(OwnershipError,"HTTP_ROUTE_NOT_SUPPORTED"):
            preflight({"mcp":f.mcp,"manager":f.manager})
        self.assertIsNone(f.routes[0].endpoint)
        f.routes[0].endpoint=handler

    def test_missing_manager_rejected(self):
        f=Fixture()
        f.manager._sessions=None
        with self.assertRaisesRegex(OwnershipError,"SESSION_MANAGER_CONTRACT_MISMATCH"):
            preflight({"mcp":f.mcp,"manager":f.manager})

    def test_missing_root_keys_rejected(self):
        with self.assertRaisesRegex(OwnershipError,"SESSION_GUARD_BOOTSTRAP_INCOMPLETE"):
            preflight({})

    def test_preflight_repeatable(self):
        f=Fixture()
        ns={"mcp":f.mcp,"manager":f.manager}
        result=preflight(ns)
        self.assertEqual(preflight(ns),result)
        self.assertEqual(ns["_CAPABILITY_PREFLIGHT_RESULT"],result)

if __name__=="__main__":
    unittest.main(verbosity=2)
