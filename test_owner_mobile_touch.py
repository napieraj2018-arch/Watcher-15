"""Isolated mobile screenshot/touch/keyboard bridge tests. No Meta or Steel I/O."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase

from starlette.responses import JSONResponse
from starlette.routing import Route

from owner_mobile_touch import PATH, FRAME_PATH, ACTION_PATH
from test_owner_mobile_handoff import (
    FakeMobileManager, request, SETUP_PATH, SETUP_ORIGIN, PROFILE, FACEBOOK,
)
from multi_capability_guard import MultiCapabilityGuard
from capability_guard import OwnershipError

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent /
                       "session_ownership" / "tests"))
from test_sdk_contract import fake_mcp


class FakeMouse:
    def __init__(self):
        self.clicks=[]
        self.scrolls=[]

    async def click(self,x,y):
        self.clicks.append((x,y))

    async def wheel(self,x,y):
        self.scrolls.append((x,y))


class FakeKeyboard:
    def __init__(self):
        self.presses=[]

    async def press(self,key):
        self.presses.append(key)


class FakeFocused:
    def __init__(self):
        self.field_type="email"
        self.tag="INPUT"
        self.disabled=False
        self.readonly=False
        self.fills=[]

    async def element_handle(self,timeout=0):
        return self

    async def evaluate(self,script):
        return {"tag":self.tag,"type":self.field_type,
                "disabled":self.disabled,"readOnly":self.readonly}

    async def fill(self,content,timeout=0):
        self.fills.append((content,timeout))


class FakePage:
    viewport_size={"width":508,"height":1074}

    def __init__(self):
        self.url="https://www.facebook.com/login/"
        self.mouse=FakeMouse()
        self.keyboard=FakeKeyboard()
        self.focused=FakeFocused()
        self.screenshots=0

    async def screenshot(self,**kwargs):
        self.screenshots += 1
        assert kwargs=={
            "type":"jpeg","quality":65,"full_page":False,"timeout":10000}
        return b"\xff\xd8" + b"SYNTHETIC_IMAGE_NOT_FROM_REAL_USER" + b"\xff\xd9"

    def locator(self,selector):
        assert selector == ":focus"
        return self.focused


class TouchTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.manager=FakeMobileManager()
        self.mcp=fake_mcp(self.manager)
        async def legacy(_):
            return JSONResponse({"leak":"unprotected"})
        self.mcp._custom_starlette_routes.append(
            Route("/setup/legacy",legacy,methods=["POST"]))
        self.guard=MultiCapabilityGuard(
            self.mcp,self.manager,capacity=5,watchdog_enabled=False)
        self.assertEqual(self.guard.install(),51)
        self.handoff=self.guard.mobile_handoff
        self.handoff.clock=lambda:100
        self.setup=await self.handoff.create({
            "profile":PROFILE,"login_url":FACEBOOK})
        self.token=self.setup["setup_url"].split("#s=",1)[1]
        self.claim=await self.handoff.claim(request(
            SETUP_PATH+"/claim","POST",{"token":self.token}))
        self.cookie=self.claim.headers["set-cookie"].split(";",1)[0]
        self.page=FakePage()
        sid=next(iter(self.manager._sessions))
        self.manager._sessions[sid].page=self.page
        self.touch=self.handoff.touch

    def action_request(self,payload,cookie=None,origin=SETUP_ORIGIN,
                       content_type="application/json"):
        return request(ACTION_PATH,"POST",payload,
                       cookie=self.cookie if cookie is None else cookie,
                       origin=origin,content_type=content_type)

    async def test_real_session_only_renders_own_screenshot(self):
        frame=await self.touch.frame(request(FRAME_PATH,cookie=self.cookie))
        self.assertEqual(frame.status_code,200)
        self.assertEqual(frame.media_type,"image/jpeg")
        self.assertEqual(self.page.screenshots,1)
        self.assertIn(b"SYNTHETIC_IMAGE",frame.body)
        self.assertIn("no-store",frame.headers["cache-control"])
        anonymous=await self.touch.frame(request(FRAME_PATH))
        self.assertEqual(anonymous.status_code,410)
        self.assertEqual(self.page.screenshots,1)

    async def test_touch_page_is_mobile_accessible_and_scoped(self):
        page=await self.touch.home(request(PATH,cookie=self.cookie))
        self.assertEqual(page.status_code,200)
        self.assertIn(b"touch-shot",page.body)
        self.assertIn(b"pointerdown",page.body)
        self.assertIn(b"touch-password",page.body)
        self.assertIn(b"Sterowanie dotykowe",page.body)
        self.assertNotIn(self.token.encode(),page.body)
        self.assertNotIn(b"app.steel.dev/sessions/synthetic-valid-debug",page.body)
        anonymous=await self.touch.home(request(PATH))
        self.assertEqual(anonymous.status_code,403)

    async def test_tap_maps_to_remote_viewport(self):
        resp=await self.touch.action(self.action_request({
            "kind":"tap","x":0.5,"y":0.25}))
        self.assertEqual(resp.status_code,200)
        self.assertEqual(self.page.mouse.clicks,[(254,268)])
        self.assertEqual(self.page.keyboard.presses,[])

    async def test_swipe_and_keys_are_allowlisted(self):
        wheel=await self.touch.action(self.action_request({
            "kind":"scroll","delta":480}))
        self.assertEqual(wheel.status_code,200)
        self.assertEqual(self.page.mouse.scrolls,[(0,480)])
        for key in ("Enter","Tab","Backspace"):
            v=await self.touch.action(self.action_request({"kind":"key","key":key}))
            self.assertEqual(v.status_code,200)
        self.assertEqual(self.page.keyboard.presses,
                         ["Enter","Tab","Backspace"])

    async def test_password_never_leaks_to_text_field_or_result(self):
        secret="SYNTHETIC_NOT_A_PASSWORD!123"
        denied=await self.touch.action(self.action_request({
            "kind":"text","field":"password","text":secret}))
        self.assertEqual(denied.status_code,409)
        self.assertNotIn(secret.encode(),denied.body)
        self.assertEqual(self.page.focused.fills,[])
        self.page.focused.field_type="password"
        success=await self.touch.action(self.action_request({
            "kind":"text","field":"password","text":secret}))
        self.assertEqual(success.status_code,200)
        self.assertEqual(self.page.focused.fills,[(secret,7000)])
        self.assertNotIn(secret.encode(),success.body)
        wrong=await self.touch.action(self.action_request({
            "kind":"text","field":"text","text":"not-a-password"}))
        self.assertEqual(wrong.status_code,409)
        self.assertEqual(len(self.page.focused.fills),1)

    async def test_regular_email_field_uses_playwright_fill(self):
        word="test@example.com"
        resp=await self.touch.action(self.action_request({
            "kind":"text","field":"text","text":word}))
        self.assertEqual(resp.status_code,200)
        self.assertEqual(self.page.focused.fills,[(word,7000)])
        self.assertNotIn(word.encode(),resp.body)

    async def test_readonly_or_disabled_focus_rejects_writes(self):
        self.page.focused.readonly=True
        denied=await self.touch.action(self.action_request({
            "kind":"text","field":"text","text":"NO!"}))
        self.assertEqual(denied.status_code,409)
        self.assertEqual(self.page.focused.fills,[])

    async def test_cross_site_csrf_and_no_cookie_denied(self):
        a=await self.touch.action(self.action_request(
            {"kind":"tap","x":0.2,"y":0.4},origin="https://evil.example"))
        b=await self.touch.action(self.action_request(
            {"kind":"tap","x":0.2,"y":0.4},cookie=""))
        c=await self.touch.action(self.action_request(
            {"kind":"tap","x":0.2,"y":0.4},content_type="text/plain"))
        self.assertEqual([a.status_code,b.status_code,c.status_code],
                         [403,403,403])
        self.assertEqual(self.page.mouse.clicks,[])

    async def test_input_validation_rejects_scripts_url_or_invalid_coords(self):
        invalid=[
            {"kind":"tap","x":1.1,"y":0.2},
            {"kind":"tap","x":True,"y":0.2},
            {"kind":"scroll","delta":999999},
            {"kind":"key","key":"Control+V"},
            {"kind":"script","source":"alert(1)"},
            {"kind":"navigate","url":"https://evil.example"},
            {"kind":"text","field":"text","text":"X"*500},
        ]
        for item in invalid:
            with self.subTest(item=item["kind"]):
                r=await self.touch.action(self.action_request(item))
                self.assertEqual(r.status_code,400)
        self.assertEqual(self.page.mouse.clicks,[])
        self.assertEqual(self.page.focused.fills,[])

    async def test_other_browser_owned_by_other_chat_untouched(self):
        other=await self.mcp.call_tool("browser_start",{
            "profile":"Meta - Other-Synthetic",
            "start_url":"https://example.com/"})
        self.assertEqual(len(self.manager._sessions),2)
        done=await self.touch.action(self.action_request({
            "kind":"tap","x":0.25,"y":0.25}))
        self.assertEqual(done.status_code,200)
        self.assertEqual(self.page.mouse.clicks,[(127,268)])
        profiles=sorted(x.profile for x in self.manager._sessions.values())
        self.assertEqual(profiles,["Meta - Other-Synthetic",PROFILE])

    async def test_phishing_redirect_blocks_screenshots_and_password(self):
        self.page.url="https://www.facebook.com.evil.test/login"
        frame=await self.touch.frame(request(FRAME_PATH,cookie=self.cookie))
        self.assertEqual(frame.status_code,410)
        denied=await self.touch.action(self.action_request({
            "kind":"text","field":"password","text":"SYNTHETIC_ONLY"}))
        self.assertEqual(denied.status_code,409)
        self.assertEqual(self.page.focused.fills,[])
        self.page.url="http://www.facebook.com/login"
        denied_http=await self.touch.action(self.action_request({
            "kind":"tap","x":0.4,"y":0.4}))
        self.assertEqual(denied_http.status_code,409)
        self.assertEqual(self.page.mouse.clicks,[])

    async def test_supported_login_service_can_reach_only_its_scoped_origins(self):
        cases = (
            ("https://chatgpt.com/", (
                "https://chatgpt.com/auth/login", "https://auth.openai.com/log-in",
                "https://auth0.openai.com/u/login", "https://accounts.google.com/v3/signin"),
                "https://app.metricool.com/login"),
            ("https://app.metricool.com/planner", (
                "https://app.metricool.com/login", "https://accounts.google.com/v3/signin",
                "https://www.facebook.com/login/"), "https://www.canva.com/login/"),
            ("https://www.canva.com/", (
                "https://www.canva.com/login/", "https://accounts.google.com/v3/signin"),
                "https://chatgpt.com/auth/login"),
            ("https://www.instagram.com/", (
                "https://www.instagram.com/accounts/login/", "https://www.facebook.com/login/"),
                "https://accounts.google.com/ServiceLogin"),
            ("https://architekt.radom.pl/poradnik/wp-admin/", (
                "https://architekt.radom.pl/poradnik/wp-login.php",),
                "https://weterynarz.radom.pl/wp-login.php"),
            ("https://weterynarz.radom.pl/wp-admin/", (
                "https://weterynarz.radom.pl/wp-login.php",),
                "https://architekt.radom.pl/poradnik/wp-login.php"),
        )
        for supplied, allowed, denied in cases:
            with self.subTest(supplied=supplied):
                await self.handoff.cancel({"setup_id":self.setup["setup_id"]})
                self.setup = await self.handoff.create({"profile":PROFILE,"login_url":supplied})
                token = self.setup["setup_url"].split("#s=",1)[1]
                claimed = await self.handoff.claim(request(
                    SETUP_PATH+"/claim", "POST", {"token":token}))
                self.cookie = claimed.headers["set-cookie"].split(";",1)[0]
                sid = next(iter(self.manager._sessions))
                self.page = FakePage()
                self.page.focused.field_type = "password"
                self.manager._sessions[sid].page = self.page
                for url in allowed:
                    self.page.url = url
                    frame = await self.touch.frame(request(FRAME_PATH,cookie=self.cookie))
                    self.assertEqual(frame.status_code,200)
                    typed = await self.touch.action(self.action_request({
                        "kind":"text", "field":"password", "text":"SYNTHETIC_ONLY"}))
                    self.assertEqual(typed.status_code,200)
                count = len(self.page.focused.fills)
                self.page.url = denied
                frame = await self.touch.frame(request(FRAME_PATH,cookie=self.cookie))
                self.assertEqual(frame.status_code,410)
                typed = await self.touch.action(self.action_request({
                    "kind":"text", "field":"password", "text":"MUST_NOT_SEND"}))
                self.assertEqual(typed.status_code,409)
                self.assertEqual(len(self.page.focused.fills),count)

    async def test_navigation_during_field_inspection_does_not_forward_input(self):
        self.page.focused.field_type = "password"
        original = self.page.focused.evaluate
        async def navigate_during_inspection(script):
            info = await original(script)
            self.page.url = "https://phishing.example/"
            return info
        self.page.focused.evaluate = navigate_during_inspection
        denied = await self.touch.action(self.action_request({
            "kind":"text", "field":"password", "text":"MUST_NOT_SEND"}))
        self.assertEqual(denied.status_code,409)
        self.assertEqual(self.page.focused.fills,[])

    async def test_invalid_page_origins_cannot_receive_input(self):
        for url in (
            "https://www.facebook.com./login", "https://www.facebook.com:444/login",
            "https://evil@www.facebook.com/login", "https://www.facebook.com/\\evil.test",
            "https://unknown.facebook.com/login", "https://www.facebook.com/ ",
            "https://chatgpt.com/auth/login", "about:blank",
        ):
            with self.subTest(url=url):
                self.page.url=url
                denied=await self.touch.action(self.action_request({
                    "kind":"tap","x":0.4,"y":0.4}))
                self.assertEqual(denied.status_code,409)
        self.assertEqual(self.page.mouse.clicks,[])

    async def test_quarantine_fails_closed_without_remote_actions(self):
        self.guard.quarantined=True
        frame=await self.touch.frame(request(FRAME_PATH,cookie=self.cookie))
        touch=await self.touch.action(self.action_request({
            "kind":"tap","x":0.25,"y":0.25}))
        self.assertEqual(frame.status_code,410)
        self.assertEqual(touch.status_code,403)
        self.assertEqual(self.page.mouse.clicks,[])
        self.assertEqual(self.page.screenshots,0)

    async def test_expired_or_finished_session_cannot_receive_input(self):
        self.handoff.clock=lambda:1000
        old=await self.touch.action(self.action_request({
            "kind":"tap","x":0.5,"y":0.5}))
        self.assertEqual(old.status_code,403)
        self.assertEqual(self.page.mouse.clicks,[])


if __name__ == "__main__":
    import unittest
    unittest.main(verbosity=2)
