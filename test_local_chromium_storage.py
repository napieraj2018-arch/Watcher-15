"""Test Playwright 1.59 real Chromium storage restore without Steel or secrets.

Uses a local loopback HTTP fixture, a disposable temporary browser profile
and fictional markers only. Does not touch any user profile, company login,
Steel, Floot, Stripe, Render or external website.
"""
from __future__ import annotations

import asyncio
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from time import time

from playwright.async_api import async_playwright


COOKIE = "aibrowser_test_cookie"
STORAGE = "aibrowser_public_test_marker"
PATH = "/browser-check"
OLD = "fixture-native-old-not-a-secret"
FRESH = "fixture-portable-fresh-not-a-secret"


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != PATH:
            self.send_response(404)
            self.end_headers()
            return
        html = """<!doctype html><html><head><title>Synthetic local E2E</title>
<meta name="viewport" content="width=device-width"></head>
<body><h1>Local Chromium fixture</h1>
<p>No private accounts or credentials are accessed.</p></body></html>"""
        encoded = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, *_args):
        pass


def cookie(value: str):
    return {
        "name": COOKIE,
        "value": value,
        "domain": "127.0.0.1",
        "path": PATH,
        "expires": int(time()) + 3600,
        "httpOnly": False,
        "secure": False,
        "sameSite": "Lax",
    }


def portable(origin: str):
    return {
        "cookies": [cookie(FRESH)],
        "origins": [{"origin": origin,
                     "localStorage": [{"name": STORAGE, "value": FRESH}]}],
    }


def verify_snapshot(snapshot, origin: str, expected: str):
    cookies = [
        row for row in snapshot.get("cookies", [])
        if row.get("name") == COOKIE
        and row.get("domain", "").lstrip(".") == "127.0.0.1"
        and row.get("path") == PATH
    ]
    origins = [
        row for row in snapshot.get("origins", [])
        if row.get("origin") == origin
    ]
    fields = [] if len(origins) != 1 else [
        row for row in origins[0].get("localStorage", [])
        if row.get("name") == STORAGE
    ]
    return {
        "cookie_expected": len(cookies) == 1 and cookies[0].get("value") == expected,
        "storage_expected": len(fields) == 1 and fields[0].get("value") == expected,
        "pair": (len(cookies) == len(fields) == 1 and
                 cookies[0].get("value") == fields[0].get("value")),
    }


async def verify_page(page, origin: str, expected: str):
    await page.goto(origin + PATH, wait_until="domcontentloaded", timeout=20000)
    report = await page.evaluate("""({name,key,expected}) => {
      const cookie = document.cookie.split('; ').find(p =>
        p.startsWith(name + '='))?.slice(name.length+1);
      const local = localStorage.getItem(key);
      return {
        cookie_expected: cookie === expected,
        storage_expected: local === expected,
        pair: Boolean(cookie && local && cookie === local)
      };
    }""", {"name": COOKIE, "key": STORAGE, "expected": expected})
    if set(report) != {"cookie_expected", "storage_expected", "pair"}:
        raise AssertionError("INVALID_BROWSER_REPORT")
    if any(type(value) is not bool for value in report.values()):
        raise AssertionError("INVALID_BROWSER_REPORT_TYPE")
    return report


async def chromium_persistent(browser, origin: str, root: str,
                              native_has_storage: bool):
    directory = str(Path(root)/("with-native-storage" if native_has_storage
                                else "missing-native-storage"))
    # First pass: create persistent native profile with an old test cookie.
    context = await browser.chromium.launch_persistent_context(
        directory, headless=True, args=["--no-sandbox"])
    try:
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(origin + PATH, wait_until="domcontentloaded", timeout=20000)
        await context.add_cookies([cookie(OLD)])
        if native_has_storage:
            await page.evaluate("(v) => localStorage.setItem('"+STORAGE+"',v)", OLD)
        native_state = await context.storage_state(indexed_db=True)
        native = verify_snapshot(native_state, origin, OLD)
        assert native["cookie_expected"], "NATIVE_COOKIE_FIXTURE_UNAVAILABLE"
        assert native["storage_expected"] == native_has_storage, "NATIVE_STORAGE_SETUP_FAILED"
    finally:
        await context.close()

    # Second pass: reopen same persistent context, apply a different fresh
    # portable state BEFORE navigating to the fixture.
    context = await browser.chromium.launch_persistent_context(
        directory, headless=True, args=["--no-sandbox"])
    try:
        page = context.pages[0] if context.pages else await context.new_page()
        before = await context.storage_state(indexed_db=True)
        assert verify_snapshot(before, origin, OLD)["cookie_expected"], "NATIVE_PROFILE_NOT_PERSISTED"
        await context.set_storage_state(portable(origin))
        immediate = verify_snapshot(
            await context.storage_state(indexed_db=True), origin, FRESH)
        if not all(immediate.values()):
            raise AssertionError("LOCAL_CHROMIUM_IMMEDIATE_APPLY_FAILED")
        page_result = await verify_page(page, origin, FRESH)
        if not all(page_result.values()):
            raise AssertionError("LOCAL_CHROMIUM_PAGE_RESTORE_FAILED")
    finally:
        await context.close()

    # Third pass: native disk persistence after clean close, no portable state
    # supplied. This must keep both values in sync.
    context = await browser.chromium.launch_persistent_context(
        directory, headless=True, args=["--no-sandbox"])
    try:
        page = context.pages[0] if context.pages else await context.new_page()
        on_disk = verify_snapshot(
            await context.storage_state(indexed_db=True), origin, FRESH)
        if not all(on_disk.values()):
            raise AssertionError("LOCAL_CHROMIUM_DISK_REOPEN_FAILED")
        page_result = await verify_page(page, origin, FRESH)
        if not all(page_result.values()):
            raise AssertionError("LOCAL_CHROMIUM_AFTER_RESTART_FAILED")
    finally:
        await context.close()
    label = "native_storage_stale" if native_has_storage else "native_storage_missing"
    print("LOCAL_PERSISTENT_" + label + "_PASS")


async def chromium_ephemeral(browser, origin: str):
    browser_process = await browser.chromium.launch(
        headless=True, args=["--no-sandbox"])
    try:
        context = await browser_process.new_context()
        try:
            page = await context.new_page()
            await context.set_storage_state(portable(origin))
            state = verify_snapshot(
                await context.storage_state(indexed_db=True), origin, FRESH)
            if not all(state.values()):
                raise AssertionError("LOCAL_NONPERSISTENT_APPLY_FAILED")
            page_result = await verify_page(page, origin, FRESH)
            if not all(page_result.values()):
                raise AssertionError("LOCAL_NONPERSISTENT_PAGE_FAILED")
        finally:
            await context.close()
    finally:
        await browser_process.close()
    print("LOCAL_EPHEMERAL_CONTEXT_PASS")


async def main():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    host, port = server.server_address
    origin = "http://127.0.0.1:" + str(port)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        async with async_playwright() as browser:
            with TemporaryDirectory(prefix="aib-local-test-") as root:
                await chromium_ephemeral(browser, origin)
                await chromium_persistent(browser, origin, root, False)
                await chromium_persistent(browser, origin, root, True)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=4)
    print("LOCAL_CHROMIUM_STORAGE_RESTORE_E2E_PASS")


if __name__ == "__main__":
    asyncio.run(main())
