"""Real Chromium, synthetic origin only, zero Steel sessions or credentials.

Run in the production Docker image with --network none. The exact fixture
origin is fulfilled in-process; no real Floot page/account is contacted.
This does not claim that Steel persistence or a real login has been tested.
"""
import asyncio
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from playwright.async_api import async_playwright
from steel_context_fix import (
    native_context, ReliabilityError, guard_synthetic_fixture_save,
    synthetic_fixture_page_readback, synthetic_fixture_browser_verified,
)

ORIGIN = "https://ai-browser-vault.floot.app"
URL = ORIGIN + "/browser-check"
KEY = "aibrowser_public_test_marker"
COOKIE = "aibrowser_test_cookie"


class RealChromiumReadback(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="aib-synthetic-only-")
        self.pw = await async_playwright().start()
        self.context = None
        self.binding = {}

    async def asyncTearDown(self):
        if self.context:
            await self.context.close()
        await self.pw.stop()
        self.tmp.cleanup()

    async def launch(self):
        if self.context:
            await self.context.close()
        self.context = await self.pw.chromium.launch_persistent_context(
            self.tmp.name, headless=True, args=["--no-sandbox"],
            executable_path=os.environ.get("AIB_TEST_CHROMIUM_EXECUTABLE") or None)
        async def fixture(route):
            if route.request.url == ORIGIN or route.request.url.startswith(ORIGIN + "/"):
                await route.fulfill(status=200, content_type="text/html",
                                    body="<html><title>Synthetic storage canary</title><body>Fixture</body></html>")
            else:
                await route.abort()
        await self.context.route("**/*", fixture)
        self.context.set_default_timeout(5000)
        return self.context

    async def page(self):
        page = await self.context.new_page()
        await page.goto(URL, wait_until="domcontentloaded")
        return page

    async def seed(self, value):
        page = await self.page()
        await page.evaluate("""({key,cookie,value}) => {
            localStorage.setItem(key,value);
            document.cookie=cookie+'='+value+'; Path=/browser-check; Max-Age=3600; Secure; SameSite=Strict';
        }""", {"key": KEY, "cookie": COOKIE, "value": value})
        await page.close()

    async def restore(self, portable):
        self.binding = {"profile": "SteelSelfTest", "hydrated": True}
        remote = SimpleNamespace(
            browser=self.context.browser, remote_id="synthetic-native-profile",
            engine=SimpleNamespace(_native_bindings={"synthetic-native-profile": self.binding}))
        await native_context(remote, storage_state=copy.deepcopy(portable))

    async def matches(self, page, expected):
        return await page.evaluate(
            "({key,value}) => localStorage.getItem(key) === value",
            {"key": KEY, "value": expected})

    async def test_newer_native_state_survives_stale_portable_and_two_restarts(self):
        await self.launch()
        await self.seed("test-only-portable-old")
        portable = await self.context.storage_state(indexed_db=True)
        await self.seed("test-only-native-current")
        for _ in range(2):
            await self.launch()
            await self.restore(portable)
            page = await self.page()
            self.assertTrue(await self.matches(page, "test-only-native-current"),
                            "Stale portable state replaced newer persistent native state")
            self.assertTrue(synthetic_fixture_browser_verified(
                await synthetic_fixture_page_readback(page)))

    async def test_incoherent_native_pair_can_use_coherent_portable_fixture(self):
        await self.launch()
        await self.seed("test-only-coherent-backup")
        portable = await self.context.storage_state(indexed_db=True)
        page = await self.page()
        await page.evaluate("key => localStorage.setItem(key,'test-only-inconsistent')", KEY)
        await self.launch()
        await self.restore(portable)
        page = await self.page()
        self.assertTrue(synthetic_fixture_browser_verified(
            await synthetic_fixture_page_readback(page)))
        self.assertTrue(await self.matches(page, "test-only-coherent-backup"))
        await guard_synthetic_fixture_save(SimpleNamespace(profile="SteelSelfTest", page=page), self.binding)

    async def test_late_page_mutation_cannot_pass_save_guard(self):
        await self.launch()
        await self.seed("test-only-known-good")
        portable = await self.context.storage_state(indexed_db=True)
        await self.restore(portable)
        page = await self.page()
        self.assertTrue(synthetic_fixture_browser_verified(
            await synthetic_fixture_page_readback(page)))
        await self.context.add_init_script(
            "if(location.origin === " + json.dumps(ORIGIN) + ") "
            "localStorage.setItem(" + json.dumps(KEY) + ", 'test-only-late-stale');")
        await page.reload(wait_until="domcontentloaded")
        self.assertFalse(synthetic_fixture_browser_verified(
            await synthetic_fixture_page_readback(page)))
        with self.assertRaisesRegex(ReliabilityError, "SYNTHETIC_FIXTURE_SAVE_NOT_VERIFIED"):
            await guard_synthetic_fixture_save(
                SimpleNamespace(profile="SteelSelfTest", page=page), self.binding)


if __name__ == "__main__":
    unittest.main(verbosity=2)
