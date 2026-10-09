"""AI Browser 0.5: native profiles, recovery metadata and scoped credential use.
No credentials or browser storage are returned by these tools. Existing generic
fill restrictions stay in place. No proxy, billing or CAPTCHA settings change.
"""
from __future__ import annotations
import asyncio
import contextlib
import contextvars
import copy
import json
import os
import re
import time
import uuid
from collections import deque
from pathlib import Path
from urllib.parse import urlsplit
import httpx
from starlette.responses import JSONResponse

VERSION = '0.5.1'
HEADERS = {'cache-control': 'no-store'}
PROFILE_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._ -]{0,63}$')

class ReliabilityError(RuntimeError):
    """Fixed error codes only: do not propagate third-party error text."""


def safe_route(url):
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or '')[:150]
        path = parsed.path.lower()
        label = '/other'
        for prefix in ('/two_step_verification', '/checkpoint', '/login', '/captcha', '/recover', '/accounts/login', '/challenge'):
            if path.startswith(prefix):
                label = prefix
                break
        if path in ('', '/'):
            label = '/'
        return host + label
    except (TypeError, ValueError):
        return 'unknown'


def exact_origin(url):
    try:
        p = urlsplit(url)
        if p.scheme != 'https' or not p.hostname or p.username or p.password:
            return None
        port = p.port
        return 'https://' + p.hostname.lower() + (':' + str(port) if port and port != 443 else '')
    except (TypeError, ValueError):
        return None


def merge_profile_state(native, backup):
    """Fill gaps in a provider snapshot without replacing its newer values."""
    def union(current, fallback, key):
        result = copy.deepcopy(current or [])
        known = {key(item) for item in result}
        for item in fallback or []:
            identity = key(item)
            if identity not in known:
                result.append(copy.deepcopy(item))
                known.add(identity)
        return result
    result = copy.deepcopy(native)
    result['cookies'] = union(native.get('cookies'), backup.get('cookies'),
                              lambda c: (c['name'], c.get('domain'), c.get('path', '/')))
    result['origins'] = copy.deepcopy(native.get('origins', []))
    by_origin = {item['origin']: item for item in result['origins']}
    for previous in backup.get('origins', []):
        origin = previous['origin']
        if origin not in by_origin:
            item = copy.deepcopy(previous)
            result['origins'].append(item)
            by_origin[origin] = item
            continue
        current = by_origin[origin]
        for field in ('localStorage', 'indexedDB'):
            if field in previous or field in current:
                current[field] = union(current.get(field), previous.get(field), lambda x: x['name'])
    return result



def synthetic_fixture_evidence(native=None, portable=None, resolved=None):
    """Non-sensitive consistency diagnostics ONLY for the disposable test site.

    The function never returns a cookie, storage key, storage value, digest,
    account identity, token, or domain. It only counts test-origin values and
    compares equality in memory. Callers must restrict this to SteelSelfTest.
    """
    from urllib.parse import unquote
    test_origin = 'https://ai-browser-vault.floot.app'
    test_host = 'ai-browser-vault.floot.app'

    def extract(state):
        if not isinstance(state, dict):
            return (), ()
        cookies = []
        for item in state.get('cookies', []) or []:
            if not isinstance(item, dict):
                continue
            host = item.get('domain')
            value = item.get('value')
            if (isinstance(host, str) and host.lstrip('.').lower() == test_host
                    and isinstance(value, str) and value):
                cookies.append(value)
        storage = []
        for entry in state.get('origins', []) or []:
            if not isinstance(entry, dict) or entry.get('origin') != test_origin:
                continue
            for item in entry.get('localStorage', []) or []:
                if isinstance(item, dict) and isinstance(item.get('value'), str) and item['value']:
                    storage.append(item['value'])
        return tuple(cookies[:30]), tuple(storage[:30])

    def overlaps(left, right):
        return any(a == b for a in left for b in right)

    def summary(state):
        cookies, storage = extract(state)
        return {
            'test_cookie_values': len(cookies),
            'test_local_storage_values': len(storage),
            'identical_pair_present': overlaps(cookies, storage),
            'url_decoded_pair_present': overlaps(tuple(unquote(x) for x in cookies), storage),
        }

    n_cookies, n_storage = extract(native)
    p_cookies, p_storage = extract(portable)
    return {
        'source': 'synthetic_fixture_only',
        'native': summary(native),
        'portable': summary(portable),
        'resolved': summary(resolved),
        'native_cookie_vs_portable_storage': overlaps(n_cookies, p_storage),
        'portable_cookie_vs_native_storage': overlaps(p_cookies, n_storage),
    }


def synthetic_fixture_exact_evidence(native=None, portable=None, resolved=None, *,
                                     now_seconds=None):
    """Inspect ONLY the test cookie/localStorage key, never their values.

    Used solely for the disposable SteelSelfTest profile. The public React
    fixture writes a cookie named aibrowser_test_cookie with Path=/browser-check
    and localStorage key aibrowser_public_test_marker. All comparisons happen
    in-process and return counts/booleans, never raw values, keys or digests.
    """
    from urllib.parse import unquote
    from math import isfinite
    import time as _time
    now = _time.time() if now_seconds is None else now_seconds
    if not isinstance(now, (int, float)) or not isfinite(now):
        raise ValueError("INVALID_TEST_CLOCK")
    expected_host = 'ai-browser-vault.floot.app'
    expected_origin = 'https://' + expected_host
    expected_cookie = 'aibrowser_test_cookie'
    expected_storage = 'aibrowser_public_test_marker'

    def read(state):
        matching_name = []
        matching_path = []
        readable = []
        local = []
        if not isinstance(state, dict):
            return (matching_name, matching_path, readable, local)
        raw_cookies = state.get('cookies', [])
        if isinstance(raw_cookies, list):
            for item in raw_cookies:
                if not isinstance(item, dict):
                    continue
                if (item.get('name') != expected_cookie or
                        not isinstance(item.get('domain'), str) or
                        item['domain'].lstrip('.').lower() != expected_host):
                    continue
                matching_name.append(item)
                if item.get('path') != '/browser-check':
                    continue
                matching_path.append(item)
                value = item.get('value')
                expires = item.get('expires')
                expired = (isinstance(expires, (int, float)) and expires >= 0
                           and expires <= now)
                # document.cookie hides HttpOnly cookies. Secure page allows
                # secure or non-secure cookies, but a test cookie must be Secure.
                if (isinstance(value, str) and value and
                        item.get('secure') is True and
                        item.get('httpOnly') is not True and not expired):
                    readable.append(value)
        origins = state.get('origins', [])
        if isinstance(origins, list):
            for entry in origins:
                if not isinstance(entry, dict) or entry.get('origin') != expected_origin:
                    continue
                pairs = entry.get('localStorage', [])
                if not isinstance(pairs, list):
                    continue
                for item in pairs:
                    if (isinstance(item, dict) and
                            item.get('name') == expected_storage and
                            isinstance(item.get('value'), str) and
                            item['value']):
                        local.append(item['value'])
        return (matching_name, matching_path, readable, local)

    def report(values):
        named, path, readable, storage = values
        singleton = len(readable) == len(storage) == 1
        return {
            'cookie_with_exact_name_count': len(named),
            'cookie_with_exact_path_count': len(path),
            'cookie_readable_count': len(readable),
            'storage_exact_key_count': len(storage),
            'exact_pair_matches': bool(singleton and readable[0] == storage[0]),
            'url_decoded_pair_matches': bool(
                singleton and unquote(readable[0]) == storage[0]),
            'duplicates_present': len(named) > 1 or len(storage) > 1,
            'valid_page_cookie_missing': not readable,
        }

    n = read(native)
    p = read(portable)
    r = read(resolved)
    return {
        'source': 'exact_synthetic_marker_v2',
        'native': report(n),
        'portable': report(p),
        'resolved': report(r),
        'native_cookie_matches_portable_storage': bool(
            len(n[2]) == len(p[3]) == 1 and n[2][0] == p[3][0]),
        'portable_cookie_matches_native_storage': bool(
            len(p[2]) == len(n[3]) == 1 and p[2][0] == n[3][0]),
        'cookie_same_between_native_and_portable': bool(
            len(n[2]) == len(p[2]) == 1 and n[2][0] == p[2][0]),
        'storage_same_between_native_and_portable': bool(
            len(n[3]) == len(p[3]) == 1 and n[3][0] == p[3][0]),
    }


async def native_context(remote, **options):
    from steel_runtime import SteelFailure
    if getattr(remote, '_native_context_claimed', False):
        raise SteelFailure('STEEL_CONTEXT_ALREADY_CLAIMED')
    contexts = remote.browser.contexts
    if not contexts:
        raise SteelFailure('STEEL_NATIVE_CONTEXT_MISSING')
    context = contexts[0]
    if not hasattr(context, 'set_storage_state'):
        raise SteelFailure('PLAYWRIGHT_159_REQUIRED')
    supported = {'storage_state', 'viewport', 'accept_downloads', 'extra_http_headers'}
    if set(options) - supported:
        raise SteelFailure('STEEL_UNSUPPORTED_CONTEXT_OPTIONS')
    binding = getattr(remote.engine, '_native_bindings', {}).get(remote.remote_id, {})
    state = options.get('storage_state')
    if state is not None:
        if isinstance(state, (str, Path)):
            state = json.loads(Path(state).read_text(encoding='utf-8'))
        if not isinstance(state, dict):
            raise SteelFailure('STEEL_INVALID_PROFILE_STATE')
        if binding.get('hydrated'):
            # The default trusts newer-looking native data over the encrypted
            # portable snapshot. For opted-in technical profiles only, trial
            # portable precedence to diagnose inconsistent cookie/storage
            # pairs after a provider-native restart. Never enable it for live
            # social accounts without a separate end-to-end test.
            import os as _aib_recovery_os
            raw_policy = _aib_recovery_os.environ.get(
                'AI_BROWSER_PORTABLE_PRIORITY_PROFILES', '')
            if raw_policy:
                profiles = [item.strip() for item in raw_policy.split(',')]
                if (len(raw_policy) > 2048 or len(profiles) > 20 or
                    any(not PROFILE_RE.fullmatch(name) for name in profiles)):
                    raise SteelFailure('PROFILE_RECOVERY_POLICY_INVALID')
            else:
                profiles = []
            prefer_portable = binding.get('profile') in profiles
            current = await context.storage_state(indexed_db=True)
            merged = (merge_profile_state(state, current) if prefer_portable
                      else merge_profile_state(current, state))
            binding['portable_priority_used'] = prefer_portable
            if binding.get('profile') == 'SteelSelfTest':
                binding['synthetic_fixture_evidence'] = synthetic_fixture_evidence(
                    current, state, merged)
                binding['synthetic_fixture_evidence']['exact_marker'] = (
                    synthetic_fixture_exact_evidence(current, state, merged))
            if merged != current:
                await context.set_storage_state(merged)
                binding['backup_recovery_applied'] = True
        else:
            await context.set_storage_state(state)
    if options.get('extra_http_headers'):
        await context.set_extra_http_headers(options['extra_http_headers'])
    remote._native_context_claimed = True
    remote._aib_context = context
    remote._aib_native_hydrated = True
    remote._auth_events = deque(maxlen=100)
    def record(event, req, status=None):
        try:
            if req.resource_type not in {'document', 'xhr', 'fetch'}:
                return
            item = {'at': round(time.time(), 3), 'event': event,
                    'method': req.method, 'route': safe_route(req.url)}
            if status is not None:
                item['status'] = int(status)
            remote._auth_events.append(item)
        except Exception:
            pass
    context.on('request', lambda req: record('request', req))
    context.on('response', lambda resp: record('response', resp.request, resp.status))
    context.on('requestfailed', lambda req: record('failed', req))
    return context


class ProfileRegistry:
    """Stores provider profile identifiers, never cookies, passwords or live URLs."""
    def __init__(self):
        base = os.environ.get('AI_BROWSER_PROFILE_STORE_URL', '')
        if not base.endswith('/profile-vault') or not exact_origin(base):
            raise ReliabilityError('PROFILE_REGISTRY_CONFIGURATION_REQUIRED')
        self.url = base[:-len('profile-vault')] + 'engine-profile'

    async def request(self, method, profile, profile_id=None, hydrated=False):
        if not isinstance(profile, str) or not PROFILE_RE.fullmatch(profile):
            raise ReliabilityError('INVALID_PROFILE_NAME')
        token = os.environ.get('AI_BROWSER_PROFILE_STORE_TOKEN', '')
        if not token:
            raise ReliabilityError('PROFILE_REGISTRY_AUTH_REQUIRED')
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
                kwargs = {'headers': {'authorization': 'Bearer ' + token}}
                if method == 'GET':
                    kwargs['params'] = {'profile': profile}
                else:
                    profile_id = str(uuid.UUID(str(profile_id)))
                    kwargs['json'] = {'profile': profile, 'profile_id': profile_id, 'hydrated': hydrated}
                r = await client.request(method, self.url, **kwargs)
                if r.status_code != 200:
                    raise ReliabilityError('PROFILE_REGISTRY_HTTP_' + str(r.status_code))
                data = r.json()
                if not isinstance(data, dict):
                    raise ValueError()
                if method == 'GET':
                    pid = data.get('profile_id')
                    if pid is not None:
                        pid = str(uuid.UUID(str(pid)))
                    return {'profile_id': pid, 'hydrated': data.get('hydrated') is True}
                if data.get('ok') is not True:
                    raise ValueError()
                return data
        except (httpx.HTTPError, OSError, ValueError):
            raise ReliabilityError('PROFILE_REGISTRY_UNAVAILABLE') from None


async def await_profile_ready(request, profile_id, attempts=10):
    profile_id = str(uuid.UUID(str(profile_id)))
    for n in range(attempts):
        data = await request('GET', '/profiles/' + profile_id, timeout=10)
        state = str(data.get('status', data.get('state', ''))).upper()
        if state == 'READY':
            return True
        if state not in {'UPLOADING', 'CREATING', 'PENDING'}:
            raise ReliabilityError('NATIVE_PROFILE_NOT_READY')
        if n + 1 < attempts:
            await asyncio.sleep(1)
    raise ReliabilityError('NATIVE_PROFILE_STILL_UPLOADING')


async def auth_probe(session):
    """Conservative current-page evidence, not a claim that cookies prove login."""
    try:
        page = session.page
        if page.is_closed():
            return {'stage': 'expired', 'authenticated': False}
        p = urlsplit(page.url)
        origin = exact_origin(page.url)
        path = p.path.lower()
        if any(x in path for x in ('checkpoint', 'two_step_verification', 'captcha', '/challenge', '/signin/v2/challenge', '/signin/challenge')):
            return {'stage': 'verification_required', 'authenticated': False}
        challenge = ('input[autocomplete="one-time-code"]:visible, '
                     'iframe[src*="recaptcha"]:visible, iframe[src*="hcaptcha"]:visible')
        if await page.locator(challenge).count():
            return {'stage': 'verification_required', 'authenticated': False}
        if await page.locator('input[type="password"]:visible').count():
            return {'stage': 'login_form', 'authenticated': False}
        host = p.hostname or ''
        required = {'c_user', 'xs'} if host in {'facebook.com', 'www.facebook.com', 'm.facebook.com', 'business.facebook.com'} else {'sessionid', 'ds_user_id'} if host in {'www.instagram.com', 'instagram.com'} else set()
        names = {c.get('name') for c in await session.context.cookies(origin)} if origin and required else set()
        if required and required <= names:
            return {'stage': 'session_present_unverified', 'authenticated': False,
                    'verification_needed': 'protected_page_and_account_identity'}
        if host in {'accounts.google.com', 'www.facebook.com', 'm.facebook.com', 'www.instagram.com'}:
            return {'stage': 'not_authenticated', 'authenticated': False}
        return {'stage': 'unverified', 'authenticated': False}
    except Exception:
        return {'stage': 'temporarily_unavailable', 'authenticated': False}


def saved_credential(credential_id, profile, url):
    """Credentials are server environment secrets, addressed only by an opaque ID."""
    if not re.fullmatch(r'[A-Za-z0-9._-]{1,64}', credential_id or ''):
        raise ReliabilityError('INVALID_CREDENTIAL_REFERENCE')
    raw = os.environ.get('AI_BROWSER_CREDENTIALS_JSON', '')
    if not raw:
        raise ReliabilityError('CREDENTIALS_NOT_CONFIGURED')
    try:
        if len(raw) > 65536:
            raise ValueError()
        records = json.loads(raw)
        record = records.get(credential_id) if isinstance(records, dict) else None
        if not isinstance(record, dict):
            raise ReliabilityError('CREDENTIAL_REFERENCE_NOT_FOUND')
        origin = record.get('origin')
        if not isinstance(origin, str) or not exact_origin(origin) or origin != exact_origin(origin) or origin != exact_origin(url):
            raise ReliabilityError('CREDENTIAL_ORIGIN_MISMATCH')
        if record.get('profile') != profile:
            raise ReliabilityError('CREDENTIAL_PROFILE_MISMATCH')
        if any(not isinstance(record.get(k), str) or not 1 <= len(record[k]) <= 2048 for k in ('username', 'password')):
            raise ValueError()
        return record
    except (ValueError, TypeError):
        raise ReliabilityError('CREDENTIAL_CONFIGURATION_INVALID') from None


def install(ns):
    if os.environ.get('AI_BROWSER_ENGINE', '').lower() != 'steel':
        return
    import steel_runtime as runtime
    manager = ns['manager']
    if getattr(manager, '_reliability_installed', False):
        return
    registry = ProfileRegistry()
    engine = manager._steel_engine
    runtime.RemoteBrowser.new_context = native_context
    runtime.VERSION = VERSION
    manager._native_context_fix = True
    engine._native_bindings = {}
    pending_profile = contextvars.ContextVar('aib_profile', default=None)
    original_request = engine.request
    start_lock = asyncio.Lock()
    old_start, old_stop, old_status = manager.start, manager.stop, manager.status
    old_flush = manager.flush_profile
    autosaves, save_locks, save_status, attempts = {}, {}, {}, {}

    async def request(method, path, body=None, timeout=25):
        if method != 'POST' or path != '/sessions':
            return await original_request(method, path, body, timeout)
        profile = pending_profile.get()
        if not profile:
            raise ReliabilityError('PROFILE_CONTEXT_REQUIRED')
        binding = await registry.request('GET', profile)
        payload = dict(body or {})
        payload['persistProfile'] = True
        # Keep the existing total/cost cap, but do not terminate an in-progress
        # authentication flow simply because no CDP command arrived for 3 min.
        payload['inactivityTimeout'] = max(15000, int(payload['timeout']) - 1000)
        if binding['profile_id']:
            await await_profile_ready(original_request, binding['profile_id'])
            payload['profileId'] = binding['profile_id']
        data = await original_request(method, path, payload, timeout)
        rid = str(data.get('id', ''))
        try:
            pid = str(uuid.UUID(str(data.get('profileId', ''))))
            if binding['profile_id'] and binding['profile_id'] != pid:
                raise ReliabilityError('NATIVE_PROFILE_ID_MISMATCH')
            await registry.request('POST', profile, pid)
            engine._native_bindings[rid] = {'profile': profile, 'profile_id': pid,
                                            'hydrated': binding['hydrated']}
            return data
        except Exception:
            with contextlib.suppress(Exception):
                await original_request('POST', '/sessions/' + str(uuid.UUID(rid)) + '/release', {}, 10)
            raise ReliabilityError('NATIVE_PROFILE_BINDING_FAILED') from None

    async def flush(sid, *args, **kwargs):
        lock = save_locks.setdefault(sid, asyncio.Lock())
        async with lock:
            try:
                result = await old_flush(sid, *args, **kwargs)
                if isinstance(result, dict) and (result.get('error') or result.get('ok') is False or result.get('saved') is False):
                    raise ReliabilityError('PROFILE_SAVE_FAILED')
                save_status[sid] = {'ok': True, 'saved_at': round(time.time())}
                return result
            except Exception:
                save_status[sid] = {'ok': False, 'error': 'PROFILE_SAVE_FAILED'}
                raise

    async def autosave(sid):
        try:
            while sid in manager._sessions:
                await asyncio.sleep(45)
                if sid not in manager._sessions:
                    break
                try:
                    await asyncio.wait_for(manager.flush_profile(sid), 20)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    save_status[sid] = {'ok': False, 'error': 'PROFILE_SAVE_FAILED'}
        except asyncio.CancelledError:
            pass

    async def status(sid):
        result = await old_status(sid)
        session = manager._session(sid)
        binding = engine._native_bindings.get(getattr(session.browser, 'remote_id', ''), {})
        result.update({'runtime_version': VERSION, 'context_mode': 'provider_native',
            'full_profile_persistence': bool(binding),
            'full_profile_restored': binding.get('hydrated', False),
            'backup_recovery_applied': binding.get('backup_recovery_applied', False),
            'portable_priority_used': binding.get('portable_priority_used', False),
            'portable_backup': save_status.get(sid, {'ok': None}),
            'authentication': await auth_probe(session),
            'saved_login_configured': bool(os.environ.get('AI_BROWSER_CREDENTIALS_JSON', ''))})
        if session.profile == 'SteelSelfTest':
            result['synthetic_fixture_evidence'] = binding.get(
                'synthetic_fixture_evidence', {'source':'not_available'})
        return result

    async def start(*args, **kwargs):
        profile = kwargs.get('profile', args[0] if args else None)
        if not isinstance(profile, str) or not PROFILE_RE.fullmatch(profile):
            raise ReliabilityError('INVALID_PROFILE_NAME')
        async with start_lock:
            token = pending_profile.set(profile)
            try:
                result = await old_start(*args, **kwargs)
                sid = result['session_id']
                session = manager._session(sid)
                if result.get('headless') is False:
                    await session.page.set_viewport_size({'width': 508, 'height': 1074})
                if sid not in autosaves:
                    autosaves[sid] = asyncio.create_task(autosave(sid))
                return await status(sid)
            finally:
                pending_profile.reset(token)

    async def stop(sid, *args, **kwargs):
        task = autosaves.pop(sid, None)
        if task and task is not asyncio.current_task():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        session = manager._sessions.get(sid)
        remote = getattr(session, 'browser', None)
        rid = getattr(remote, 'remote_id', '')
        binding = engine._native_bindings.get(rid)
        result = await old_stop(sid, *args, **kwargs)
        if binding and getattr(remote, '_aib_native_hydrated', False):
            try:
                await await_profile_ready(original_request, binding['profile_id'])
                if isinstance(result, dict) and result.get('profile_saved') is True:
                    await registry.request('POST', binding['profile'], binding['profile_id'], True)
                if isinstance(result, dict):
                    result['full_profile_saved'] = True
            except Exception:
                if isinstance(result, dict):
                    result['full_profile_saved'] = False
                    result['full_profile_error'] = 'PERSISTENCE_NOT_CONFIRMED'
        engine._native_bindings.pop(rid, None)
        save_locks.pop(sid, None)
        save_status.pop(sid, None)
        return result

    async def browser_auth_status(session_id: str) -> dict:
        """Read current authentication evidence; never assume saved means signed in."""
        return await auth_probe(manager._session(session_id))

    async def browser_login_saved(session_id: str, credential_id: str) -> dict:
        """Use an existing server-side credential reference in WRITE mode only.
        Never accepts a password argument. One submission, exact HTTPS origin and
        profile binding; verification challenges stop this operation.
        """
        try:
            session = manager._session(session_id)
            if session.mode != 'write':
                raise ReliabilityError('WRITE_MODE_REQUIRED')
            record = saved_credential(credential_id, session.profile, session.page.url)
            if (await auth_probe(session))['stage'] == 'verification_required':
                raise ReliabilityError('VERIFICATION_REQUIRED')
            key = (session.profile, credential_id)
            if time.monotonic() - attempts.get(key, -100000) < 1800:
                raise ReliabilityError('LOGIN_RETRY_PAUSED')
            page = session.page
            user = page.locator('input[name="email"]:visible, input[name="username"]:visible, input[type="email"]:visible')
            password = page.locator('input[type="password"]:visible')
            if await user.count() != 1 or await password.count() != 1:
                raise ReliabilityError('SUPPORTED_LOGIN_FORM_REQUIRED')
            action = await password.evaluate('(el)=>el.form ? el.form.action : location.href')
            if exact_origin(action) != record['origin']:
                raise ReliabilityError('LOGIN_FORM_ORIGIN_MISMATCH')
            attempts[key] = time.monotonic()
            # Use the dedicated secret path; generic browser_fill stays blocked.
            await user.fill(record['username'])
            if exact_origin(page.url) != record['origin']:
                raise ReliabilityError('CREDENTIAL_ORIGIN_MISMATCH')
            action = await password.evaluate('(el)=>el.form ? el.form.action : location.href')
            if exact_origin(action) != record['origin']:
                raise ReliabilityError('LOGIN_FORM_ORIGIN_MISMATCH')
            await password.fill(record['password'])
            if exact_origin(page.url) != record['origin']:
                raise ReliabilityError('CREDENTIAL_ORIGIN_MISMATCH')
            await password.press('Enter')
            await asyncio.sleep(2)
            await manager.flush_profile(session_id)
            return {'submitted_once': True, 'authentication': await auth_probe(session)}
        except ReliabilityError as exc:
            return {'submitted_once': False, 'error': str(exc)}
        except Exception:
            return {'submitted_once': None, 'error': 'LOGIN_RESULT_UNCONFIRMED_NO_RETRY'}

    engine.request = request
    manager.start, manager.stop, manager.status = start, stop, status
    manager.flush_profile = flush
    ns['mcp'].tool()(browser_auth_status)
    ns['mcp'].tool()(browser_login_saved)
    manager._reliability_installed = True
    html = ns['_SETUP_HTML'].replace('0.4.2', VERSION).replace('0.4.3', VERSION)
    ns['_SETUP_HTML'] = html.replace(
        'Strona wymaga dodatkowego potwierdzenia albo blokuje tę przeglądarkę.',
        'Logowanie nie zostało potwierdzone. Dalsze automatyczne próby są zatrzymane.')

    async def health(_request):
        return JSONResponse({'status': 'ok', 'runtime': 'steel', 'version': VERSION,
            'context_mode': 'provider_native', 'native_profiles': True,
            'portable_backup_interval_seconds': 45, 'password_retry': False,
            'credentials_configured': bool(os.environ.get('AI_BROWSER_CREDENTIALS_JSON', '')),
            'local_chrome_processes': runtime.local_chrome_count(),
            'controller_memory': runtime.memory_info()}, headers=HEADERS)

    async def diagnostics(request):
        rec = ns['_setup_record'](request)
        if not rec:
            return JSONResponse({'error': 'unauthorized'}, status_code=401, headers=HEADERS)
        session = manager._sessions.get(rec['session_id'])
        if session is None:
            return JSONResponse({'stage': 'expired', 'version': VERSION}, headers=HEADERS)
        evidence = await auth_probe(session)
        evidence.update({'version': VERSION, 'route': safe_route(session.page.url),
                         'profile': session.profile, 'context_mode': 'provider_native'})
        return JSONResponse(evidence, headers=HEADERS)

    ns['mcp'].custom_route('/health/context', methods=['GET'])(health)
    ns['mcp'].custom_route('/setup/{setup_id}/auth-status', methods=['GET'])(diagnostics)
    print('AI_BROWSER_RELIABILITY_READY ' + VERSION, flush=True)
