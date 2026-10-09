"""Offline MCP profile deletion interlock tests; NO live profiles or API calls."""
import asyncio
import inspect
import unittest
from types import SimpleNamespace

from profile_delete_guard import install, ErasureGuardError, ERROR, FIX


class FakeTool:
    def __init__(self, fn):
        self.fn = fn
        self.is_async = True


class ProfileDeletionFailClosed(unittest.TestCase):
    def setUp(self):
        self.calls = 0

        async def dangerous_delete(*, profile, confirmation):
            self.calls += 1
            return {"ok": True, "profile": profile}
        self.original = dangerous_delete
        self.tool = FakeTool(dangerous_delete)
        self.namespace = {
            "mcp": SimpleNamespace(_tool_manager=SimpleNamespace(
                _tools={"profile_delete": self.tool, "profile_list": FakeTool(
                    dangerous_delete)}))
        }

    def test_installed_guard_blocks_destructive_tool(self):
        install(self.namespace)
        self.assertEqual(self.namespace["_AIB_PROFILE_ERASURE_GUARD"], FIX)
        with self.assertRaisesRegex(Exception, ERROR) as err:
            asyncio.run(self.tool.fn(profile="FixtureNeverReal", confirmation="FixtureNeverReal"))
        self.assertNotIn("FixtureNeverReal", str(err.exception))
        self.assertEqual(self.calls, 0)

    def test_unrelated_browser_tool_is_not_modified(self):
        sibling = self.namespace["mcp"]._tool_manager._tools["profile_list"]
        old = sibling.fn
        install(self.namespace)
        self.assertIs(sibling.fn, old)
        self.assertIs(self.original, old)

    def test_idempotent_install_retains_guard(self):
        install(self.namespace)
        first = self.tool.fn
        install(self.namespace)
        self.assertIs(self.tool.fn, first)
        self.assertEqual(self.calls, 0)

    def test_absent_profile_delete_fails_closed(self):
        self.namespace["mcp"]._tool_manager._tools.pop("profile_delete")
        with self.assertRaisesRegex(ErasureGuardError, "CATALOG_UNAVAILABLE"):
            install(self.namespace)
        self.assertNotIn("_AIB_PROFILE_ERASURE_GUARD", self.namespace)

    def test_unknown_async_contract_fails_closed(self):
        self.tool.is_async = False
        with self.assertRaisesRegex(ErasureGuardError, "CONTRACT_MISMATCH"):
            install(self.namespace)

    def test_unexpected_sync_function_fails_closed(self):
        self.tool.fn = lambda **_: {"ok": True}
        with self.assertRaisesRegex(ErasureGuardError, "FUNCTION_MISMATCH"):
            install(self.namespace)

    def test_no_profile_access_during_installation(self):
        install(self.namespace)
        self.assertEqual(self.calls, 0)
        self.assertTrue(inspect.iscoroutinefunction(self.tool.fn))


if __name__ == "__main__":
    unittest.main(verbosity=2)
