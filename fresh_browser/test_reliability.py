"""Synthetic regression coverage, no real website writes."""
import asyncio
import copy
import hashlib
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import test_security
import server
import production_runtime as prod
import reliability_runtime as repair


class Validation(unittest.TestCase):
    def spec(self):
        return {'path':'theme-css/fixture/style.css','operation_id':'fixture-operation-01',
                'expected_sha256':'a'*64,'patches':[{'find':'color:red','replace':'color:blue'}]}
    def test_large_css_small_patch(self):
        css='/* unchanged */\n'*10000+'body{color:red}'
        out=repair.patched_text(css,self.spec()['patches'])
        self.assertGreater(len(css),144777)
        self.assertTrue(out.endswith('body{color:blue}'))
        self.assertEqual(out[:-16],css[:-15])
    def test_read_response_is_bounded(self):
        for extra in [{'limit':6001},{'limit':True},{'offset':-1},{'offset':512001}]:
            with self.subTest(extra=extra),self.assertRaises(server.HTTPException):
                repair.parse_spec(json.dumps({'path':'theme-css/fixture/style.css',**extra}),'wordpress_css_read')
    def test_paths_and_secrets_cannot_be_smuggled(self):
        for path in ['theme-css/fixture/../a.css','https://evil.invalid/a.css','theme-css/fixture/a.php',
                     'theme-css/fixture/a.css?nonce=x','theme-css/fixture/%2e%2e/a.css','theme-css/fixture/a.css#x']:
            with self.subTest(path=path),self.assertRaises(server.HTTPException):
                repair.parse_spec(json.dumps({'path':path}),'wordpress_css_read')
    def test_unknown_fields_and_unbounded_payload_rejected(self):
        for raw in ['null','[]','{}',json.dumps({**self.spec(),'unknown':1}),
                    json.dumps({**self.spec(),'patches':[{'find':'x','replace':'a'*20001}]}),
                    json.dumps({**self.spec(),'commit':'true'}),json.dumps({**self.spec(),'commit':True})]:
            with self.subTest(raw=raw[:100]),self.assertRaises(server.HTTPException):
                repair.parse_spec(raw,'wordpress_css_patch')
    def test_preview_is_default_and_commit_needs_result_hash(self):
        self.assertFalse(repair.parse_spec(json.dumps(self.spec()),'wordpress_css_patch').get('commit',False))
        s={**self.spec(),'commit':True,'expected_result_sha256':'b'*64}
        self.assertTrue(repair.parse_spec(json.dumps(s),'wordpress_css_patch')['commit'])
    def test_ambiguous_and_absent_match_rejected(self):
        for text in ['color:red color:red','color:green']:
            with self.subTest(text=text),self.assertRaises(server.HTTPException):
                repair.patched_text(text,self.spec()['patches'])
    def test_css_security_check_assembled_document(self):
        for value in ['<?php echo 1;','@import "x";','expression(alert(1))','javascript:alert(1)']:
            with self.subTest(value=value),self.assertRaises(server.HTTPException):
                repair.patched_text('abc',[{'find':'abc','replace':value}])
    def test_document_limit_uses_utf8_bytes(self):
        with self.assertRaises(server.HTTPException):
            repair.patched_text('ą'*256001,[{'find':'ą','replace':'x'}])
    def test_noop_rejected(self):
        with self.assertRaises(server.HTTPException):
            repair.patched_text('abc',[{'find':'abc','replace':'abc'}])
    def test_status_has_strict_id_only(self):
        for x in [{'operation_id':'short'},{'operation_id':'valid-operation','path':'pages/1'}]:
            with self.subTest(x=x),self.assertRaises(server.HTTPException):
                repair.parse_spec(json.dumps(x),'wordpress_css_status')
    def test_compare_write_checks_hash_before_nonce_and_post(self):
        self.assertIn('css_source_changed',repair.CSS_COMPARE_WRITE)
        self.assertLess(repair.CSS_COMPARE_WRITE.index('css_source_changed'),repair.CSS_COMPARE_WRITE.index('const sent='))
        self.assertNotIn('document.cookie',repair.CSS_COMPARE_WRITE)


class CSSWorkflow(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.content='/* fixture */\n'*11000+'body{color:red}'
        self.original=self.content
        self.db={};self.external_writes=0;self.calls=[];self.slug='edycjanapieraj'
        self.w=SimpleNamespace(lock=asyncio.Lock(),context=object(),profile=prod.WP_PROFILE,human=False,
              assert_lease=AsyncMock(),last_activity=0,page=lambda:SimpleNamespace(url=prod.WP_ORIGIN+'/wp-admin/'))
        def checkpoint(key,payload=None,revision=None):
            old=self.db.get(key)
            if payload is None:
                if old is None:raise server.HTTPException(404,'missing')
                return copy.deepcopy(old)
            if (revision is None and old is not None) or (revision is not None and (old is None or old['revision']!=revision)):
                raise server.HTTPException(409,'CAS')
            self.db[key]={'checkpoint':copy.deepcopy(payload),'revision':1 if old is None else revision+1}
            return {'revision':self.db[key]['revision']}
        async def rest(page,path,method='GET',body=None,upload=None):
            self.calls.append((path,method))
            self.assertEqual(method,'GET')
            if path.startswith('users/me'):return {'data':{'slug':self.slug}}
            return {'data':self.record()}
        async def write(page,path,content,expected):
            self.assertEqual(expected,repair.sha(self.content))
            self.external_writes+=1;self.content=content
        self.backup=AsyncMock(return_value={'chunks':['wp-b-'+'b'*32],'bytes':len(self.content),'sha256':'a'*64})
        self.patches=[patch.object(server,'workspace',self.w),patch.object(server,'db_checkpoint',checkpoint),
                      patch.object(prod,'rest',rest),patch.object(prod,'backup_document',self.backup),
                      patch.object(repair,'write_css',write)]
        for p in self.patches:p.start()
        self.spec={'path':'theme-css/fixture/style.css','operation_id':'fixture-workflow-01',
                   'expected_sha256':prod.fingerprint(self.record()),'patches':[{'find':'color:red','replace':'color:blue'}]}
    async def asyncTearDown(self):
        for p in reversed(self.patches):p.stop()
    def record(self):
        return {'id':'fixture:style.css','type':'theme-css','content':{'raw':self.content},
                'link':prod.WP_ORIGIN+'/wp-content/themes/fixture/style.css'}
    async def call(self,action='wordpress_css_patch',spec=None,**kwargs):
        return await repair.reliability_action({'action':action,'name':prod.WP_PROFILE,
                      'text':json.dumps(self.spec if spec is None else spec)},automated=True,**kwargs)
    async def commit(self):
        preview=await self.call()
        self.spec.update(commit=True,expected_result_sha256=preview['expected_result_sha256'])
        return await self.call()
    async def test_live_shape_read_never_returns_whole_document(self):
        r=await self.call('wordpress_css_read',{'path':self.spec['path'],'offset':0,'limit':200})
        self.assertEqual(len(r['excerpt']),200);self.assertGreater(r['bytes'],144777)
        self.assertLess(len(json.dumps(r)),1000);self.assertEqual(r['next_offset'],200)
        self.assertEqual(self.external_writes,0)
    async def test_preview_has_no_db_or_website_write(self):
        r=await self.call();self.assertTrue(r['preview']);self.assertFalse(r['external_write'])
        self.assertEqual(self.db,{});self.assertEqual(self.external_writes,0);self.backup.assert_not_awaited()
    async def test_commit_backs_up_and_reads_back(self):
        r=await self.commit();self.assertTrue(r['verified']);self.assertEqual(self.external_writes,1)
        self.backup.assert_awaited_once();self.assertEqual(self.backup.await_args.args[2]['content']['raw'],self.original)
        self.assertEqual(self.db[r['task_id']]['checkpoint']['phase'],'verified')
    async def test_confirmed_replay_returns_receipt_without_write(self):
        await self.commit();r=await self.call();self.assertTrue(r['already_confirmed'])
        self.assertEqual(self.external_writes,1)
    async def test_changed_source_stops_before_backup(self):
        self.content+='/* concurrent */'
        with self.assertRaises(server.HTTPException):await self.call()
        self.assertEqual(self.external_writes,0);self.backup.assert_not_awaited()
    async def test_result_hash_mismatch_stops_before_write(self):
        self.spec.update(commit=True,expected_result_sha256='0'*64)
        with self.assertRaises(server.HTTPException):await self.call()
        self.assertEqual(self.external_writes,0);self.backup.assert_not_awaited()
    async def test_owner_handoff_and_wrong_profile_protected(self):
        self.w.human=True
        with self.assertRaises(server.HTTPException):await self.call()
        self.w.human=False;self.w.profile='other'
        with self.assertRaises(server.HTTPException):await self.call()
        self.assertEqual(self.calls,[])
    async def test_identity_and_owner_context_protected(self):
        with self.assertRaises(server.HTTPException):await self.call(owner_context=object())
        self.assertEqual(self.calls,[])
        self.slug='other'
        with self.assertRaises(server.HTTPException):await self.call()
        self.assertEqual(self.external_writes,0)
    async def test_uncertain_success_reconciles_without_second_post(self):
        preview=await self.call();self.spec.update(commit=True,expected_result_sha256=preview['expected_result_sha256'])
        async def uncertain(page,path,content,expected):
            self.external_writes+=1;self.content=content;raise TimeoutError('unknown result')
        with patch.object(repair,'write_css',uncertain):
            with self.assertRaises(TimeoutError):await self.call()
        with self.assertRaises(server.HTTPException):await self.call()
        r=await self.call('wordpress_css_reconcile',{'operation_id':self.spec['operation_id']})
        self.assertTrue(r['verified']);self.assertFalse(r['external_write_replayed'])
        self.assertEqual(self.external_writes,1)
    async def test_uncertain_failure_stays_blocked(self):
        p=await self.call();self.spec.update(commit=True,expected_result_sha256=p['expected_result_sha256'])
        with patch.object(repair,'write_css',AsyncMock(side_effect=TimeoutError())):
            with self.assertRaises(TimeoutError):await self.call()
        with self.assertRaises(server.HTTPException):
            await self.call('wordpress_css_reconcile',{'operation_id':self.spec['operation_id']})
        self.assertEqual(self.external_writes,0)
    async def test_status_does_not_open_browser_or_reveal_content(self):
        r=await self.commit();self.calls=[];self.w.context=None
        r=await self.call('wordpress_css_status',{'operation_id':self.spec['operation_id']})
        self.assertEqual(r['phase'],'verified');self.assertEqual(self.calls,[])
        self.assertNotIn('color:',json.dumps(r))
    async def test_same_id_different_request_rejected(self):
        await self.commit();self.spec['patches'][0]['replace']='color:green'
        with self.assertRaises(server.HTTPException):await self.call()
        self.assertEqual(self.external_writes,1)


class LateNavigation(unittest.IsolatedAsyncioTestCase):
    async def run_case(self,*,status=200,method='GET',failed=False,ready=True,wait_error=False,response_seen=True):
        events={};frame=object();p=SimpleNamespace(url='https://fixture.invalid/a',main_frame=frame,
            on=lambda e,c:events.update({e:c}),remove_listener=lambda e,c:events.pop(e),
            wait_for_load_state=AsyncMock(side_effect=TimeoutError() if wait_error else None),
            evaluate=AsyncMock(return_value=ready))
        req=SimpleNamespace(method=method,frame=frame,is_navigation_request=lambda:True)
        resp=SimpleNamespace(request=req,status=status,url=p.url)
        w=SimpleNamespace(failed_pages=set(),pending_urls={})
        class Page:pass
        page=Page();page.__dict__.update(p.__dict__);w.failed_pages.add(page);w.pending_urls[page]=page.url
        async def navigate(page,raw,restoring=False):
            if response_seen:events['response'](resp)
            if failed:events['requestfailed'](req)
            return False
        with patch.object(server,'workspace',w),patch.object(repair,'_original_navigate',AsyncMock(side_effect=navigate)) as original:
            result=await repair.navigate_ready(page,page.url,restoring=True)
            original.assert_awaited_once()
        self.assertEqual(events,{})
        return result,page,w
    async def test_late_success_rechecks_same_document_without_navigation_replay(self):
        result,page,w=await self.run_case();self.assertTrue(result)
        self.assertNotIn(page,w.failed_pages);self.assertNotIn(page,w.pending_urls)
    async def test_http_errors_are_never_success(self):
        for s in [401,403,429,500,502]:
            result,page,w=await self.run_case(status=s);self.assertFalse(result)
            page.wait_for_load_state.assert_not_awaited()
    async def test_post_is_never_replayed_or_marked_success(self):
        result,page,w=await self.run_case(method='POST');self.assertFalse(result)
        page.wait_for_load_state.assert_not_awaited()
    async def test_failed_document_stays_failed(self):
        result,page,w=await self.run_case(failed=True);self.assertFalse(result)
    async def test_missing_response_is_not_proof(self):
        result,page,w=await self.run_case(response_seen=False);self.assertFalse(result)
    async def test_late_timeout_stays_failed(self):
        result,page,w=await self.run_case(wait_error=True);self.assertFalse(result)
    async def test_incomplete_dom_stays_failed(self):
        result,page,w=await self.run_case(ready=False);self.assertFalse(result)


class BrowserCompareWrite(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from playwright.async_api import async_playwright
        from urllib.parse import parse_qs,urlsplit
        from html import escape
        self.pw=await async_playwright().start();self.browser=await self.pw.chromium.launch()
        self.page=await self.browser.new_page();self.content='/* fixture */\n'*11000+'body{color:red}';self.posts=0
        async def route(r):
            path=urlsplit(r.request.url).path
            if path.endswith('theme-editor.php'):
                html='<form><input name="theme" value="fixture"><input name="file" value="style.css"><input name="nonce" value="fixture123"><textarea name="newcontent">'+escape(self.content)+'</textarea></form>'
                return await r.fulfill(content_type='text/html',body=html)
            if path.endswith('admin-ajax.php'):
                fields=parse_qs(r.request.post_data);self.assertEqual(fields['action'],['edit-theme-plugin-file'])
                self.assertEqual(fields['nonce'],['fixture123']);self.content=fields['newcontent'][0];self.posts+=1
                return await r.fulfill(json={'success':True})
            return await r.fulfill(content_type='text/html',body='<title>Synthetic editor</title>')
        await self.page.route('**/*',route);await self.page.goto(prod.WP_ORIGIN+'/wp-admin/')
    async def asyncTearDown(self):
        await self.browser.close();await self.pw.stop()
    async def test_large_css_compare_and_write_in_own_origin(self):
        original=self.content;desired=original.replace('color:red','color:blue')
        await repair.write_css(self.page,'theme-css/fixture/style.css',desired,repair.sha(original))
        self.assertEqual(self.content,desired);self.assertEqual(self.posts,1)
    async def test_browser_rechecks_hash_before_dispatch(self):
        with self.assertRaises(server.HTTPException) as error:
            await repair.write_css(self.page,'theme-css/fixture/style.css','body{color:green}','0'*64)
        self.assertEqual(error.exception.status_code,409);self.assertEqual(self.posts,0)

if __name__=='__main__':unittest.main()
