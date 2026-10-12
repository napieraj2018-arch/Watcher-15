"""Offline REAL Chromium integration of the owner-scoped iPhone touch bridge.

No Steel Cloud calls. No Facebook network requests, cookies, tokens or real
accounts. The exact Facebook login URL is intercepted and locally fulfilled
with a synthetic page. Exercises actual Playwright mouse, keyboard, focus,
input events and screenshot paths, not merely fake methods.
"""
from __future__ import annotations

import unittest
from playwright.async_api import async_playwright
from starlette.responses import JSONResponse
from starlette.routing import Route

from multi_capability_guard import MultiCapabilityGuard
from test_owner_mobile_handoff import (
    FakeMobileManager, PROFILE, FACEBOOK, SETUP_PATH, request,
)
from owner_mobile_touch import FRAME_PATH, ACTION_PATH
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent /
                       "session_ownership" / "tests"))
from test_sdk_contract import fake_mcp

PAGE = """<!doctype html><html><head><meta name="viewport"
 content="width=device-width,initial-scale=1"></head>
<body style="margin:0;font-family:sans-serif">
<input id="email" type="email" placeholder="Synthetic email"
 style="position:absolute;top:100px;left:40px;width:320px;height:52px">
<input id="password" type="password" placeholder="Synthetic password"
 style="position:absolute;top:185px;left:40px;width:320px;height:52px">
<button id="submit" type="button"
 style="position:absolute;top:265px;left:40px;width:320px;height:52px"
 onclick="document.querySelector('#out').textContent='synthetic-clicked'">
 Synthetic submit</button>
<div id="out" style="position:absolute;top:335px;left:40px">waiting</div>
<div style="position:absolute;top:2800px;height:200px">Scroll target</div>
</body></html>"""


class RealChromiumTouch(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.manager=FakeMobileManager()
        self.mcp=fake_mcp(self.manager)
        async def legacy(_):
            return JSONResponse({"unsafe":"legacy"})
        self.mcp._custom_starlette_routes.append(
            Route("/setup/legacy",legacy,methods=["POST"]))
        self.guard=MultiCapabilityGuard(
            self.mcp,self.manager,capacity=5,watchdog_enabled=False)
        self.guard.install()
        self.handoff=self.guard.mobile_handoff
        self.handoff.clock=lambda:100
        self.setup=await self.handoff.create({
            "profile":PROFILE,"login_url":FACEBOOK})
        t=self.setup["setup_url"].split("#s=",1)[1]
        claim=await self.handoff.claim(request(
            SETUP_PATH+"/claim","POST",{"token":t}))
        self.assertEqual(claim.status_code,200)
        self.cookie=claim.headers["set-cookie"].split(";",1)[0]
        self.playwright=await async_playwright().start()
        self.browser=await self.playwright.chromium.launch(
            headless=True,args=["--no-sandbox"])
        self.context=await self.browser.new_context(
            viewport={"width":508,"height":1074},
            device_scale_factor=1,is_mobile=True,has_touch=True)
        self.page=await self.context.new_page()
        async def local_facebook(route):
            await route.fulfill(status=200,content_type="text/html",body=PAGE)
        await self.page.route(FACEBOOK,local_facebook)
        await self.page.goto(FACEBOOK,wait_until="domcontentloaded")
        self.assertEqual(self.page.url,FACEBOOK)
        sid=next(iter(self.manager._sessions))
        self.manager._sessions[sid].page=self.page
        self.touch=self.handoff.touch

    async def asyncTearDown(self):
        await self.context.close()
        await self.browser.close()
        await self.playwright.stop()

    def touch_request(self,payload):
        return request(ACTION_PATH,"POST",payload,cookie=self.cookie)

    async def tap(self,css):
        bb=await self.page.locator(css).bounding_box()
        self.assertIsNotNone(bb)
        x=(bb["x"]+bb["width"]/2)/508
        y=(bb["y"]+bb["height"]/2)/1074
        reply=await self.touch.action(self.touch_request({
            "kind":"tap","x":x,"y":y}))
        self.assertEqual(reply.status_code,200)

    async def test_real_chrome_screenshot_input_focus_and_mobile_scroll(self):
        shot=await self.touch.frame(request(FRAME_PATH,cookie=self.cookie))
        self.assertEqual(shot.status_code,200)
        self.assertTrue(shot.body.startswith(b"\xff\xd8"))
        self.assertGreater(len(shot.body),500)

        await self.tap("#email")
        secret_email="synthetic-no-real-email@example.invalid"
        typed=await self.touch.action(self.touch_request({
            "kind":"text","field":"text","text":secret_email}))
        self.assertEqual(typed.status_code,200)
        self.assertNotIn(secret_email.encode(),typed.body)
        self.assertEqual(await self.page.locator("#email").input_value(),
                         secret_email)

        await self.tap("#password")
        sentinel="SYNTHETIC_NOT_A_REAL_PASSWORD_123"
        sent=await self.touch.action(self.touch_request({
            "kind":"text","field":"password","text":sentinel}))
        self.assertEqual(sent.status_code,200)
        self.assertNotIn(sentinel.encode(),sent.body)
        self.assertEqual(await self.page.locator("#password").input_value(),
                         sentinel)

        await self.tap("#submit")
        self.assertEqual(await self.page.locator("#out").text_content(),
                         "synthetic-clicked")

        scrolled=await self.touch.action(self.touch_request({
            "kind":"scroll","delta":550}))
        self.assertEqual(scrolled.status_code,200)
        await self.page.wait_for_timeout(200)
        self.assertGreater(await self.page.evaluate("scrollY"),0)

        receipt=await self.handoff.finish(request(
            SETUP_PATH+"/finish","POST",{},cookie=self.cookie))
        self.assertEqual(receipt.status_code,200)
        self.assertEqual(self.guard.safe_sessions(),[])
        after=await self.touch.frame(request(FRAME_PATH,cookie=self.cookie))
        self.assertEqual(after.status_code,410)


if __name__=="__main__":
    unittest.main(verbosity=2)
