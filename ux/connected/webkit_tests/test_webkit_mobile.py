"""Mobile WebKit smoke checks for the local-only browser auto-window demo.

WebKit on Linux is a rendering-engine approximation; this is NOT the same as
physical iPhone Safari or an Apple accessibility/VoiceOver certification.
"""
from __future__ import annotations
import pathlib
import sys
import threading
import unittest

from playwright.sync_api import sync_playwright

HERE=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
from demo_server import DemoServer

class DemoMobileWebKit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.play=sync_playwright().start()
        cls.browser=cls.play.webkit.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.play.stop()

    def setUp(self):
        self.http=DemoServer(("127.0.0.1",0))
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True)
        self.thread.start()
        self.base="http://127.0.0.1:"+str(self.http.server_port)
        self.ctx=self.browser.new_context(viewport={"width":390,"height":844},
            is_mobile=True,has_touch=True)
        self.page=self.ctx.new_page()
        self.bad_requests=[]
        self.errors=[]
        self.page.on("request",lambda req:self.bad_requests.append(req.url)
                     if not req.url.startswith(self.base) else None)
        self.page.on("pageerror",lambda e:self.errors.append(str(e)))
        self.page.goto(self.base+"/demo",wait_until="networkidle")

    def tearDown(self):
        self.assertEqual(self.errors,[])
        self.assertEqual(self.bad_requests,[])
        self.ctx.close()
        self.http.shutdown()
        self.http.server_close()
        self.thread.join(timeout=1)

    def enter(self,url):
        self.page.locator("#address").fill(url)
        # Press the *input* as a real iPhone user would, rather than sending
        # an Enter key event to the FORM element (engine-dependent behavior).
        self.page.locator("#address").press("Enter")

    def assertStatus(self,expected,timeout=6000):
        try:
            self.page.wait_for_function(
                "(needle)=>document.querySelector('#connection-label').textContent.includes(needle)",
                expected,timeout=timeout)
        except Exception as exc:
            state=self.page.evaluate("""() => ({
                label:document.querySelector('#connection-label')?.textContent,
                placeholder:document.querySelector('#page-view .tip')?.textContent,
                secureContext:window.isSecureContext,
                randomUUID:typeof crypto.randomUUID,
                domain:document.querySelector('#page-domain')?.textContent
            })""")
            raise AssertionError("WEBKIT_DEMO_STATE "+repr(state)+" page_errors="+repr(self.errors)) from exc

    def switch(self,name):
        self.page.locator("#workspace-switch").click()
        self.page.locator(".workspace-entry").filter(has_text=name).click()

    def test_ipad_and_iphone_layout_not_overflow(self):
        self.assertTrue(self.page.get_by_role("heading",name="W czym dzisiaj pomóc?").is_visible())
        for width in (320,390,430,768):
            with self.subTest(width=width):
                self.page.set_viewport_size({"width":width,"height":844})
                self.assertFalse(self.page.evaluate(
                    "document.documentElement.scrollWidth>window.innerWidth+1"))
        size=self.page.locator("#address").evaluate(
            "(el)=>parseFloat(getComputedStyle(el).fontSize)")
        self.assertGreaterEqual(size,16)

    def test_new_address_auto_starts_without_live_button(self):
        self.enter("https://business.facebook.com/latest/home")
        self.assertStatus("Gotowe")
        self.assertEqual(self.http.adapter.count,1)
        self.assertEqual(self.http.adapter.current[0]["mode"],"read_only")
        self.assertEqual(self.page.get_by_role("button",name="Uruchom sesję").count(),0)

    def test_another_workspace_queued_then_resumes(self):
        self.enter("https://business.facebook.com/latest/home")
        self.assertStatus("Gotowe")
        self.switch("Architekt")
        self.enter("https://www.google.com/")
        self.assertStatus("kolejce")
        self.assertEqual(len(self.http.broker.queue),1)
        self.switch("Przychodnia")
        self.page.locator("#open-menu").click()
        self.page.locator("#demo-end-task").click()
        self.switch("Architekt")
        self.assertStatus("Gotowe",timeout=10000)
        self.assertEqual(self.http.adapter.count,2)

    def test_sheet_escape_restores_focus(self):
        self.page.locator("#open-tabs").click()
        self.assertTrue(self.page.locator("#tabs-sheet").is_visible())
        self.page.keyboard.press("Escape")
        self.assertTrue(self.page.locator("#tabs-sheet").is_hidden())
        self.assertEqual(
            self.page.evaluate("document.activeElement.id"),"open-tabs")

    def test_untrusted_scheme_does_not_start_browser(self):
        self.enter("javascript:alert(1)")
        self.assertTrue(self.page.locator("#welcome").is_visible())
        self.assertEqual(self.http.adapter.count,0)

    def test_background_tab_status_and_separation(self):
        self.enter("https://www.google.com/")
        self.assertStatus("Gotowe")
        self.page.locator("#open-tabs").click()
        self.page.locator("#new-tab").click()
        self.enter("https://github.com/")
        self.assertStatus("Gotowe")
        self.assertEqual(self.http.adapter.count,1)
        self.assertEqual(len(self.http.broker.active.tab_ids),2)

if __name__=="__main__":
    unittest.main(verbosity=2)
