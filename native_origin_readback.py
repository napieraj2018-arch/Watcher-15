"""Opt-in SteelSelfTest origin observation before existing profile recovery.

Persistent Chromium storage_state may omit an origin until this connection
has visited it. Missing from that snapshot does NOT mean absent on disk.
Only a disposable canary origin is visited, with all its traffic intercepted.
No customer origins, passwords, provider IDs or browser data are exported.
"""
from __future__ import annotations

import asyncio
import functools
import inspect
import os

from steel_context_fix import ReliabilityError, synthetic_fixture_page_readback

FLAG = 'AI_BROWSER_SELFTEST_ORIGIN_READBACK'
URL = 'https://ai-browser-vault.floot.app/browser-check'
ERROR = 'SYNTHETIC_NATIVE_ORIGIN_READBACK_REQUIRED'


async def observe_native_origin(context):
    """Register and read the canary origin without network or storage writes.

    Close only the page created here. Do not close the context, release Steel,
    save a profile, touch other pages, or infer authentication from the result.
    """
    page = None
    try:
        async with asyncio.timeout(10):
            page = await context.new_page()

            async def fixture_only(route):
                req = route.request
                if req.url == URL and req.resource_type == 'document' and req.method == 'GET':
                    await route.fulfill(
                        status=200, content_type='text/html',
                        headers={'cache-control': 'no-store',
                                 'content-security-policy': "default-src 'none'"},
                        body='<!doctype html><title>Native storage canary</title>')
                else:
                    await route.abort()

            await page.route('**/*', fixture_only)
            await page.goto(URL, wait_until='domcontentloaded', timeout=5000)
            observed = await synthetic_fixture_page_readback(page)
            if observed.get('status') != 'observed':
                raise ReliabilityError(ERROR)
            return observed
    except asyncio.CancelledError:
        raise
    except Exception:
        raise ReliabilityError(ERROR) from None
    finally:
        if page is not None:
            try:
                await asyncio.wait_for(page.close(), timeout=3)
            except asyncio.CancelledError:
                raise
            except Exception:
                # An unclosed diagnostic page is not permission to continue
                # restoring/saving the profile. Keep a fixed redacted failure.
                raise ReliabilityError(ERROR) from None


def wrap_native_context(original):
    """Keep all existing context/ownership/restore checks; add a canary probe."""
    if getattr(original, '_aib_canary_native_readback', False):
        return original
    if not inspect.iscoroutinefunction(original):
        raise ReliabilityError('NATIVE_READBACK_CONTEXT_CONTRACT_INVALID')
    params = list(inspect.signature(original).parameters.values())
    if (len(params) != 2 or params[0].name != 'remote'
            or params[1].kind is not inspect.Parameter.VAR_KEYWORD):
        raise ReliabilityError('NATIVE_READBACK_CONTEXT_CONTRACT_INVALID')

    @functools.wraps(original)
    async def guarded(remote, **options):
        binding = getattr(remote.engine, '_native_bindings', {}).get(remote.remote_id, {})
        opted_in = (os.environ.get(FLAG) == '1'
                    and binding.get('profile') == 'SteelSelfTest'
                    and binding.get('hydrated') is True)
        if opted_in:
            # Respect original admission validation before opening any page.
            # Unsupported/claimed/missing contexts remain the original error.
            allowed = {'storage_state', 'viewport', 'accept_downloads', 'extra_http_headers'}
            contexts = remote.browser.contexts
            if (not getattr(remote, '_native_context_claimed', False)
                    and not set(options) - allowed and contexts
                    and hasattr(contexts[0], 'set_storage_state')
                    and isinstance(options.get('storage_state'), dict)):
                # No unreviewed portable-priority combination: valid native
                # data must not be intentionally replaced during this canary.
                policy = os.environ.get('AI_BROWSER_PORTABLE_PRIORITY_PROFILES', '')
                if policy:
                    raise ReliabilityError('NATIVE_READBACK_POLICY_CONFLICT')
                observed = await observe_native_origin(contexts[0])
                binding['synthetic_native_origin_readback'] = observed
        return await original(remote, **options)

    guarded._aib_canary_native_readback = True
    return guarded


def install(ns):
    """Wire after existing Steel context fix, without altering guards/tools."""
    if os.environ.get('AI_BROWSER_ENGINE', '').lower() != 'steel':
        return
    import steel_context_fix
    import steel_runtime
    current = steel_runtime.RemoteBrowser.new_context
    if getattr(current, '_aib_canary_native_readback', False):
        return
    if current is not steel_context_fix.native_context:
        raise ReliabilityError('NATIVE_READBACK_CONTEXT_CONTRACT_INVALID')
    wrapped = wrap_native_context(current)
    steel_runtime.RemoteBrowser.new_context = wrapped
    print('AI_BROWSER_NATIVE_ORIGIN_READBACK_READY 2026-10-10.canary.1', flush=True)
