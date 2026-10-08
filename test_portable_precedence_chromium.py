"""Real local Chromium test for cookie/localStorage coherence.

The served page contains only synthetic markers; no Steel key, no external site,
no user account, and no actual Meta authentication.
"""
from __future__ import annotations
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from playwright.async_api import async_playwright
from steel_context_fix import merge_profile_state


class Fixture(BaseHTTPRequestHandler):
    def do_GET(self):
        data = b"<!doctype html><html><body>LOCAL TEST ONLY</body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_args):
        pass


async def read_markers(page):
    return await page.evaluate("""() => ({
        cookie: (document.cookie.split('; ').find(v => v.startsWith('aib_coherence=')) || '').split('=')[1] || null,
        local: localStorage.getItem('aib_coherence')
    })""")


async def write_markers(page, cookie, local):
    await page.evaluate("""([a,b]) => {
      document.cookie = 'aib_coherence=' + a + '; Path=/; SameSite=Lax';
      localStorage.setItem('aib_coherence', b);
    }""", [cookie, local])


async def run(origin):
    async with async_playwright() as play:
        browser=await play.chromium.launch(headless=True,args=["--no-sandbox"])
        original=await browser.new_context()
        page=await original.new_page()
        await page.goto(origin)
        await write_markers(page,"old-synthetic-cookie","new-synthetic-store")
        native=await original.storage_state()
        # A saved portable snapshot whose two fields were written together.
        await write_markers(page,"new-synthetic-store","new-synthetic-store")
        portable=await original.storage_state()
        await original.close()

        restored=await browser.new_context(storage_state=native)
        rpage=await restored.new_page()
        await rpage.goto(origin)
        before=await read_markers(rpage)
        assert before["cookie"]!=before["local"], "fixture must reproduce mismatch"

        merged=merge_profile_state(portable,native)
        await restored.set_storage_state(merged)
        await rpage.reload()
        after=await read_markers(rpage)
        assert after=={"cookie":"new-synthetic-store","local":"new-synthetic-store"}, after

        snapshot=await restored.storage_state()
        await restored.close()
        repeated=await browser.new_context(storage_state=snapshot)
        p=await repeated.new_page()
        await p.goto(origin)
        reopened=await read_markers(p)
        assert reopened==after, {"result":"REOPENED_STATE_NOT_COHERENT"}
        print("REAL_CHROMIUM_PORTABLE_PRIORITY_TEST=PASS")
        await repeated.close()
        await browser.close()


if __name__=="__main__":
    web=ThreadingHTTPServer(("127.0.0.1",0), Fixture)
    Thread(target=web.serve_forever,daemon=True).start()
    try:
        asyncio.run(run(f"http://127.0.0.1:{web.server_port}/"))
    finally:
        web.shutdown()
        web.server_close()
