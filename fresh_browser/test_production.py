import asyncio, copy, json, unittest
from unittest.mock import AsyncMock, patch
import test_security
import server
import production_runtime as prod
from playwright.async_api import async_playwright

class Validation(unittest.TestCase):
    def test_rest_rejects_cross_origin_traversal_credentials_and_unsafe_writes(self):
        for spec in [dict(path='https://evil.invalid/'),dict(path='pages/../users'),dict(path='users/1'),dict(path='pages%2f1'),dict(path='pages?per_page=100'),dict(path='pages',method='DELETE'),dict(path='pages/1',method='POST',body={'content':'x'},operation_id='operation1'),dict(path='pages',method='POST',body={'status':'publish'},operation_id='operation1')]:
            with self.subTest(spec=spec),self.assertRaises(server.HTTPException):prod.validate_spec(json.dumps(spec))
    def test_official_scope_and_revision_hash_are_required(self):
        s={'path':'pages/1','method':'POST','body':{'title':'neutral'},'expected_sha256':'a'*64,'operation_id':'operation1'}
        self.assertEqual(prod.validate_spec(json.dumps(s)),s)
        self.assertIn('redirect:',prod.WP_FETCH)
        self.assertIn('X-WP-Nonce',prod.WP_FETCH)
        self.assertNotIn('document.cookie',prod.WP_FETCH)

class WriteSafety(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db={};self.writes=0
        self.before={'id':1,'title':{'raw':'before'},'content':{'raw':'neutral'},'status':'draft'}
        self.after={**self.before,'title':{'raw':'after'}}
        self.spec={'path':'pages/1','method':'POST','body':{'title':'after'},'operation_id':'neutral-operation-1','expected_sha256':prod.fingerprint(prod.editable(self.before))}
        self.w=type('Workspace',(),{})();self.w.lock=asyncio.Lock();self.w.context=object();self.w.profile=prod.WP_PROFILE;self.w.human=False
        self.w.assert_lease=AsyncMock();self.w._save=AsyncMock();self.w.page=lambda:type('Page',(),{'url':prod.WP_ORIGIN+'/wp-admin/'})()
        def checkpoint(ident,payload=None,revision=None):
            if payload is None:
                if ident not in self.db:raise server.HTTPException(404,'missing')
                return copy.deepcopy(self.db[ident])
            old=self.db.get(ident)
            if (revision is None and old) or (revision is not None and (not old or revision!=old['revision'])):raise server.HTTPException(409,'conflict')
            self.db[ident]={'checkpoint':copy.deepcopy(payload),'revision':old['revision']+1 if old else 1}
            return {'revision':self.db[ident]['revision']}
        async def rest(page,path,method='GET',body=None,upload=None):
            if path.startswith('users/me'):return {'data':{'id':1,'slug':'edycjanapieraj','name':'Owner'}}
            if method=='POST':self.writes+=1;return {'data':self.after}
            return {'data':self.after if self.writes else self.before}
        self.patches=[patch.object(server,'workspace',self.w),patch.object(server,'db_checkpoint',checkpoint),patch.object(prod,'rest',rest)]
        for p in self.patches:p.start()
    async def asyncTearDown(self):
        for p in reversed(self.patches):p.stop()
    async def run_write(self):return await prod.wordpress_action({'name':prod.WP_PROFILE,'text':json.dumps(self.spec)})
    async def test_confirmed_write_has_encrypted_store_backups_and_never_replays(self):
        a=await self.run_write();b=await self.run_write()
        self.assertTrue(a['verified']);self.assertTrue(b['already_confirmed']);self.assertEqual(self.writes,1)
        records=[v['checkpoint'] for v in self.db.values()];self.assertTrue(any(v.get('phase')=='verified' for v in records));self.assertTrue(any(v.get('encoding')=='base64-json-chunk' for v in records))
    async def test_conflict_stops_before_external_write(self):
        self.spec['expected_sha256']='0'*64
        with self.assertRaises(server.HTTPException):await self.run_write()
        self.assertEqual(self.writes,0)

    async def test_uncertain_external_write_is_never_repeated(self):
        original=prod.rest
        async def fail(page,path,method='GET',body=None,upload=None):
            if method=='POST':self.writes+=1;raise TimeoutError('unknown result')
            return await original(page,path,method,body,upload)
        with patch.object(prod,'rest',fail):
            with self.assertRaises(TimeoutError):await self.run_write()
            with self.assertRaises(server.HTTPException):await self.run_write()
        self.assertEqual(self.writes,1)
    async def test_owner_handoff_cannot_be_interrupted(self):
        self.w.human=True
        with self.assertRaises(server.HTTPException):await self.run_write()
        self.assertEqual(self.writes,0)


class BrowserProtocol(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.pw=await async_playwright().start()
        self.browser=await self.pw.chromium.launch()
        self.page=await self.browser.new_page()
        self.calls=[]
        self.css='/* existing fixture */'
        async def route(r):
            from urllib.parse import parse_qs,urlsplit
            req=r.request;self.calls.append((req.url,req.method))
            path=urlsplit(req.url).path
            if path.endswith('/admin-ajax.php'):
                if req.method=='POST':
                    fields=parse_qs(req.post_data)
                    self.assertEqual(fields['nonce'],['fixture123'])
                    self.css=fields['newcontent'][0]
                    return await r.fulfill(json={'success':True})
                return await r.fulfill(body='fixture123')
            if path.endswith('/theme-editor.php'):
                return await r.fulfill(content_type='text/html',body='<form><input name="theme" value="fixture"><input name="file" value="style.css"><input name="nonce" value="fixture123"><textarea name="newcontent">'+self.css+'</textarea></form>')
            if '/wp-json/wp/v2/' in path:
                self.assertEqual(req.headers.get('x-wp-nonce'),'fixture123')
                return await r.fulfill(json={'id':1,'slug':'edycjanapieraj'})
            return await r.fulfill(content_type='text/html',body='<title>Owner fixture</title>')
        await self.page.route('**/*',route)
        await self.page.goto(prod.WP_ORIGIN+'/wp-admin/')
    async def asyncTearDown(self):
        await self.browser.close();await self.pw.stop()
    async def test_rest_uses_nonce_inside_owner_origin_without_export(self):
        result=await prod.rest(self.page,'users/me?context=edit')
        self.assertEqual(result['data']['slug'],'edycjanapieraj')
        self.assertNotIn('fixture123',json.dumps(result))
        self.assertTrue(any('/wp-json/wp/v2/users/me?' in u for u,m in self.calls))
    async def test_theme_css_uses_wordpress_core_nonce_and_readback(self):
        before=await prod.rest(self.page,'theme-css/fixture/style.css?context=edit')
        self.assertEqual(before['data']['content']['raw'],self.css)
        await prod.rest(self.page,'theme-css/fixture/style.css','POST',{'content':'/* changed fixture */'})
        after=await prod.rest(self.page,'theme-css/fixture/style.css?context=edit')
        self.assertEqual(after['data']['content']['raw'],'/* changed fixture */')
