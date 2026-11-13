"""Bounded CSS patches and evidence-based completion of late GET navigation.

No provider-limit bypass, background keepalive, credential export or automatic
write replay. CSS reads return a small excerpt; large documents stay server-side.
"""
from __future__ import annotations
import asyncio
import hashlib
import json
import re
import time
from urllib.parse import urlsplit
from email.utils import parsedate_to_datetime
from fastapi import HTTPException
import completion_runtime as previous
import production_runtime as prod
import server

app = previous.app
MAX_CSS = 512000
MAX_REQUEST = 20000
MAX_EXCERPT = 6000
BAD_CSS = re.compile(r"<\?|@import|expression\s*\(|javascript:", re.I)
_previous_action = server.workspace.action
_original_navigate = server.workspace.navigate


def sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def parse_spec(raw, kind):
    try:
        if not isinstance(raw, str) or len(raw.encode('utf-8')) > MAX_REQUEST:
            raise ValueError()
        spec = json.loads(raw)
        if not isinstance(spec, dict):
            raise ValueError()
        if kind in {'wordpress_css_status', 'wordpress_css_reconcile'}:
            if set(spec) != {'operation_id'}:
                raise ValueError()
        else:
            permitted = {'path', 'offset', 'limit'} if kind == 'wordpress_css_read' else {
                'path', 'operation_id', 'expected_sha256', 'expected_result_sha256', 'patches', 'commit'}
            if set(spec) - permitted:
                raise ValueError()
            path = spec.get('path')
            if (not isinstance(path, str) or len(path) > 1000 or '..' in path
                    or re.fullmatch(prod.CSS_PATH, path) is None):
                raise ValueError()
            if kind == 'wordpress_css_read':
                for key, default, low, high in [('offset', 0, 0, MAX_CSS), ('limit', 3000, 1, MAX_EXCERPT)]:
                    val = spec.get(key, default)
                    if type(val) is not int or not low <= val <= high:
                        raise ValueError()
                return spec
            if type(spec.get('commit', False)) is not bool:
                raise ValueError()
            if re.fullmatch(r'[a-f0-9]{64}', str(spec.get('expected_sha256', ''))) is None:
                raise ValueError()
            patches = spec.get('patches')
            if not isinstance(patches, list) or not 1 <= len(patches) <= 10:
                raise ValueError()
            for patch in patches:
                if (not isinstance(patch, dict) or set(patch) != {'find', 'replace'}
                        or not isinstance(patch['find'], str) or not patch['find']
                        or not isinstance(patch['replace'], str)):
                    raise ValueError()
            if spec.get('commit') and re.fullmatch(r'[a-f0-9]{64}', str(spec.get('expected_result_sha256', ''))) is None:
                raise ValueError()
        op = spec.get('operation_id')
        if not isinstance(op, str) or re.fullmatch(r'[a-zA-Z0-9_-]{8,80}', op) is None:
            raise ValueError()
        return spec
    except (ValueError, TypeError):
        raise HTTPException(400, 'Nieprawidłowe żądanie CSS; zmiana musi być mała i jednoznaczna.') from None


def patched_text(content, patches):
    if not isinstance(content, str) or len(content.encode('utf-8')) > MAX_CSS:
        raise HTTPException(413, 'Plik CSS przekracza bezpieczny limit 512000 bajtów.')
    result = content
    for patch in patches:
        if result.count(patch['find']) != 1:
            raise HTTPException(409, 'Fragment musi występować dokładnie raz. Nie wysłano zapisu.')
        result = result.replace(patch['find'], patch['replace'], 1)
    # Retain the original CSS policy, including checking the assembled result.
    if len(result.encode('utf-8')) > MAX_CSS or BAD_CSS.search(result):
        raise HTTPException(400, 'Wynik zmiany CSS jest niedozwolony lub zbyt duży.')
    if result == content:
        raise HTTPException(400, 'Zmiana nie zmienia zawartości pliku.')
    return result


def task_key(operation):
    return 'css-op-' + hashlib.sha256(operation.encode()).hexdigest()[:32]


def validate_state(record):
    state = record.get('checkpoint') if isinstance(record, dict) else None
    if (not isinstance(state, dict) or state.get('kind') != 'bounded_css_patch_v1'
            or state.get('account') != 'edycjanapieraj' or type(record.get('revision')) is not int
            or record['revision'] < 1 or state.get('phase') not in {'prepared', 'submitted', 'acknowledged', 'verified'}
            or re.fullmatch(prod.CSS_PATH, str(state.get('path', ''))) is None
            or '..' in state.get('path', '')
            or re.fullmatch(r'[a-f0-9]{64}', str(state.get('desired_sha256', ''))) is None):
        raise HTTPException(409, 'Nieprawidłowy zapis operacji CSS.')
    return state


async def read_record(key):
    try:
        return await asyncio.to_thread(server.db_checkpoint, key)
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        return None


async def checked_page(args, owner_context):
    w = server.workspace
    if w.context is None or w.profile != prod.WP_PROFILE or w.human:
        raise HTTPException(409, 'Wymagany otwarty profil WordPress przekazany agentowi.')
    if owner_context is not None and owner_context is not w.context:
        raise HTTPException(409, 'Sesja właścicielska wygasła.')
    await w.assert_lease()
    page = w.page()
    if not page.url.startswith(prod.WP_ORIGIN + '/wp-admin/'):
        raise HTTPException(409, 'Otwórz kokpit WordPress; nie przekierowano przeglądarki.')
    me = (await prod.rest(page, 'users/me?context=edit&_fields=id,name,slug'))['data']
    if not isinstance(me, dict) or me.get('slug') != 'edycjanapieraj':
        raise HTTPException(403, 'Nie potwierdzono właściwego konta WordPress.')
    w.last_activity = time.monotonic()
    return page


async def read_css(page, path):
    data = prod.editable((await prod.rest(page, path + '?context=edit'))['data'])
    content = data.get('content', {}).get('raw') if isinstance(data, dict) else None
    if not isinstance(content, str) or len(content.encode('utf-8')) > MAX_CSS:
        raise HTTPException(413, 'Nieprawidłowy lub zbyt duży plik CSS.')
    return data, content


# Recheck the current source hash inside WordPress's own origin immediately
# before its core editor POST. Do not claim an atomic cross-client filesystem CAS.
CSS_COMPARE_WRITE = prod.CSS_EDITOR_JS.replace(
    'const nonce=form.querySelector',
    "const currentHash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(area.value)))).map(b=>b.toString(16).padStart(2,'0')).join('');"
    "if(currentHash!==body.expected_raw_sha256)return {status:409,data:{code:'css_source_changed'}};"
    'const nonce=form.querySelector')
if CSS_COMPARE_WRITE == prod.CSS_EDITOR_JS:
    raise RuntimeError('CSS editor contract changed; recheck integration before deployment')
CSS_COMPARE_WRITE = CSS_COMPARE_WRITE.replace(
    "if(!r.ok||html.length>2000000)throw new Error('Editor unavailable');",
    "if(!r.ok)return {status:r.status,data:{code:'editor_unavailable'},retry_after:r.headers.get('Retry-After')};if(html.length>2000000)return {status:413,data:{code:'editor_too_large'}};")
CSS_COMPARE_WRITE = CSS_COMPARE_WRITE.replace(
    "status:sent.ok?409:sent.status,data:{code:'theme_write_not_confirmed'}",
    "status:sent.ok?409:sent.status,data:{code:'theme_write_not_confirmed'},retry_after:sent.headers.get('Retry-After')")


async def write_css(page, path, content, expected_raw):
    if time.monotonic() < prod.WP_COOLDOWN_UNTIL:
        raise HTTPException(429, {'code': 'wordpress_cooldown', 'retry_after_seconds': max(1, int(prod.WP_COOLDOWN_UNTIL-time.monotonic())+1)})
    result = await page.evaluate(CSS_COMPARE_WRITE, {
        'path': path, 'method': 'POST', 'body': {'content': content, 'expected_raw_sha256': expected_raw}})
    status = result.get('status', 502)
    if status >= 400:
        if status == 429:
            raw = result.get('retry_after') or '30'
            try:
                seconds = int(raw) if str(raw).isdigit() else max(0, parsedate_to_datetime(raw).timestamp()-time.time())
            except (ValueError, TypeError, OverflowError):
                seconds = 30
            prod.WP_COOLDOWN_UNTIL = max(prod.WP_COOLDOWN_UNTIL, time.monotonic()+max(1, seconds))
        raise HTTPException(status, {'code': 'css_write_not_confirmed', 'upstream': 'wordpress'})


async def css_action(args, owner_context=None):
    action = args['action']
    spec = parse_spec(args.get('text', ''), action)
    if args.get('name') != prod.WP_PROFILE:
        raise HTTPException(403, 'Wymagany istniejący profil WordPress kliniki.')
    if action == 'wordpress_css_status':
        record = await read_record(task_key(spec['operation_id']))
        if record is None:
            raise HTTPException(404, 'Nie znaleziono operacji CSS.')
        state = validate_state(record)
        return {'phase': state['phase'], 'task_id': task_key(spec['operation_id']),
                'operation_id': spec['operation_id'], 'revision': record['revision'],
                'requires_readback': state['phase'] in {'submitted', 'acknowledged'},
                'external_write_replayed': False}
    w = server.workspace
    async with w.lock:
        page = await checked_page(args, owner_context)
        if action == 'wordpress_css_reconcile':
            key = task_key(spec['operation_id'])
            record = await read_record(key)
            if record is None:
                raise HTTPException(404, 'Nie znaleziono operacji CSS.')
            state = validate_state(record)
            if state['phase'] == 'verified':
                return {**state['receipt'], 'already_confirmed': True}
            if state['phase'] not in {'submitted', 'acknowledged'}:
                raise HTTPException(409, 'Zapis nie został wysłany; nie ponowiono operacji.')
            data, content = await read_css(page, state['path'])
            if sha(content) != state['desired_sha256']:
                raise HTTPException(409, 'Treść różni się od oczekiwanej. Nie ponowiono zapisu.')
            receipt = {'ok': True, 'verified': True, 'operation_id': spec['operation_id'],
                       'task_id': key, 'sha256': prod.fingerprint(data), 'raw_sha256': sha(content),
                       'external_write_replayed': False, 'verification_basis': 'readback_only'}
            await asyncio.to_thread(server.db_checkpoint, key,
                {**state, 'phase': 'verified', 'receipt': receipt}, record['revision'])
            return receipt
        before, content = await read_css(page, spec['path'])
        current_hash = prod.fingerprint(before)
        if action == 'wordpress_css_read':
            offset, limit = spec.get('offset', 0), spec.get('limit', 3000)
            return {'path': spec['path'], 'sha256': current_hash, 'raw_sha256': sha(content),
                    'bytes': len(content.encode('utf-8')), 'characters': len(content),
                    'offset': offset, 'excerpt': content[offset:offset+limit],
                    'next_offset': offset+limit if offset+limit < len(content) else None}
        key = task_key(spec['operation_id'])
        request_hash = prod.fingerprint(spec)
        if spec.get('commit'):
            prior = await read_record(key)
            if prior is not None:
                state = validate_state(prior)
                if state.get('request_hash') != request_hash:
                    raise HTTPException(409, 'Identyfikator operacji ma już inną treść.')
                if state['phase'] == 'verified':
                    return {**state['receipt'], 'already_confirmed': True}
                raise HTTPException(409, {'code': 'css_requires_readback', 'task_id': key, 'phase': state['phase']})
        if current_hash != spec['expected_sha256']:
            raise HTTPException(409, 'Plik zmienił się od odczytu. Nie wysłano zapisu.')
        desired = patched_text(content, spec['patches'])
        desired_hash = sha(desired)
        if not spec.get('commit'):
            return {'preview': True, 'external_write': False, 'path': spec['path'],
                    'before_sha256': current_hash, 'expected_result_sha256': desired_hash,
                    'before_bytes': len(content.encode('utf-8')), 'after_bytes': len(desired.encode('utf-8')),
                    'patch_count': len(spec['patches'])}
        if desired_hash != spec['expected_result_sha256']:
            raise HTTPException(409, 'Wynik różni się od zaakceptowanego podglądu.')
        before_ref = await prod.backup_document(spec['operation_id'], 'css-before', before)
        state = {'kind': 'bounded_css_patch_v1', 'account': 'edycjanapieraj', 'phase': 'prepared',
                 'path': spec['path'], 'request_hash': request_hash, 'before_backup': before_ref,
                 'before_sha256': sha(content), 'desired_sha256': desired_hash,
                 'patches': spec['patches']}
        record = await asyncio.to_thread(server.db_checkpoint, key, state)
        state = {**state, 'phase': 'submitted'}
        record = await asyncio.to_thread(server.db_checkpoint, key, state, record['revision'])
        await write_css(page, spec['path'], desired, sha(content))
        state = {**state, 'phase': 'acknowledged'}
        record = await asyncio.to_thread(server.db_checkpoint, key, state, record['revision'])
        after, actual = await read_css(page, spec['path'])
        if sha(actual) != desired_hash:
            raise HTTPException(409, {'code': 'css_readback_mismatch', 'task_id': key})
        receipt = {'ok': True, 'verified': True, 'task_id': key, 'operation_id': spec['operation_id'],
                   'sha256': prod.fingerprint(after), 'raw_sha256': desired_hash, 'bytes': len(actual.encode('utf-8'))}
        await asyncio.to_thread(server.db_checkpoint, key, {**state, 'phase': 'verified', 'receipt': receipt}, record['revision'])
        return receipt


async def navigate_ready(page, raw, *, restoring=False):
    """Wait for the same committed GET document, never issue another navigation."""
    observed = {'response': None, 'failed': False}
    def response_seen(response):
        try:
            request = response.request
            if request.is_navigation_request() and request.frame == page.main_frame:
                observed['response'] = response
        except Exception:
            pass
    def request_failed(request):
        try:
            if request.is_navigation_request() and request.frame == page.main_frame:
                observed['failed'] = True
        except Exception:
            pass
    page.on('response', response_seen)
    page.on('requestfailed', request_failed)
    try:
        result = await _original_navigate(page, raw, restoring=restoring)
        response = observed['response']
        if (result or observed['failed'] or response is None or not 200 <= response.status < 400
                or response.request.method not in {'GET', 'HEAD'} or page.url != response.url
                or urlsplit(page.url).scheme != 'https'):
            return result
        try:
            await page.wait_for_load_state('domcontentloaded', timeout=8000)
            if (observed['failed'] or observed['response'] is not response or page.url != response.url
                    or not await page.evaluate("document.readyState === 'interactive' || document.readyState === 'complete'")):
                return False
        except Exception:
            return False
        w = server.workspace
        w.failed_pages.discard(page)
        w.pending_urls.pop(page, None)
        return True
    finally:
        page.remove_listener('response', response_seen)
        page.remove_listener('requestfailed', request_failed)


async def reliability_action(args, automated=False, owner_context=None):
    action = args.get('action')
    if action in {'wordpress_css_read', 'wordpress_css_patch', 'wordpress_css_status', 'wordpress_css_reconcile'}:
        if owner_context is not None and owner_context is not server.workspace.context:
            raise HTTPException(409, 'Sesja właścicielska wygasła.')
        return await css_action(args, owner_context)
    result = await _previous_action(args, automated=automated, owner_context=owner_context)
    if action == 'runtime_status':
        result = {**result, 'version': '2.0.2', 'css_document_limit_bytes': MAX_CSS,
                  'css_patch_request_limit_bytes': MAX_REQUEST,
                  'capabilities': result['capabilities'] + ['wordpress_css_read', 'wordpress_css_patch',
                                                          'wordpress_css_status', 'wordpress_css_reconcile']}
    return result


server.workspace.navigate = navigate_ready
server.workspace.action = reliability_action
