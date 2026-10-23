"""Remote Chromium adapter. All service keys stay in the server environment.

Existing AI Browser owns encrypted profile storage and the mobile login UI.
Each profile uses its own isolated browser context inside its Steel session.
This intentionally preserves Playwright's full storage_state (including IDB).
"""
from __future__ import annotations
import asyncio
import contextlib
import hashlib
import hmac
import os
import time
import uuid
from pathlib import Path
from urllib.parse import urlencode, urlsplit, urlunsplit

import httpx
from starlette.responses import JSONResponse

VERSION = "0.4.5"
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


def admin_health_authorized(authorization):
    """Admin-only health diagnostics. No secret values in outputs or logs."""
    expected = os.environ.get("AI_BROWSER_ADMIN_TOKEN", "")
    if (not isinstance(authorization, str) or not authorization.startswith("Bearer ")
            or len(authorization) > 512 or not 32 <= len(expected) <= 256):
        return False
    supplied = authorization[7:]
    if len(supplied) != len(expected):
        return False
    try:
        return hmac.compare_digest(supplied.encode("ascii"), expected.encode("ascii"))
    except UnicodeEncodeError:
        return False


def steel_health_payload(engine, authorization=""):
    """Public liveness stays minimal; private diagnostics require owner token."""
    public = {
        "status": "degraded" if engine._quarantined else "ok",
        "runtime": "steel", "version": VERSION,
    }
    if admin_health_authorized(authorization):
        public.update({
            "key_configured": bool(os.environ.get("STEEL_API_KEY", "").strip()),
            "remote_connection_verified": engine.authenticated,
            "local_chrome_processes": local_chrome_count(),
            "controller_memory": memory_info(),
            "active_remote_sessions": len(engine.remote),
            "requires_reconciliation": engine._quarantined,
            "max_session_seconds": 870,
            "proxy_enabled": False,
            "captcha_solving_requested": getattr(engine, 'captcha_requested', False),
        })
    return public


class SteelFailure(RuntimeError):
    """Only fixed messages/status numbers; never third-party exception text."""


class SteelCreateNotAttempted(SteelFailure):
    """Internal proof from a local wrapper that no session POST was called.

    Emit only around read-only preparation, never around a provider-create
    request or its aftermath. Preserve the original exception (including
    cancellation) without treating a failed registry read as an orphan.
    """
    def __init__(self, failure):
        super().__init__('STEEL_CREATE_NOT_ATTEMPTED')
        self.failure = failure


class SteelCaptchaNotAvailable(SteelFailure):
    """An explicit HTTP 402 rejected the paid option before session creation.

    Only the HTTP transport produces this for a CAPTCHA-enabled create.
    Timeouts, malformed responses and other statuses remain uncertain and
    never permit a second create request.
    """


def captcha_automation_enabled():
    value = os.environ.get('AI_BROWSER_CAPTCHA_AUTOMATION', '1')
    if value not in {'0', '1'}:
        raise SteelFailure('STEEL_CAPTCHA_CONFIG_INVALID')
    return value == '1'


def _captcha_page_key(url):
    """Match a page in memory without retaining or returning sign-in tokens."""
    try:
        p = urlsplit(url)
        if (p.scheme != 'https' or not p.hostname or p.username or p.password
                or p.port not in (None, 443) or len(url) > 8192):
            return None
        normalized = urlunsplit(('https', p.hostname.lower(), p.path or '/', p.query, p.fragment))
        return hashlib.sha256(normalized.encode('utf-8')).digest()
    except (TypeError, ValueError, UnicodeError):
        return None


class Engine:
    def __init__(self):
        self.remote = {}
        # ONE by default. Opt-in owner beta may increase this only when the
        # entire 51-tool MCP surface has a verified profile capability guard.
        self.max_sessions = 1
        # Serialize the entire remote-create/CDP-connect/cleanup sequence.
        # Checking only active sessions before the first await races with
        # simultaneous browser_start calls and can consume extra Steel sessions.
        self._launch_lock = asyncio.Lock()
        # Once the provider outcome is unknown, no new session may launch
        # until an independently authenticated reconciliation occurs.
        self._quarantined = False
        self.authenticated = False
        self.timeout_ms = 900000
        self.captcha_requested = captcha_automation_enabled()

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
        if (response.status_code == 402 and method == 'POST' and path == '/sessions'
                and isinstance(body, dict) and body.get('solveCaptcha') is True
                and body.get('useProxy') is False):
            # Steel's documented feature rejection. Do not echo its free-form
            # message. The paid-option fallback is limited to this response.
            raise SteelCaptchaNotAvailable('STEEL_CAPTCHA_ACCOUNT_ACCESS_REQUIRED')
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
        async with self._launch_lock:
            return await self._launch_serialized(chromium)

    async def _launch_serialized(self, chromium):
        # A session that is closing still counts until Steel confirms release.
        # Never create a replacement while the previous release is in flight.
        if self._quarantined:
            raise SteelFailure('STEEL_SESSION_QUARANTINED')
        if len(self.remote) >= self.max_sessions:
            raise SteelFailure('STEEL_SESSION_LIMIT_' + str(self.max_sessions))
        remote_id = str(uuid.uuid4())
        browser = None
        creation_confirmed = False
        try:
            payload = {
                'sessionId': remote_id,
                'timeout': self.timeout_ms,
                'inactivityTimeout': 180000,
                'useProxy': False,
                'solveCaptcha': self.captcha_requested,
                'headless': False,
                # Require actual server-side input support for the short-lived
                # owner-authorized human takeover. A viewer URL parameter
                # alone cannot override a read-only provider session.
                # Steel defaults to True today; pin the production contract.
                'debugConfig': {'interactive': True, 'systemCursor': True},
                # The mobile-first service must retain one consistent device
                # fingerprint across setup and later automated sessions.
                'deviceConfig': {'device': 'mobile'},
                'dimensions': {'width': 508, 'height': 1074},
            }
            captcha_unavailable = False
            try:
                data = await self.request('POST', '/sessions', payload)
            except SteelCaptchaNotAvailable:
                # Same requested UUID and profile; only remove the explicitly
                # rejected optional feature, once. No timeout/error retries.
                captcha_unavailable = True
                payload = {**payload, 'solveCaptcha': False}
                data = await self.request('POST', '/sessions', payload)
            returned_id = str(data.get('id', ''))
            if returned_id != remote_id:
                # Releasing the REQUESTED id cannot prove that an unexpected
                # provider-returned id was removed. Fail closed.
                self._quarantined = True
                raise SteelFailure('STEEL_SESSION_ID_MISMATCH')
            creation_confirmed = True
            self.authenticated = True
            endpoint = 'wss://connect.steel.dev?' + urlencode({
                'apiKey': os.environ['STEEL_API_KEY'].strip(), 'sessionId': remote_id})
            try:
                browser = await chromium.connect_over_cdp(endpoint, timeout=25000)
            except Exception:
                raise SteelFailure('STEEL_CDP_CONNECTION_FAILED') from None
            remote = RemoteBrowser(self, browser, remote_id)
            remote._captcha_requested = self.captcha_requested
            remote._captcha_enabled = (payload['solveCaptcha'] is True
                                       and data.get('solveCaptcha') is not False)
            remote._captcha_confirmed = (payload['solveCaptcha'] is True
                                         and data.get('solveCaptcha') is True)
            remote._captcha_availability = (
                'account_access_required' if captcha_unavailable else
                'disabled' if not self.captcha_requested else
                'enabled' if remote._captcha_confirmed else
                'provider_disabled' if data.get('solveCaptcha') is False else
                'provider_unconfirmed')
            # Keep the provider's unauthenticated live-view URL SERVER-SIDE.
            # Only a separate, one-time, owner-scoped mobile handoff may expose
            # it after authentication. Never send it through MCP or logs.
            remote._aib_viewer_url = (
                data.get('debugUrl') or data.get('sessionViewerUrl')
                or data.get('sessionViewerURL'))
            self.remote[remote_id] = remote
            return remote
        except BaseException as failure:
            if (type(failure) is SteelCreateNotAttempted
                    and not creation_confirmed and browser is None):
                # The context wrapper has not called the provider's create
                # method. There is no new session to release or quarantine.
                # This never clears existing uncertainty or retries a POST.
                raise failure.failure from None
            # A timed-out/invalid create response may have started a provider
            # session. A 404 for our requested id is NOT proof otherwise.
            if not creation_confirmed:
                self._quarantined = True
            if browser is not None:
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(browser.close(), 5)
            confirmed_released = False
            try:
                confirmed_released = await self.release(remote_id)
            finally:
                if not confirmed_released:
                    self._quarantined = True
            raise


class RemoteBrowser:
    def __init__(self, engine, browser, remote_id):
        self.engine, self.browser, self.remote_id = engine, browser, remote_id
        self.created_at = time.time()
        # CDP shutdown and provider release are separate lifecycle stages.
        # `closed` makes the connection unavailable once CDP close starts;
        # it does not certify that a provider release was even attempted.
        self.closed = False
        self._release_started = False
        self._release_confirmed = False
        self.close_lock = asyncio.Lock()
        self._captcha_requested = False
        self._captcha_enabled = False
        self._captcha_confirmed = False
        self._captcha_availability = 'disabled'
        self._captcha_cache = None
        self._captcha_status_lock = asyncio.Lock()

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

    def captcha_configuration(self):
        return {
            'requested': self._captcha_requested,
            'provider_confirmed': self._captcha_confirmed,
            'availability': self._captcha_availability,
        }

    async def captcha_status(self, page_url):
        """Read bounded progress for this page; False is never proof of success.

        The caller must inspect the page again. URLs, page IDs, tokens and raw
        task payloads stay server-side. No solve/retry or browser action occurs.
        """
        base = {
            'requested': self._captcha_requested,
            'enabled': self._captcha_enabled,
            'provider_confirmed': self._captcha_confirmed,
            'availability': self._captcha_availability,
            'check_after_seconds': 3,
            'completion_confirmed': False,
        }
        if not self._captcha_enabled:
            return {**base, 'status': 'disabled'}
        key = _captcha_page_key(page_url)
        if key is None or self.closed:
            return {**base, 'status': 'unavailable'}
        async with self._captcha_status_lock:
            cached = self._captcha_cache
            if cached and cached[0] == key and time.monotonic() - cached[1] < 3:
                return dict(cached[2])
            status = 'unavailable'
            try:
                data = await asyncio.wait_for(self.engine.request(
                    'GET', '/sessions/' + self.remote_id + '/captchas/status',
                    timeout=5), timeout=6)
                if isinstance(data, list) and len(data) <= 50:
                    matching = [item for item in data if isinstance(item, dict)
                                and _captcha_page_key(item.get('url')) == key]
                    if not matching:
                        status = 'not_reported'
                    elif len(matching) == 1 and type(matching[0].get('isSolvingCaptcha')) is bool:
                        status = 'solving' if matching[0]['isSolvingCaptcha'] else 'not_running'
            except Exception:
                # Cancellation propagates. Failure never triggers a write,
                # release, login retry or false success.
                pass
            output = {**base, 'status': status}
            self._captcha_cache = (key, time.monotonic(), output)
            return dict(output)

    async def close(self, **_kwargs):
        async with self.close_lock:
            if self._release_confirmed:
                return
            try:
                if not self.closed:
                    self.closed = True
                    with contextlib.suppress(Exception):
                        await asyncio.wait_for(self.browser.close(), 5)
                # A cancelled CDP close must not permanently skip a release
                # that was never started (including install.stop's finally).
                if self._release_started:
                    # The earlier outcome is unknown. Do not repeat a write
                    # or report success without independent reconciliation.
                    raise SteelFailure('STEEL_REMOTE_RELEASE_UNCONFIRMED')
                self._release_started = True
                confirmed_released = await self.engine.release(self.remote_id)
                if not confirmed_released:
                    raise SteelFailure('STEEL_REMOTE_RELEASE_UNCONFIRMED')
                self._release_confirmed = True
                if self.engine.remote.get(self.remote_id) is self:
                    self.engine.remote.pop(self.remote_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                # Never expose arbitrary provider exceptions or private URLs.
                raise SteelFailure('STEEL_REMOTE_RELEASE_UNCONFIRMED') from None
            finally:
                if not self._release_confirmed:
                    # Cancellation and uncertain outcomes retain the reference.
                    # A later successful close must never clear quarantine.
                    self.engine._quarantined = True


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


def parallel_session_capacity():
    """Opt-in only: Steel Launch supports up to 10, but owner beta caps at 5.

    Explicit flags prevent deployment of an unsecured numeric session limit.
    This is not per-tenant isolation and is not suitable for public SaaS.
    """
    raw = os.environ.get("AI_BROWSER_PARALLEL_SESSIONS", "1")
    if raw not in ("1", "2", "3", "4", "5"):
        raise SteelFailure("PARALLEL_SESSIONS_CONFIG_INVALID")
    slots = int(raw)
    mode = os.environ.get("AI_BROWSER_SESSION_GUARD", "0")
    if slots > 1 and mode != "multi":
        raise SteelFailure("PARALLEL_OWNER_GUARD_REQUIRED")
    if mode == "multi" and os.environ.get("AI_BROWSER_PARALLEL_OWNER_BETA") != "1":
        raise SteelFailure("PARALLEL_OWNER_BETA_REQUIRED")
    return slots


def install(ns):
    if os.environ.get('AI_BROWSER_ENGINE', '').lower() != 'steel':
        return
    manager, mcp = ns['manager'], ns['mcp']
    if getattr(manager, '_steel_engine', None) is not None:
        return
    if not manager.portable_profiles:
        raise SteelFailure('STEEL_REQUIRES_PORTABLE_PROFILES')
    slots = parallel_session_capacity()
    engine = Engine()
    engine.max_sessions = slots
    manager._steel_engine = engine
    manager.max_sessions = slots
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
            result['captcha_automation'] = remote.captcha_configuration()
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

    # The live player uses WebRTC; the dashboard URL only shows session traces.
    # Steel's player URL itself grants interactive browser access. Release it
    # solely through the existing short-lived setup capability, no-store headers,
    # and an exact, server-generated URL. Never include an API key or credential.
    async def steel_viewer(request):
        setup = ns['_setup_record'](request)
        if not setup:
            return JSONResponse({'error': 'unauthorized'}, status_code=401, headers=HEADERS)
        session = manager._sessions.get(setup.get('session_id'))
        remote = getattr(session, 'browser', None)
        if not isinstance(remote, RemoteBrowser) or remote.closed:
            return JSONResponse({'error': 'session_not_active'}, status_code=410, headers=HEADERS)
        # sessionId is generated with uuid4 during launch; do not accept input
        # from the web page as a session identifier.
        return JSONResponse({
            'viewer_url': 'https://api.steel.dev/v1/sessions/' + remote.remote_id + '/player?interactive=true',
            'requires_steel_login': False,
        }, headers={**HEADERS, 'referrer-policy': 'no-referrer',
                    'x-content-type-options': 'nosniff'})

    mcp.custom_route('/setup/{setup_id}/steel-viewer', methods=['GET'])(steel_viewer)

    # The current image-based panel stays available as a fallback for all
    # existing workflows. Only a separate, opt-in live-view button is added.
    viewer_control = r'''<script>
    (() => {
      "use strict";
      function mountSteelViewer() {
        if (document.getElementById('aib-steel-live-btn')) return;
        const wrapper = document.createElement('section');
        wrapper.style.cssText = 'margin:12px 20px;padding:12px;border-radius:14px;background:#14223b;color:white;';
        const button = document.createElement('button');
        button.id = 'aib-steel-live-btn';
        button.type = 'button';
        button.textContent = 'Płynny podgląd Steel — otwórz na żywo';
        button.style.cssText = 'width:100%;padding:14px 10px;background:#4970e4;color:white;border:0;border-radius:10px;font:600 16px -apple-system,Arial,sans-serif;cursor:pointer;';
        const note = document.createElement('p');
        note.style.cssText = 'font-size:13px;line-height:1.4;margin:8px 0 0;color:#ccd5ec;';
        note.textContent = 'Obraz WebRTC na żywo, bez odświeżanych zdjęć. Wróć strzałką, aby zapisać profil. Nie udostępniaj linku transmisji.';
        wrapper.append(button,note);
        const title = document.querySelector('h1');
        if (title) title.after(wrapper); else document.body.prepend(wrapper);
        button.addEventListener('click', async () => {
          // The original mobile setup page deliberately removes the URL
          // fragment after saving it in sessionStorage. Read its scoped key.
          const setupPath = location.pathname.endsWith('/') ? location.pathname.slice(0, -1) : location.pathname;
          let capability = location.hash.slice(1);
          if (!capability) {
            try { capability = sessionStorage.getItem('aib-setup:' + setupPath) || ''; }
            catch (_) { capability = ''; }
          }
          if (!capability) {
            note.textContent = 'Uprawnienie do sesji wygasło. Potrzebny będzie nowy link testowy.';
            return;
          }
          button.disabled = true;
          try {
            const base = location.pathname.replace(/\/$/, '');
            const response = await fetch(base + '/steel-viewer', {
              cache:'no-store', credentials:'same-origin',
              headers: { 'x-setup-capability': capability, 'accept': 'application/json' }
            });
            if (!response.ok) throw new Error('viewer_unavailable');
            const data = await response.json();
            const url = new URL(data.viewer_url);
            if (url.protocol !== 'https:' || url.hostname !== 'api.steel.dev'
                || !/^\/v1\/sessions\/[0-9a-fA-F-]{36}\/player$/.test(url.pathname)
                || url.searchParams.toString() !== 'interactive=true'
                || url.hash) throw new Error('invalid_viewer_url');
            location.assign(url.href);
          } catch (_) {
            note.textContent = 'Nie można otworzyć podglądu. Sesja mogła wygasnąć. Użyj dotychczasowego panelu.';
            button.disabled = false;
          }
        });
      }
      if (document.readyState === 'loading')
        document.addEventListener('DOMContentLoaded', mountSteelViewer, {once:true});
      else mountSteelViewer();
    })();
    </script>'''
    html = ns['_SETUP_HTML']
    idx = html.lower().rfind('</body>')
    ns['_SETUP_HTML'] = html[:idx] + viewer_control + html[idx:] if idx >= 0 else html + viewer_control

    async def health(request):
        return JSONResponse(
            steel_health_payload(engine, request.headers.get('authorization', '')),
            headers={**HEADERS, 'x-content-type-options': 'nosniff',
                     'referrer-policy': 'no-referrer'})
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
