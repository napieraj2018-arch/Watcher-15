"""White-page regression. Synthetic routes only; no third-party login or database."""
import json
import os
import secrets
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import server
from playwright.async_api import async_playwright

class FakePage:
    def __init__(self, failure="net::ERR_FAILED", url="about:blank", status=None):
        self.url, self.failure, self.status = url, failure, status
        self.calls, self.html = [], ""
        self.main_frame = object()
        self.viewport_size = server.VIEWPORT
    def on(self, *_): pass
    async def goto(self, url, **kwargs):
        if url == "about:blank":
            self.url = url
            return None
        self.calls.append((url, kwargs))
        if self.failure: raise RuntimeError(self.failure)
        self.url = url
        return SimpleNamespace(status=self.status or 200)
    async def wait_for_timeout(self, *_): pass
    async def set_content(self, text, **kwargs): self.html = text

class NavigationPolicy(unittest.IsolatedAsyncioTestCase):
    async def test_only_one_bounded_retry_for_bare_homepage(self):
        w, p = server.BrowserWorkspace(), FakePage()
        self.assertFalse(await w.navigate(p, "https://fixture.invalid/", restoring=True))
        self.assertEqual(len(p.calls), 2)
        self.assertEqual([x[1]["timeout"] for x in p.calls], [12000, 8000])
        self.assertEqual(w.saved_url(p), "https://fixture.invalid/")
        self.assertEqual(w.navigation_state(p), "failed")
    async def test_no_replay_of_query_path_fragment_or_explicit_operation(self):
        for url in ["https://fixture.invalid/callback", "https://fixture.invalid/?code=private", "https://fixture.invalid/#private"]:
            w, p = server.BrowserWorkspace(), FakePage()
            self.assertFalse(await w.navigate(p, url, restoring=True))
            self.assertEqual(len(p.calls), 1)
            self.assertNotIn("private", p.html)
            self.assertNotIn("private", json.dumps(w.navigation_failures))
        w, p = server.BrowserWorkspace(), FakePage()
        await w.navigate(p, "https://fixture.invalid/")
        self.assertEqual(len(p.calls), 1)
    async def test_certificate_and_policy_denials_not_retried(self):
        for error in ["net::ERR_CERT_AUTHORITY_INVALID", "net::ERR_BLOCKED_BY_CLIENT", "unknown"]:
            w, p = server.BrowserWorkspace(), FakePage(error)
            self.assertFalse(await w.navigate(p, "https://fixture.invalid/", restoring=True))
            self.assertEqual(len(p.calls), 1)
    async def test_http_429_is_not_retried(self):
        w, p = server.BrowserWorkspace(), FakePage(failure=None, status=429)
        self.assertFalse(await w.navigate(p, "https://fixture.invalid/", restoring=True))
        self.assertEqual(len(p.calls), 1)
        self.assertEqual(w.navigation_state(p), "failed")
    async def test_existing_https_page_not_retried_or_replaced(self):
        w, p = server.BrowserWorkspace(), FakePage(url="https://previous.invalid/")
        await w.navigate(p, "https://fixture.invalid/", restoring=True)
        self.assertEqual(len(p.calls), 1)
        self.assertEqual(p.html, "")
        self.assertEqual(w.saved_url(p), "https://previous.invalid/")
    async def test_unsafe_url_stops_before_network(self):
        for url in ["http://fixture.invalid", "https://127.0.0.1/", "https://localhost/", "https://user:secret@fixture.invalid/"]:
            w, p = server.BrowserWorkspace(), FakePage()
            with self.assertRaises(server.HTTPException):
                await w.navigate(p, url, restoring=True)
            self.assertEqual(p.calls, [])
    async def test_success_clears_pending_and_error(self):
        w, p = server.BrowserWorkspace(), FakePage(failure=None)
        w.failed_pages.add(p)
        self.assertTrue(await w.navigate(p, "https://fixture.invalid/", restoring=True))
        self.assertNotIn(p, w.pending_urls)
        self.assertEqual(w.navigation_state(p), "ready")
    async def test_blank_popup_without_failed_restore_stays_empty(self):
        w, p = server.BrowserWorkspace(), FakePage()
        self.assertEqual(w.saved_url(p), "")
        self.assertEqual(w.navigation_state(p), "empty")

class RealChromiumNavigation(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.pw = await async_playwright().start()
        options = {"headless": True, "args": ["--no-sandbox", "--disable-dev-shm-usage"]}
        if os.environ.get("AIB_TEST_CHROMIUM"):
            options["executable_path"] = os.environ["AIB_TEST_CHROMIUM"]
        self.browser = await self.pw.chromium.launch(**options)
        self.context = await self.browser.new_context(viewport=server.VIEWPORT)
        self.w = server.BrowserWorkspace()
        self.w.context, self.w.profile, self.w.rev = self.context, "acceptance-navigation-fixture", 1
        self.w.assert_lease = AsyncMock()
        self.context.on("page", self.w.register_page)
    async def asyncTearDown(self):
        await self.browser.close()
        await self.pw.stop()
    async def test_real_transient_failure_restores_page(self):
        calls = []
        async def route(r):
            calls.append(r.request.method)
            if len(calls) == 1: await r.abort("failed")
            else: await r.fulfill(status=200, content_type="text/html", body="<title>Recovered</title><h1>Restored</h1>")
        await self.context.route("https://fixture.invalid/", route)
        p = await self.context.new_page()
        self.assertTrue(await self.w.navigate(p, "https://fixture.invalid/", restoring=True))
        self.assertEqual(calls, ["GET", "GET"])
        self.assertEqual(await p.title(), "Recovered")
        self.assertEqual(self.w.navigation_state(p), "ready")
    async def test_real_persistent_failure_visible_and_preserves_encrypted_state(self):
        target = "https://fixture.invalid/"
        await self.context.route(target, lambda r: r.abort("failed"))
        p = await self.context.new_page()
        self.w.active_page = p
        self.assertFalse(await self.w.navigate(p, target, restoring=True))
        self.assertIn("Strona nie została wczytana", await p.locator("body").inner_text())
        original = {"origin": "https://fixture.invalid", "localStorage": [{"name": "marker", "value": "keep"}]}
        self.w.restore_origins = [original]
        storage, key = [], secrets.token_bytes(32)
        real_seal = server.seal
        with patch.object(server, "seal", side_effect=lambda b: real_seal(b, key)), patch.object(server, "db_save", side_effect=lambda n, b, r: storage.append((n, b, r)) or r+1):
            await self.w._save()
        decoded = json.loads(server.unseal(storage[0][1], key))
        self.assertEqual(decoded["aib_tabs"], [target])
        self.assertEqual(decoded["origins"], [original])
        self.assertNotIn(b'"aib_tabs"', storage[0][1])
        png, meta = await self.w.screenshot(self.w.profile, with_metadata=True)
        self.assertGreater(len(png), 100)
        self.assertEqual(meta["X-AIB-Navigation"], "failed")
        self.assertEqual(meta["X-AIB-Origin"], "https://fixture.invalid")
        self.assertEqual(self.w.rev, 2)
    async def test_explicit_reload_recovers_preserved_target(self):
        target = "https://fixture.invalid/"
        await self.context.route(target, lambda r: r.abort("failed"))
        p = await self.context.new_page()
        self.w.active_page = p
        await self.w.navigate(p, target, restoring=True)
        await self.context.unroute(target)
        await self.context.route(target, lambda r: r.fulfill(status=200, content_type="text/html", body="<title>Ready</title><p>Recovered</p>"))
        with patch.object(self.w, "_save", new=AsyncMock()):
            result = await self.w.action({"name": self.w.profile, "action": "reload"}, automated=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["navigation"], "ready")
        self.assertEqual(await p.title(), "Ready")
        self.assertEqual(self.w.pending_urls, {})
    async def test_success_does_not_resurrect_logged_out_origin(self):
        p = await self.context.new_page()
        await self.context.route("https://fixture.invalid/", lambda r: r.fulfill(status=200, body="ok"))
        await self.w.navigate(p, "https://fixture.invalid/")
        self.w.restore_origins = [{"origin":"https://fixture.invalid","localStorage":[{"name":"old-login","value":"stale"}]}]
        saved = []
        with patch.object(server, "seal", side_effect=lambda x: x), patch.object(server, "db_save", side_effect=lambda n,b,r: saved.append(json.loads(b)) or r+1):
            await self.w._save()
        self.assertNotIn("stale", json.dumps(saved[0]["origins"]))
    async def test_owner_lock_still_blocks_agent(self):
        self.w.human = True
        with self.assertRaises(server.HTTPException) as exc:
            await self.w.action({"name":self.w.profile,"action":"reload"}, automated=True)
        self.assertEqual(exc.exception.status_code,409)
    async def test_screen_stays_read_only(self):
        p = await self.context.new_page()
        await self.context.route("https://fixture.invalid/",lambda r:r.fulfill(status=200,body="ready"))
        await self.w.navigate(p,"https://fixture.invalid/")
        self.w.active_page = p
        with patch.object(self.w,"_save",new=AsyncMock()) as save:
            await self.w.screenshot(self.w.profile)
            save.assert_not_awaited()
        self.assertEqual(self.w.rev,1)

if __name__ == '__main__': unittest.main()
