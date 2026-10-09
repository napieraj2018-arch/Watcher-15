"""Visual and interaction smoke checks for the offline browser-window prototype.

The preview never talks to Steel, Meta, Google, secrets or MCP. It is not the
production login UI. Tests use real Chromium and synthetic profile labels.
"""
from __future__ import annotations
import asyncio
from pathlib import Path
import unittest
from playwright.async_api import async_playwright

HTML = Path(__file__).resolve().parents[1] / "index.html"


class BrowserWindowUX(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=True, args=["--no-sandbox"]
        )
        self.context = await self.browser.new_context(
            viewport={"width": 390, "height": 844}, device_scale_factor=1,
            is_mobile=True, has_touch=True
        )
        self.page = await self.context.new_page()
        self.requests = []
        self.page.on("request", lambda req: self.requests.append(req.url))
        self.errors = []
        self.page.on("pageerror", lambda exc: self.errors.append(str(exc)))
        await self.page.goto(HTML.as_uri())

    async def asyncTearDown(self):
        await self.context.close()
        await self.browser.close()
        await self.playwright.stop()

    async def test_explicit_demo_state_not_disguised_as_authenticated(self):
        self.assertIn("Podgląd interfejsu", await self.page.locator("#demo-badge").inner_text())
        self.assertIn("bez połączenia", await self.page.locator("#status-label").inner_text())
        self.assertFalse(await self.page.locator("input[type=password]").count())

    async def test_responsive_without_horizontal_scroll_at_320(self):
        await self.page.set_viewport_size({"width": 320, "height": 680})
        x = await self.page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        self.assertTrue(x, "Small iPhones must not overflow sideways")

    async def test_responsive_at_390(self):
        self.assertTrue(await self.page.locator(".bottom-bar").is_visible())
        self.assertFalse(await self.page.locator(".sidebar").is_visible())

    async def test_desktop_sidebar_visible(self):
        await self.page.set_viewport_size({"width": 1280, "height": 900})
        self.assertTrue(await self.page.locator(".sidebar").is_visible())
        self.assertFalse(await self.page.locator(".bottom-bar").is_visible())

    async def test_mobile_controls_touch_target_minimum(self):
        for button in await self.page.locator(".bottom-bar button").all():
            size = await button.bounding_box()
            self.assertGreaterEqual(size["width"], 44)
            self.assertGreaterEqual(size["height"], 44)

    async def test_phone_address_does_not_trigger_zoom(self):
        size = await self.page.locator("#address").evaluate(
            "(el) => parseFloat(getComputedStyle(el).fontSize)"
        )
        self.assertGreaterEqual(size, 16, "iOS zooms controls below 16px")

    async def test_change_profile_using_mobile_sheet(self):
        await self.page.get_by_role("button", name="Zmień profil").click()
        await self.page.get_by_role("button", name="Studio – Google", exact=False).last.click()
        self.assertEqual(await self.page.locator("#mobile-profile-label").inner_text(), "Studio – Google")
        self.assertEqual(await self.page.locator("#address").input_value(), "https://example.org/")

    async def test_tab_count_updates(self):
        await self.page.get_by_role("button", name="Nowa karta").first.click()
        self.assertEqual(await self.page.locator("#mobile-tab-count").inner_text(), "2")
        self.assertIn("2 z 2", await self.page.locator("#tab-status").inner_text())

    async def test_tab_switcher_shows_existing_and_new(self):
        await self.page.get_by_role("button", name="Nowa karta").first.click()
        await self.page.get_by_role("button", name="Pokaż karty").click()
        self.assertTrue(await self.page.get_by_role("dialog").is_visible())
        self.assertGreaterEqual(await self.page.get_by_role("dialog").get_by_role("button").count(), 3)

    async def test_tab_selector_desktop(self):
        await self.page.set_viewport_size({"width": 1220, "height": 800})
        await self.page.locator(".tab-add").click()
        await self.page.locator("#tabs .tab").first.click()
        self.assertEqual(await self.page.locator("#tab-status").inner_text(), "Karta 1 z 2")

    async def test_close_last_tab_makes_blank_tab(self):
        await self.page.set_viewport_size({"width": 1220, "height": 800})
        await self.page.locator("#tabs [data-close]").first.click()
        self.assertEqual(await self.page.locator("#mobile-tab-count").inner_text(), "1")

    async def test_address_changes_only_demo_and_not_network(self):
        await self.page.locator("#address").fill("https://example.com/demo/123")
        await self.page.locator("#address").press("Enter")
        self.assertIn("Podgląd: example.com", await self.page.locator("#page-title").inner_text())
        self.assertFalse(any(u.startswith("http") for u in self.requests),
                         "The prototype must never fetch a real website")

    async def test_back_and_forward(self):
        await self.page.locator("#address").fill("https://example.org/one")
        await self.page.locator("#address").press("Enter")
        await self.page.locator("#address").fill("https://example.org/two")
        await self.page.locator("#address").press("Enter")
        await self.page.get_by_role("button", name="Wstecz").last.click()
        self.assertEqual(await self.page.locator("#address").input_value(), "https://example.org/one")
        await self.page.get_by_role("button", name="Dalej").last.click()
        self.assertEqual(await self.page.locator("#address").input_value(), "https://example.org/two")

    async def test_no_plain_http_navigation(self):
        original = await self.page.locator("#address").input_value()
        await self.page.locator("#address").fill("http://example.com/insecure")
        await self.page.locator("#address").press("Enter")
        self.assertEqual(await self.page.locator("#address").input_value(), original)

    async def test_no_script_scheme_navigation(self):
        original = await self.page.locator("#address").input_value()
        await self.page.locator("#address").fill("javascript:alert(1)")
        await self.page.locator("#address").press("Enter")
        self.assertEqual(await self.page.locator("#address").input_value(), original)

    async def test_more_sheet_and_close(self):
        await self.page.get_by_role("button", name="Więcej opcji").last.click()
        self.assertTrue(await self.page.get_by_role("dialog").is_visible())
        await self.page.get_by_role("button", name="Zamknij").click()
        self.assertFalse(await self.page.get_by_role("dialog").is_visible())

    async def test_no_runtime_js_errors(self):
        await self.page.get_by_role("button", name="Nowa karta").first.click()
        await self.page.get_by_role("button", name="Odśwież").last.click()
        self.assertEqual(self.errors, [])

    async def test_keyboard_new_tab(self):
        await self.page.keyboard.press("Control+t")
        self.assertEqual(await self.page.locator("#mobile-tab-count").inner_text(), "2")

    async def test_outside_sheet_tap_closes_modal(self):
        await self.page.get_by_role("button", name="Pokaż karty").click()
        await self.page.locator("#cover").click(position={"x": 4, "y": 20})
        self.assertFalse(await self.page.get_by_role("dialog").is_visible())

    async def test_mobile_and_desktop_screen_shots_created(self):
        output=Path("/tmp/ai-browser-ux-mobile.png")
        await self.page.screenshot(path=str(output),full_page=True)
        self.assertGreater(output.stat().st_size,5_000)
        await self.page.set_viewport_size({"width": 1330, "height": 900})
        output=Path("/tmp/ai-browser-ux-desktop.png")
        await self.page.screenshot(path=str(output),full_page=True)
        self.assertGreater(output.stat().st_size,5_000)


if __name__ == "__main__":
    unittest.main(verbosity=2)
