"""Actual Chromium tests of the standalone UX prototype, not real accounts."""
from __future__ import annotations

import functools
import json
import pathlib
import threading
import unittest
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "screenshots"


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


class BrowserUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        handler=functools.partial(QuietHandler,directory=str(ROOT))
        cls.server=ThreadingHTTPServer(("127.0.0.1",0),handler)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()
        cls.url="http://127.0.0.1:"+str(cls.server.server_port)+"/workspace.html"
        cls.play=sync_playwright().start()
        cls.browser=cls.play.chromium.launch(headless=True,args=["--no-sandbox"])
        ARTIFACTS.mkdir(exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.play.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=1)

    def setUp(self):
        self.context=self.browser.new_context(viewport={"width":390,"height":844},
            device_scale_factor=3,is_mobile=True,has_touch=True)
        self.page=self.context.new_page()
        self.requests=[]
        self.errors=[]
        self.page.on("request",lambda r:self.requests.append(r.url))
        self.page.on("pageerror",lambda e:self.errors.append(str(e)))
        self.page.goto(self.url,wait_until="networkidle")

    def tearDown(self):
        self.assertEqual([],self.errors,"Client runtime exception")
        self.context.close()

    def test_home_is_visible_and_no_external_requests(self):
        self.assertTrue(self.page.get_by_role("heading",name="W czym dzisiaj pomóc?").is_visible())
        self.assertEqual(self.page.title(),"AI Browser (prototyp)")
        self.assertTrue(all(x.startswith("http://127.0.0.1:") for x in self.requests))
        self.assertIn("Podgląd interfejsu",self.page.locator("#connection-label").inner_text())

    def test_snapshot_mobile_home(self):
        self.page.screenshot(path=str(ARTIFACTS/"mobile-home.png"),full_page=True)
        self.assertFalse(self.page.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1"))

    def test_mobile_controls_have_large_touch_targets(self):
        results=self.page.evaluate("""() => [...document.querySelectorAll('button')].filter(
          b => b.getClientRects().length && !b.disabled && !b.closest('[hidden]')
        ).map(b => ({id:b.id || b.className,width:b.getBoundingClientRect().width,height:b.getBoundingClientRect().height}))""")
        self.assertTrue(len(results)>=10)
        self.assertEqual([], [x for x in results if x["width"]<43.5 or x["height"]<43.5], results)

    def test_footer_inside_mobile_safe_area(self):
        bounds=self.page.locator(".toolbar").bounding_box()
        self.assertGreaterEqual(bounds["x"],0)
        self.assertLessEqual(bounds["x"]+bounds["width"],390)
        self.assertLessEqual(bounds["y"]+bounds["height"],844)

    def test_address_search_does_not_open_remote_site(self):
        self.page.locator("#address").fill("lekarz weterynarii radom")
        self.page.locator("#address-form").press("Enter")
        self.assertTrue(self.page.locator("#page-view").is_visible())
        self.assertIn("www.google.com/search",self.page.locator("#page-domain").inner_text())
        self.assertTrue(all(x.startswith("http://127.0.0.1:") for x in self.requests))

    def test_address_navigation_back_forward(self):
        self.page.locator("#address").fill("example.com/path")
        self.page.locator("#address-form").press("Enter")
        self.assertEqual(self.page.locator("#page-title").inner_text(),"example.com")
        self.assertFalse(self.page.locator("#go-back").is_disabled())
        self.page.locator("#go-back").click()
        self.assertTrue(self.page.locator("#welcome").is_visible())
        self.page.locator("#go-forward").click()
        self.assertTrue(self.page.locator("#page-view").is_visible())

    def test_reject_unsafe_schemes(self):
        for bad in ["javascript:alert(1)","data:text/html,abc","http://example.com",
                    "https://owner:password@example.com","file:///etc/passwd",
                    "http://127.0.0.1", "https://localhost", "https://evil.example\\test"]:
            with self.subTest(address=bad):
                self.page.locator("#address").fill(bad)
                self.page.locator("#address-form").press("Enter")
                self.assertTrue(self.page.locator("#welcome").is_visible())

    def test_quick_links_are_safe_demo_only(self):
        self.page.get_by_role("button",name="Meta Business").click()
        self.assertIn("business.facebook.com",self.page.locator("#page-domain").inner_text())
        self.assertTrue(all(x.startswith("http://127.0.0.1:") for x in self.requests))

    def test_create_and_close_tabs(self):
        self.page.locator("#open-tabs").click()
        self.assertTrue(self.page.locator("#tabs-sheet").is_visible())
        self.page.locator("#new-tab").click()
        self.assertEqual(self.page.locator("#tab-count").inner_text(),"2")
        self.page.locator("#open-tabs").click()
        self.page.get_by_role("button",name="Zamknij kartę 2").click()
        self.assertEqual(self.page.locator("#tab-count").inner_text(),"1")
        self.page.locator("#close-tabs").click()

    def test_tab_switch_preserves_individual_history(self):
        self.page.locator("#address").fill("https://example.com/a")
        self.page.locator("#address-form").press("Enter")
        self.page.locator("#open-tabs").click()
        self.page.locator("#new-tab").click()
        self.page.locator("#address").fill("https://example.net/b")
        self.page.locator("#address-form").press("Enter")
        self.page.locator("#open-tabs").click()
        self.page.get_by_role("button",name="Przejdź do karty 1").click()
        self.assertIn("example.com/a",self.page.locator("#page-domain").inner_text())
        self.page.locator("#open-tabs").click()
        self.page.get_by_role("button",name="Przejdź do karty 2").click()
        self.assertIn("example.net/b",self.page.locator("#page-domain").inner_text())

    def test_workspaces_have_separate_tabs(self):
        self.page.locator("#address").fill("https://example.com/clinic")
        self.page.locator("#address-form").press("Enter")
        self.page.locator("#workspace-switch").click()
        self.page.locator(".workspace-entry").filter(has_text="Architekt").click()
        self.assertTrue(self.page.locator("#welcome").is_visible())
        self.assertIn("Architekt",self.page.locator("#workspace-label").inner_text())
        self.page.locator("#workspace-switch").click()
        self.page.locator(".workspace-entry").filter(has_text="Przychodnia").click()
        self.assertIn("example.com/clinic",self.page.locator("#page-domain").inner_text())

    def test_sheet_escape_and_focus(self):
        self.page.locator("#open-tabs").click()
        self.assertTrue(self.page.locator("#tabs-sheet").is_visible())
        self.page.keyboard.press("Escape")
        self.assertTrue(self.page.locator("#tabs-sheet").is_hidden())
        self.assertEqual(self.page.evaluate("document.activeElement.id"),"open-tabs")

    def test_menu_navigation(self):
        self.page.locator("#open-menu").click()
        self.assertTrue(self.page.locator("#menu-sheet").is_visible())
        self.page.locator("#menu-home").click()
        self.assertTrue(self.page.locator("#welcome").is_visible())

    def test_no_persisted_credentials_in_web_storage(self):
        self.page.locator("#address").fill("example.com")
        self.page.locator("#address-form").press("Enter")
        data=self.page.evaluate("""() => ({local:Object.keys(localStorage),
        session:Object.keys(sessionStorage),cookies:document.cookie})""")
        self.assertEqual({"local":[],"session":[],"cookies":""},data)

    def test_tab_list_text_cannot_inject_markup(self):
        self.page.locator("#address").fill("https://example.com/path/<img src=x onerror=alert(1)>")
        self.page.locator("#address-form").press("Enter")
        self.page.locator("#open-tabs").click()
        self.assertEqual(self.page.locator("#tab-items img").count(),0)
        self.assertTrue(all(x.startswith("http://127.0.0.1:") for x in self.requests))

    def test_desktop_layout(self):
        ctx=self.browser.new_context(viewport={"width":1365,"height":810})
        page=ctx.new_page()
        errors=[]
        page.on("pageerror",lambda e:errors.append(str(e)))
        page.goto(self.url)
        self.assertTrue(page.locator(".toolbar").is_visible())
        self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"),1365)
        self.assertEqual(errors,[])
        page.screenshot(path=str(ARTIFACTS/"desktop-home.png"),full_page=True)
        ctx.close()

    def test_narrow_iPhone_layout(self):
        self.page.set_viewport_size({"width":320,"height":680})
        self.assertLessEqual(self.page.evaluate("document.documentElement.scrollWidth"),320)
        self.assertTrue(self.page.locator("#address").is_visible())
        self.page.screenshot(path=str(ARTIFACTS/"small-iphone-home.png"),full_page=True)

    def test_no_technical_sessions_start_button(self):
        self.assertEqual(self.page.get_by_role("button",name="Start live").count(),0)
        self.assertEqual(self.page.get_by_role("button",name="Uruchom sesję").count(),0)


if __name__=="__main__":
    unittest.main(verbosity=2)
