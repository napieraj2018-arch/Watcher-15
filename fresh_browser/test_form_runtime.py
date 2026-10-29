"""Offline regressions: no real provider login, credentials or database."""
import asyncio
import json
import os
import re
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from pathlib import Path
from playwright.async_api import async_playwright
import server
from navigation_runtime import AuditedWorkspace, PublicNetworkPolicy, network_host

PUBLIC = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34',443))]
PRIVATE = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1',443))]

class PolicyTests(unittest.IsolatedAsyncioTestCase):
    def request(self, url='https://fixture.invalid/', method='POST', navigation=True):
        return SimpleNamespace(url=url,method=method,is_navigation_request=lambda:navigation)
    def route(self, req):
        return SimpleNamespace(request=req,continue_=AsyncMock(),abort=AsyncMock())
    async def test_long_https_callback_is_not_ui_length_limited(self):
        req=self.request('https://fixture.invalid/callback?state='+'x'*3000)
        events=[];p=PublicNetworkPolicy(lambda r,c:events.append(c),resolver=lambda *a,**k:PUBLIC)
        r=self.route(req);await p(r)
        r.continue_.assert_awaited_once_with();r.abort.assert_not_awaited();self.assertEqual(events,[])
    async def test_private_addresses_still_blocked_and_classified(self):
        events=[];p=PublicNetworkPolicy(lambda r,c:events.append(c),resolver=lambda *a,**k:PRIVATE)
        r=self.route(self.request());await p(r)
        self.assertEqual(events,['address_policy']);r.abort.assert_awaited_once_with('blockedbyclient');r.continue_.assert_not_awaited()
    async def test_dns_failure_is_not_generic_form_failure(self):
        def dns(*a,**k):raise socket.gaierror('DO_NOT_ECHO_DNS_DETAILS')
        events=[];p=PublicNetworkPolicy(lambda r,c:events.append(c),resolver=dns)
        r=self.route(self.request());await p(r)
        self.assertEqual(events,['dns_unavailable']);r.abort.assert_awaited_once_with('namenotresolved');r.continue_.assert_not_awaited()
    async def test_continue_transport_error_not_replayed_or_double_aborted(self):
        events=[];p=PublicNetworkPolicy(lambda r,c:events.append(c),resolver=lambda *a,**k:PUBLIC)
        r=self.route(self.request());r.continue_.side_effect=RuntimeError('PRIVATE_BODY_NO_LOG')
        await p(r);r.continue_.assert_awaited_once();r.abort.assert_not_awaited();self.assertEqual(events,['transport_unconfirmed'])
    async def test_main_navigation_revalidates_and_subresources_share_dns(self):
        calls=[]
        def dns(*a,**kw):calls.append(a);return PUBLIC
        p=PublicNetworkPolicy(lambda *_:None,resolver=dns)
        for main in [False,False,False,True,True]:await p(self.route(self.request(navigation=main)))
        self.assertEqual(len(calls),3)
    async def test_network_url_boundaries_unchanged(self):
        for u in ['http://fixture.invalid/','https://localhost/','https://127.0.0.1/','https://host.internal/','https://user:password@fixture.invalid/','https://fixture.invalid:88/','https://fixture.invalid/?x='+'x'*17000]:
            with self.subTest(u=u[:40]):
                with self.assertRaises(ValueError):network_host(u)

class RealFormTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.pw=await async_playwright().start()
        options={'headless':True,'args':['--no-sandbox','--disable-dev-shm-usage']}
        if os.environ.get('AIB_TEST_CHROMIUM'):options['executable_path']=os.environ['AIB_TEST_CHROMIUM']
        self.browser=await self.pw.chromium.launch(**options)
        self.context=await self.browser.new_context()
        self.w=AuditedWorkspace();self.w.context=self.context;self.w.profile='acceptance-form-fixture';self.w.rev=1
        self.w.guarded_context=self.context;self.w.assert_lease=AsyncMock();self.w._save=AsyncMock()
        self.context.on('page',self.w.register_page)
        self.page=await self.context.new_page();self.w.active_page=self.page
    async def asyncTearDown(self):
        await self.context.close();await self.browser.close();await self.pw.stop()
    async def broken_form(self):
        self.methods=[]
        async def route(r):
            self.methods.append(r.request.method)
            if r.request.method=='POST':await r.abort('failed')
            else:await r.fulfill(content_type='text/html',body="<title>Fixture</title><form method='post' action='/submit?private=not-for-logs'><input name='fixture' value='SYNTHETIC_BODY_NO_LOG'><button>Submit</button></form>")
        await self.context.route('https://fixture.invalid/**',route)
        await self.page.goto('https://fixture.invalid/form')
        async with self.page.expect_event('requestfailed',predicate=lambda r:r.method=='POST'):
            await self.page.locator('button').click(no_wait_after=True)
        await self.page.wait_for_url(re.compile(r'^(about:|chrome-error:)'),wait_until='commit',timeout=5000)
    async def test_failed_post_preserves_prior_get_and_is_not_replayed(self):
        await self.broken_form()
        self.assertEqual(self.w.navigation_state(self.page),'failed')
        self.assertEqual(self.w.saved_url(self.page),'https://fixture.invalid/form')
        self.assertEqual(self.methods.count('POST'),1)
        diagnostic=await self.w.diagnostics(self.w.profile)
        text=json.dumps(diagnostic)
        self.assertNotIn('not-for-logs',text);self.assertNotIn('SYNTHETIC_BODY_NO_LOG',text)
        self.assertEqual(diagnostic['navigation_failures'][-1]['method'],'POST')
        result=await self.w.action({'name':self.w.profile,'action':'reload'},automated=True)
        self.assertEqual(self.methods.count('POST'),1)
        self.assertTrue(result['ok']);self.assertEqual(result['navigation'],'ready')
    async def test_redirect_login_sets_cookies_before_state_is_reused(self):
        # Route interception is not a redirect server: redirects after a mocked
        # 303 can leave the mocked .invalid origin. Use an isolated real HTTP
        # server on loopback; production network policy still rejects loopback.
        class Fixture(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def do_POST(self):
                self.rfile.read(int(self.headers.get('Content-Length','0')))
                self.send_response(303)
                self.send_header('Location','/done')
                self.send_header('Set-Cookie','synthetic_session=ok; SameSite=Lax; Path=/')
                self.end_headers()
            def do_GET(self):
                body=(b'<title>Fixture account</title><h1>Signed in fixture</h1>' if self.path=='/done'
                      else b"<form method='post' action='/submit'><button>Submit</button></form>")
                self.send_response(200);self.send_header('Content-Type','text/html')
                self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        srv=ThreadingHTTPServer(('127.0.0.1',0),Fixture)
        thread=Thread(target=srv.serve_forever,daemon=True);thread.start()
        origin=f'http://127.0.0.1:{srv.server_port}'
        try:
            await self.page.goto(origin+'/form');await self.page.locator('button').click()
            await self.page.wait_for_url(origin+'/done',wait_until='domcontentloaded',timeout=10000)
            self.assertEqual(await self.page.locator('h1').inner_text(),'Signed in fixture')
            state=await self.context.storage_state(indexed_db=True)
            self.assertTrue(any(c['name']=='synthetic_session' and c['value']=='ok' for c in state['cookies']))
            second=await self.browser.new_context(storage_state=state)
            try:self.assertTrue(any(c['name']=='synthetic_session' and c['value']=='ok' for c in await second.cookies()))
            finally:await second.close()
        finally:
            await asyncio.to_thread(srv.shutdown);srv.server_close();thread.join(timeout=2)
    async def test_diagnostics_human_mode_read_only_and_no_form_values(self):
        await self.context.route('https://fixture.invalid/**',lambda r:r.fulfill(content_type='text/html',body="<form action='/login?secret=PRIVATE_QUERY' method='post'><input name='password' value='PRIVATE_INPUT'></form>"))
        await self.page.goto('https://fixture.invalid/form');self.w.human=True
        result=await self.w.action({'name':self.w.profile,'action':'diagnostics'},automated=True)
        text=json.dumps(result);self.assertNotIn('PRIVATE_QUERY',text);self.assertNotIn('PRIVATE_INPUT',text)
        self.assertTrue(result['human']);self.w._save.assert_not_awaited()
        with self.assertRaises(server.HTTPException) as e:await self.w.action({'name':self.w.profile,'action':'reload'},automated=True)
        self.assertEqual(e.exception.status_code,409)
    async def test_panel_failed_frame_does_not_report_success_or_submit(self):
        html=Path(__file__).with_name('index.html').read_text()
        requests=[]
        async def api(r):
            u=r.request.url;requests.append((r.request.method,u))
            if '/api/session' in u:payload={'ok':True}
            elif '/api/profiles' in u:payload={'profiles':[{'name':'acceptance-form-fixture'}]}
            elif '/api/action' in u:payload={'ok':False,'navigation':'failed','url':'https://fixture.invalid'}
            elif '/api/tabs' in u:payload={'tabs':[{'id':'tab-1','active':True,'url':'https://fixture.invalid','title':'','navigation':'failed'}]}
            elif '/api/screen' in u:
                await r.fulfill(status=200,body=b'not-a-real-image',content_type='image/png',headers={'X-AIB-Navigation':'failed','X-AIB-Page':'tab-1','X-AIB-Tabs':'1','X-AIB-Origin':'https://fixture.invalid'});return
            else:await r.fulfill(content_type='text/html',body=html);return
            await r.fulfill(content_type='application/json',body=json.dumps(payload))
        await self.context.route('https://panel.invalid/**',api)
        await self.page.goto('https://panel.invalid/')
        await self.page.wait_for_function("document.getElementById('profile').value === 'acceptance-form-fixture'",timeout=5000)
        await self.page.locator('#openBtn').click()
        await self.page.wait_for_function("document.getElementById('liveStatus').textContent.includes('Błąd')",timeout=5000)
        self.assertTrue(await self.page.locator('#screen').is_hidden())
        self.assertTrue(await self.page.locator('#emptyScreen').is_visible())
        self.assertTrue(await self.page.locator('#typeBtn').is_disabled())
        self.assertTrue(await self.page.locator('#enterBtn').is_disabled())
        self.assertNotIn('Gotowe',await self.page.locator('#message').inner_text())
        self.assertEqual(sum(1 for m,u in requests if m=='POST' and '/api/action' in u),1)

if __name__=='__main__':unittest.main()
