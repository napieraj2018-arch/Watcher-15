"""Accessibility tests of synthetic browser chrome (no customer accounts)."""
from __future__ import annotations
import functools
import os
import pathlib
import re
import threading
import unittest
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer

from playwright.sync_api import sync_playwright

ROOT=pathlib.Path(__file__).resolve().parents[3]
AXE=ROOT/"node_modules"/"axe-core"/"axe.min.js"

class Quiet(SimpleHTTPRequestHandler):
    def log_message(self,*_):pass

def ratio(a,b):
    def parse(s):
        nums=[int(v) for v in re.findall(r"[\d]+",s)[:3]]
        if len(nums)!=3:raise AssertionError("Unexpected RGB format: "+s)
        return [x/255 for x in nums]
    def lum(s):
        rgb=parse(s)
        rgb=[x/12.92 if x<=.04045 else ((x+.055)/1.055)**2.4 for x in rgb]
        return .2126*rgb[0]+.7152*rgb[1]+.0722*rgb[2]
    la,lb=lum(a),lum(b)
    return (max(la,lb)+.05)/(min(la,lb)+.05)

class AccessibilityChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not AXE.is_file():
            raise RuntimeError("npm --no-save install axe-core before accessibility tests")
        handler=functools.partial(Quiet,directory=str(ROOT))
        cls.server=ThreadingHTTPServer(("127.0.0.1",0),handler)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()
        cls.origin="http://127.0.0.1:"+str(cls.server.server_port)
        cls.play=sync_playwright().start()
        cls.browser=cls.play.chromium.launch(headless=True,args=["--no-sandbox"])

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.play.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=1)

    def setUp(self):
        self.ctx=self.browser.new_context(viewport={"width":390,"height":844},
            is_mobile=True,has_touch=True)
        self.page=self.ctx.new_page()
        self.external=[]
        self.page.on("request",lambda req:self.external.append(req.url)
                     if not req.url.startswith(self.origin) else None)
        self.page.goto(self.origin+"/ux/mobile/workspace.html",wait_until="networkidle")
        self.page.add_script_tag(url=self.origin+"/node_modules/axe-core/axe.min.js")

    def tearDown(self):
        self.assertEqual(self.external,[],"UX test must not load remote websites")
        self.ctx.close()

    def axe_violations(self):
        result=self.page.evaluate("""async () => {
          const result=await axe.run(document,{runOnly:{type:'tag',
            values:['wcag2a','wcag2aa','wcag21a','wcag21aa','wcag22aa']}});
          return result.violations.map(v=>({
            id:v.id,impact:v.impact,
            nodes:v.nodes.map(n=>n.target.join(' > ')).slice(0,6)
          }));
        }""")
        self.assertEqual(result,[],"Accessibility audit failures: "+repr(result))

    def test_mobile_home_wcag(self):
        self.axe_violations()

    def test_tabs_drawer_wcag(self):
        self.page.locator("#open-tabs").click()
        self.axe_violations()

    def test_workspace_switcher_wcag(self):
        self.page.locator("#workspace-switch").click()
        self.axe_violations()

    def test_workspace_selection_is_single_accessible_toggle(self):
        self.page.locator("#workspace-switch").click()
        buttons=self.page.locator(".workspace-entry")
        self.assertEqual(buttons.count(),3)
        self.assertEqual(buttons.locator('[aria-pressed="true"]').count(),0)
        selected=self.page.locator('.workspace-entry[aria-pressed="true"]')
        self.assertEqual(selected.count(),1)
        self.page.locator(".workspace-entry").filter(has_text="Architekt").click()
        self.page.locator("#workspace-switch").click()
        selected=self.page.locator('.workspace-entry[aria-pressed="true"]')
        self.assertEqual(selected.count(),1)
        self.assertIn("Architekt",selected.inner_text())

    def test_modal_animation_does_not_fade_text_opacity(self):
        self.page.locator("#open-tabs").click()
        opacity=self.page.locator("#tabs-sheet").evaluate(
            "(node) => getComputedStyle(node).opacity")
        self.assertEqual(opacity,"1")

    def test_options_menu_wcag(self):
        self.page.locator("#open-menu").click()
        self.axe_violations()

    def test_page_placeholder_wcag(self):
        self.page.locator("#address").fill("https://example.com/")
        self.page.locator("#address-form").press("Enter")
        self.axe_violations()

    def test_desktop_home_wcag(self):
        self.page.set_viewport_size({"width":1365,"height":810})
        self.axe_violations()

    def assert_text_pair(self,selector,bg,minimum=4.5):
        foreground=self.page.locator(selector).evaluate(
            "(node) => getComputedStyle(node).color")
        c=ratio(foreground,bg)
        self.assertGreaterEqual(c,minimum,f"{selector}: contrast {c:.2f} < {minimum:.2f}")

    def test_small_mobile_labels_minimum_aa_contrast(self):
        self.assert_text_pair(".welcome .eyebrow","rgb(252,253,255)")
        self.assert_text_pair(".welcome-note","rgb(247,249,253)")
        self.assert_text_pair(".strip-trailing","rgb(247,248,251)")
        self.assert_text_pair(".welcome-sub","rgb(252,253,255)")

    def test_address_placeholder_aa_contrast(self):
        color=self.page.locator("#address").evaluate(
            "(node) => getComputedStyle(node,'::placeholder').color")
        bg=self.page.locator(".address-bar").evaluate(
            "(node) => getComputedStyle(node).backgroundColor")
        self.assertGreaterEqual(ratio(color,bg),4.5)

    def test_modal_small_type_aa_contrast(self):
        self.page.locator("#open-tabs").click()
        self.assert_text_pair(".tab-domain","rgb(255,255,255)")
        self.page.locator("#close-tabs").click()
        self.page.locator("#open-menu").click()
        self.assert_text_pair("#menu-sheet .sheet-footnote","rgb(255,255,255)")

if __name__=="__main__":
    unittest.main(verbosity=2)
