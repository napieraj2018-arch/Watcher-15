"""Real Chromium tests of shipped HTML with synthetic same-origin APIs only."""
import asyncio
import os
import unittest
from pathlib import Path
from playwright.async_api import async_playwright

HTML = Path(__file__).with_name('index.html').read_text()
FIXTURE = '<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><body><h1>Neutralny formularz testowy</h1><label>E-mail<input></label><label>Hasło<input type="password"></label></body>'

class HumanUI(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.pw=await async_playwright().start()
        self.browser=await self.pw.chromium.launch(headless=True,executable_path=os.getenv('AIB_TEST_CHROMIUM') or None,args=['--no-sandbox','--disable-dev-shm-usage'])
        self.ctx=await self.browser.new_context(viewport={'width':390,'height':844},is_mobile=True,has_touch=True,color_scheme='light')
        self.page=await self.ctx.new_page()
        fixture=await self.ctx.new_page();await fixture.set_content(FIXTURE)
        self.image=await fixture.screenshot(type='jpeg');await fixture.close()
        self.actions=[];self.calls=[];self.errors=[];self.screen_headers=[]
        self.page.on('pageerror',lambda e:self.errors.append(str(e)))
        self.human=False;self.fail_action=None;self.fail_screen=False;self.auth_failure=False;self.rate_until=None
        self.profiles=[{'name':'wordpress-klinika'},{'name':'google-youtube'},{'name':'acceptance-ui-fixture'},{'name':'facebook-klinika'}]
        self.tab_title='Formularz testowy'
        await self.ctx.route('http://127.0.0.1:8765/**',self.route)

    async def asyncTearDown(self):
        await self.ctx.close();await self.browser.close();await self.pw.stop()

    async def route(self,r):
        request=r.request;url=request.url;self.calls.append((request.method,url))
        if '/api/' not in url:
            await r.fulfill(status=200,content_type='text/html',body=HTML);return
        if self.auth_failure:
            await r.fulfill(status=401,json={'detail':'Link wygasł.'});return
        if url.endswith('/api/session') or url.endswith('/api/pair'):value={'ok':True}
        elif url.endswith('/api/profiles'):value={'profiles':self.profiles[:1] if '/owner/' in url else self.profiles}
        elif '/api/action' in url:
            a=request.post_data_json;self.actions.append(a)
            if self.fail_action:
                await r.fulfill(status=self.fail_action,json={'detail':{'code':'browser_busy_before_start'} if self.fail_action==409 else 'Niepewna odpowiedź'});return
            if a['action']=='handoff':self.human=a['human']
            value={'ok':True,'human':self.human,'navigation':'ready','url':'https://fixture.invalid','title':'Formularz testowy'}
            if a['action']=='click':value.update(editing=True,password=True)
            if a['action']=='close':value={'ok':True,'closed':True}
        elif '/api/screen' in url:
            if self.rate_until is not None:
                await r.fulfill(status=429,headers={'Retry-After':self.rate_until},json={'detail':'Limit'});return
            if self.fail_screen:
                await r.fulfill(status=503,json={'detail':'Obraz niedostępny'});return
            tag=request.headers.get('if-none-match');self.screen_headers.append(tag)
            headers={'ETag':'"human-ui-test"','X-AIB-Page':'tab-1','X-AIB-Origin':'https://fixture.invalid','X-AIB-Navigation':'ready','X-AIB-Tabs':'1'}
            if tag=='"human-ui-test"':await r.fulfill(status=304,headers=headers)
            else:await r.fulfill(status=200,headers=headers,content_type='image/jpeg',body=self.image)
            return
        elif '/api/tabs' in url:value={'tabs':[{'id':'tab-1','title':self.tab_title,'url':'https://fixture.invalid','active':True}]}
        elif '/api/logout' in url:value={'ok':True}
        else:
            await r.fulfill(status=404,json={'detail':'Unknown fixture endpoint'});return
        await r.fulfill(status=200,json=value)

    async def start(self,owner=True):
        await self.page.goto('http://127.0.0.1:8765/owner/#SYNTHETIC' if owner else 'http://127.0.0.1:8765/')
        await self.page.wait_for_function('authenticated && !busy && allProfiles.length>0')
        if owner:await self.page.wait_for_function('screenActive && frameInFlight===null')

    async def take(self):
        await self.page.locator('#humanBtn').click()
        await self.page.wait_for_function('!busy && controlMode==="human" && frameInFlight===null')

    async def test_01_owner_starts_readonly_no_auto_takeover(self):
        await self.start();self.assertEqual([a['action'] for a in self.actions],['open'])
        self.assertEqual(await self.page.locator('#controlLabel').inner_text(),'Steruje ChatGPT')
        self.assertTrue(await self.page.locator('#typingBtn').is_disabled())
        self.assertEqual(await self.page.evaluate('location.hash'),'')
        self.assertEqual(await self.page.evaluate('ownerToken'),'')

    async def test_02_takeover_is_explicit_and_fit_mobile(self):
        await self.start();await self.take()
        self.assertEqual([a['action'] for a in self.actions],['open','handoff','viewport'])
        self.assertTrue(self.actions[1]['human']);self.assertEqual(self.actions[2]['text'],'mobile')
        self.assertTrue(await self.page.locator('#agentBtn').is_visible())

    async def test_03_handoff_stops_polling_and_explains_resume(self):
        await self.start();await self.take();await self.page.locator('#agentBtn').click()
        await self.page.wait_for_function('!busy && controlMode==="agent"')
        self.assertIsNone(await self.page.evaluate('liveTimer'))
        n=len(self.calls);await self.page.wait_for_timeout(2200);self.assertEqual(len(self.calls),n)
        self.assertTrue(await self.page.locator('#handoffDone').is_visible())
        self.assertIn('nie uruchamia',await self.page.locator('#handoffDone').inner_text())

    async def test_04_typing_does_not_submit_or_store_secret(self):
        await self.start();await self.take();await self.page.locator('#typingBtn').click()
        await self.page.locator('#keyboard').fill('SYNTHETIC-SECRET');await self.page.locator('#typeBtn').click()
        await self.page.wait_for_function('!busy')
        self.assertEqual(self.actions[-1]['action'],'type');self.assertEqual(self.actions[-1]['text'],'SYNTHETIC-SECRET')
        self.assertFalse(any(a['action']=='press' for a in self.actions))
        self.assertEqual(await self.page.locator('#keyboard').input_value(),'')
        self.assertNotIn('SYNTHETIC-SECRET',await self.page.evaluate('JSON.stringify({...localStorage})'))

    async def test_05_keyboard_enter_sends_text_not_remote_enter(self):
        await self.start();await self.take();await self.page.locator('#typingBtn').click()
        await self.page.locator('#keyboard').fill('fixture');await self.page.locator('#keyboard').press('Enter')
        await self.page.wait_for_function('!busy');self.assertEqual(self.actions[-1]['action'],'type')

    async def test_06_uncertain_write_never_replayed_and_secret_cleared(self):
        await self.start();await self.take();self.fail_action=502
        await self.page.locator('#typingBtn').click();await self.page.locator('#keyboard').fill('SYNTHETIC')
        await self.page.locator('#typeBtn').click();await self.page.wait_for_function('!busy')
        self.assertEqual(await self.page.locator('#keyboard').input_value(),'')
        self.assertTrue(await self.page.evaluate('uncertain'))
        await self.page.wait_for_timeout(300)
        self.assertEqual(sum(a['action']=='type' for a in self.actions),1)

    async def test_07_owner_hides_unsupported_actions(self):
        await self.start();await self.page.locator('#moreBtn').click()
        for ident in ['forwardBtn','fileFieldsBtn','uploadBtn','downloadBtn']:
            self.assertFalse(await self.page.locator('#'+ident).is_visible())
        await self.page.locator('#moreSheet [data-close]').click();await self.page.locator('#tabsBtn').click()
        self.assertFalse(await self.page.locator('#newTabBtn').is_visible())
        self.assertFalse(await self.page.locator('#closeTabBtn').is_visible())

    async def test_08_theme_persists_without_network_mutation(self):
        await self.start();n=len(self.actions);await self.page.locator('#appearanceBtn').click()
        await self.page.locator('[data-theme-choice="dark"]').click()
        self.assertEqual(await self.page.evaluate('document.documentElement.dataset.theme'),'dark')
        self.assertEqual(await self.page.evaluate('localStorage.getItem("aib-ui-theme")'),'dark')
        self.assertEqual(len(self.actions),n)

    async def test_09_admin_profiles_friendly_and_tests_hidden(self):
        await self.start(False)
        self.assertIn('WordPress · Klinika',await self.page.locator('#profile').inner_text())
        self.assertNotIn('acceptance',await self.page.locator('#profile').inner_text())
        await self.page.locator('#showTechnical').check()
        self.assertIn('acceptance',await self.page.locator('#profile').inner_text());self.assertEqual(self.actions,[])

    async def test_10_profile_switch_clears_stale_frame_without_post(self):
        await self.start(False);await self.page.locator('#profile').select_option('wordpress-klinika')
        await self.page.locator('#openBtn').click();await self.page.wait_for_function('!busy && frameInFlight===null')
        n=len(self.actions);await self.page.locator('#moreBtn').click();await self.page.locator('#profilesBtn').click()
        await self.page.locator('#profile').select_option('facebook-klinika')
        self.assertEqual(len(self.actions),n);self.assertFalse(await self.page.locator('#screen').is_visible())

    async def test_11_conditional_frame_does_not_replay_action(self):
        await self.start();n=len(self.actions);await self.page.evaluate('screenshot()')
        self.assertIn('"human-ui-test"',self.screen_headers);self.assertEqual(len(self.actions),n)
        self.assertTrue(await self.page.locator('#screen').is_visible())

    async def test_12_image_failure_not_claimed_action_failure(self):
        await self.start();self.fail_screen=True
        await self.page.locator('#humanBtn').click();await self.page.wait_for_function('!busy')
        self.assertEqual(sum(a['action']=='handoff' for a in self.actions),1)
        self.assertIn('podgląd',await self.page.locator('#error').inner_text())

    async def test_13_auth_expired_shows_recovery_not_admin_key(self):
        self.auth_failure=True;await self.page.goto('http://127.0.0.1:8765/owner/#SYNTHETIC')
        await self.page.wait_for_function('document.getElementById("accessTitle").textContent.includes("nowy link")')
        self.assertFalse(await self.page.locator('#adminKey').is_visible())
        self.assertFalse(await self.page.locator('#appBox').is_visible());self.assertEqual(self.actions,[])

    async def test_14_busy_not_started_not_replayed(self):
        await self.start();self.fail_action=409;await self.page.locator('#humanBtn').click()
        await self.page.wait_for_function('!busy')
        self.assertIn('nie rozpoczął',await self.page.locator('#error').inner_text())
        self.assertEqual(sum(a['action']=='handoff' for a in self.actions),1)
        self.assertFalse(await self.page.evaluate('uncertain'))

    async def test_15_rate_limit_honors_long_retry_after(self):
        await self.start();self.rate_until='600';await self.page.locator('#screenBtn').click()
        await self.page.wait_for_function('!busy');n=len(self.calls)
        self.assertGreater(await self.page.evaluate('(cooldownUntil-Date.now())/1000'),590)
        await self.page.locator('#screenBtn').click();await self.page.wait_for_function('!busy')
        self.assertEqual(len(self.calls),n)

    async def test_16_untrusted_tab_title_is_text_not_html(self):
        self.tab_title='<img src=x onerror="window.BAD=true">';await self.start();await self.page.locator('#tabsBtn').click()
        self.assertEqual(await self.page.locator('#tabCards img').count(),0)
        self.assertFalse(await self.page.evaluate('Boolean(window.BAD)'))

    async def test_17_layout_widths_no_horizontal_scroll(self):
        await self.start()
        for w,h in [(320,740),(390,844),(430,932),(844,390),(1440,1000)]:
            await self.page.set_viewport_size({'width':w,'height':h})
            self.assertLessEqual(await self.page.evaluate('document.documentElement.scrollWidth'),w)
            b=await self.page.locator('#humanBtn').bounding_box()
            self.assertGreaterEqual(b['height'],48);self.assertLessEqual(b['x']+b['width'],w)

    async def test_18_sheet_can_close_and_keyboard_text_is_cleared(self):
        await self.start();await self.take();await self.page.locator('#typingBtn').click()
        await self.page.locator('#keyboard').fill('SYNTHETIC');await self.page.locator('#typingSheet [data-close]').click()
        self.assertEqual(await self.page.locator('#keyboard').input_value(),'')
        self.assertEqual(await self.page.locator('#keyboard').get_attribute('type'),'password')

    async def test_19_stale_click_refreshes_without_click(self):
        await self.start();await self.take();await self.page.evaluate('lastFrameAt=Date.now()-30000')
        n=sum(a['action']=='click' for a in self.actions)
        await self.page.locator('#screen').click(position={'x':40,'y':50});await self.page.wait_for_function('!busy')
        self.assertEqual(sum(a['action']=='click' for a in self.actions),n)
        self.assertIn('uaktualniony',await self.page.locator('#error').inner_text())

    async def test_20_no_script_errors_and_unique_ids(self):
        await self.start();self.assertEqual(self.errors,[])
        self.assertTrue(await self.page.evaluate('(()=>{let a=[...document.querySelectorAll("[id]")].map(e=>e.id);return a.length===new Set(a).size})()'))

    async def test_21_all_test_profiles_still_selectable_for_regressions(self):
        self.profiles=[{'name':'acceptance-free-efficiency'}];await self.start(False)
        await self.page.locator('#profile').select_option('acceptance-free-efficiency')
        await self.page.locator('#openBtn').click();await self.page.wait_for_function('!busy && frameInFlight===null')
        self.assertEqual(len(self.actions),1)

    async def test_22_agent_mode_cannot_send_manual_command(self):
        await self.start();n=len(self.actions)
        await self.page.evaluate('command("type",{text:"must not send"}).catch(()=>{})')
        self.assertEqual(len(self.actions),n)

    async def test_23_typing_sheet_focus_and_remote_tab_binding(self):
        await self.start();await self.take();await self.page.locator('#typingBtn').click()
        self.assertEqual(await self.page.evaluate('document.activeElement.id'),'keyboard')
        await self.page.locator('#keyboard').fill('fixture');await self.page.locator('#typeBtn').click()
        await self.page.wait_for_function('!busy');self.assertEqual(self.actions[-1]['page_id'],'tab-1')

    async def test_24_transient_startup_not_reported_as_expired_link(self):
        self.fail_action=503;await self.page.goto('http://127.0.0.1:8765/owner/#SYNTHETIC')
        await self.page.wait_for_function('document.getElementById("accessTitle").textContent.includes("niepotwierdzone")')
        self.assertNotIn('nowy link',await self.page.locator('#accessTitle').inner_text())
        self.assertEqual(sum(a['action']=='open' for a in self.actions),1)

if __name__=='__main__':unittest.main()
