"""Use the provider's native browser context, with credential-free diagnostics.
No new credentials, proxies, CAPTCHA solvers, or billing settings are created.
"""
from __future__ import annotations
import asyncio
import contextlib
import json
import os
import time
from collections import deque
from pathlib import Path
from urllib.parse import urlsplit
from starlette.responses import JSONResponse

VERSION = '0.4.6'
HEADERS = {'cache-control': 'no-store'}


def safe_route(url):
    """Return only an origin and a fixed route label, never URL tokens."""
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or '')[:150]
        path = parsed.path.lower()
        label = '/other'
        for prefix in ('/two_step_verification', '/checkpoint', '/login', '/captcha', '/recover'):
            if path.startswith(prefix):
                label = prefix
                break
        if path in ('', '/'):
            label = '/'
        return host + label
    except (TypeError, ValueError):
        return 'unknown'


async def native_context(remote, **options):
    """One isolated Steel session already owns one native browser context."""
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
    extra = set(options) - supported
    if extra:
        raise SteelFailure('STEEL_UNSUPPORTED_CONTEXT_OPTIONS_' + '_'.join(sorted(extra)))
    state = options.get('storage_state')
    if isinstance(state, (str, Path)):
        state = json.loads(Path(state).read_text(encoding='utf-8'))
    if state is not None:
        if not isinstance(state, dict):
            raise SteelFailure('STEEL_INVALID_PROFILE_STATE')
        # Import all supported state once, never reset it during authentication.
        await context.set_storage_state(state)
    if options.get('extra_http_headers'):
        await context.set_extra_http_headers(options['extra_http_headers'])
    # The core supplies a desktop-oriented 1000x700 viewport by default.
    # It is not an explicit user override and must never override Steel's
    # native portrait mobile screen (508x1074) during context creation.
    # Explicit later browser_set_viewport calls still work normally.
    remote._native_context_claimed = True
    remote._aib_context = context
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


def install(ns):
    if os.environ.get('AI_BROWSER_ENGINE', '').lower() != 'steel':
        return
    import steel_runtime as runtime
    manager = ns['manager']
    if getattr(manager, '_native_context_fix', False):
        return
    runtime.RemoteBrowser.new_context = native_context
    runtime.VERSION = VERSION
    manager._native_context_fix = True
    old_start = manager.start

    async def start(*args, **kwargs):
        result = await old_start(*args, **kwargs)
        session = manager._session(result['session_id'])
        # Steel mobile mode controls the native viewport and touch mapping.
        # Do not resize just the page inside its differently sized OS window;
        # that creates a split view and black bars in the WebRTC viewer.
        result['context_mode'] = 'provider_native'
        return result

    manager.start = start
    html = ns['_SETUP_HTML'].replace('0.4.2', VERSION).replace('0.4.3', VERSION)
    html = html.replace(
        'Strona wymaga dodatkowego potwierdzenia albo blokuje tę przeglądarkę.',
        'Logowanie nie zostało potwierdzone. Strona może wymagać ręcznej weryfikacji.')
    ns['_SETUP_HTML'] = html

    async def health(_request):
        return JSONResponse({'status': 'ok', 'runtime': 'steel', 'version': VERSION,
            'context_mode': 'provider_native', 'state_import': 'playwright_set_storage_state',
            'password_retry': False, 'local_chrome_processes': runtime.local_chrome_count(),
            'controller_memory': runtime.memory_info()}, headers=HEADERS)

    async def diagnostics(request):
        rec = ns['_setup_record'](request)
        if not rec:
            return JSONResponse({'error': 'unauthorized'}, status_code=401, headers=HEADERS)
        s = manager._sessions.get(rec['session_id'])
        if s is None or s.page.is_closed():
            return JSONResponse({'stage': 'expired', 'version': VERSION}, headers=HEADERS)
        try:
            remote = s.browser
            has_password = await s.page.locator('input[type=password]:visible').count() > 0
            path = urlsplit(s.page.url).path.lower()
            host = urlsplit(s.page.url).hostname or ''
            facebook = host == 'facebook.com' or host.endswith('.facebook.com')
            cookies = await s.context.cookies('https://www.facebook.com') if facebook else []
            names = {c['name'] for c in cookies if c.get('value')}
            verified = facebook and not has_password and {'c_user', 'xs'} <= names
            stage = 'authenticated' if verified else 'login_form' if has_password else 'unconfirmed'
            if any(x in path for x in ('checkpoint', 'two_step_verification', 'captcha')):
                stage = 'manual_verification'
            return JSONResponse({'version': VERSION, 'stage': stage,
                'route': safe_route(s.page.url), 'profile': s.profile,
                'context_mode': 'provider_native',
                'browser_contexts': len(remote.browser.contexts),
                'using_native_context': s.context is getattr(remote, '_aib_context', None),
                'remaining_seconds': max(0, int(870 - (time.time() - remote.created_at))),
                'events': list(getattr(remote, '_auth_events', []))[-25:],
                'controller_memory': runtime.memory_info()}, headers=HEADERS)
        except Exception:
            return JSONResponse({'stage': 'temporarily_unavailable', 'version': VERSION},
                                status_code=503, headers=HEADERS)

    ns['mcp'].custom_route('/health/context', methods=['GET'])(health)
    ns['mcp'].custom_route('/setup/{setup_id}/auth-status', methods=['GET'])(diagnostics)
    print('AI_BROWSER_NATIVE_CONTEXT_READY ' + VERSION, flush=True)
