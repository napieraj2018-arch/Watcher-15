"""iPhone WebKit touch UI smoke test with fully intercepted HTTPS requests.

No provider, Facebook, real tokens, credentials or open network. Chromium
remote-control path is tested separately; this tests the actual mobile DOM,
nonce CSP, touch events, image scaling and keyboard buttons in WebKit.
"""
from __future__ import annotations

import asyncio
import json
import unittest
from urllib.parse import urlsplit

from playwright.async_api import async_playwright
from starlette.responses import JSONResponse
from starlette.routing import Route

from test_owner_mobile_handoff import (
    FakeMobileManager, PROFILE, FACEBOOK, SETUP_PATH, request,
)
from multi_capability_guard import MultiCapabilityGuard
from owner_mobile_touch import PATH, FRAME_PATH, ACTION_PATH
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent /
                       "session_ownership" / "tests"))
from test_sdk_contract import fake_mcp


class IOSWebKitTouch(unittest.IsolatedAsyncioTestCase):
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
        setup=await self.handoff.create({"profile":PROFILE,"login_url":FACEBOOK})
        token=setup["setup_url"].split("#s=",1)[1]
        claimed=await self.handoff.claim(request(
            SETUP_PATH+"/claim","POST",{"token":token}))
        self.assertEqual(claimed.status_code,200)
        cookie=claimed.headers["set-cookie"].split(";",1)[0]
        view=await self.handoff.touch.home(request(PATH,cookie=cookie))
        self.assertEqual(view.status_code,200)

        self.browser_engine=await async_playwright().start()
        self.browser=await self.browser_engine.webkit.launch(headless=True)
        self.context=await self.browser.new_context(
            viewport={"width":390,"height":844},device_scale_factor=2,
            is_mobile=True,has_touch=True)
        self.page=await self.context.new_page()
        await self.page.set_content(
            "<html><body style='background:white'>Synthetic image</body></html>")
        self.sample_image=await self.page.screenshot(type="jpeg",quality=50)
        self.assertTrue(self.sample_image.startswith(b"\xff\xd8"))
        self.events=[]
        self.action_status=200
        self.action_gate=None

        async def mock_requests(route):
            url=route.request.url
            parsed=urlsplit(url)
            if (parsed.path==PATH and route.request.method=="GET"):
                await route.fulfill(
                    status=200,body=view.body,content_type="text/html",
                    headers={
                        "Content-Security-Policy":
                            view.headers["content-security-policy"],
                        "Cache-Control":"no-store"
                    })
            elif parsed.path==FRAME_PATH and route.request.method=="GET":
                await route.fulfill(
                    status=200,body=self.sample_image,
                    content_type="image/jpeg")
            elif parsed.path==ACTION_PATH and route.request.method=="POST":
                event=route.request.post_data_json
                self.events.append(event)
                if self.action_gate is not None:
                    await self.action_gate.wait()
                await route.fulfill(status=self.action_status,
                                    content_type="application/json",
                                    body='{"status":"ok"}' if self.action_status==200
                                    else '{"error":"TOUCH_ACTION_FAILED"}')
            else:
                await route.abort("blockedbyclient")

        await self.page.route("https://ai-browser-cloud.onrender.com/**",
                              mock_requests)
        await self.page.goto("https://ai-browser-cloud.onrender.com"+PATH,
                             wait_until="domcontentloaded")
        await self.page.locator("#touch-shot").wait_for(state="visible")
        await self.page.wait_for_function(
            "document.querySelector('#touch-shot').naturalWidth > 0")

    async def asyncTearDown(self):
        if self.action_gate is not None:
            self.action_gate.set()
        await self.context.close()
        await self.browser.close()
        await self.browser_engine.stop()

    async def wait_for_events(self,number):
        for _ in range(45):
            if len(self.events)>=number:
                return
            await asyncio.sleep(.035)
        self.fail(f"Expected {number} touch requests, got {len(self.events)}")

    async def test_webkit_touch_and_native_keyboard_controls(self):
        img=self.page.locator("#touch-shot")
        box=await img.bounding_box()
        self.assertGreater(box["width"],250)
        self.assertLessEqual(box["width"],390)
        await img.tap(position={"x":75,"y":55})
        await self.wait_for_events(1)
        first=self.events[0]
        self.assertEqual(first["kind"],"tap")
        self.assertGreater(first["x"],0)
        self.assertLess(first["x"],1)
        self.assertGreater(first["y"],0)
        self.assertLess(first["y"],1)

        await self.page.locator("#touch-value").fill("synthetic@example.invalid")
        await self.page.locator("#touch-send").tap()
        await self.wait_for_events(2)
        self.assertEqual(self.events[1],{
            "kind":"text","field":"text",
            "text":"synthetic@example.invalid"})
        self.assertEqual(await self.page.locator("#touch-value").input_value(),"")

        secret="SYNTHETIC_ONLY_NOT_REAL"
        await self.page.locator("#touch-password").fill(secret)
        self.assertEqual(await self.page.locator(
            "#touch-password").get_attribute("type"),"password")
        await self.page.locator("#touch-send-password").tap()
        await self.wait_for_events(3)
        self.assertEqual(self.events[2],{
            "kind":"text","field":"password","text":secret})
        self.assertEqual(await self.page.locator(
            "#touch-password").input_value(),"")

        await self.page.locator("#touch-enter").tap()
        await self.wait_for_events(4)
        self.assertEqual(self.events[3],{"kind":"key","key":"Enter"})
        self.assertEqual(
            await self.page.locator("#touch-status").text_content(),
            "Wykonano. Odświeżam widok…")

    async def test_native_enter_sends_current_text_or_password_before_enter(self):
        for element_id,field,text in (
            ("touch-value","text","synthetic@example.invalid"),
            ("touch-password","password","SYNTHETIC_NOT_A_PASSWORD"),
        ):
            with self.subTest(field=field):
                before=len(self.events)
                element=self.page.locator("#"+element_id)
                await element.fill(text)
                await element.press("Enter")
                await self.wait_for_events(before+2)
                await self.page.wait_for_function(
                    "id => document.getElementById(id).value === ''",arg=element_id)
                self.assertEqual(self.events[before:],[
                    {"kind":"text","field":field,"text":text},
                    {"kind":"key","key":"Enter"},
                ])

    async def test_enter_button_remembers_last_local_editor_after_focus_moves(self):
        await self.page.locator("#touch-value").fill("UNSENT_OTHER_FIELD")
        await self.page.locator("#touch-password").fill("SYNTHETIC_CURRENT_FIELD")
        button=self.page.locator("#touch-enter")
        await button.focus()
        self.assertEqual(await self.page.evaluate("document.activeElement.id"),"touch-enter")
        await button.tap()
        await self.wait_for_events(2)
        await self.page.wait_for_function(
            "document.getElementById('touch-password').value === ''")
        self.assertEqual(self.events,[
            {"kind":"text","field":"password","text":"SYNTHETIC_CURRENT_FIELD"},
            {"kind":"key","key":"Enter"},
        ])
        self.assertEqual(await self.page.locator("#touch-value").input_value(),
                         "UNSENT_OTHER_FIELD")

    async def test_failed_text_keeps_local_value_and_never_submits(self):
        self.action_status=409
        element=self.page.locator("#touch-password")
        await element.fill("SYNTHETIC_KEEP_ON_FAILURE")
        await element.press("Enter")
        await self.wait_for_events(1)
        await self.page.wait_for_function(
            "document.getElementById('touch-status').textContent.startsWith('Nie udało')")
        self.assertEqual(self.events,[{
            "kind":"text","field":"password","text":"SYNTHETIC_KEEP_ON_FAILURE"}])
        self.assertEqual(await element.input_value(),"SYNTHETIC_KEEP_ON_FAILURE")

    async def test_busy_enter_does_not_duplicate_text_or_submit(self):
        self.action_gate=asyncio.Event()
        element=self.page.locator("#touch-value")
        await element.fill("synthetic@example.invalid")
        await element.press("Enter")
        await self.wait_for_events(1)
        await self.page.locator("#touch-enter").tap()
        self.assertEqual(len(self.events),1)
        self.assertEqual(await element.input_value(),"synthetic@example.invalid")
        self.assertIn("Trwa poprzednia operacja",
                      await self.page.locator("#touch-status").text_content())
        self.action_gate.set()
        await self.wait_for_events(2)
        await self.page.wait_for_function(
            "document.getElementById('touch-value').value === ''")
        self.assertEqual(self.events,[
            {"kind":"text","field":"text","text":"synthetic@example.invalid"},
            {"kind":"key","key":"Enter"},
        ])

    async def test_composing_or_repeated_enter_does_not_submit(self):
        element=self.page.locator("#touch-value")
        await element.fill("SYNTHETIC_COMPOSING")
        await element.dispatch_event("keydown",{"key":"Enter","isComposing":True})
        await element.dispatch_event("keydown",{"key":"Enter","repeat":True})
        self.assertEqual(self.events,[])
        self.assertEqual(await element.input_value(),"SYNTHETIC_COMPOSING")

    async def test_navigation_buttons_send_only_fixed_actions(self):
        for count,kind in enumerate(("back","forward","reload"),1):
            await self.page.locator("#touch-"+kind).tap()
            await self.wait_for_events(count)
            await self.page.wait_for_function(
                "document.getElementById('touch-status').textContent.startsWith('Wykonano')")
        self.assertEqual(self.events,[
            {"kind":"back"},{"kind":"forward"},{"kind":"reload"}])


if __name__=="__main__":
    unittest.main(verbosity=2)
