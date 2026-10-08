"""Experimental per-task capability guard for AI Browser MCP 2.3.

Not installed in production. The session_id presented to MCP clients becomes a
new opaque capability, not the internal Chromium session ID. The same guard
protects direct manager calls and custom mobile HTTP routes while a task owns
the browser. Unknown catalog versions fail closed before installation.
"""
from __future__ import annotations

import asyncio
import contextvars
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from starlette.responses import JSONResponse
from starlette.routing import request_response

try:
    from mcp.server.mcpserver.exceptions import ToolError as _ToolError
except ImportError:  # Offline unit tests may omit the MCP SDK.
    _ToolError = RuntimeError

class OwnershipError(_ToolError):
    """Fixed error code; never reveal the candidate capability or raw session ID."""

TOOLS = frozenset("""profile_list profile_start_setup profile_cancel_setup
browser_start profile_login_window browser_sessions browser_status
browser_set_mode browser_stop browser_navigate browser_snapshot
browser_set_checked browser_scroll browser_hover browser_scroll_into_view
browser_screenshot browser_back browser_forward browser_reload
browser_wait_for_text browser_wait_for_url browser_links browser_wait
browser_click browser_fill browser_press browser_select browser_tabs
browser_new_tab browser_switch_tab browser_close_tab browser_downloads
browser_read_download_text browser_upload_file profile_flush
browser_network_log browser_console_log browser_clear_diagnostics
browser_page_metadata browser_set_viewport browser_frames
browser_frame_snapshot browser_set_next_dialog_action browser_dialogs
browser_staged_files browser_upload_staged_file browser_read_download_pdf
browser_recent_audit profile_delete browser_auth_status browser_login_saved""".split())
START_TOOLS = {"browser_start", "profile_login_window"}
OWNED = {s for s in TOOLS if s.startswith("browser_")} - {
    "browser_start", "browser_sessions", "browser_staged_files", "browser_recent_audit"
}
OWNED |= {"profile_flush", "browser_auth_status", "browser_login_saved"}
WRAPPED_ASYNC = OWNED | START_TOOLS | {
    "profile_start_setup", "profile_cancel_setup", "profile_delete"
}
ALLOWED_PUBLIC_GET = {"/health", "/health/context"}

@dataclass
class Lease:
    internal_session_id: str
    capability_digest: bytes
    profile: str
    started_at: float
    recovery_required: bool = False

def public_url(v):
    if not isinstance(v, str):
        return v
    try:
        u = urlsplit(v)
        if u.scheme not in {"https", "http"}:
            return "[redacted]"
        return urlunsplit((u.scheme, u.netloc, u.path, "", ""))
    except (TypeError, ValueError):
        return "[redacted]"

def scrub(v, internal_id="", handle="", public=False):
    """No session IDs in public session/audit listings; no query/fragment URLs."""
    if isinstance(v, dict):
        return {
            k: ("[redacted]" if public or val != internal_id else handle)
            if k == "session_id" else
            public_url(val) if k in {"url", "href", "page_url", "start_url", "target_url"} else
            scrub(val, internal_id, handle, public)
            for k, val in v.items()
        }
    if isinstance(v, list):
        return [scrub(x, internal_id, handle, public) for x in v]
    if isinstance(v, str) and internal_id and v == internal_id:
        return "[redacted]" if public else handle
    return v

def scrub_result(v, internal_id="", handle="", public=False):
    if isinstance(v, str):
        try:
            parsed = json.loads(v)
        except ValueError:
            raise OwnershipError("SESSION_RESULT_UNSUPPORTED") from None
        return json.dumps(scrub(parsed, internal_id, handle, public),
                          ensure_ascii=False)
    if not isinstance(v, (dict, list)):
        raise OwnershipError("SESSION_RESULT_UNSUPPORTED")
    return scrub(v, internal_id, handle, public)

class CapabilityGuard:
    def __init__(self, mcp, manager, *, clock=time.monotonic,
                 watchdog_enabled=True):
        self.mcp = mcp
        self.manager = manager
        self.clock = clock
        self.watchdog_enabled = watchdog_enabled
        self.lock = asyncio.Lock()
        self.lease = None
        self.actor_session = contextvars.ContextVar(
            "aib_authorized_internal_session", default=None)
        self.internal_save = contextvars.ContextVar(
            "aib_background_save", default=None)
        self.watchdogs = set()
        self.installed = False

    def sessions(self):
        return getattr(self.manager, "_sessions", {})

    def mark_missing(self):
        if self.lease and self.lease.internal_session_id not in self.sessions():
            self.lease.recovery_required = True

    def authorize(self, handle, *, allow_expired_stop=False):
        current = self.lease
        if current is None:
            raise OwnershipError("SESSION_CAPABILITY_REQUIRED")
        try:
            valid = (isinstance(handle, str)
                     and handle.startswith("aib_")
                     and len(handle) == 47
                     and hmac.compare_digest(
                         hashlib.sha256(handle.encode("ascii")).digest(),
                         current.capability_digest))
        except (UnicodeError, TypeError, ValueError):
            valid = False
        if not valid:
            raise OwnershipError("SESSION_NOT_OWNED")
        if not allow_expired_stop and self.clock() - current.started_at > 900:
            raise OwnershipError("SESSION_CAPABILITY_EXPIRED")
        return current

    def check_direct_manager_access(self, sid):
        if (self.lease is not None
            and self.lease.internal_session_id == sid
            and self.actor_session.get() != sid
            and self.internal_save.get() != sid):
            raise OwnershipError("DIRECT_SESSION_ACCESS_BLOCKED")

    def wrap_manager(self):
        old_get = self.manager._session
        old_start, old_stop = self.manager.start, self.manager.stop
        old_flush, old_status = self.manager.flush_profile, self.manager.status

        def get(sid, *args, **kwargs):
            self.check_direct_manager_access(sid)
            return old_get(sid, *args, **kwargs)

        async def start(*args, **kwargs):
            if self.lease:
                raise OwnershipError("SESSION_OWNED_BY_OTHER_TASK")
            return await old_start(*args, **kwargs)

        async def stop(sid, *args, **kwargs):
            self.check_direct_manager_access(sid)
            return await old_stop(sid, *args, **kwargs)

        async def flush(sid, *args, **kwargs):
            token = self.internal_save.set(sid)
            try:
                return await old_flush(sid, *args, **kwargs)
            finally:
                self.internal_save.reset(token)

        async def status(sid, *args, **kwargs):
            token = self.internal_save.set(sid)
            try:
                return await old_status(sid, *args, **kwargs)
            finally:
                self.internal_save.reset(token)

        self.manager._session = get
        self.manager.start = start
        self.manager.stop = stop
        self.manager.flush_profile = flush
        self.manager.status = status

    async def watchdog(self, current):
        # Legacy runtime enforces ~870 sec, so save well before it closes.
        await asyncio.sleep(800)
        async with self.lock:
            if self.lease is not current:
                return
            if current.internal_session_id not in self.sessions():
                current.recovery_required = True
                return
            token = self.actor_session.set(current.internal_session_id)
            try:
                result = await self.manager.stop(current.internal_session_id)
                if (isinstance(result, dict)
                    and result.get("profile_saved") is True
                    and result.get("full_profile_saved") is True):
                    self.lease = None
                else:
                    current.recovery_required = True
            except Exception:
                current.recovery_required = True
            finally:
                self.actor_session.reset(token)

    def start_watchdog(self, current):
        if not self.watchdog_enabled:
            return
        task = asyncio.create_task(self.watchdog(current))
        self.watchdogs.add(task)
        task.add_done_callback(self.watchdogs.discard)

    async def start_session(self, fn, args):
        async with self.lock:
            self.mark_missing()
            if self.lease or self.sessions():
                raise OwnershipError("BROWSER_BUSY_OTHER_TASK")
            result = await fn(**args)
            if not isinstance(result, dict) or not isinstance(
                result.get("session_id"), str):
                raise OwnershipError("SESSION_START_NOT_VERIFIED")
            sid = result["session_id"]
            if sid not in self.sessions():
                raise OwnershipError("SESSION_START_NOT_VERIFIED")
            handle = "aib_" + secrets.token_urlsafe(32)
            current = Lease(sid, hashlib.sha256(handle.encode()).digest(),
                            result.get("profile", args.get("profile", "")),
                            self.clock())
            self.lease = current
            self.start_watchdog(current)
            return scrub(result, sid, handle)

    async def owner_action(self, name, fn, args):
        handle = args.get("session_id")
        async with self.lock:
            current = self.authorize(
                handle, allow_expired_stop=(name == "browser_stop"))
            if (current.recovery_required
                and name not in {"browser_stop", "profile_flush"}):
                raise OwnershipError("SESSION_RECOVERY_REQUIRED")
            sid = current.internal_session_id
            if sid not in self.sessions():
                current.recovery_required = True
                raise OwnershipError("SESSION_DISAPPEARED")
            token = self.actor_session.set(sid)
            try:
                result = await fn(**{**args, "session_id": sid})
                if name == "browser_stop":
                    if (isinstance(result, dict)
                        and result.get("profile_saved") is True
                        and result.get("full_profile_saved") is True):
                        self.lease = None
                    else:
                        current.recovery_required = True
                elif sid not in self.sessions():
                    current.recovery_required = True
                    raise OwnershipError("SESSION_DISAPPEARED")
                return scrub_result(result, sid, handle)
            finally:
                self.actor_session.reset(token)

    async def standalone(self, fn, args, name):
        async with self.lock:
            self.mark_missing()
            if self.lease or self.sessions():
                raise OwnershipError("BROWSER_BUSY_OTHER_TASK")
            return await fn(**args)

    def guard_http_routes(self):
        routes = getattr(self.mcp, "_custom_starlette_routes", None)
        if not isinstance(routes, list) or not routes:
            raise OwnershipError("HTTP_ROUTE_CATALOG_UNAVAILABLE")
        for route in routes:
            path, endpoint = getattr(route, "path", None), getattr(route, "endpoint", None)
            if not isinstance(path, str) or not callable(endpoint):
                raise OwnershipError("HTTP_ROUTE_NOT_SUPPORTED")
        for route in routes:
            path, endpoint = route.path, route.endpoint
            if path in ALLOWED_PUBLIC_GET and set(route.methods or []) <= {"GET", "HEAD"}:
                continue
            async def gate(request, _original=endpoint):
                if self.lease is not None:
                    return JSONResponse(
                        {"error": "SESSION_OWNED_BY_OTHER_TASK"},
                        status_code=409,
                        headers={"cache-control": "no-store"})
                return await _original(request)
            route.endpoint = gate
            route.app = request_response(gate)

    def install(self):
        if self.installed:
            raise OwnershipError("SESSION_GUARD_ALREADY_INSTALLED")
        registry = self.mcp._tool_manager._tools
        present = set(registry)
        # Refuse unreviewed tool names, even if they do not start browser_.
        if present != TOOLS:
            raise OwnershipError("SESSION_TOOL_CATALOG_MISMATCH")
        if any(not registry[n].is_async for n in WRAPPED_ASYNC):
            raise OwnershipError("SESSION_ASYNC_TOOL_CONTRACT_MISMATCH")
        self.guard_http_routes()
        self.wrap_manager()
        for name in present:
            tool = registry[name]
            fn = tool.fn
            if name in START_TOOLS:
                async def run(*a, _fn=fn, **kw):
                    if a: raise OwnershipError("POSITIONAL_ARGS_UNSUPPORTED")
                    return await self.start_session(_fn, kw)
                tool.fn = run
            elif name in OWNED:
                async def run(*a, _fn=fn, _name=name, **kw):
                    if a: raise OwnershipError("POSITIONAL_ARGS_UNSUPPORTED")
                    return await self.owner_action(_name, _fn, kw)
                tool.fn = run
            elif name in {"profile_start_setup", "profile_delete"}:
                async def run(*a, _fn=fn, _name=name, **kw):
                    if a: raise OwnershipError("POSITIONAL_ARGS_UNSUPPORTED")
                    return await self.standalone(_fn, kw, _name)
                tool.fn = run
            elif name == "profile_cancel_setup":
                async def run(*a, _fn=fn, **kw):
                    if a: raise OwnershipError("POSITIONAL_ARGS_UNSUPPORTED")
                    async with self.lock:
                        if self.lease:
                            raise OwnershipError("BROWSER_BUSY_OTHER_TASK")
                        return await _fn(**kw)
                tool.fn = run
            elif name in {"browser_sessions", "browser_recent_audit"}:
                if tool.is_async:
                    async def run(*a, _fn=fn, _name=name, **kw):
                        if a: raise OwnershipError("POSITIONAL_ARGS_UNSUPPORTED")
                        if _name == "browser_recent_audit" and kw.get("session_id"):
                            kw["session_id"] = self.authorize(
                                kw["session_id"]).internal_session_id
                        return scrub_result(await _fn(**kw), public=True)
                else:
                    def run(*a, _fn=fn, _name=name, **kw):
                        if a: raise OwnershipError("POSITIONAL_ARGS_UNSUPPORTED")
                        if _name == "browser_recent_audit" and kw.get("session_id"):
                            kw["session_id"] = self.authorize(
                                kw["session_id"]).internal_session_id
                        return scrub_result(_fn(**kw), public=True)
                tool.fn = run
            elif name == "browser_staged_files":
                if tool.is_async:
                    async def run(*a, **kw):
                        raise OwnershipError("STAGED_FILES_REQUIRE_OWNED_API")
                else:
                    def run(*a, **kw):
                        raise OwnershipError("STAGED_FILES_REQUIRE_OWNED_API")
                tool.fn = run
            # profile_list is read-only and has no session IDs.
        self.installed = True
        return len(present)

def preflight(ns):
    """Read-only bootstrap contract check; does not patch manager, routes or tools."""
    if "mcp" not in ns or "manager" not in ns:
        raise OwnershipError("SESSION_GUARD_BOOTSTRAP_INCOMPLETE")
    mcp, manager = ns["mcp"], ns["manager"]
    registry = getattr(getattr(mcp, "_tool_manager", None), "_tools", None)
    if not isinstance(registry, dict) or set(registry) != TOOLS:
        raise OwnershipError("SESSION_TOOL_CATALOG_MISMATCH")
    if any(not registry[n].is_async for n in WRAPPED_ASYNC):
        raise OwnershipError("SESSION_ASYNC_TOOL_CONTRACT_MISMATCH")
    for name in ("_session", "start", "stop", "flush_profile", "status"):
        if not callable(getattr(manager, name, None)):
            raise OwnershipError("SESSION_MANAGER_CONTRACT_MISMATCH")
    if not isinstance(getattr(manager, "_sessions", None), dict):
        raise OwnershipError("SESSION_MANAGER_CONTRACT_MISMATCH")
    routes = getattr(mcp, "_custom_starlette_routes", None)
    if not isinstance(routes, list) or not routes:
        raise OwnershipError("HTTP_ROUTE_CATALOG_UNAVAILABLE")
    for route in routes:
        if not isinstance(getattr(route, "path", None), str) or not callable(getattr(route, "endpoint", None)):
            raise OwnershipError("HTTP_ROUTE_NOT_SUPPORTED")
    result = {"tools":len(registry), "mobile_and_support_routes":len(routes),
              "mode":"read_only_preflight", "changed":False}
    ns["_CAPABILITY_PREFLIGHT_RESULT"] = result
    print("AI_BROWSER_SESSION_GUARD_PREFLIGHT_OK tools="+str(result["tools"])+
          " routes="+str(result["mobile_and_support_routes"]),flush=True)
    return result


def install(ns):
    if ns.get("_CAPABILITY_GUARD_INSTALLED"):
        return
    if "mcp" not in ns or "manager" not in ns:
        raise OwnershipError("SESSION_GUARD_BOOTSTRAP_INCOMPLETE")
    guard = CapabilityGuard(ns["mcp"], ns["manager"])
    count = guard.install()
    ns["_CAPABILITY_GUARD_INSTALLED"] = guard
    print("AI_BROWSER_CAPABILITY_GUARD_READY " + str(count), flush=True)
