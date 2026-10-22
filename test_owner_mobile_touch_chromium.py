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
            if route.request.url == FACEBOOK:
                await route.fulfill(status=200,content_type="text/html",body=PAGE)
            else:
                await route.abort("blockedbyclient")
        await self.context.route("**/*",local_facebook)
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

    async def test_real_textarea_and_acknowledged_text_before_form_enter(self):
        await self.page.set_content("""<!doctype html><html><body>
        <script>window.syntheticSubmits = 0;</script>
        <form onsubmit="event.preventDefault(); window.syntheticSubmits += 1;
          document.getElementById('out').textContent =
          document.getElementById('email').value;">
          <textarea id="message" style="display:block;width:300px;height:100px"
            aria-label="Synthetic message"></textarea>
          <input id="email" type="email" required
            style="display:block;width:300px;height:45px"
            aria-label="Synthetic email">
          <button type="submit">Synthetic submit</button>
        </form><p id="out">waiting</p></body></html>""")
        await self.tap("#message")
        text="SYNTHETIC FIRST LINE\nSYNTHETIC SECOND LINE"
        sent=await self.touch.action(self.touch_request({
            "kind":"text","field":"text","text":text}))
        self.assertEqual(sent.status_code,200)
        self.assertEqual(await self.page.locator("#message").input_value(),text)
        wrong_field=await self.touch.action(self.touch_request({
            "kind":"text","field":"password","text":"MUST_NOT_WRITE"}))
        self.assertEqual(wrong_field.status_code,409)
        self.assertEqual(await self.page.locator("#message").input_value(),text)

        await self.tap("#email")
        email="synthetic@example.invalid"
        sent=await self.touch.action(self.touch_request({
            "kind":"text","field":"text","text":email}))
        self.assertEqual(sent.status_code,200)
        self.assertEqual(await self.page.evaluate("window.syntheticSubmits"),0)
        enter=await self.touch.action(self.touch_request({"kind":"key","key":"Enter"}))
        self.assertEqual(enter.status_code,200)
        self.assertEqual(await self.page.evaluate("window.syntheticSubmits"),1)
        self.assertEqual(await self.page.locator("#out").text_content(),email)

    async def test_real_history_and_reload_on_two_offline_pages(self):
        initial_url=self.page.url
        # A new Chromium page may retain about:blank as an actual history
        # entry. Explicitly establish the empty-history case on this offline
        # fixture rather than assuming that the first goto erased it.
        cdp=await self.context.new_cdp_session(self.page)
        try:
            await cdp.send("Page.resetNavigationHistory")
            history=await cdp.send("Page.getNavigationHistory")
            self.assertEqual(history["currentIndex"],0)
            self.assertEqual([entry["url"] for entry in history["entries"]],
                             [initial_url])
        finally:
            await cdp.detach()
        for kind in ("back","forward"):
            empty=await self.touch.action(self.touch_request({"kind":kind}))
            self.assertEqual(empty.status_code,200,
                             f"Empty-history {kind}: URL={self.page.url}")
            self.assertEqual(self.page.url,initial_url)

        first="https://www.facebook.com/synthetic-history-a"
        second="https://www.facebook.com/synthetic-history-b"
        loads={first:0,second:0}
        async def history_pages(route):
            url=route.request.url
            if url not in loads:
                await route.abort("blockedbyclient")
                return
            loads[url]+=1
            body=(f'<html><body><h1>{"A" if url==first else "B"}</h1>'
                  f'<p id="visit">{loads[url]}</p>'
                  f'<a id="next" href="{second}">Next synthetic page</a>'
                  '</body></html>')
            await route.fulfill(status=200,content_type="text/html",body=body,
                                headers={"Cache-Control":"no-store"})
        await self.context.route("**/*",history_pages)
        await self.page.goto(first,wait_until="domcontentloaded")
        await self.tap("#next")
        await self.page.wait_for_url(second,wait_until="domcontentloaded")
        self.assertEqual(self.page.url,second)
        self.assertEqual(await self.page.locator("h1").text_content(),"B")

        back=await self.touch.action(self.touch_request({"kind":"back"}))
        self.assertEqual(back.status_code,200)
        self.assertEqual(self.page.url,first)
        forward=await self.touch.action(self.touch_request({"kind":"forward"}))
        self.assertEqual(forward.status_code,200)
        self.assertEqual(self.page.url,second)
        before=loads[second]
        reload=await self.touch.action(self.touch_request({"kind":"reload"}))
        self.assertEqual(reload.status_code,200)
        self.assertEqual(loads[second],before+1)
        self.assertEqual(await self.page.locator("#visit").text_content(),str(before+1))

    async def test_real_back_cannot_strand_login_on_initial_blank(self):
        # Build exactly [about:blank, official fixture]. Navigating to blank
        # after a loaded document avoids initial-document replacement rules.
        await self.page.goto("about:blank",wait_until="domcontentloaded")
        cdp=await self.context.new_cdp_session(self.page)
        try:
            await cdp.send("Page.resetNavigationHistory")
            await self.page.goto(FACEBOOK,wait_until="domcontentloaded")
            history=await cdp.send("Page.getNavigationHistory")
            self.assertEqual(history["currentIndex"],1)
            self.assertEqual([entry["url"] for entry in history["entries"]],
                             ["about:blank",FACEBOOK])
        finally:
            await cdp.detach()

        back=await self.touch.action(self.touch_request({"kind":"back"}))
        self.assertEqual(back.status_code,200,
                         f"Initial-blank back: URL={self.page.url}")
        self.assertEqual(self.page.url,FACEBOOK)
        forward=await self.touch.action(self.touch_request({"kind":"forward"}))
        self.assertEqual(forward.status_code,200)
        self.assertEqual(self.page.url,FACEBOOK)
        frame=await self.touch.frame(request(FRAME_PATH,cookie=self.cookie))
        self.assertEqual(frame.status_code,200)
        await self.tap("#email")
        text="synthetic-still-active@example.invalid"
        typed=await self.touch.action(self.touch_request({
            "kind":"text","field":"text","text":text}))
        self.assertEqual(typed.status_code,200)
        self.assertEqual(await self.page.locator("#email").input_value(),text)

    async def test_real_history_cannot_return_an_out_of_scope_page_as_success(self):
        outside="https://phishing.example/synthetic-history"
        inside="https://www.facebook.com/synthetic-history"
        async def local_history(route):
            if route.request.url not in {outside,inside}:
                await route.abort("blockedbyclient")
                return
            await route.fulfill(status=200,content_type="text/html",
                                body="<html><body>Synthetic history</body></html>")
        await self.context.route("**/*",local_history)
        # Seed browser history directly inside the offline test, never by a
        # user-supplied mobile URL or a request to an external site.
        await self.page.goto(outside,wait_until="domcontentloaded")
        await self.page.goto(inside,wait_until="domcontentloaded")
        result=await self.touch.action(self.touch_request({"kind":"back"}))
        self.assertEqual(result.status_code,409)
        self.assertEqual(self.page.url,outside)
        frame=await self.touch.frame(request(FRAME_PATH,cookie=self.cookie))
        self.assertEqual(frame.status_code,410)
        blocked=await self.touch.action(self.touch_request({"kind":"forward"}))
        self.assertEqual(blocked.status_code,409)
        self.assertEqual(self.page.url,outside)

    async def test_multiservice_login_and_auth_redirects_with_real_chromium(self):
        # No network is needed for any service. The hostnames exercise the
        # production origin policy; every document below is synthetic.
        paths = {
            "https://chatgpt.com/auth/login",
            "https://auth.openai.com/log-in",
            "https://app.metricool.com/login",
            "https://www.canva.com/login/",
            "https://accounts.google.com/v3/signin/identifier",
            "https://phishing.example/login",
            "https://architekt.radom.pl/poradnik/wp-login.php",
            "https://weterynarz.radom.pl/wp-login.php",
        }
        async def local_only(route):
            if route.request.url in paths:
                await route.fulfill(status=200,content_type="text/html",body=PAGE)
            else:
                await route.abort("blockedbyclient")
        await self.context.route("**/*",local_only)
        services = (
            ("https://chatgpt.com/g/synthetic/project?tab=sources", (
                "https://chatgpt.com/auth/login", "https://auth.openai.com/log-in",
                "https://accounts.google.com/v3/signin/identifier")),
            ("https://app.metricool.com/planner", (
                "https://app.metricool.com/login", "https://accounts.google.com/v3/signin/identifier")),
            ("https://www.canva.com/design/synthetic/edit", (
                "https://www.canva.com/login/", "https://accounts.google.com/v3/signin/identifier")),
            ("https://architekt.radom.pl/poradnik/wp-admin/", (
                "https://architekt.radom.pl/poradnik/wp-login.php",)),
            ("https://weterynarz.radom.pl/wp-admin/", (
                "https://weterynarz.radom.pl/wp-login.php",)),
        )
        for supplied, expected_steps in services:
            with self.subTest(service=supplied):
                await self.handoff.cancel({"setup_id":self.setup["setup_id"]})
                self.setup=await self.handoff.create({
                    "profile":PROFILE,"login_url":supplied})
                token=self.setup["setup_url"].split("#s=",1)[1]
                claim=await self.handoff.claim(request(
                    SETUP_PATH+"/claim","POST",{"token":token}))
                self.assertEqual(claim.status_code,200)
                self.cookie=claim.headers["set-cookie"].split(";",1)[0]
                sid=next(iter(self.manager._sessions))
                self.manager._sessions[sid].page=self.page
                for step in expected_steps:
                    await self.page.goto(step,wait_until="domcontentloaded")
                    frame=await self.touch.frame(request(FRAME_PATH,cookie=self.cookie))
                    self.assertEqual(frame.status_code,200)
                    await self.tap("#password")
                    sent=await self.touch.action(self.touch_request({
                        "kind":"text","field":"password","text":"SYNTHETIC_SERVICE_VALUE"}))
                    self.assertEqual(sent.status_code,200)
                    self.assertEqual(await self.page.locator("#password").input_value(),
                                     "SYNTHETIC_SERVICE_VALUE")
                await self.page.goto("https://phishing.example/login")
                await self.page.locator("#password").focus()
                denied=await self.touch.action(self.touch_request({
                    "kind":"text","field":"password","text":"MUST_NOT_SEND"}))
                self.assertEqual(denied.status_code,409)
                self.assertEqual(await self.page.locator("#password").input_value(),"")
        finished=await self.handoff.finish(request(
            SETUP_PATH+"/finish","POST",{},cookie=self.cookie))
        self.assertEqual(finished.status_code,200)
        self.assertEqual(self.guard.safe_sessions(),[])


if __name__=="__main__":
    unittest.main(verbosity=2)
