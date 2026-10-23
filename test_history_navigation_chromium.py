"""Real external Chromium/CDP history regression, using only localhost HTTP.

Run in the pinned production image with --network none. Chromium is launched
directly with a temporary profile, without Playwright's BFCache-disabling launch
defaults. No Playwright routes, provider sessions or real account data are used.
"""
from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack, asynccontextmanager, contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from urllib.parse import urlsplit

from playwright.async_api import Error, TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright, expect

from history_navigation import install_context_history


@asynccontextmanager
async def external_chromium(playwright):
    with TemporaryDirectory(prefix="aib-local-history-") as directory:
        process = await asyncio.create_subprocess_exec(
            playwright.chromium.executable_path,
            "--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
            "--no-first-run", "--no-default-browser-check",
            "--disable-background-networking", "--disable-component-update",
            "--disable-sync", "--remote-debugging-address=127.0.0.1",
            "--remote-debugging-port=0", "--user-data-dir=" + directory,
            "about:blank", stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL)
        browser = None
        try:
            async def endpoint():
                active_port = Path(directory) / "DevToolsActivePort"
                while True:
                    if active_port.exists():
                        lines = active_port.read_text().splitlines()
                        if lines and lines[0].isdigit():
                            return "http://127.0.0.1:" + lines[0]
                    if process.returncode is not None:
                        raise RuntimeError("LOCAL_CHROMIUM_START_FAILED")
                    await asyncio.sleep(0.05)
            browser = await playwright.chromium.connect_over_cdp(
                await asyncio.wait_for(endpoint(), 10), timeout=10000)
            yield browser
        finally:
            try:
                if browser is not None:
                    await asyncio.wait_for(browser.close(), 5)
            finally:
                if process.returncode is None:
                    try:
                        process.terminate()
                    except ProcessLookupError:
                        pass
                    try:
                        await asyncio.wait_for(process.wait(), 3)
                    except asyncio.TimeoutError:
                        process.kill()
                        await process.wait()


@contextmanager
def local_site():
    release = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            path = urlsplit(self.path).path
            if path == "/hold.js":
                release.wait(20)
                body = b"window.syntheticDeferredFinished=true;"
                content_type = "application/javascript"
            else:
                deferred = '<script defer src="/hold.js"></script>' if path.startswith("/pending") else ""
                body = ("<!doctype html><html><head>" + deferred +
                    "</head><body><h1>" + path + "</h1><script>"
                    "window.syntheticRestored=false;"
                    "addEventListener('pageshow',e=>window.syntheticRestored=e.persisted);"
                    "</script></body></html>").encode()
                content_type = "text/html"
            try:
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "max-age=0")
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass  # The previous document can leave while its script waits.

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:" + str(server.server_port)
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


class ExternalHistoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.resources = AsyncExitStack()
        self.addAsyncCleanup(self.resources.aclose)
        self.origin = self.resources.enter_context(local_site())
        playwright = await self.resources.enter_async_context(async_playwright())
        browser = await self.resources.enter_async_context(external_chromium(playwright))
        self.context = browser.contexts[0]
        self.page = self.context.pages[0]
        install_context_history(self.context)

    async def assert_document(self, path, page=None):
        page = page or self.page
        self.assertEqual(page.url, self.origin + path)
        await expect(page.locator("h1")).to_have_text(path, timeout=2000)

    async def test_back_and_forward_commit_while_deferred_script_is_pending(self):
        # An unfinished deferred script prevents a fresh DOMContentLoaded.
        # The old caller timed out after moving history; commit returns once.
        pending, ready = self.origin + "/pending-a", self.origin + "/ready-b"
        await self.page.goto(pending, wait_until="commit")
        await self.assert_document("/pending-a")
        await self.page.goto(ready, wait_until="domcontentloaded")
        await asyncio.wait_for(self.page.go_back(
            wait_until="domcontentloaded", timeout=2000), 3)
        await self.assert_document("/pending-a")
        with self.assertRaises(PlaywrightTimeoutError):
            await self.page.wait_for_load_state("domcontentloaded", timeout=150)
        await asyncio.wait_for(self.page.go_forward(
            wait_until="domcontentloaded", timeout=2000), 3)
        await self.assert_document("/ready-b")
        # Put another unfinished document ahead, then exercise forward into it.
        await self.page.goto(self.origin + "/pending-c", wait_until="commit")
        await self.assert_document("/pending-c")
        await self.page.go_back(timeout=2000)
        await self.assert_document("/ready-b")
        await asyncio.wait_for(self.page.go_forward(
            wait_until="load", timeout=2000), 3)
        await self.assert_document("/pending-c")
        with self.assertRaises(PlaywrightTimeoutError):
            await self.page.wait_for_load_state("domcontentloaded", timeout=150)

    async def test_external_history_keeps_dom_usable_with_bfcache_defaults(self):
        await self.page.goto(self.origin + "/cache-a")
        await self.page.goto(self.origin + "/cache-b")
        await self.page.go_back(wait_until="domcontentloaded", timeout=2000)
        await self.assert_document("/cache-a")
        restored_back = await self.page.evaluate("window.syntheticRestored")
        await self.page.go_forward(wait_until="load", timeout=2000)
        await self.assert_document("/cache-b")
        restored_forward = await self.page.evaluate("window.syntheticRestored")
        # Cache eligibility belongs to Chromium; record whether this run used
        # it while requiring usable DOM in either restore or network traversal.
        self.assertIsInstance(restored_back, bool)
        self.assertIsInstance(restored_forward, bool)
        print("LOCAL_HISTORY_BFCACHE", restored_back, restored_forward)

    async def test_future_page_no_history_and_same_document_history(self):
        page = await self.context.new_page()
        self.assertIsNone(await page.go_back(timeout=1000))
        self.assertIsNone(await page.go_forward(timeout=1000))
        await page.goto(self.origin + "/same")
        await page.evaluate("history.pushState({}, '', '#one'); history.pushState({}, '', '#two')")
        self.assertIsNone(await page.go_back(wait_until="domcontentloaded", timeout=1000))
        self.assertEqual(page.url, self.origin + "/same#one")
        self.assertIsNone(await page.go_forward(wait_until="load", timeout=1000))
        self.assertEqual(page.url, self.origin + "/same#two")
        await expect(page.locator("h1")).to_have_text("/same", timeout=2000)

    async def test_closed_page_error_is_not_converted_to_success(self):
        page = await self.context.new_page()
        await page.close()
        with self.assertRaises(Error):
            await page.go_back(timeout=1000)


if __name__ == "__main__":
    unittest.main(verbosity=2)
