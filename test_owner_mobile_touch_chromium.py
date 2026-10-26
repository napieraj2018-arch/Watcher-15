"""Offline REAL Chromium integration of the owner-scoped iPhone touch bridge.

No Steel Cloud calls. No Facebook network requests, cookies, tokens or real
accounts. The exact Facebook login URL is intercepted and locally fulfilled
with a synthetic page. Exercises actual Playwright mouse, keyboard, focus,
input events and screenshot paths, not merely fake methods.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
from tempfile import TemporaryDirectory
import unittest
from playwright.async_api import TimeoutError as PlaywrightTimeoutError, async_playwright
from starlette.responses import JSONResponse
from starlette.routing import Route

from multi_capability_guard import MultiCapabilityGuard
from test_owner_mobile_handoff import (
    FakeMobileManager, PROFILE, FACEBOOK, SETUP_PATH, request,
)
from owner_mobile_touch import FRAME_PATH, ACTION_PATH, TABS_PATH
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
        if "ref" not in payload:
            record=self.handoff.active
            lease=self.guard.authorize(record.handle)
            rows=self.touch._tab_inventory(
                self.manager._sessions[lease.internal_session_id],record)["tabs"]
            ref=next((row["ref"] for row in rows if row["active"]),"X"*16)
            payload={**payload,"ref":ref}
        return request(ACTION_PATH,"POST",payload,cookie=self.cookie)

    async def tap(self,css,page=None):
        bb=await (page or self.page).locator(css).bounding_box()
        self.assertIsNotNone(bb)
        x=(bb["x"]+bb["width"]/2)/508
        y=(bb["y"]+bb["height"]/2)/1074
        reply=await self.touch.action(self.touch_request({
            "kind":"tap","x":x,"y":y}))
        self.assertEqual(reply.status_code,200)

    @asynccontextmanager
    async def external_chromium_over_cdp(self):
        # Like Steel, this browser is started independently of Playwright and
        # then attached over CDP. Every page/resource is intercepted below.
        # Disable BFCache only to force a deterministic delayed-resource case.
        with TemporaryDirectory(prefix="aib-synthetic-history-") as directory:
            process=await asyncio.create_subprocess_exec(
                self.playwright.chromium.executable_path,
                "--headless=new","--no-sandbox","--no-first-run",
                "--disable-dev-shm-usage",
                "--no-default-browser-check","--disable-background-networking",
                "--disable-component-update","--disable-sync",
                "--disable-features=BackForwardCache",
                "--remote-debugging-address=127.0.0.1","--remote-debugging-port=0",
                "--user-data-dir="+directory,"about:blank",
                stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.DEVNULL)
            browser=None
            try:
                async def endpoint():
                    active_port=Path(directory)/"DevToolsActivePort"
                    while True:
                        if active_port.exists():
                            lines=active_port.read_text().splitlines()
                            if lines and lines[0].isdigit():
                                return "http://127.0.0.1:"+lines[0]
                        if process.returncode is not None:
                            raise RuntimeError("SYNTHETIC_CHROMIUM_START_FAILED")
                        await asyncio.sleep(0.05)
                browser=await self.playwright.chromium.connect_over_cdp(
                    await asyncio.wait_for(endpoint(),10),timeout=10000)
                yield browser
            finally:
                try:
                    if browser is not None:
                        await browser.close()
                finally:
                    if process.returncode is None:
                        process.terminate()
                        try:
                            await asyncio.wait_for(process.wait(),3)
                        except asyncio.TimeoutError:
                            process.kill()
                            await process.wait()

    async def test_real_numeric_verification_input_and_password_type_guard(self):
        await self.page.set_content('<input id="otp" type="number" '
                                    'aria-label="Synthetic verification code">')
        await self.tap("#otp")
        typed=await self.touch.action(self.touch_request({
            "kind":"text","field":"text","text":"123456"}))
        self.assertEqual(typed.status_code,200)
        self.assertEqual(await self.page.locator("#otp").input_value(),"123456")
        denied=await self.touch.action(self.touch_request({
            "kind":"text","field":"password","text":"SYNTHETIC_SECRET"}))
        self.assertEqual(denied.status_code,409)
        invalid=await self.touch.action(self.touch_request({
            "kind":"text","field":"text","text":"not-a-number"}))
        self.assertEqual(invalid.status_code,409)
        self.assertEqual(await self.page.locator("#otp").input_value(),"123456")

    async def test_real_focused_login_and_code_hints_never_read_values(self):
        await self.page.set_content('''<input id="email" type="email"
          name="SYNTHETIC_PRIVATE_EMAIL_NAME" value="SYNTHETIC_PRIVATE_EMAIL_VALUE">
          <input id="password" type="password" value="SYNTHETIC_PRIVATE_PASSWORD">
          <input id="code" type="text" autocomplete="one-time-code" value="012345">
          <input id="readonly" type="text" readonly value="SYNTHETIC_PRIVATE_READONLY">''')
        for field,kind in (("email","email"),("password","password"),
                           ("code","code"),("readonly",None)):
            await self.page.locator("#"+field).focus()
            response=await self.touch.tabs(request(TABS_PATH,cookie=self.cookie))
            self.assertEqual(response.status_code,200)
            self.assertEqual(json.loads(response.body)["focus_kind"],kind)
            self.assertNotIn(b"SYNTHETIC_PRIVATE",response.body)
            self.assertNotIn(b"012345",response.body)

    async def test_real_scoped_popup_can_be_selected_filled_and_return_to_opener(self):
        popup_url="https://m.facebook.com/synthetic-auth?state=SYNTHETIC_PRIVATE_QUERY"
        async def popup_document(route):
            await route.fulfill(status=200,content_type="text/html",body='''
                <html><body><input id="otp" type="number">
                <button id="finish" onclick="window.opener.postMessage(
                  'synthetic-auth-finished','https://www.facebook.com');
                  window.close()">Finish synthetic login</button></body></html>''')
        await self.context.route(popup_url,popup_document)
        await self.page.set_content('''<html><body>
          <p id="result">waiting</p>
          <button id="open" onclick="window.open('''+repr(popup_url)+''',
            'synthetic-login')">Open synthetic login popup</button>
          <script>addEventListener('message',e=>{
            if(e.origin==='https://m.facebook.com')
              document.getElementById('result').textContent=e.data;
          });</script></body></html>''')
        async with self.context.expect_page() as popup_info:
            await self.tap("#open")
        popup=await popup_info.value
        await popup.wait_for_load_state("domcontentloaded")
        inventory=await self.touch.tabs(request(TABS_PATH,cookie=self.cookie))
        self.assertEqual(inventory.status_code,200)
        self.assertNotIn(b"SYNTHETIC_PRIVATE_QUERY",inventory.body)
        rows=json.loads(inventory.body)["tabs"]
        self.assertEqual(len(rows),2)
        popup_ref=next(row["ref"] for row in rows if not row["active"])
        switch=await self.touch.action(self.touch_request({
            "kind":"switch_tab","ref":popup_ref}))
        self.assertEqual(switch.status_code,200)
        frame=await self.touch.frame(request(FRAME_PATH,cookie=self.cookie))
        self.assertEqual(frame.status_code,200)
        await self.tap("#otp",page=popup)
        typed=await self.touch.action(self.touch_request({
            "kind":"text","field":"text","text":"123456"}))
        self.assertEqual(typed.status_code,200)
        self.assertEqual(await popup.locator("#otp").input_value(),"123456")
        async with popup.expect_event("close"):
            await self.tap("#finish",page=popup)
        await self.page.wait_for_function(
            "document.getElementById('result').textContent === 'synthetic-auth-finished'")
        self.assertTrue(popup.is_closed())
        returned=await self.touch.frame(request(FRAME_PATH,cookie=self.cookie))
        self.assertEqual(returned.status_code,200)
        rows=json.loads((await self.touch.tabs(
            request(TABS_PATH,cookie=self.cookie))).body)["tabs"]
        self.assertEqual(len(rows),1)
        self.assertTrue(rows[0]["active"])
        stale_input=await self.touch.action(self.touch_request({
            "kind":"text","field":"text","text":"MUST_NOT_REACH_OPENER",
            "ref":popup_ref}))
        self.assertEqual(stale_input.status_code,409)
        stale=await self.touch.action(self.touch_request({
            "kind":"switch_tab","ref":popup_ref}))
        self.assertEqual(stale.status_code,409)

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

    async def test_owner_scroll_targets_cross_origin_frame_without_inspecting_or_clicking_it(self):
        # Neutral cross-origin iframe, not a verification provider/challenge.
        await self.context.route('https://nested.synthetic.invalid/frame',
            lambda route: route.fulfill(status=200,content_type='text/html',body=
                '<html><body style="margin:0;height:2500px">Neutral nested scroll</body></html>'))
        await self.page.set_content('<html><body style="margin:0;height:3000px">'
            '<iframe name="nested" src="https://nested.synthetic.invalid/frame" '
            'style="position:absolute;left:40px;top:40px;width:320px;height:240px"></iframe></body></html>')
        await self.page.locator('iframe').wait_for()
        frame=self.page.frame(name='nested')
        await frame.wait_for_load_state('domcontentloaded')
        await self.page.mouse.move(500,800)  # Simulate a stale previous pointer.
        response=await self.touch.action(self.touch_request({'kind':'scroll','delta':320,'x':.25,'y':.12}))
        self.assertEqual(response.status_code,200)
        await frame.wait_for_function('scrollY > 0')
        self.assertEqual(await self.page.evaluate('scrollY'),0)
        response=await self.touch.action(self.touch_request({'kind':'scroll','delta':320,'x':.94,'y':.6}))
        self.assertEqual(response.status_code,200)
        await self.page.wait_for_function('scrollY > 0')

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

    async def test_real_cdp_history_returns_before_a_deferred_script_finishes(self):
        first="https://www.facebook.com/synthetic-deferred-a"
        second="https://www.facebook.com/synthetic-deferred-b"
        documents={first:"A",second:"B"}
        scripts={url+".js" for url in documents}
        loads={url:0 for url in documents}
        delay_scripts=False
        script_entered=asyncio.Event()
        script_continue=asyncio.Event()

        async def synthetic_routes(route):
            url=route.request.url
            if url in documents:
                loads[url]+=1
                await route.fulfill(status=200,content_type="text/html",
                    headers={"Cache-Control":"no-store"},body=(
                        '<!doctype html><html><head><script defer src="'+url+
                        '.js"></script></head><body><h1>'+documents[url]+
                        '</h1></body></html>'))
            elif url in scripts:
                if delay_scripts:
                    script_entered.set()
                    await script_continue.wait()
                await route.fulfill(status=200,content_type="application/javascript",
                                    body="window.syntheticDeferredFinished=true;")
            else:
                await route.abort("blockedbyclient")

        session=self.manager._sessions[next(iter(self.manager._sessions))]
        original_page=session.page
        async with self.external_chromium_over_cdp() as browser:
            context=browser.contexts[0]
            await context.route("**/*",synthetic_routes)
            page=await context.new_page()
            session.page=page
            try:
                await page.goto(first,wait_until="domcontentloaded")
                await page.goto(second,wait_until="domcontentloaded")
                delay_scripts=True
                for kind,target in (("back",first),("forward",second)):
                    script_entered=asyncio.Event()
                    script_continue=asyncio.Event()
                    # The old DOMContentLoaded wait cannot complete while the
                    # deferred response is held. Commit must acknowledge the
                    # history move once, before releasing that response.
                    response=await asyncio.wait_for(self.touch.action(
                        self.touch_request({"kind":kind})),3)
                    self.assertEqual(response.status_code,200)
                    self.assertEqual(page.url,target)
                    await asyncio.wait_for(script_entered.wait(),2)
                    self.assertEqual(loads[target],2)
                    self.assertEqual(await page.locator("h1").text_content(timeout=2000),
                                     documents[target])
                    with self.assertRaises(PlaywrightTimeoutError):
                        await page.wait_for_load_state("domcontentloaded",timeout=150)
                    script_continue.set()
                    await page.wait_for_load_state("domcontentloaded",timeout=2000)
            finally:
                script_continue.set()
                session.page=original_page
                await context.unroute_all(behavior="wait")

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
