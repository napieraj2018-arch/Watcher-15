"""Zero-cost Fresh resource safeguards; synthetic profiles and local Chromium only."""
import asyncio
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import server
from navigation_runtime import AuditedWorkspace
from playwright.async_api import async_playwright
from starlette.requests import Request


class FakePage:
    def __init__(self):
        self.url = "https://fixture.invalid/form"
        self.viewport_size = {"width": 390, "height": 844}
        self.screenshot = AsyncMock(return_value=b"synthetic-image")


class EfficientWrites(unittest.IsolatedAsyncioTestCase):
    def workspace(self):
        w = server.BrowserWorkspace()
        p = FakePage()
        w.context = SimpleNamespace(
            pages=[p],
            storage_state=AsyncMock(return_value={"cookies": [], "origins": []}),
        )
        w.profile = "acceptance-free-efficiency"
        w.rev = 1
        w.active_page = p
        w.assert_lease = AsyncMock()
        return w

    async def test_idle_autosaves_do_not_create_versions(self):
        w = self.workspace()
        calls = []
        def store(name, payload, revision):
            calls.append((name, payload, revision))
            return revision + 1
        with patch.object(server, "seal", side_effect=lambda raw: raw), \
             patch.object(server, "db_save", side_effect=store):
            await w._save()
            for _ in range(30):
                await w._save()
            self.assertEqual(len(calls), 1)
            self.assertEqual(w.rev, 2)
            self.assertEqual(w.assert_lease.await_count, 31)
            w.history.append({"url": "https://fixture.invalid/next", "time": 1})
            await w._save()
            self.assertEqual(len(calls), 2)
            self.assertEqual(w.rev, 3)
            self.assertEqual(json.loads(calls[-1][1])["aib_history"][0]["time"], 1)
            await w._save()
            self.assertEqual(len(calls), 2)

    async def test_failed_write_does_not_mark_state_persisted(self):
        w = self.workspace()
        with patch.object(server, "seal", side_effect=lambda raw: raw), \
             patch.object(server, "db_save", side_effect=[None, 2]) as db:
            with self.assertRaises(server.HTTPException) as error:
                await w._save()
            self.assertEqual(error.exception.status_code, 409)
            self.assertIsNone(w.saved_digest)
            await w._save()
            self.assertEqual(db.call_count, 2)
            self.assertEqual(w.rev, 2)
            self.assertIsNotNone(w.saved_digest)

    async def test_full_resolution_mcp_png_and_compact_panel_jpeg(self):
        w = self.workspace()
        raw = await w.screenshot(w.profile, with_metadata=False)
        self.assertEqual(raw, b"synthetic-image")
        self.assertEqual(w.page().screenshot.await_args.kwargs["type"], "png")
        frame, metadata = await w.screenshot(w.profile, with_metadata=True)
        self.assertEqual(frame, b"synthetic-image")
        self.assertEqual(w.page().screenshot.await_args.kwargs["type"], "jpeg")
        self.assertEqual(w.page().screenshot.await_args.kwargs["quality"], 80)
        self.assertEqual(metadata["X-AIB-Navigation"], "ready")


class Mobile304(unittest.TestCase):
    def request(self, if_none_match=None):
        headers = [] if if_none_match is None else [
            (b"if-none-match", if_none_match.encode())]
        return Request({"type": "http", "method": "GET", "path": "/api/screen",
                        "headers": headers, "query_string": b""})

    def test_unchanged_pixels_and_metadata_are_not_transferred_again(self):
        meta = {"X-AIB-Page": "tab-1", "X-AIB-Origin": "https://fixture.invalid",
                "X-AIB-Navigation": "ready", "X-AIB-Tabs": "1"}
        first = server.conditional_mobile_frame(self.request(), b"jpeg-bytes", meta)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.media_type, "image/jpeg")
        etag = first.headers["etag"]
        same = server.conditional_mobile_frame(self.request(etag), b"jpeg-bytes", meta)
        self.assertEqual(same.status_code, 304)
        self.assertEqual(same.body, b"")
        changed = server.conditional_mobile_frame(
            self.request(etag), b"jpeg-bytes",
            {**meta, "X-AIB-Page": "tab-2"})
        self.assertEqual(changed.status_code, 200)

    def test_post_target_not_saved_as_replayable_tab(self):
        w = AuditedWorkspace()
        p = FakePage()
        w.last_safe_urls[p] = "https://fixture.invalid/form"
        w.document_methods[p] = "POST"
        p.url = "https://fixture.invalid/submit"
        self.assertEqual(w.saved_url(p), "https://fixture.invalid/form")
        p.url = "about:blank"
        w.failed_pages.add(p)
        self.assertEqual(w.saved_url(p), "https://fixture.invalid/form")


class RealPanel304(unittest.IsolatedAsyncioTestCase):
    async def test_browser_keeps_cached_image_after_304(self):
        html = Path(__file__).with_name("index.html").read_text()
        pw = await async_playwright().start()
        browser = await pw.chromium.launch(
            headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        try:
            ctx = await browser.new_context()
            page = await ctx.new_page()
            jpeg = await page.screenshot(type="jpeg", quality=80)
            frame_headers = []
            requests = []
            async def route(r):
                url = r.request.url
                if url.endswith("/api/session"):
                    result = {"ok": True}
                elif url.endswith("/api/profiles"):
                    result = {"profiles": [{"name": "acceptance-free-efficiency"}]}
                elif "/api/action" in url:
                    requests.append("action")
                    result = {"ok": True, "title": "Fixture", "url": "https://fixture.invalid",
                              "navigation": "ready", "human": False}
                elif "/api/tabs" in url:
                    result = {"tabs": [{"id": "tab-1", "title": "Fixture",
                                        "url": "https://fixture.invalid",
                                        "active": True, "navigation": "ready"}]}
                elif "/api/screen" in url:
                    requested = r.request.headers.get("if-none-match")
                    frame_headers.append(requested)
                    headers = {"ETag": '"stable-fixture-v1"', "X-AIB-Page": "tab-1",
                               "X-AIB-Origin": "https://fixture.invalid",
                               "X-AIB-Navigation": "ready", "X-AIB-Tabs": "1"}
                    if requested == '"stable-fixture-v1"':
                        await r.fulfill(status=304, headers=headers)
                    else:
                        await r.fulfill(status=200, content_type="image/jpeg",
                                        headers=headers, body=jpeg)
                    return
                else:
                    await r.fulfill(content_type="text/html", body=html)
                    return
                await r.fulfill(content_type="application/json",
                                body=json.dumps(result))
            await ctx.route("https://panel.invalid/**", route)
            await page.goto("https://panel.invalid/")
            await page.wait_for_function(
                "Array.from(document.getElementById('profile').options).some(o=>o.value==='acceptance-free-efficiency')",
                timeout=5000)
            await page.locator("#profile").select_option("acceptance-free-efficiency")
            await page.locator("#openBtn").click()
            await page.wait_for_function(
                "Boolean(document.getElementById('screen').dataset.objectUrl)",
                timeout=5000)
            await page.evaluate("screenshot()")
            self.assertIn('"stable-fixture-v1"', frame_headers)
            self.assertTrue(await page.locator("#screen").is_visible())
            self.assertEqual(requests.count("action"), 1,
                             "Conditional image GET must not replay an action")
            self.assertEqual(await page.locator("#error").inner_text(), "")
            await ctx.close()
        finally:
            await browser.close()
            await pw.stop()


if __name__ == "__main__":
    unittest.main()
