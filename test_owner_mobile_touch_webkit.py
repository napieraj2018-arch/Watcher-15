"""iPhone WebKit takeover UI tests with intercepted HTTPS and neutral images.

No provider, real account, credentials or open network. Chromium separately
checks the remote control path. These tests exercise the production nonce CSP,
phone layout, native input hints, touch coordinates and confirmed completion.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import re
import sys
import unittest
from urllib.parse import urlsplit, parse_qs

from playwright.async_api import async_playwright, expect
from starlette.responses import JSONResponse
from starlette.routing import Route

from test_owner_mobile_handoff import (
    FakeMobileManager, PROFILE, FACEBOOK, SETUP_PATH, request,
)
from multi_capability_guard import MultiCapabilityGuard
from owner_mobile_touch import PATH, FRAME_PATH, ACTION_PATH, TABS_PATH

sys.path.insert(0, str(Path(__file__).resolve().parent /
                       "session_ownership" / "tests"))
from test_sdk_contract import fake_mcp


class IOSWebKitTouch(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.manager = FakeMobileManager()
        self.mcp = fake_mcp(self.manager)
        async def legacy(_):
            return JSONResponse({"unsafe": "legacy"})
        self.mcp._custom_starlette_routes.append(
            Route("/setup/legacy", legacy, methods=["POST"]))
        self.guard = MultiCapabilityGuard(
            self.mcp, self.manager, capacity=5, watchdog_enabled=False)
        self.guard.install()
        self.handoff = self.guard.mobile_handoff
        self.handoff.clock = lambda: 100
        setup = await self.handoff.create({"profile": PROFILE, "login_url": FACEBOOK})
        token = setup["setup_url"].split("#s=", 1)[1]
        claimed = await self.handoff.claim(request(
            SETUP_PATH+"/claim", "POST", {"token": token}))
        self.assertEqual(claimed.status_code, 200)
        cookie = claimed.headers["set-cookie"].split(";", 1)[0]
        view = await self.handoff.touch.home(request(PATH, cookie=cookie))
        self.assertEqual(view.status_code, 200)

        self.browser_engine = await async_playwright().start()
        self.browser = await self.browser_engine.webkit.launch(headless=True)
        self.context = await self.browser.new_context(
            viewport={"width": 390, "height": 844}, device_scale_factor=2,
            is_mobile=True, has_touch=True)
        self.page = await self.context.new_page()
        # These are test-owned neutral remote screenshots, never account data.
        source_style = """
          <meta name="viewport" content="width=device-width,initial-scale=1">
          <style>body{margin:0;background:#fff;font:18px system-ui;color:#243248}
          main{padding:60px 35px}small{color:#718094;font-size:14px}h1{font-size:32px;margin-top:40px}
          p{line-height:1.6;color:#5a687b}label{display:block;margin-top:25px;font-size:16px}
          input{display:block;box-sizing:border-box;width:100%;padding:18px;border:1px solid #c5d1dd;
          border-radius:9px;margin:8px 0 20px;font-size:18px}button{width:100%;background:#245c86;
          color:white;padding:18px;border:0;border-radius:9px;font-size:19px;margin-top:15px}</style>
        """
        await self.page.set_viewport_size({"width": 508, "height": 1074})
        await self.page.set_content(source_style + """
          <main><small>STRONA TESTOWA · BEZ PRAWDZIWEGO KONTA</small><h1>Zaloguj się</h1>
          <p>Kontynuuj w swojej prywatnej sesji.</p><label>E-mail</label><input placeholder="Twój e-mail">
          <label>Hasło</label><input type="password" placeholder="Twoje hasło"><button>Kontynuuj</button>
          <p>Możesz wrócić do rozmowy po zapisaniu profilu.</p></main>
        """)
        self.sample_image = await self.page.screenshot(type="jpeg", quality=75, scale="css")
        await self.page.set_viewport_size({"width": 508, "height": 760})
        await self.page.set_content(source_style + """
          <main><small>STRONA TESTOWA · BEZ PRAWDZIWEGO KONTA</small><h1>Wpisz kod</h1>
          <p>To następny etap testowego logowania.</p><label>Kod jednorazowy</label>
          <input inputmode="numeric" autocomplete="one-time-code" placeholder="6 cyfr">
          <button>Potwierdź</button></main>
        """)
        self.challenge_image = await self.page.screenshot(type="jpeg", quality=75, scale="css")
        await self.page.set_viewport_size({"width": 390, "height": 844})
        self.assertTrue(self.sample_image.startswith(b"\xff\xd8"))
        self.events = []
        self.requests = []
        self.action_status = 200
        self.action_gate = None
        self.action_progression = False
        self.frame_gate = None
        self.frame_requests = 0
        self.active_frames = 0
        self.max_active_frames = 0
        self.focus_kind = None
        self.tabs_gate = None
        self.tabs_waiting = asyncio.Event()
        self.tabs_delivered = asyncio.Event()
        self.finish_requests = 0
        self.finish_status = 200
        self.session_snapshot = {
            "status": "active", "remaining_seconds": 600,
            "auto_save_close_in_seconds": 720, "profile_saved": False,
            "full_profile_saved": False, "auth_verified": False,
            "authentication_stage": "unverified",
        }
        self.finish_result = {
            **self.session_snapshot, "status": "saved_and_closed",
            "profile_saved": True, "full_profile_saved": True,
        }
        self.tab_rows = [{"ref": "A"*16, "label": "Karta 1 — www.facebook.com", "active": True}]

        async def mock_requests(route):
            parsed = urlsplit(route.request.url)
            if parsed.path == PATH and route.request.method == "GET":
                await route.fulfill(
                    status=200, body=view.body, content_type="text/html",
                    headers={"Content-Security-Policy": view.headers["content-security-policy"],
                             "Cache-Control": "no-store"})
            elif parsed.path == FRAME_PATH and route.request.method == "GET":
                self.frame_requests += 1
                self.active_frames += 1
                self.max_active_frames = max(self.max_active_frames, self.active_frames)
                try:
                    if self.frame_gate is not None:
                        await self.frame_gate.wait()
                    active = next((tab["ref"] for tab in self.tab_rows if tab["active"]), None)
                    if parse_qs(parsed.query).get("ref") != [active]:
                        await route.fulfill(status=410)
                        return
                    await route.fulfill(status=200, body=self.sample_image,
                                        content_type="image/jpeg")
                finally:
                    self.active_frames -= 1
            elif parsed.path == TABS_PATH and route.request.method == "GET":
                if self.tabs_gate is not None:
                    self.tabs_waiting.set()
                    await self.tabs_gate.wait()
                await route.fulfill(status=200, content_type="application/json",
                                    body=json.dumps({"tabs": self.tab_rows,
                                                     "focus_kind": self.focus_kind}))
                if self.tabs_gate is not None:
                    self.tabs_delivered.set()
            elif parsed.path == "/owner-mobile-login/status":
                await route.fulfill(status=200, content_type="application/json",
                                    body=json.dumps(self.session_snapshot))
            elif parsed.path == "/owner-mobile-login/finish" and route.request.method == "POST":
                self.finish_requests += 1
                self.session_snapshot = dict(self.finish_result)
                await route.fulfill(status=self.finish_status, content_type="application/json",
                                    body=json.dumps(self.finish_result))
            elif parsed.path == ACTION_PATH and route.request.method == "POST":
                event = route.request.post_data_json
                self.requests.append(event)
                self.events.append(event if event["kind"] == "switch_tab"
                                   else {k: v for k, v in event.items() if k != "ref"})
                if self.action_gate is not None:
                    await self.action_gate.wait()
                active = next((tab["ref"] for tab in self.tab_rows if tab["active"]), None)
                if event["kind"] != "switch_tab" and event.get("ref") != active:
                    await route.fulfill(status=409, content_type="application/json",
                                        body='{"error":"TOUCH_ACTION_FAILED"}')
                    return
                if self.action_status == 200 and event["kind"] == "switch_tab":
                    for tab in self.tab_rows:
                        tab["active"] = tab["ref"] == event["ref"]
                if self.action_progression:
                    self.sample_image = self.challenge_image
                    self.focus_kind = "code"
                await route.fulfill(status=self.action_status,
                                    content_type="application/json",
                                    body='{"status":"ok"}' if self.action_status == 200
                                    else '{"error":"TOUCH_ACTION_FAILED"}')
            else:
                await route.abort("blockedbyclient")

        await self.page.route("https://ai-browser-cloud.onrender.com/**", mock_requests)
        await self.page.goto("https://ai-browser-cloud.onrender.com"+PATH,
                             wait_until="domcontentloaded")
        await expect(self.page.locator("#touch-app")).to_have_attribute("data-image", "ready")
        await expect(self.page.locator("#touch-shot")).to_have_js_property("naturalWidth", 508)

    async def asyncTearDown(self):
        for gate in (self.action_gate, self.frame_gate, self.tabs_gate):
            if gate is not None:
                gate.set()
        await self.context.close()
        await self.browser.close()
        await self.browser_engine.stop()

    async def wait_for_events(self, number):
        for _ in range(70):
            if len(self.events) >= number:
                return
            await asyncio.sleep(.035)
        self.fail(f"Expected {number} touch requests, got {len(self.events)}")

    async def open_editor(self, element_id="touch-value"):
        if not await self.page.locator("#touch-editor").is_visible():
            await self.page.locator("#touch-keyboard").tap()
        mode = {"touch-value": "text", "touch-password": "password", "touch-code": "code"}[element_id]
        await self.page.locator("#touch-mode-"+mode).tap()
        element = self.page.locator("#"+element_id)
        await expect(element).to_be_visible()
        return element

    async def open_more(self):
        if not await self.page.locator("#touch-menu").is_visible():
            await self.page.locator("#touch-more").tap()

    async def artifact(self, name):
        directory = os.environ.get("AIB_MOBILE_UX_ARTIFACTS")
        if directory:
            target = Path(directory)
            target.mkdir(parents=True, exist_ok=True)
            await self.page.screenshot(path=str(target/name), scale="css")

    async def test_webkit_touch_and_native_keyboard_controls(self):
        img = self.page.locator("#touch-shot")
        box = await img.bounding_box()
        self.assertGreater(box["width"], 250)
        self.assertLessEqual(box["width"], 390)
        await img.tap(position={"x": 75, "y": 55})
        await self.wait_for_events(1)
        first = self.events[0]
        self.assertEqual(first["kind"], "tap")
        self.assertGreater(first["x"], 0)
        self.assertLess(first["x"], 1)
        self.assertGreater(first["y"], 0)
        self.assertLess(first["y"], 1)

        element = await self.open_editor()
        await element.fill("synthetic@example.invalid")
        await self.page.locator("#touch-send").tap()
        await self.wait_for_events(2)
        await expect(element).to_have_value("")
        self.assertEqual(self.events[1], {
            "kind": "text", "field": "text", "text": "synthetic@example.invalid"})
        password = await self.open_editor("touch-password")
        await password.fill("SYNTHETIC_ONLY_NOT_REAL")
        await expect(password).to_have_attribute("type", "password")
        await self.page.locator("#touch-send-password").tap()
        await self.wait_for_events(3)
        await expect(password).to_have_value("")
        self.assertEqual(self.events[2], {
            "kind": "text", "field": "password", "text": "SYNTHETIC_ONLY_NOT_REAL"})
        await self.page.locator("#touch-enter").tap()
        await self.wait_for_events(4)
        self.assertEqual(self.events[3], {"kind": "key", "key": "Enter"})

    async def test_native_enter_sends_current_text_or_password_before_enter(self):
        for element_id, field, text in (
            ("touch-value", "text", "synthetic@example.invalid"),
            ("touch-password", "password", "SYNTHETIC_NOT_A_PASSWORD"),
            ("touch-code", "text", "012345"),
        ):
            with self.subTest(field=element_id):
                before = len(self.events)
                element = await self.open_editor(element_id)
                await element.fill(text)
                await element.press("Enter")
                await self.wait_for_events(before+2)
                await expect(element).to_have_value("")
                self.assertEqual(self.events[before:], [
                    {"kind": "text", "field": field, "text": text},
                    {"kind": "key", "key": "Enter"},
                ])

    async def test_enter_button_remembers_last_local_editor_after_focus_moves(self):
        await (await self.open_editor()).fill("UNSENT_OTHER_FIELD")
        await (await self.open_editor("touch-password")).fill("SYNTHETIC_CURRENT_FIELD")
        button = self.page.locator("#touch-enter")
        await button.focus()
        await expect(button).to_be_focused()
        await button.tap()
        await self.wait_for_events(2)
        await expect(self.page.locator("#touch-password")).to_have_value("")
        self.assertEqual(self.events, [
            {"kind": "text", "field": "password", "text": "SYNTHETIC_CURRENT_FIELD"},
            {"kind": "key", "key": "Enter"},
        ])
        await expect(self.page.locator("#touch-value")).to_have_value("UNSENT_OTHER_FIELD")

    async def test_failed_text_keeps_local_value_and_never_submits(self):
        self.action_status = 409
        element = await self.open_editor("touch-password")
        await element.fill("SYNTHETIC_KEEP_ON_FAILURE")
        await element.press("Enter")
        await self.wait_for_events(1)
        await expect(self.page.locator("#touch-status")).to_have_text(re.compile(r"^Nie udało"))
        self.assertEqual(self.events, [{
            "kind": "text", "field": "password", "text": "SYNTHETIC_KEEP_ON_FAILURE"}])
        await expect(element).to_have_value("SYNTHETIC_KEEP_ON_FAILURE")

    async def test_busy_enter_does_not_duplicate_text_or_submit(self):
        self.action_gate = asyncio.Event()
        element = await self.open_editor()
        await element.fill("synthetic@example.invalid")
        await element.press("Enter")
        await self.wait_for_events(1)
        await self.page.locator("#touch-enter").tap()
        self.assertEqual(len(self.events), 1)
        await expect(element).to_have_value("synthetic@example.invalid")
        await expect(self.page.locator("#touch-status")).to_contain_text("Trwa poprzednia operacja")
        self.action_gate.set()
        await self.wait_for_events(2)
        await expect(element).to_have_value("")
        self.assertEqual(self.events, [
            {"kind": "text", "field": "text", "text": "synthetic@example.invalid"},
            {"kind": "key", "key": "Enter"},
        ])

    async def test_composing_or_repeated_enter_does_not_submit(self):
        element = await self.open_editor()
        await element.fill("SYNTHETIC_COMPOSING")
        await element.dispatch_event("keydown", {"key": "Enter", "isComposing": True})
        await element.dispatch_event("keydown", {"key": "Enter", "repeat": True})
        self.assertEqual(self.events, [])
        await expect(element).to_have_value("SYNTHETIC_COMPOSING")

    async def test_navigation_buttons_send_only_fixed_actions(self):
        for count, kind in enumerate(("back", "forward", "reload"), 1):
            if kind == "reload":
                await self.open_more()
            await self.page.locator("#touch-"+kind).tap()
            await self.wait_for_events(count)
            await expect(self.page.locator("#touch-status")).to_have_text(re.compile(r"^Wykonano"))
        self.assertEqual(self.events, [{"kind": "back"}, {"kind": "forward"}, {"kind": "reload"}])

    async def test_tab_picker_switches_popup_without_forwarding_unsent_password(self):
        self.tab_rows.append({"ref": "B"*16, "label": "Karta 2 — m.facebook.com", "active": False})
        password = await self.open_editor("touch-password")
        await password.fill("SYNTHETIC_KEEP_LOCAL")
        await self.open_more()
        await expect(self.page.locator("#touch-tabs option")).to_have_count(2)
        await self.page.locator("#touch-tabs").select_option("B"*16)
        await self.wait_for_events(1)
        await expect(self.page.locator("#touch-tabs")).to_have_value("B"*16)
        await expect(self.page.locator("#touch-status")).to_have_text(re.compile(r"^Obraz gotowy"))
        await expect(self.page.locator("#touch-app")).to_have_attribute("data-image", "ready")
        self.assertEqual(self.events, [{"kind": "switch_tab", "ref": "B"*16}])
        await expect(password).to_have_value("SYNTHETIC_KEEP_LOCAL")
        # Opening the sheet alone must not rebind pending input to the new tab.
        await self.page.locator("#touch-keyboard").tap()
        await self.page.locator("#touch-enter").tap()
        await self.wait_for_events(2)
        self.assertEqual(self.events[1], {"kind": "key", "key": "Enter"})
        self.assertEqual(self.requests[1]["ref"], "B"*16)
        await expect(password).to_have_value("SYNTHETIC_KEEP_LOCAL")

    async def test_automatic_popup_return_does_not_submit_pending_password_to_opener(self):
        self.tab_rows = [{"ref": "B"*16, "label": "Karta 1 — m.facebook.com", "active": True}]
        await expect(self.page.locator("#touch-tabs")).to_have_value("B"*16)
        password = await self.open_editor("touch-password")
        await password.fill("SYNTHETIC_POPUP_PASSWORD")
        self.tab_rows = [{"ref": "A"*16, "label": "Karta 1 — www.facebook.com", "active": True}]
        await expect(self.page.locator("#touch-tabs")).to_have_value("A"*16)
        await self.page.locator("#touch-send-password").tap()
        self.assertEqual(self.requests, [])
        await expect(password).to_have_value("SYNTHETIC_POPUP_PASSWORD")
        await expect(self.page.locator("#touch-status")).to_contain_text("Karta się zmieniła")

    async def test_one_safe_tab_remains_selectable_when_current_tab_is_out_of_scope(self):
        self.tab_rows = [{"ref": "C"*16, "label": "Karta 1 — www.facebook.com", "active": False}]
        await self.open_more()
        picker = self.page.locator("#touch-tabs")
        await expect(picker.locator("option")).to_have_count(2)
        await expect(picker).to_have_value("")
        await expect(picker).to_be_enabled()
        await picker.select_option("C"*16)
        await self.wait_for_events(1)
        self.assertEqual(self.events, [{"kind": "switch_tab", "ref": "C"*16}])

    async def test_phone_viewport_keyboard_hints_and_visual_artifacts(self):
        app = await self.page.locator("#touch-app").bounding_box()
        viewport = await self.page.locator("#touch-viewport").bounding_box()
        self.assertAlmostEqual(app["width"], 390, delta=1)
        self.assertAlmostEqual(app["height"], 844, delta=1)
        self.assertGreater(viewport["height"], 590)
        await self.artifact("iphone-390x844-login.png")
        password = await self.open_editor("touch-password")
        await expect(password).to_have_attribute("autocomplete", "current-password")
        await expect(self.page.locator("#touch-value")).to_have_attribute("autocomplete", "username")
        await expect(self.page.locator("#touch-code")).to_have_attribute("autocomplete", "one-time-code")
        await expect(self.page.locator("#touch-code")).to_have_attribute("inputmode", "numeric")
        await self.artifact("iphone-390x844-keyboard.png")
        # Headless WebKit has no OS keyboard; exercise the smaller visual area
        # it leaves. This does not certify physical iPhone keyboard behavior.
        await self.page.set_viewport_size({"width": 390, "height": 390})
        await expect(self.page.locator("#touch-app")).to_have_css("height", "390px")
        for element_id in ("touch-password", "touch-send-password", "touch-enter", "touch-dock"):
            box = await self.page.locator("#"+element_id).bounding_box()
            self.assertIsNotNone(box)
            self.assertGreaterEqual(box["y"], 0)
            self.assertLessEqual(box["y"]+box["height"], 391)
        await self.artifact("iphone-keyboard-available-area.png")

    async def test_zoom_pan_keeps_tap_coordinates_and_does_not_scroll_remote_page(self):
        await self.page.locator("#touch-zoom").tap()
        await expect(self.page.locator("#touch-zoom")).to_have_attribute("aria-pressed", "true")
        viewport = await self.page.locator("#touch-viewport").bounding_box()
        x = viewport["x"]+viewport["width"]/2
        y = viewport["y"]+viewport["height"]/2
        await self.page.mouse.move(x, y)
        await self.page.mouse.down()
        await self.page.mouse.move(x+35, y+50, steps=4)
        await self.page.mouse.up()
        self.assertEqual(self.events, [])
        box = await self.page.locator("#touch-shot").bounding_box()
        await self.page.touchscreen.tap(x, y)
        await self.wait_for_events(1)
        self.assertEqual(self.events[0]["kind"], "tap")
        self.assertAlmostEqual(self.events[0]["x"], (x-box["x"])/box["width"], delta=.01)
        self.assertAlmostEqual(self.events[0]["y"], (y-box["y"])/box["height"], delta=.01)

    async def test_explicit_scroll_mode_sends_owner_position_even_when_zoomed(self):
        await self.page.locator('#touch-zoom').tap()
        await self.page.locator('#touch-more').tap()
        await self.page.locator('#touch-scroll-mode').tap()
        await expect(self.page.locator('#touch-editor')).to_be_hidden()
        area=await self.page.locator('#touch-viewport').bounding_box()
        box=await self.page.locator('#touch-shot').bounding_box()
        x=area['x']+area['width']*.5;y=area['y']+area['height']*.6
        await self.page.mouse.move(x,y);await self.page.mouse.down()
        await self.page.mouse.move(x,y-70,steps=4);await self.page.mouse.up()
        await self.wait_for_events(1)
        self.assertEqual(self.events[0]['kind'],'scroll')
        self.assertAlmostEqual(self.events[0]['x'],(x-box['x'])/box['width'],delta=.01)
        self.assertAlmostEqual(self.events[0]['y'],(y-box['y'])/box['height'],delta=.01)
        await self.artifact('iphone-nested-scroll-mode.png')

    async def test_non_input_after_submit_hides_editor_without_resending_pending_value(self):
        await self.open_editor('touch-password')
        await self.page.locator('#touch-password').fill('synthetic-preserved-value')
        self.action_status=409
        self.focus_kind=None
        await self.page.locator('#touch-enter').tap()
        await self.wait_for_events(1)
        await expect(self.page.locator('#touch-editor')).to_be_hidden(timeout=10000)
        self.assertEqual(await self.page.locator('#touch-password').input_value(),'synthetic-preserved-value')
        self.assertEqual(len(self.events),1)

    async def test_visual_viewport_only_keyboard_resize_keeps_controls_reachable(self):
        await self.open_editor("touch-password")
        # Model Safari's OS-keyboard geometry, which does not change CSS
        # media-query height. No CSP bypass or page script is enabled; this
        # fixed test probe changes only the native geometry object's getter.
        await self.page.evaluate("""() => {
            const viewport = window.visualViewport;
            Object.defineProperty(viewport, 'height', {configurable: true, get: () => 390});
            viewport.dispatchEvent(new Event('resize'));
        }""")
        self.assertEqual(self.page.viewport_size, {"width": 390, "height": 844})
        await expect(self.page.locator("#touch-app")).to_have_attribute("data-compact", "true")
        await expect(self.page.locator("#touch-app")).to_have_css("height", "390px")
        for element_id in ("touch-password", "touch-send-password", "touch-enter", "touch-dock"):
            box = await self.page.locator("#"+element_id).bounding_box()
            self.assertIsNotNone(box)
            self.assertGreaterEqual(box["y"], 0)
            self.assertLessEqual(box["y"]+box["height"], 391)

    async def test_editor_crop_keeps_tap_anchor_and_coordinates_after_keyboard_and_pan(self):
        source = await self.page.locator("#touch-shot").bounding_box()
        await self.page.touchscreen.tap(source["x"]+source["width"]*.5,
                                        source["y"]+source["height"]*.4)
        await self.wait_for_events(1)
        await expect(self.page.locator("#touch-status")).to_have_text(re.compile(r"^Wykonano"))
        anchor = self.events[0]
        await self.open_editor("touch-password")
        await self.page.evaluate("""() => {
            const viewport = window.visualViewport;
            Object.defineProperty(viewport, 'height', {configurable: true, get: () => 390});
            viewport.dispatchEvent(new Event('resize'));
        }""")
        await expect(self.page.locator("#touch-app")).to_have_css("height", "390px")
        area = await self.page.locator("#touch-viewport").bounding_box()
        image = await self.page.locator("#touch-shot").bounding_box()
        self.assertAlmostEqual(image["width"], 390, delta=1)
        self.assertGreater(image["height"], area["height"]*3)
        x, y = area["x"]+area["width"]/2, area["y"]+area["height"]/2
        # The source point tapped before opening the keyboard stays centered.
        self.assertAlmostEqual(image["y"]+image["height"]*anchor["y"], y, delta=2)
        await self.page.touchscreen.tap(x, y)
        await self.wait_for_events(2)
        self.assertAlmostEqual(self.events[1]["x"], anchor["x"], delta=.01)
        self.assertAlmostEqual(self.events[1]["y"], anchor["y"], delta=.01)
        await expect(self.page.locator("#touch-status")).to_have_text(re.compile(r"^Wykonano"))
        await self.page.mouse.move(x, y)
        await self.page.mouse.down()
        await self.page.mouse.move(x, y+40, steps=4)
        await self.page.mouse.up()
        self.assertEqual(len(self.events), 2)  # Local crop pan, no remote wheel.
        panned = await self.page.locator("#touch-shot").bounding_box()
        self.assertAlmostEqual(panned["y"]-image["y"], 40, delta=2)
        await self.page.touchscreen.tap(x, y)
        await self.wait_for_events(3)
        self.assertEqual(self.events[2]["kind"], "tap")
        self.assertAlmostEqual(self.events[2]["x"], (x-panned["x"])/panned["width"], delta=.01)
        self.assertAlmostEqual(self.events[2]["y"], anchor["y"]-40/image["height"], delta=.01)

    async def test_uncertain_login_response_still_refreshes_code_screen_without_replay(self):
        self.action_status = 503
        self.action_progression = True
        password = await self.open_editor("touch-password")
        await password.fill("SYNTHETIC_UNCONFIRMED")
        await password.press("Enter")
        await self.wait_for_events(1)
        await expect(self.page.locator("#touch-shot")).to_have_js_property("naturalHeight", 760)
        await expect(self.page.locator("#touch-field-hint")).to_have_text("Kod jednorazowy")
        await expect(password).to_have_value("SYNTHETIC_UNCONFIRMED")
        await expect(password).to_be_hidden()
        code = self.page.locator("#touch-code")
        await expect(code).to_be_visible()
        await expect(code).to_have_value("")
        await expect(self.page.locator("#touch-mode-code")).to_have_attribute("aria-pressed", "true")
        await expect(self.page.locator("#touch-status")).to_have_text(re.compile(r"^Strona prosi teraz o kod"))
        self.assertEqual(self.events, [{
            "kind": "text", "field": "password", "text": "SYNTHETIC_UNCONFIRMED"}])
        await self.artifact("iphone-login-to-code-after-uncertain-response.png")
        self.action_status = 200
        await self.page.locator("#touch-enter").tap()
        await self.wait_for_events(2)
        await expect(self.page.locator("#touch-status")).to_have_text(re.compile(r"^Wykonano"))
        self.assertEqual(self.events[1], {"kind": "key", "key": "Enter"})
        await expect(password).to_have_value("SYNTHETIC_UNCONFIRMED")
        await code.fill("012345")
        await code.press("Enter")
        await self.wait_for_events(4)
        await expect(code).to_have_value("")
        self.assertEqual(self.events[2:], [
            {"kind": "text", "field": "text", "text": "012345"},
            {"kind": "key", "key": "Enter"},
        ])
        await expect(password).to_have_value("SYNTHETIC_UNCONFIRMED")

    async def test_repeated_refresh_has_only_one_image_request_in_flight(self):
        await self.open_more()
        self.frame_gate = asyncio.Event()
        await self.page.locator("#touch-refresh").tap()
        for _ in range(45):
            if self.active_frames:
                break
            await asyncio.sleep(.035)
        self.assertEqual(self.active_frames, 1)
        count = self.frame_requests
        for _ in range(4):
            await self.page.locator("#touch-refresh").tap()
        self.assertEqual(self.frame_requests, count)
        self.assertEqual(self.max_active_frames, 1)
        self.frame_gate.set()
        await expect(self.page.locator("#touch-app")).to_have_attribute("data-image", "ready")

    async def test_confirmed_password_send_advances_to_empty_code_without_replay(self):
        self.action_progression = True
        password = await self.open_editor("touch-password")
        await password.fill("SYNTHETIC_CONFIRMED")
        await password.press("Enter")
        await self.wait_for_events(2)
        await expect(password).to_have_value("")
        await expect(password).to_be_hidden()
        await expect(self.page.locator("#touch-code")).to_be_visible()
        await expect(self.page.locator("#touch-code")).to_have_value("")
        await expect(self.page.locator("#touch-mode-code")).to_have_attribute("aria-pressed", "true")
        await expect(self.page.locator("#touch-status")).to_have_text(re.compile(r"^Strona prosi teraz o kod"))
        self.assertEqual(self.events, [
            {"kind": "text", "field": "password", "text": "SYNTHETIC_CONFIRMED"},
            {"kind": "key", "key": "Enter"},
        ])
        await self.page.locator("#touch-enter").tap()
        await self.wait_for_events(3)
        self.assertEqual(self.events[2], {"kind": "key", "key": "Enter"})

    async def test_finish_waits_for_full_receipt_and_clears_private_editor(self):
        password = await self.open_editor("touch-password")
        await password.fill("SYNTHETIC_DISCARD_AFTER_SAVE")
        await self.page.dispatch_event("body", "pagehide", {"bubbles": True})
        self.assertEqual(self.finish_requests, 0)
        await self.page.locator("#touch-finish").tap()
        await expect(self.page.locator("#touch-ended")).to_be_visible()
        await expect(password).to_have_value("")
        await expect(self.page.locator("#touch-shot")).not_to_have_attribute("src", re.compile(r".+"))
        await expect(self.page.locator("#touch-dock")).to_be_hidden()
        self.assertEqual(self.finish_requests, 1)
        self.assertEqual(self.requests, [])
        await self.artifact("iphone-390x844-saved-and-closed.png")

    async def test_partial_finish_never_claims_saved_or_retries_close(self):
        self.finish_result = {**self.session_snapshot, "status": "save_unconfirmed",
                              "profile_saved": True, "full_profile_saved": False}
        password = await self.open_editor("touch-password")
        await password.fill("SYNTHETIC_KEEP_UNCONFIRMED")
        await self.page.locator("#touch-finish").tap()
        await expect(self.page.locator("#touch-status")).to_contain_text("Zapisu nie potwierdzono")
        await expect(self.page.locator("#touch-ended")).to_be_hidden()
        await expect(password).to_have_value("SYNTHETIC_KEEP_UNCONFIRMED")
        await expect(self.page.locator("#touch-finish")).to_be_disabled()
        await self.page.locator("#touch-finish").dispatch_event("click")
        self.assertEqual(self.finish_requests, 1)

    async def test_late_focus_hint_cannot_reopen_keyboard_after_confirmed_finish(self):
        self.focus_kind = "password"
        self.tabs_gate = asyncio.Event()
        await self.page.locator("#touch-shot").tap(position={"x": 75, "y": 55})
        await asyncio.wait_for(self.tabs_waiting.wait(), 3)
        await expect(self.page.locator("#touch-status")).to_have_text(re.compile(r"^Wykonano"))
        await self.page.locator("#touch-finish").tap()
        await expect(self.page.locator("#touch-ended")).to_be_visible()
        self.tabs_gate.set()
        await asyncio.wait_for(self.tabs_delivered.wait(), 3)
        # Let the already-delivered fetch callback run. The focus suggestion
        # must not reopen any control on the terminal receipt screen.
        await self.page.wait_for_timeout(150)
        await expect(self.page.locator("#touch-editor")).to_be_hidden()
        await expect(self.page.locator("#touch-dock")).to_be_hidden()
        await expect(self.page.locator("#touch-ended")).to_be_visible()
        self.assertEqual(self.finish_requests, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
