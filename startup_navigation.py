"""Keep an authorized browser alive when the optional startup page is unreachable.

No new URL or auth bypass: use the existing capability-guarded navigation tool.
Creation, navigation and outcome are separate; never retry writes or login.
"""
from __future__ import annotations
import asyncio
import json
from urllib.parse import urlsplit


def unpack(value):
    return json.loads(value) if isinstance(value, str) else value


def safe_navigation_failure(exc):
    from playwright.async_api import Error, TimeoutError
    if isinstance(exc, TimeoutError):
        return 'START_PAGE_TIMEOUT_OUTCOME_UNCONFIRMED'
    if isinstance(exc, Error):
        for code in ('ERR_ADDRESS_UNREACHABLE', 'ERR_NAME_NOT_RESOLVED',
                     'ERR_CONNECTION_REFUSED', 'ERR_CONNECTION_TIMED_OUT',
                     'ERR_CONNECTION_RESET', 'ERR_BLOCKED_BY_ADMINISTRATOR'):
            if code in str(exc):
                return 'START_PAGE_' + code
    return 'START_PAGE_NAVIGATION_UNCONFIRMED'


def install(ns):
    if ns.get('_AIB_START_NAVIGATION_INSTALLED'):
        return
    guard = ns.get('_AIB_OWNER_PARALLEL_GUARD')
    if guard is None:
        return
    registry = ns['mcp']._tool_manager._tools
    original = registry['browser_start'].fn
    cleanup_tasks = set()

    async def start(**args):
        from mcp.server.mcpserver.exceptions import ToolError
        url = args.get('start_url', 'about:blank')
        if url == 'about:blank' or url == '':
            return await original(**args)
        try:
            p = urlsplit(url)
            valid = (isinstance(url, str) and len(url) <= 8192
                     and p.scheme in {'http', 'https'} and p.hostname
                     and p.username is None and p.password is None)
        except (TypeError, ValueError):
            valid = False
        if not valid:
            raise ToolError('START_PAGE_URL_INVALID')
        result = unpack(await original(**{**args, 'start_url': 'about:blank'}))
        if not isinstance(result, dict) or not isinstance(result.get('session_id'), str):
            raise ToolError('START_SESSION_RESULT_INVALID')
        handle = result['session_id']
        try:
            await registry['browser_navigate'].fn(session_id=handle, url=url)
        except asyncio.CancelledError:
            cleanup = asyncio.create_task(registry['browser_stop'].fn(session_id=handle))
            cleanup_tasks.add(cleanup)
            def finished(task):
                cleanup_tasks.discard(task)
                if not task.cancelled(): task.exception()
            cleanup.add_done_callback(finished)
            try:
                await asyncio.shield(cleanup)
            except BaseException:
                pass
            raise
        except Exception as exc:
            return {**result, 'navigation': {'status': 'unconfirmed',
                'error': safe_navigation_failure(exc), 'retry_automatically': False},
                'next_step': 'Inspect this owned browser with browser_status/browser_snapshot; do not log in again or repeat a write.'}
        # The creation receipt describes about:blank, not the visited account.
        # Return a fresh guarded read; never repeat navigation if readback fails.
        try:
            status = unpack(await registry['browser_status'].fn(session_id=handle))
            if not isinstance(status, dict) or status.get('session_id') != handle:
                raise ValueError('invalid owned status')
        except Exception:
            status = {'url': None, 'title': None, 'authentication': {
                'stage': 'unverified', 'authenticated': None,
                'reason': 'post_navigation_readback_unavailable'}}
        return {**result, **status, 'navigation': {'status': 'completed', 'retry_automatically': False},
                'next_step': 'Read browser_status/browser_snapshot to verify the destination and account.'}

    registry['browser_start'].fn = start
    ns['_AIB_START_NAVIGATION_INSTALLED'] = True
    ns['_AIB_START_NAVIGATION_CLEANUPS'] = cleanup_tasks
