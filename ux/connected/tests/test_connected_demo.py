"""End-to-end localhost-only integration of browser UI and synthetic broker.

No external websites are fetched and no real browser profiles are opened.
"""
from __future__ import annotations
import json
import pathlib
import sys
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request,urlopen

from playwright.sync_api import sync_playwright

HERE=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
from demo_server import DemoServer

class AutoOpenDemoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.play=sync_playwright().start()
        cls.browser=cls.play.chromium.launch(headless=True,args=["--no-sandbox"])

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
        self.external=[]
        self.errors=[]
        self.page.on("request",lambda req:self.external.append(req.url)
                     if not req.url.startswith(self.base) else None)
        self.page.on("pageerror",lambda e:self.errors.append(str(e)))
        self.page.goto(self.base+"/demo",wait_until="networkidle")

    def tearDown(self):
        self.assertEqual(self.errors,[])
        self.assertEqual(self.external,[],"The demo must NEVER call external sites")
        self.ctx.close()
        self.http.shutdown()
        self.http.server_close()
        self.thread.join(timeout=1)

    def address(self,url):
        self.page.locator("#address").fill(url)
        self.page.locator("#address-form").press("Enter")

    def select_workspace(self,label):
        self.page.locator("#workspace-switch").click()
        self.page.locator(".workspace-entry").filter(has_text=label).click()

    def request_api(self,path,data,origin=None):
        payload=json.dumps(data).encode("utf-8")
        request=Request(self.base+path,data=payload,method="POST",
            headers={"content-type":"application/json","Origin":origin if origin is not None else self.base})
        try:
            with urlopen(request,timeout=4) as response:
                return response.status,json.loads(response.read())
        except HTTPError as error:
            return error.code,json.loads(error.read())

    def test_demo_opens_normal_mobile_window(self):
        self.assertTrue(self.page.get_by_role("heading",name="W czym dzisiaj pomóc?").is_visible())
        self.assertIn("Symulator",self.page.locator("#connection-label").inner_text())
        self.assertFalse(self.page.locator("#demo-end-task").is_visible())

    def test_typing_address_starts_session_without_live_button(self):
        self.address("https://business.facebook.com/latest/home")
        self.page.wait_for_function("""() => document.querySelector('#connection-label').textContent.includes('Gotowe')""")
        self.assertEqual(self.http.adapter.count,1)
        self.assertEqual(self.http.adapter.current[0]["mode"],"read_only")
        self.assertEqual(self.page.locator("#tab-count").inner_text(),"1")
        self.assertFalse(self.page.get_by_role("button",name="Uruchom sesję").count())
        self.assertIn("fikcyjna",self.page.locator(".tip").inner_text())

    def test_same_workspace_new_browser_tab_reuses_synthetic_session(self):
        self.address("https://business.facebook.com/latest/home")
        self.page.wait_for_function("""() => document.querySelector('#connection-label').textContent.includes('Gotowe')""")
        self.page.locator("#open-tabs").click()
        self.page.locator("#new-tab").click()
        self.address("https://www.google.com/")
        self.page.wait_for_function("""() => document.querySelector('#connection-label').textContent.includes('Gotowe')""")
        self.assertEqual(self.http.adapter.count,1)
        self.assertEqual(len(self.http.broker.active.tab_ids),2)

    def test_other_workspace_goes_to_queue_until_owner_closes(self):
        self.address("https://business.facebook.com/latest/home")
        self.page.wait_for_function("""() => document.querySelector('#connection-label').textContent.includes('Gotowe')""")
        self.select_workspace("Architekt")
        self.address("https://www.google.com/")
        self.page.wait_for_function("""() => document.querySelector('#connection-label').textContent.includes('kolejce')""")
        self.assertEqual(self.http.adapter.count,1)
        self.assertEqual(len(self.http.broker.queue),1)
        self.select_workspace("Przychodnia")
        self.page.locator("#open-menu").click()
        self.page.locator("#demo-end-task").click()
        self.assertEqual(self.http.adapter.current,[])
        self.select_workspace("Architekt")
        self.page.wait_for_function("""() => document.querySelector('#connection-label').textContent.includes('Gotowe')""",timeout=8000)
        self.assertEqual(self.http.adapter.count,2)
        self.assertEqual(self.http.adapter.current[0]["profile"],"Synthetic - Architect")

    def test_close_other_workspace_task_rejected(self):
        self.address("https://business.facebook.com/latest/home")
        self.page.wait_for_function("""() => document.querySelector('#connection-label').textContent.includes('Gotowe')""")
        self.select_workspace("Architekt")
        self.page.locator("#open-menu").click()
        self.page.locator("#demo-end-task").click()
        self.assertEqual(self.http.adapter.count,1)
        self.assertEqual(len(self.http.adapter.current),1)

    def test_reject_cross_origin_post(self):
        code,result=self.request_api("/_demo/api/open",{
            "workspace_id":"clinic",
            "url":"https://business.facebook.com",
            "request_id":"test-request-000001","tab_id":1},
            origin="https://evil.example.test")
        self.assertEqual(code,403)
        self.assertEqual(self.http.adapter.count,0)

    def test_block_unexpected_tenant_field(self):
        code,result=self.request_api("/_demo/api/open",{
            "workspace_id":"clinic",
            "url":"https://business.facebook.com",
            "request_id":"test-request-000001","tab_id":1,
            "tenant_id":"other-tenant"})
        self.assertEqual(code,409)
        self.assertEqual(self.http.adapter.count,0)

    def test_cross_tenant_domain_out_of_scope(self):
        code,result=self.request_api("/_demo/api/open",{
            "workspace_id":"clinic",
            "url":"https://internal.corp.example.test/private",
            "request_id":"test-request-000001","tab_id":1})
        self.assertEqual(code,409)
        self.assertEqual(self.http.adapter.count,0)

    def test_idempotent_post_does_not_start_twice(self):
        body={"workspace_id":"clinic","url":"https://business.facebook.com/",
              "request_id":"test-request-000001","tab_id":1}
        code,a=self.request_api("/_demo/api/open",body)
        code2,b=self.request_api("/_demo/api/open",body)
        self.assertEqual((code,code2),(200,200))
        self.assertEqual(a,b)
        self.assertEqual(self.http.adapter.count,1)
        self.assertNotIn("fake-remote-",json.dumps(a))

    def test_unknown_workspace_disallowed(self):
        code,result=self.request_api("/_demo/api/open",{
            "workspace_id":"other-tenant",
            "url":"https://business.facebook.com",
            "request_id":"test-request-000001","tab_id":1})
        self.assertEqual(code,409)
        self.assertEqual(self.http.adapter.count,0)

    def test_payload_does_not_expose_internal_session_id(self):
        self.address("https://business.facebook.com/latest/home")
        self.page.wait_for_function("""() => document.querySelector('#connection-label').textContent.includes('Gotowe')""")
        status_url=self.base+"/_demo/api/status?workspace_id=clinic"
        with urlopen(status_url,timeout=4) as response:
            data=response.read().decode()
        self.assertNotIn("fake-remote-",data)
        self.assertIn('"my_task_active":true',data)

    def test_demo_has_no_external_requests_after_queue_and_close(self):
        self.address("https://www.google.com/")
        self.page.wait_for_function("""() => document.querySelector('#connection-label').textContent.includes('Gotowe')""")
        self.page.locator("#open-menu").click()
        self.page.locator("#demo-end-task").click()
        self.assertEqual(self.external,[])
        self.assertEqual(self.http.adapter.current,[])

if __name__=="__main__":
    unittest.main(verbosity=2)
