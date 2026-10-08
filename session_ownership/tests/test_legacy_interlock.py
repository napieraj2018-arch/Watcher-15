"""Offline tests. All legacy tools are fake, no real user session is touched."""
import unittest
from legacy_tool_interlock import (
    LegacyToolInterlock, LegacyInterlockError, LEGACY_TOOLS, READ_ONLY_PUBLIC
)

class FakeTool:
    def __init__(self, name, is_async=True):
        self.is_async=is_async
        self.calls=[]
        if is_async:
            async def fn(**kwargs):
                self.calls.append(kwargs)
                return name
        else:
            def fn(**kwargs):
                self.calls.append(kwargs)
                return name
        self.fn=fn

class LegacyGateTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tools={name:FakeTool(name,is_async=name!="profile_delete") for name in LEGACY_TOOLS}
        self.gate=LegacyToolInterlock(self.tools)

    async def test_catalog_has_49_tools(self):
        self.assertEqual(len(LEGACY_TOOLS),49)

    async def test_guard_patches_46(self):
        self.assertEqual(self.gate.install(),46)

    async def test_mode_escalation_denied(self):
        self.gate.install()
        with self.assertRaisesRegex(LegacyInterlockError,"LEGACY_BROWSER_API_DISABLED"):
            await self.tools["browser_set_mode"].fn(session_id="fake",mode="write")

    async def test_click_denied(self):
        self.gate.install()
        with self.assertRaises(LegacyInterlockError):
            await self.tools["browser_click"].fn(session_id="fake",ref="e1")

    async def test_unleased_legacy_start_also_denied(self):
        self.gate.install()
        with self.assertRaises(LegacyInterlockError):
            await self.tools["browser_start"].fn(profile="Fake",mode="write")

    async def test_mobile_login_tool_denied(self):
        self.gate.install()
        with self.assertRaises(LegacyInterlockError):
            await self.tools["profile_start_setup"].fn(profile="Fake")

    async def test_profile_delete_denied_synchronously(self):
        self.gate.install()
        with self.assertRaises(LegacyInterlockError):
            self.tools["profile_delete"].fn(profile="Fake")

    async def test_inspection_allowed(self):
        self.gate.install()
        for name in READ_ONLY_PUBLIC:
            with self.subTest(name=name):
                self.assertEqual(await self.tools[name].fn(),name)

    async def test_all_legacy_mutations_blocked(self):
        self.gate.install()
        for name in LEGACY_TOOLS-READ_ONLY_PUBLIC-{"profile_delete"}:
            with self.subTest(name=name), self.assertRaises(LegacyInterlockError):
                await self.tools[name].fn()
            self.assertEqual(self.tools[name].calls,[])

    async def test_missing_tool_refuses_partial_patch(self):
        del self.tools["browser_set_mode"]
        with self.assertRaisesRegex(LegacyInterlockError,"LEGACY_CATALOG_INCOMPLETE"):
            self.gate.install()
        self.assertEqual(await self.tools["browser_click"].fn(),"browser_click")

    async def test_unknown_new_browser_tool_requires_review(self):
        self.tools["browser_silent_override"]=FakeTool("browser_silent_override")
        with self.assertRaisesRegex(LegacyInterlockError,"LEGACY_CATALOG_CHANGED"):
            self.gate.install()

    async def test_install_twice_refused(self):
        self.gate.install()
        with self.assertRaisesRegex(LegacyInterlockError,"ALREADY_INSTALLED"):
            self.gate.install()

    async def test_restore_for_tests(self):
        self.gate.install()
        self.gate.restore_for_tests_only()
        self.assertEqual(await self.tools["browser_click"].fn(),"browser_click")

if __name__=="__main__":
    unittest.main(verbosity=2)
