"""Isolated mobile screenshot/touch/keyboard bridge tests. No Meta or Steel I/O."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from starlette.responses import JSONResponse
from starlette.routing import Route

from owner_mobile_touch import PATH, FRAME_PATH, ACTION_PATH, TABS_PATH
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
        self.moves=[]

    async def move(self,x,y):
        self.moves.append((x,y))

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


class FakeHistorySession:
    def __init__(self,page):
        self.page=page

    async def send(self,method):
        assert method == "Page.getNavigationHistory"
        self.page.history_reads+=1
        if self.page.history_error:
            raise RuntimeError("SYNTHETIC_PRIVATE_HISTORY_ERROR")
        return self.page.history

    async def detach(self):
        self.page.history_detaches+=1
        if self.page.history_detach_blocked:
            await asyncio.Event().wait()
        if self.page.history_redirect is not None:
            self.page.url=self.page.history_redirect


class FakePage:
    viewport_size={"width":508,"height":1074}

    def __init__(self):
        self.url="https://www.facebook.com/login/"
        self.mouse=FakeMouse()
        self.keyboard=FakeKeyboard()
        self.focused=FakeFocused()
        self.screenshots=0
        self.navigations=[]
        self.navigation_target=None
        self.history={"currentIndex":0,"entries":[{"url":self.url}]}
        self.history_reads=0
        self.history_detaches=0
        self.history_error=False
        self.history_redirect=None
        self.history_detach_blocked=False
        self.closed=False
        self.fronts=0
        self.context=SimpleNamespace(new_cdp_session=self.new_cdp_session,
                                     pages=[self])

    def is_closed(self):
        return self.closed

    async def bring_to_front(self):
        self.fronts+=1

    async def new_cdp_session(self,page):
        assert page is self
        return FakeHistorySession(self)

    async def screenshot(self,**kwargs):
        self.screenshots += 1
        assert kwargs=={
            "type":"jpeg","quality":65,"full_page":False,"timeout":10000}
        return b"\xff\xd8" + b"SYNTHETIC_IMAGE_NOT_FROM_REAL_USER" + b"\xff\xd9"

    def locator(self,selector):
        assert selector == ":focus"
        return self.focused

    async def _navigate(self,kind,**kwargs):
        self.navigations.append((kind,kwargs))
        if self.navigation_target is not None:
            self.url=self.navigation_target
        return None

    async def go_back(self,**kwargs):
        return await self._navigate("back",**kwargs)

    async def go_forward(self,**kwargs):
        return await self._navigate("forward",**kwargs)

    async def reload(self,**kwargs):
        return await self._navigate("reload",**kwargs)


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
        if "ref" not in payload:
            record=self.handoff.active
            lease=self.guard.authorize(record.handle)
            rows=self.touch._tab_inventory(
                self.manager._sessions[lease.internal_session_id],record)["tabs"]
            current=next((row["ref"] for row in rows if row["active"]),"X"*16)
            payload={**payload,"ref":current}
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

    async def test_focus_hint_is_a_fixed_kind_and_never_returns_remote_contents(self):
        for candidate,expected in (
            ("password","password"),("email","email"),("code","code"),
            ("tel","tel"),("number","number"),("text","text"),
            ("SYNTHETIC_PRIVATE_VALUE",None),
            ({"name":"SYNTHETIC_PRIVATE_NAME","value":"SYNTHETIC_PRIVATE_VALUE"},None),
        ):
            with self.subTest(candidate=candidate):
                self.page.evaluate=AsyncMock(return_value=candidate)
                response=await self.touch.tabs(request(TABS_PATH,cookie=self.cookie))
                self.assertEqual(response.status_code,200)
                self.assertEqual(json.loads(response.body)["focus_kind"],expected)
                self.assertNotIn(b"SYNTHETIC_PRIVATE",response.body)
                self.assertEqual(self.page.focused.fills,[])

    async def test_focus_hint_rechecks_origin_and_exact_page_after_read(self):
        async def redirect(_script):
            self.page.url="https://phishing.example/"
            return "password"
        self.page.evaluate=redirect
        response=await self.touch.tabs(request(TABS_PATH,cookie=self.cookie))
        self.assertIsNone(json.loads(response.body)["focus_kind"])

        self.page.url=FACEBOOK
        async def close(_script):
            self.page.closed=True
            self.page.context.pages=[]
            return "password"
        self.page.evaluate=close
        response=await self.touch.tabs(request(TABS_PATH,cookie=self.cookie))
        self.assertIsNone(json.loads(response.body)["focus_kind"])

    async def test_focus_hint_failure_keeps_safe_tab_inventory_available(self):
        self.page.evaluate=AsyncMock(side_effect=RuntimeError("SYNTHETIC_PRIVATE_ERROR"))
        response=await self.touch.tabs(request(TABS_PATH,cookie=self.cookie))
        body=json.loads(response.body)
        self.assertEqual(response.status_code,200)
        self.assertEqual(len(body["tabs"]),1)
        self.assertIsNone(body["focus_kind"])
        self.assertNotIn(b"SYNTHETIC_PRIVATE_ERROR",response.body)

    async def test_phone_screen_preserves_nonce_csp_and_native_input_hints(self):
        response=await self.touch.home(request(PATH,cookie=self.cookie))
        csp=response.headers["content-security-policy"]
        self.assertNotIn("unsafe-inline",csp)
        self.assertNotIn("unsafe-eval",csp)
        self.assertIn(b'viewport-fit=cover',response.body)
        self.assertIn(b'autocomplete="current-password"',response.body)
        self.assertIn(b'autocomplete="one-time-code"',response.body)
        self.assertIn(b'inputmode="numeric"',response.body)
        self.assertIn(b'id="touch-finish"',response.body)
        self.assertNotIn(b'user-scalable=no',response.body)

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
        self.assertEqual(self.page.mouse.moves,[(254,537)])
        for key in ("Enter","Tab","Backspace"):
            v=await self.touch.action(self.action_request({"kind":"key","key":key}))
            self.assertEqual(v.status_code,200)
        self.assertEqual(self.page.keyboard.presses,
                         ["Enter","Tab","Backspace"])

    async def test_nested_scroll_uses_exact_owner_gesture_position_without_click(self):
        result=await self.touch.action(self.action_request({'kind':'scroll','delta':-240,'x':0.25,'y':0.75}))
        self.assertEqual(result.status_code,200)
        self.assertEqual(self.page.mouse.moves,[(127,806)])
        self.assertEqual(self.page.mouse.scrolls,[(0,-240)])
        self.assertEqual(self.page.mouse.clicks,[])

    async def test_invalid_scroll_coordinates_never_move_or_scroll(self):
        for extra in [{'x':True,'y':.5},{'x':-1,'y':.5},{'x':.5},{'x':.5,'y':float('nan')}]:
            r=await self.touch.action(self.action_request({'kind':'scroll','delta':200,**extra}))
            self.assertEqual(r.status_code,400)
        self.assertEqual(self.page.mouse.moves,[]);self.assertEqual(self.page.mouse.scrolls,[])

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

    async def test_numeric_verification_field_accepts_human_text_never_password(self):
        self.page.focused.field_type="number"
        typed=await self.touch.action(self.action_request({
            "kind":"text","field":"text","text":"123456"}))
        self.assertEqual(typed.status_code,200)
        self.assertEqual(self.page.focused.fills,[("123456",7000)])
        denied=await self.touch.action(self.action_request({
            "kind":"text","field":"password","text":"SYNTHETIC_SECRET"}))
        self.assertEqual(denied.status_code,409)
        self.assertEqual(self.page.focused.fills,[("123456",7000)])

    async def test_popup_tabs_stay_in_exact_context_and_service_scope(self):
        popup=FakePage()
        popup.url="https://m.facebook.com/synthetic-login?private=SYNTHETIC_SECRET"
        popup.context=self.page.context
        unsafe=FakePage()
        unsafe.url="https://phishing.example/"
        unsafe.context=self.page.context
        self.page.context.pages.extend([popup,unsafe])
        other=FakePage()
        other.url="https://www.facebook.com/other-owner"
        # The other context is deliberately absent from this session's pages.
        inventory=await self.touch.tabs(request(TABS_PATH,cookie=self.cookie))
        self.assertEqual(inventory.status_code,200)
        rows=json.loads(inventory.body)["tabs"]
        self.assertEqual(len(rows),2)
        self.assertTrue(rows[0]["active"])
        self.assertFalse(rows[1]["active"])
        self.assertNotIn(b"SYNTHETIC_SECRET",inventory.body)
        self.assertNotIn(b"phishing",inventory.body)
        self.assertNotIn(b"other-owner",inventory.body)
        switched=await self.touch.action(self.action_request({
            "kind":"switch_tab","ref":rows[1]["ref"]}))
        self.assertEqual(switched.status_code,200)
        self.assertEqual(popup.fronts,1)
        frame=await self.touch.frame(request(FRAME_PATH,cookie=self.cookie))
        self.assertEqual(frame.status_code,200)
        self.assertEqual(popup.screenshots,1)
        self.assertEqual(self.page.screenshots,0)
        typed=await self.touch.action(self.action_request({
            "kind":"text","field":"text","text":"SYNTHETIC_POPUP_INPUT"}))
        self.assertEqual(typed.status_code,200)
        self.assertEqual(popup.focused.fills,[("SYNTHETIC_POPUP_INPUT",7000)])
        self.assertEqual(self.page.focused.fills,[])
        self.assertEqual(other.focused.fills,[])

    async def test_closed_popup_returns_to_opener_and_stale_ref_never_retargets(self):
        popup=FakePage()
        popup.context=self.page.context
        self.page.context.pages.append(popup)
        rows=json.loads((await self.touch.tabs(
            request(TABS_PATH,cookie=self.cookie))).body)["tabs"]
        ref=rows[1]["ref"]
        switched=await self.touch.action(self.action_request({
            "kind":"switch_tab","ref":ref}))
        self.assertEqual(switched.status_code,200)
        popup.closed=True
        self.page.context.pages.remove(popup)
        replacement=FakePage()
        replacement.context=self.page.context
        self.page.context.pages.append(replacement)
        self.page.focused.field_type="password"
        for action in (
            {"kind":"text","field":"password","text":"MUST_STAY_IN_POPUP"},
            {"kind":"tap","x":0.5,"y":0.5},
            {"kind":"key","key":"Enter"},
        ):
            stale_input=await self.touch.action(self.action_request({**action,"ref":ref}))
            self.assertEqual(stale_input.status_code,409)
        self.assertEqual(self.page.focused.fills,[])
        self.assertEqual(self.page.mouse.clicks,[])
        self.assertEqual(self.page.keyboard.presses,[])
        stale=await self.touch.action(self.action_request({
            "kind":"switch_tab","ref":ref}))
        self.assertEqual(stale.status_code,409)
        self.assertEqual(replacement.fronts,0)
        frame=await self.touch.frame(request(FRAME_PATH,cookie=self.cookie))
        self.assertEqual(frame.status_code,200)
        self.assertEqual(self.page.screenshots,1)
        self.assertEqual(replacement.screenshots,0)

    async def test_touch_input_requires_observed_tab_ref(self):
        unbound=await self.touch.action(request(ACTION_PATH,"POST",{
            "kind":"tap","x":0.4,"y":0.4},cookie=self.cookie))
        self.assertEqual(unbound.status_code,400)
        self.assertEqual(self.page.mouse.clicks,[])

    async def test_tab_selection_rechecks_origin_after_bring_to_front(self):
        popup=FakePage()
        popup.context=self.page.context
        self.page.context.pages.append(popup)
        rows=json.loads((await self.touch.tabs(
            request(TABS_PATH,cookie=self.cookie))).body)["tabs"]
        async def redirect():
            popup.url="https://phishing.example/"
        popup.bring_to_front=redirect
        switched=await self.touch.action(self.action_request({
            "kind":"switch_tab","ref":rows[1]["ref"]}))
        self.assertEqual(switched.status_code,409)
        frame=await self.touch.frame(request(FRAME_PATH,cookie=self.cookie))
        self.assertEqual(frame.status_code,200)
        self.assertEqual(self.page.screenshots,1)
        self.assertEqual(popup.screenshots,0)

    async def test_tab_inventory_requires_cookie_and_rejects_unknown_refs(self):
        denied=await self.touch.tabs(request(TABS_PATH))
        self.assertEqual(denied.status_code,403)
        unknown=await self.touch.action(self.action_request({
            "kind":"switch_tab","ref":"X"*16}))
        self.assertEqual(unknown.status_code,409)
        self.assertEqual(self.page.fronts,0)

    async def test_textarea_accepts_text_but_never_password_or_readonly_write(self):
        self.page.focused.tag="TEXTAREA"
        self.page.focused.field_type="textarea"
        text="SYNTHETIC FIRST LINE\nSYNTHETIC SECOND LINE"
        filled=await self.touch.action(self.action_request({
            "kind":"text","field":"text","text":text}))
        self.assertEqual(filled.status_code,200)
        self.assertEqual(self.page.focused.fills,[(text,7000)])
        self.assertNotIn(text.encode(),filled.body)

        password=await self.touch.action(self.action_request({
            "kind":"text","field":"password","text":"SYNTHETIC_SECRET"}))
        self.assertEqual(password.status_code,409)
        self.page.focused.readonly=True
        readonly=await self.touch.action(self.action_request({
            "kind":"text","field":"text","text":"MUST_NOT_WRITE"}))
        self.assertEqual(readonly.status_code,409)
        self.assertEqual(self.page.focused.fills,[(text,7000)])

    async def test_fixed_navigation_accepts_empty_history_without_url_argument(self):
        for kind in ("back","forward","reload"):
            result=await self.touch.action(self.action_request({"kind":kind}))
            self.assertEqual(result.status_code,200)
        self.assertEqual([kind for kind,_ in self.page.navigations],
                         ["back","forward","reload"])
        self.assertEqual(self.page.navigations,[
            ("back",{"wait_until":"commit","timeout":10000}),
            ("forward",{"wait_until":"commit","timeout":10000}),
            ("reload",{"wait_until":"domcontentloaded","timeout":10000}),
        ])
        self.assertEqual(self.page.mouse.clicks,[])

    async def test_back_skips_only_entry_zero_exact_about_blank(self):
        self.page.history={"currentIndex":1,"entries":[
            {"url":"about:blank"},{"url":self.page.url}]}
        result=await self.touch.action(self.action_request({"kind":"back"}))
        self.assertEqual(result.status_code,200)
        self.assertEqual(self.page.navigations,[])
        self.assertEqual(self.page.history_reads,1)
        self.assertEqual(self.page.history_detaches,1)
        frame=await self.touch.frame(request(FRAME_PATH,cookie=self.cookie))
        self.assertEqual(frame.status_code,200)

        for index,urls in (
            (1,["about:blank#fragment",self.page.url]),
            (1,["https://www.facebook.com/previous",self.page.url]),
            (2,["https://www.facebook.com/first","about:blank",self.page.url]),
        ):
            with self.subTest(index=index,previous=urls[index-1]):
                self.page.history={"currentIndex":index,
                                   "entries":[{"url":url} for url in urls]}
                before=len(self.page.navigations)
                result=await self.touch.action(self.action_request({"kind":"back"}))
                self.assertEqual(result.status_code,200)
                self.assertEqual(len(self.page.navigations),before+1)
        self.assertEqual(self.page.history_reads,self.page.history_detaches)

    async def test_unreadable_or_invalid_history_never_navigates_and_always_detaches(self):
        bad_histories=(
            None,{},
            {"currentIndex":True,"entries":[{"url":self.page.url}]},
            {"currentIndex":-1,"entries":[{"url":self.page.url}]},
            {"currentIndex":1,"entries":[{"url":self.page.url}]},
            {"currentIndex":0,"entries":[]},
            {"currentIndex":0,"entries":["invalid"]},
            {"currentIndex":0,"entries":[{"url":None}]},
            {"currentIndex":0,"entries":[{"url":"https://www.facebook.com/changed"}]},
        )
        for history in bad_histories:
            self.page.history=history
            result=await self.touch.action(self.action_request({"kind":"back"}))
            self.assertEqual(result.status_code,409)
        self.page.history_error=True
        failed=await self.touch.action(self.action_request({"kind":"back"}))
        self.assertEqual(failed.status_code,409)
        self.assertNotIn(b"SYNTHETIC_PRIVATE_HISTORY_ERROR",failed.body)
        self.assertEqual(self.page.navigations,[])
        self.assertEqual(self.page.history_reads,len(bad_histories)+1)
        self.assertEqual(self.page.history_reads,self.page.history_detaches)

    async def test_scope_is_rechecked_after_history_detach_before_back(self):
        self.page.history_redirect="https://phishing.example/"
        result=await self.touch.action(self.action_request({"kind":"back"}))
        self.assertEqual(result.status_code,409)
        self.assertEqual(self.page.history_reads,1)
        self.assertEqual(self.page.history_detaches,1)
        self.assertEqual(self.page.navigations,[])

    async def test_stalled_history_detach_is_bounded_and_never_navigates(self):
        self.page.history_detach_blocked=True
        with patch("owner_mobile_touch.HISTORY_DETACH_TIMEOUT",0.01):
            result=await asyncio.wait_for(self.touch.action(
                self.action_request({"kind":"back"})),0.5)
        self.assertEqual(result.status_code,409)
        self.assertEqual(self.page.history_reads,1)
        self.assertEqual(self.page.history_detaches,1)
        self.assertEqual(self.page.navigations,[])

    async def test_navigation_leaving_service_scope_is_not_reported_as_success(self):
        self.page.navigation_target="https://phishing.example/"
        result=await self.touch.action(self.action_request({"kind":"back"}))
        self.assertEqual(result.status_code,409)
        self.assertEqual(len(self.page.navigations),1)
        frame=await self.touch.frame(request(FRAME_PATH,cookie=self.cookie))
        self.assertEqual(frame.status_code,410)
        for kind in ("back","forward","reload"):
            blocked=await self.touch.action(self.action_request({"kind":kind}))
            self.assertEqual(blocked.status_code,409)
        self.assertEqual(len(self.page.navigations),1)
        self.assertEqual(self.page.screenshots,0)

    async def test_frame_redirect_cannot_return_an_out_of_scope_screenshot(self):
        original=self.page.screenshot
        async def redirected_capture(**kwargs):
            result=await original(**kwargs)
            self.page.url="https://phishing.example/"
            return result
        self.page.screenshot=redirected_capture
        frame=await self.touch.frame(request(FRAME_PATH,cookie=self.cookie))
        self.assertEqual(frame.status_code,410)
        self.assertEqual(frame.body,b"")

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
            {"kind":"back","url":"https://evil.example"},
            {"kind":"forward","steps":3},
            {"kind":"reload","url":"https://evil.example"},
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

    async def test_touch_landing_reload_after_saved_close_keeps_receipt_only(self):
        done = await self.handoff.finish(request(
            SETUP_PATH + "/finish", "POST", {}, cookie=self.cookie))
        self.assertEqual(done.status_code, 200)
        self.assertTrue(json.loads(done.body)["full_profile_saved"])
        returned = await self.touch.home(request(PATH, cookie=self.cookie))
        self.assertEqual(returned.status_code, 200)
        self.assertIn("Profil zapisany i sesja zamknięta".encode(), returned.body)
        self.assertNotIn(b'id="touch-app"', returned.body)
        self.assertNotIn(b'id="fullscreen"', returned.body)
        self.assertEqual(len(self.manager.saved), 1)
        self.assertEqual((await self.touch.frame(request(
            FRAME_PATH, cookie=self.cookie))).status_code, 410)

    async def test_touch_landing_after_control_expiry_keeps_bounded_status_only(self):
        self.handoff.clock = lambda: self.handoff.active.expires_at + 91
        returned = await self.touch.home(request(PATH, cookie=self.cookie))
        self.assertEqual(returned.status_code, 200)
        self.assertIn(b'/owner-mobile-login/status', returned.body)
        self.assertNotIn(b'id="touch-app"', returned.body)
        self.assertNotIn(b'id="fullscreen"', returned.body)
        self.assertEqual(self.page.screenshots, 0)
        self.handoff.clock = lambda: self.handoff.active.receipt_expires_at + 1
        self.assertEqual((await self.touch.home(request(
            PATH, cookie=self.cookie))).status_code, 403)
        self.assertEqual((await self.touch.home(request(PATH))).status_code, 403)


if __name__ == "__main__":
    import unittest
    unittest.main(verbosity=2)
