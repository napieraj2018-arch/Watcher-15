"""Remote Chromium adapter. All service keys stay in the server environment.

Existing AI Browser owns encrypted profile storage and the mobile login UI.
Each profile uses its own isolated browser context inside its Steel session.
This intentionally preserves Playwright's full storage_state (including IDB).
"""
from __future__ import annotations
import asyncio
import contextlib
import os
import time
import uuid
from pathlib import Path
from urllib.parse import urlencode

import httpx
from starlette.responses import JSONResponse

VERSION = "0.4.3"
API = "https://api.steel.dev/v1"
HEADERS = {"cache-control": "no-store"}


def memory_info():
    try:
        used = int(Path('/sys/fs/cgroup/memory.current').read_text())
        limit = int(Path('/sys/fs/cgroup/memory.max').read_text())
        return {'used_mib': round(used / 1048576, 1),
                'limit_mib': round(limit / 1048576, 1),
                'percent': round(used * 100 / limit, 1)}
    except (OSError, ValueError, ZeroDivisionError):
        return {}


def local_chrome_count():
    count = 0
    for p in Path('/proc').glob('[0-9]*/comm'):
        try:
            name = p.read_text().strip()
            if name in {'chrome', 'chromium', 'headless_shell', 'chrome-headless-shell'}:
                count += 1
        except OSError:
            pass
    return count


class SteelFailure(RuntimeError):
    """Only fixed messages/status numbers; never third-party exception text."""


class Engine:
    def __init__(self):
        self.remote = {}
        self.authenticated = False
        self.timeout_ms = 900000

    async def request(self, method, path, body=None, timeout=25):
        key = os.environ.get('STEEL_API_KEY', '').strip()
        if not key:
            raise SteelFailure('STEEL_KEY_MISSING')
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
                response = await client.request(method, API + path,
                    headers={'steel-api-key': key, 'content-type': 'application/json'},
                    json=body)
        except (httpx.HTTPError, OSError):
            raise SteelFailure('STEEL_CONNECTION_FAILED') from None
        if not 200 <= response.status_code < 300:
            raise SteelFailure('STEEL_HTTP_' + str(response.status_code)) from None
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError:
            raise SteelFailure('STEEL_INVALID_RESPONSE') from None

    async def release(self, remote_id):
        # Never release other callers' sessions and never retry session creation.
        for attempt in range(2):
            try:
                await self.request('POST', '/sessions/' + remote_id + '/release', {}, 12)
                return True
            except SteelFailure as exc:
                if str(exc) in {'STEEL_HTTP_404', 'STEEL_HTTP_410'}:
                    return True
                if attempt == 0:
                    await asyncio.sleep(0.3)
        return False

    async def launch(self, chromium, **_ignored_local_options):
        if any(not r.closed for r in self.remote.values()):
            raise SteelFailure('STEEL_SESSION_LIMIT_1')
        remote_id = str(uuid.uuid4())
        browser = None
        try:
            data = await self.request('POST', '/sessions', {
                'sessionId': remote_id,
                'timeout': self.timeout_ms,
                'inactivityTimeout': 180000,
                'useProxy': False,
                'solveCaptcha': False,
                'headless': False,
                'dimensions': {'width': 1000, 'height': 700},
            })
            returned_id = str(data.get('id', ''))
            if returned_id != remote_id:
                raise SteelFailure('STEEL_SESSION_ID_MISMATCH')
            self.authenticated = True
            endpoint = 'wss://connect.steel.dev?' + urlencode({
                'apiKey': os.environ['STEEL_API_KEY'].strip(), 'sessionId': remote_id})
            try:
                browser = await chromium.connect_over_cdp(endpoint, timeout=25000)
            except Exception:
                raise SteelFailure('STEEL_CDP_CONNECTION_FAILED') from None
            remote = RemoteBrowser(self, browser, remote_id)
            self.remote[remote_id] = remote
            return remote
        except BaseException:
            if browser is not None:
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(browser.close(), 5)
            await self.release(remote_id)
            raise


class RemoteBrowser:
    def __init__(self, engine, browser, remote_id):
        self.engine, self.browser, self.remote_id = engine, browser, remote_id
        self.created_at = time.time()
        self.closed = False
        self.close_lock = asyncio.Lock()

    def __getattr__(self, name):
        return getattr(self.browser, name)

    async def new_context(self, **options):
        try:
            # Native Playwright storage import preserves all supported state.
            # No cookie or localStorage values are returned to the assistant.
            return await self.browser.new_context(**options)
        except Exception:
            await self.close()
            raise SteelFailure('STEEL_PROFILE_CONTEXT_FAILED') from None

    async def close(self, **_kwargs):
        async with self.close_lock:
            if self.closed:
                return
            self.closed = True
            try:
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(self.browser.close(), 5)
                await self.engine.release(self.remote_id)
            finally:
                self.engine.remote.pop(self.remote_id, None)


class RemoteChromium:
    def __init__(self, chromium, engine):
        self.chromium, self.engine = chromium, engine

    async def launch(self, **options):
        return await self.engine.launch(self.chromium, **options)

    async def launch_persistent_context(self, **_options):
        raise SteelFailure('STEEL_REQUIRES_PORTABLE_PROFILES')

    def __getattr__(self, name):
        return getattr(self.chromium, name)


class RemotePlaywright:
    def __init__(self, playwright, engine):
        self.playwright = playwright
        self.chromium = RemoteChromium(playwright.chromium, engine)

    def __getattr__(self, name):
        return getattr(self.playwright, name)


def install(ns):
    if os.environ.get('AI_BROWSER_ENGINE', '').lower() != 'steel':
        return
    manager, mcp = ns['manager'], ns['mcp']
    if getattr(manager, '_steel_engine', None) is not None:
        return
    if not manager.portable_profiles:
        raise SteelFailure('STEEL_REQUIRES_PORTABLE_PROFILES')
    engine = Engine()
    manager._steel_engine = engine
    manager.max_sessions = 1
    old_ensure = manager._ensure_playwright
    old_start, old_stop, old_status = manager.start, manager.stop, manager.status
    timers = {}

    async def ensure():
        return RemotePlaywright(await old_ensure(), engine)

    async def status(sid):
        result = await old_status(sid)
        s = manager._sessions.get(sid)
        remote = getattr(s, 'browser', None)
        result.update({'runtime': 'steel', 'runtime_version': VERSION,
                       'local_chrome_processes': local_chrome_count(),
                       'controller_memory': memory_info()})
        if isinstance(remote, RemoteBrowser):
            result['remaining_seconds'] = max(0, int(870 - (time.time() - remote.created_at)))
        return result

    async def expire(sid, delay):
        try:
            await asyncio.sleep(delay)
            if sid in manager._sessions:
                await manager.stop(sid)
        except asyncio.CancelledError:
            pass
        except Exception:
            # Final cleanup; never print errors containing browser URLs or state.
            pass
        finally:
            timers.pop(sid, None)

    async def start(*args, **kwargs):
        before = set(engine.remote)
        try:
            result = await old_start(*args, **kwargs)
            sid = result['session_id']
            if sid not in timers:
                remote = manager._session(sid).browser
                remaining = max(1, 870 - (time.time() - remote.created_at))
                timers[sid] = asyncio.create_task(expire(sid, remaining))
            return await status(sid)
        except BaseException:
            for remote_id in set(engine.remote) - before:
                remote = engine.remote.get(remote_id)
                if remote is not None:
                    with contextlib.suppress(Exception):
                        await remote.close()
            raise

    async def stop(sid, *args, **kwargs):
        timer = timers.pop(sid, None)
        if timer and timer is not asyncio.current_task():
            timer.cancel()
        s = manager._sessions.get(sid)
        remote = getattr(s, 'browser', None)
        try:
            return await old_stop(sid, *args, **kwargs)
        finally:
            if isinstance(remote, RemoteBrowser):
                await remote.close()

    manager._ensure_playwright = ensure
    manager.status, manager.start, manager.stop = status, start, stop
    ns['_SETUP_HTML'] = ns['_SETUP_HTML'].replace(
        'AI Browser · logowanie', 'AI Browser · logowanie · Steel')

    async def health(_request):
        return JSONResponse({'status': 'ok', 'runtime': 'steel', 'version': VERSION,
            'key_configured': bool(os.environ.get('STEEL_API_KEY', '').strip()),
            'remote_connection_verified': engine.authenticated,
            'local_chrome_processes': local_chrome_count(),
            'controller_memory': memory_info(),
            'active_remote_sessions': len(engine.remote),
            'max_session_seconds': 870, 'proxy_enabled': False, 'captcha_solving': False},
            headers=HEADERS)
    mcp.custom_route('/health/steel', methods=['GET'])(health)

    async def selftest(request):
        rec = ns['_setup_record'](request)
        if not rec:
            return JSONResponse({'error': 'unauthorized'}, status_code=401, headers=HEADERS)
        s = manager._session(rec['session_id'])
        if s.profile != 'SteelSelfTest':
            return JSONResponse({'error': 'test_profile_required'}, status_code=403, headers=HEADERS)
        try:
            result = await asyncio.wait_for(exercise(manager, rec), 90)
            return JSONResponse(result, headers=HEADERS)
        except Exception:
            return JSONResponse({'ok': False, 'error': 'SELFTEST_FAILED'}, status_code=500, headers=HEADERS)
    mcp.custom_route('/setup/{setup_id}/steel-selftest', methods=['POST'])(selftest)
    print('AI_BROWSER_STEEL_READY ' + VERSION, flush=True)


async def exercise(manager, rec):
    """Test fixture only. Never type test credentials into a real identity provider."""
    s = manager._session(rec['session_id'])
    page = s.page
    await page.goto('https://example.com', wait_until='domcontentloaded', timeout=20000)
    marker = uuid.uuid4().hex
    fixture = '''<!doctype html><meta name="viewport" content="width=device-width">
<title>AI Browser technical self-test</title><h1>TEST TECHNICZNY</h1>
<p>Nie wpisuj prawdziwych danych. To nie jest strona logowania do konta.</p>
<form id="test"><label>Login<input id="email" name="email" autocomplete="username"></label>
<label>Hasło<input id="password" type="password" autocomplete="current-password"></label>
<button>Test</button></form><p id="result"></p><script>
window.testSubmits=0;test.onsubmit=e=>{e.preventDefault();window.testSubmits++;
result.textContent=email.value==='demo@example.test'&&password.value==='demo-only-not-a-real-secret'?'PASS':'FAIL'};
</script>'''
    await page.set_content(fixture)
    await page.locator('#email').fill('demo@example.test')
    await page.locator('#password').fill('demo-only-not-a-real-secret')
    await page.locator('#password').press('Enter')
    form_ok = await page.locator('#result').inner_text() == 'PASS'
    once = await page.evaluate('window.testSubmits') == 1
    shot_sizes = []
    for _ in range(6):
        image = await page.screenshot(type='jpeg', quality=45, timeout=8000)
        shot_sizes.append(len(image))
        await asyncio.sleep(0.3)
    await s.context.add_cookies([{'name': 'aib_steel_selftest', 'value': marker,
        'domain': 'example.com', 'path': '/', 'secure': True, 'sameSite': 'Lax',
        'expires': time.time()+3600}])
    await page.evaluate('(v)=>localStorage.setItem("aib_steel_selftest",v)', marker)
    await manager.flush_profile(s.session_id)
    first_memory = memory_info()
    await manager.stop(s.session_id)
    fresh = await manager.start('SteelSelfTest', mode='write', headless=False,
                               start_url='https://example.com')
    rec['session_id'] = fresh['session_id']
    second = manager._session(fresh['session_id'])
    cookies = await second.context.cookies('https://example.com')
    cookie_ok = any(c['name']=='aib_steel_selftest' and c['value']==marker for c in cookies)
    ls_ok = await second.page.evaluate('localStorage.getItem("aib_steel_selftest")') == marker
    result = {'ok': all((form_ok, once, cookie_ok, ls_ok, all(shot_sizes))),
        'runtime': 'steel', 'form_fill_and_enter': form_ok, 'single_submit': once,
        'screenshots_completed': len(shot_sizes),
        'encrypted_profile_reopen_cookie': cookie_ok,
        'encrypted_profile_reopen_localstorage': ls_ok,
        'local_chrome_processes': local_chrome_count(),
        'memory_during_test': first_memory, 'memory_after_reopen': memory_info(),
        'test_scope': 'controlled fixture, not Facebook or Google authentication'}
    return result
