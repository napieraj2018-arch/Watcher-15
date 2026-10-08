"""Read-only authentication evidence and controller lifecycle hardening.

Does not log in, accept challenges, obtain passwords, alter account settings,
change proxy settings, or change the existing generic secret-field restrictions.
"""
from __future__ import annotations
import asyncio
import json
import logging
import os
import re
from urllib.parse import urlsplit

VERSION = '0.5.2'
EMAIL = re.compile(r'(?<![\w.+-])[A-Z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[A-Z0-9](?:[A-Z0-9.-]*[A-Z0-9])?\.[A-Z]{2,}(?![\w.-])', re.I)
GOOGLE_ACCOUNT = 'a[href^="https://accounts.google.com/SignOutOptions"]:visible'
CHALLENGE = ('input[autocomplete="one-time-code"]:visible, '
             'iframe[src*="recaptcha"]:visible, iframe[src*="hcaptcha"]:visible')
PASSWORD = 'input[type="password"]:visible'
META_HOSTS = {'facebook.com', 'www.facebook.com', 'm.facebook.com', 'business.facebook.com'}
IG_HOSTS = {'instagram.com', 'www.instagram.com'}


def canonical_origin(url):
    try:
        p = urlsplit(url)
        if p.scheme != 'https' or not p.hostname or p.username or p.password or p.port not in (None, 443):
            return None
        return 'https://' + p.hostname.lower()
    except (TypeError, ValueError):
        return None


def google_identity_matches(labels, body_text):
    """Require one unambiguous account identity in both control and page text.
    Return a boolean only; email addresses never leave this function.
    """
    if not isinstance(labels, list) or not 1 <= len(labels) <= 4 or not isinstance(body_text, str):
        return False
    control_ids = set()
    for label in labels:
        if isinstance(label, str):
            control_ids.update(s.casefold() for s in EMAIL.findall(label[:2048]))
    visible_ids = {s.casefold() for s in EMAIL.findall(body_text[:30000])}
    return len(control_ids) == 1 and control_ids <= visible_ids


def result(stage, authenticated=None, **extra):
    return {'stage': stage, 'authenticated': authenticated, **extra}


async def inspect_session(session):
    """Never infer logged-out from a lack of evidence. No navigation or writes."""
    try:
        page = session.page
        if page.is_closed():
            return result('expired', False)
        initial_url = page.url
        origin = canonical_origin(initial_url)
        if origin is None:
            return result('unverified', reason='unsupported_origin')
        p = urlsplit(initial_url)
        host, path = p.hostname.lower(), p.path.lower()
        if any(s in path for s in ('/checkpoint', '/two_step_verification', '/captcha', '/challenge')):
            return result('verification_required', False, next_action='stop_automatic_login')
        if await page.locator(CHALLENGE).count():
            return result('verification_required', False, next_action='stop_automatic_login')
        if await page.locator(PASSWORD).count():
            return result('login_form', False, next_action='check_saved_credential')
        if host == 'myaccount.google.com':
            control = page.locator(GOOGLE_ACCOUNT)
            count = await control.count()
            if not 1 <= count <= 4:
                return result('unverified', provider='google', reason='account_control_missing')
            labels = await control.evaluate_all('(nodes) => nodes.slice(0,4).map(n => (n.getAttribute("aria-label") || "").slice(0,2048))')
            body = await page.locator('body').inner_text(timeout=3000)
            if page.url != initial_url:
                return result('unverified', reason='page_changed_during_check')
            if google_identity_matches(labels, body):
                return result('authenticated', True, provider='google',
                              evidence='account_control_and_matching_visible_identity',
                              next_action='reuse_session')
            return result('unverified', provider='google', reason='identity_not_confirmed')
        if host == 'accounts.google.com':
            return result('not_authenticated', False, provider='google', next_action='check_login_flow')
        if host in META_HOSTS or host in IG_HOSTS:
            required = {'c_user', 'xs'} if host in META_HOSTS else {'sessionid', 'ds_user_id'}
            cookies = await session.context.cookies(origin)
            names = {c.get('name') for c in cookies if c.get('value')}
            if page.url != initial_url:
                return result('unverified', reason='page_changed_during_check')
            if required <= names:
                # Cookies alone are not proof. Never retry login automatically
                # while a potentially valid session is awaiting page validation.
                return result('session_present_unverified', provider='meta' if host in META_HOSTS else 'instagram',
                              next_action='verify_protected_page_without_login')
            return result('not_authenticated', False, next_action='check_saved_credential')
        return result('unverified', reason='provider_not_verified')
    except Exception:
        return result('temporarily_unavailable', reason='read_failed_no_login_retry')


def credential_readiness(profile, url):
    """Validate configuration shape without returning any credential material.
    An existing environment secret is the only input. Nothing is imported here.
    """
    raw = os.environ.get('AI_BROWSER_CREDENTIALS_JSON', '')
    if not raw:
        return {'status': 'not_configured', 'matching_credentials': 0}
    try:
        if len(raw) > 65536:
            raise ValueError()
        data = json.loads(raw)
        if not isinstance(data, dict) or len(data) > 100:
            raise ValueError()
        matches = 0
        for cid, record in data.items():
            if not isinstance(cid, str) or not re.fullmatch(r'[A-Za-z0-9._-]{1,64}', cid) or not isinstance(record, dict):
                raise ValueError()
            target = record.get('origin')
            if not isinstance(target, str) or canonical_origin(target) != target:
                raise ValueError()
            if not isinstance(record.get('profile'), str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._ -]{0,63}', record['profile']):
                raise ValueError()
            if any(not isinstance(record.get(k), str) or not 1 <= len(record[k]) <= 2048 for k in ('username', 'password')):
                raise ValueError()
            if record['profile'] == profile and target == canonical_origin(url):
                matches += 1
        state = 'configured_for_current_origin' if matches == 1 else 'ambiguous_configuration' if matches > 1 else 'no_match_for_current_origin'
        return {'status': state, 'matching_credentials': matches}
    except (ValueError, TypeError):
        return {'status': 'invalid_configuration', 'matching_credentials': 0}


def redact_log_text(value):
    value = re.sub(r'(/mcp/)[^\s?\"\x27]+', r'\1[redacted]', value)
    return re.sub(r'([?&](?:[^=&\s]*token|[^=&\s]*key|code|password|secret|capability|authorization)=)[^&\s\"\x27]+',
                  r'\1[redacted]', value, flags=re.I)


class AccessSecretFilter(logging.Filter):
    def filter(self, record):
        # Preserve Uvicorn's five-element args tuple for AccessFormatter.
        if isinstance(record.msg, str):
            record.msg = redact_log_text(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(redact_log_text(v) if isinstance(v, str) else v for v in record.args)
        elif isinstance(record.args, dict):
            record.args = {k: redact_log_text(v) if isinstance(v, str) else v for k, v in record.args.items()}
        return True


def install(ns):
    if os.environ.get('AI_BROWSER_ENGINE', '').lower() != 'steel':
        return
    import steel_context_fix as core
    import steel_runtime as runtime
    manager = ns['manager']
    if getattr(manager, '_auth_status_v052', False):
        return
    core.VERSION = runtime.VERSION = VERSION
    core.auth_probe = inspect_session
    old_status, old_start, old_stop = manager.status, manager.start, manager.stop
    lifecycle = asyncio.Lock()

    async def status(sid):
        output = await old_status(sid)
        session = manager._session(sid)
        output['saved_login'] = credential_readiness(session.profile, session.page.url)
        output['saved_login_configured'] = output['saved_login']['status'] == 'configured_for_current_origin'
        output['controller_revision'] = VERSION
        return output

    async def start(*args, **kwargs):
        # Starting a new context cannot overtake another context's close/save.
        async with lifecycle:
            output = await old_start(*args, **kwargs)
            return await status(output['session_id'])

    async def stop(*args, **kwargs):
        async with lifecycle:
            return await old_stop(*args, **kwargs)

    manager.status, manager.start, manager.stop = status, start, stop
    manager._auth_status_v052 = True
    for name in ('uvicorn.access', 'httpx', 'httpcore'):
        logging.getLogger(name).addFilter(AccessSecretFilter())
    print('AI_BROWSER_AUTH_EVIDENCE_READY ' + VERSION, flush=True)
