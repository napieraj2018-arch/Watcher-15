"""Contract tests for isolated owner-browser OAuth handoff; no real Google calls."""
import json
import unittest
from urllib.parse import urlsplit

import httpx
from starlette.applications import Starlette
from youtube_oauth_handoff import OwnerYouTubeHandoff, HandoffError, COOKIE

ORIGIN = 'https://ai-browser-cloud.onrender.com'

class MemoryCAS:
    def __init__(self):
        self.rows = {}
        self.fail_write = False
    async def read(self, key):
        return self.rows.get(key)
    async def write(self, key, rev, data):
        if self.fail_write: raise ValueError('test failure: private secret')
        old = self.rows.get(key)
        if (old[0] if old else None) != rev: raise ValueError('CAS conflict')
        new = (rev or 0) + 1
        self.rows[key] = (new, data)
        return new

class StubYouTube:
    def __init__(self): self.begin_calls=[];self.finish_calls=[];self.fail=False
    async def begin(self, nonce):
        self.begin_calls.append(nonce)
        return 'https://accounts.google.com/o/oauth2/v2/auth?client_id=synthetic&state=stub-state'
    async def finish(self, state, code, nonce):
        self.finish_calls.append((state, code, nonce))
        if self.fail or (state,code) != ('stub-state','test-code'): return {'connected': False}
        if self.begin_calls[-1] != nonce: return {'connected': False}
        return {'connected':True,'channel_id':'UC'+'a'*22}

class Tests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clock=[1000]
        self.store=MemoryCAS()
        self.google=StubYouTube()
        self.handoff=OwnerYouTubeHandoff(ORIGIN,self.google,self.store,now=lambda:self.clock[0])
        self.client=httpx.AsyncClient(transport=httpx.ASGITransport(app=Starlette(routes=self.handoff.routes())),
                                      base_url=ORIGIN,follow_redirects=False)
    async def asyncTearDown(self): await self.client.aclose()
    async def invite(self): return (await self.handoff.new_invite()).split('invite=')[1]
    async def claim(self,token,**kwargs):
        headers={'Origin':ORIGIN,'Content-Type':'application/json'}
        headers.update(kwargs.pop('headers',{}))
        return await self.client.post('/youtube/oauth/claim',headers=headers,json={'invite':token},**kwargs)
    async def test_invitation_fragment_hidden_from_server(self):
        uri=await self.handoff.new_invite()
        self.assertEqual(urlsplit(uri).path, '/youtube/oauth/connect')
        self.assertEqual(urlsplit(uri).query,'')
        self.assertGreater(len(urlsplit(uri).fragment),40)
        self.assertNotIn('invite=',json.dumps(self.store.rows))
        page=await self.client.get('/youtube/oauth/connect')
        self.assertEqual(page.status_code,200)
        self.assertIn('Otwórz ten ekran w Safari',page.text)
        self.assertNotIn('unsafe-inline',page.headers['content-security-policy'])
        self.assertIn('no-store',page.headers['cache-control'])
    async def test_approved_claim_sets_first_party_cookie(self):
        token=await self.invite(); r=await self.claim(token)
        self.assertEqual(r.status_code,200)
        self.assertIn('Secure',r.headers['set-cookie'])
        self.assertIn('HttpOnly',r.headers['set-cookie'])
        self.assertIn('SameSite=lax',r.headers['set-cookie'])
        self.assertIn('__Host-aib-youtube-oauth=',r.headers['set-cookie'])
        self.assertTrue(r.json()['google_url'].startswith('https://accounts.google.com'))
        self.assertEqual(len(self.google.begin_calls),1)
    async def test_cannot_claim_twice(self):
        token=await self.invite()
        self.assertEqual((await self.claim(token)).status_code,200)
        self.assertEqual((await self.claim(token)).status_code,403)
        self.assertEqual(len(self.google.begin_calls),1)
    async def test_expired_invitation(self):
        token=await self.invite(); self.clock[0]+=301
        self.assertEqual((await self.claim(token)).status_code,403)
        self.assertEqual(len(self.google.begin_calls),0)
    async def test_wrong_origin_blocked(self):
        token=await self.invite()
        r=await self.claim(token,headers={'Origin':'https://evil.test'})
        self.assertEqual(r.status_code,403)
        self.assertEqual(len(self.google.begin_calls),0)
        self.assertEqual((await self.claim(token)).status_code,200)
    async def test_missing_origin_blocked(self):
        token=await self.invite()
        r=await self.client.post('/youtube/oauth/claim',json={'invite':token})
        self.assertEqual(r.status_code,403)
    async def test_other_content_type_blocked(self):
        token=await self.invite()
        r=await self.client.post('/youtube/oauth/claim',headers={'Origin':ORIGIN},data={'invite':token})
        self.assertEqual(r.status_code,415)
        self.assertEqual(len(self.google.begin_calls),0)
    async def test_malformed_body_does_not_use_token(self):
        token=await self.invite()
        r=await self.client.post('/youtube/oauth/claim',headers={'Origin':ORIGIN,'Content-Type':'application/json'},content=b'{}')
        self.assertEqual(r.status_code,403)
        self.assertEqual((await self.claim(token)).status_code,200)
    async def test_oversized_body(self):
        token=await self.invite()
        r=await self.client.post('/youtube/oauth/claim',headers={'Origin':ORIGIN,'Content-Type':'application/json'},content=b'x'*2000)
        self.assertEqual(r.status_code,413)
        self.assertEqual((await self.claim(token)).status_code,200)
    async def test_successful_callback_redirects_and_purges_cookie(self):
        await self.claim(await self.invite())
        r=await self.client.get('/youtube/oauth/callback?state=stub-state&code=test-code')
        self.assertEqual(r.status_code,303)
        self.assertEqual(r.headers['location'],'/youtube/oauth/done')
        self.assertNotIn('test-code',r.text)
        self.assertIn('Max-Age=0',r.headers['set-cookie'])
        self.assertEqual(len(self.google.finish_calls),1)
    async def test_callback_other_browser_without_cookie_fails(self):
        await self.claim(await self.invite())
        async with httpx.AsyncClient(transport=self.client._transport,base_url=ORIGIN) as other:
            r=await other.get('/youtube/oauth/callback?state=stub-state&code=test-code')
        self.assertEqual(r.status_code,403)
        self.assertEqual(len(self.google.finish_calls),0)
    async def test_callback_wrong_state_fails(self):
        await self.claim(await self.invite())
        r=await self.client.get('/youtube/oauth/callback?state=incorrect&code=test-code')
        self.assertEqual(r.status_code,403)
    async def test_callback_query_extra_not_accepted(self):
        await self.claim(await self.invite())
        r=await self.client.get('/youtube/oauth/callback?state=stub-state&code=test-code&next=https://evil.test')
        self.assertEqual(r.status_code,403)
    async def test_callback_denied_does_not_echo_google_error(self):
        r=await self.client.get('/youtube/oauth/callback?state=stub-state&error=access_denied')
        self.assertEqual(r.status_code,403)
        self.assertNotIn('access_denied',r.text)
    async def test_cas_failure_does_not_call_google(self):
        token=await self.invite()
        self.store.fail_write=True
        r=await self.claim(token)
        self.assertEqual(r.status_code,503)
        self.assertEqual(len(self.google.begin_calls),0)
        self.assertNotIn('private secret',r.text)
    async def test_callback_duplicate_parameters_fail(self):
        await self.claim(await self.invite())
        r=await self.client.get('/youtube/oauth/callback?state=stub-state&state=stub-state&code=test-code')
        self.assertEqual(r.status_code,403)
        self.assertEqual(len(self.google.finish_calls),0)
    async def test_provider_begin_failure_no_cookie(self):
        token=await self.invite()
        async def fail(nonce): raise RuntimeError('secret:internal')
        self.google.begin=fail
        r=await self.claim(token)
        self.assertEqual(r.status_code,503)
        self.assertNotIn('secret:internal',r.text)
        self.assertEqual((await self.claim(token)).status_code,403)
    async def test_origin_validation(self):
        for origin in ('http://x.test','https://x.test/a','https://u:p@x.test','https://x.test:444','https://x.test?x=1'):
            with self.assertRaises(HandoffError): OwnerYouTubeHandoff(origin,self.google,self.store)
    async def test_no_secrets_in_status_page(self):
        r=await self.client.get('/youtube/oauth/done')
        self.assertEqual(r.status_code,200)
        self.assertNotIn('token',r.text)
        self.assertIn('no-referrer',r.headers['referrer-policy'])

if __name__=='__main__': unittest.main()
