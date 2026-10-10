"""Owner-only beta: independent browser capabilities for up to five MCP jobs.

This is NOT commercial multi-tenancy. The existing MCP bearer belongs to one
private owner. A capability returned to one chat permits actions only on that
chat's session. Never enable without explicit AI_BROWSER_SESSION_GUARD=multi
and AI_BROWSER_PARALLEL_OWNER_BETA=1; bootstrap and Steel validate the mode.

No session may bypass the capability through an old HTTP/mobile endpoint.
The iPhone can still use the existing ChatGPT MCP tools, not the old viewer.
No database-backed crash recovery is implied; fail closed on uncertain save.
"""
from __future__ import annotations

import asyncio
import contextvars
import hashlib
import hmac
import secrets
import time

from starlette.responses import JSONResponse
from starlette.routing import request_response

from capability_guard import (
    TOOLS, OWNED, START_TOOLS, WRAPPED_ASYNC,
    Lease, OwnershipError, preflight, scrub_result,
)

VERSION = "2026-10-10.multi-beta.1"
READ_ONLY_ROUTES = frozenset({"/health", "/health/context", "/health/steel"})


class MultiCapabilityGuard:
    def __init__(self, mcp, manager, *, capacity=1, clock=time.monotonic,
                 watchdog_enabled=True):
        if type(capacity) is not int or not 1 <= capacity <= 5:
            raise OwnershipError("PARALLEL_CAPACITY_INVALID")
        self.mcp, self.manager = mcp, manager
        self.capacity, self.clock = capacity, clock
        self.watchdog_enabled = watchdog_enabled
        self.admission = asyncio.Lock()
        self.leases: dict[str, Lease] = {}
        self.by_profile: dict[str, str] = {}
        self.session_locks: dict[str, asyncio.Lock] = {}
        self.pending_start = contextvars.ContextVar(
            "aib_multi_pending_start_profile", default=None)
        self.actor_session = contextvars.ContextVar(
            "aib_multi_current_session", default=None)
        self.internal_save = contextvars.ContextVar(
            "aib_multi_internal_autosave", default=None)
        self.watchdogs: set[asyncio.Task] = set()
        self.quarantined = False
        self.installed = False

    def sessions(self):
        return self.manager._sessions

    def _assess(self) -> None:
        actual = set(self.sessions())
        owned = set(self.leases)
        if actual - owned:
            self.quarantined = True
            raise OwnershipError("UNMANAGED_SESSION_QUARANTINED")
        for sid in owned - actual:
            self.leases[sid].recovery_required = True
            self.quarantined = True

    def authorize(self, handle, *, allow_expired_stop=False) -> Lease:
        try:
            if (not isinstance(handle, str) or not handle.startswith("aib_")
                    or len(handle) != 47):
                raise ValueError()
            digest = hashlib.sha256(handle.encode("ascii")).digest()
        except (UnicodeError, ValueError, TypeError):
            raise OwnershipError("SESSION_CAPABILITY_REQUIRED") from None
        found = None
        for lease in self.leases.values():
            if hmac.compare_digest(digest, lease.capability_digest):
                found = lease
                break
        if found is None:
            raise OwnershipError("SESSION_NOT_OWNED")
        if not allow_expired_stop and self.clock() - found.started_at > 850:
            raise OwnershipError("SESSION_CAPABILITY_EXPIRED")
        return found

    def _approved_manager(self, sid) -> bool:
        if self.actor_session.get() == sid or self.internal_save.get() == sid:
            return True
        profile = self.pending_start.get()
        session = self.sessions().get(sid)
        return (profile is not None and session is not None
                and getattr(session, "profile", None) == profile
                and sid not in self.leases)

    def wrap_manager(self):
        old_get = self.manager._session
        old_start, old_stop = self.manager.start, self.manager.stop
        old_status, old_flush = self.manager.status, self.manager.flush_profile

        def guarded_get(sid, *a, **kw):
            if not self._approved_manager(sid):
                raise OwnershipError("DIRECT_SESSION_ACCESS_BLOCKED")
            return old_get(sid, *a, **kw)

        async def guarded_start(*a, **kw):
            profile = kw.get("profile", a[0] if a else None)
            if not isinstance(profile, str) or self.pending_start.get() != profile:
                raise OwnershipError("DIRECT_SESSION_START_BLOCKED")
            return await old_start(*a, **kw)

        async def guarded_stop(sid, *a, **kw):
            if self.actor_session.get() != sid and not self._approved_manager(sid):
                raise OwnershipError("DIRECT_SESSION_STOP_BLOCKED")
            return await old_stop(sid, *a, **kw)

        async def guarded_status(sid, *a, **kw):
            if not self._approved_manager(sid):
                raise OwnershipError("DIRECT_SESSION_STATUS_BLOCKED")
            token = self.internal_save.set(sid)
            try:
                return await old_status(sid, *a, **kw)
            finally:
                self.internal_save.reset(token)

        async def guarded_flush(sid, *a, **kw):
            # Profile autosave jobs are internal, not authenticated MCP actions.
            # They can only flush an existing leased session or one just
            # started within this same exclusive admission context.
            if sid not in self.leases and not self._approved_manager(sid):
                raise OwnershipError("DIRECT_PROFILE_SAVE_BLOCKED")
            token = self.internal_save.set(sid)
            try:
                return await old_flush(sid, *a, **kw)
            finally:
                self.internal_save.reset(token)

        self.manager._session = guarded_get
        self.manager.start = guarded_start
        self.manager.stop = guarded_stop
        self.manager.status = guarded_status
        self.manager.flush_profile = guarded_flush

    def guard_routes(self):
        routes = getattr(self.mcp, "_custom_starlette_routes", None)
        if not isinstance(routes, list) or not routes:
            raise OwnershipError("PARALLEL_HTTP_ROUTES_UNAVAILABLE")
        for route in routes:
            if not isinstance(getattr(route, "path", None), str) or not callable(
                getattr(route, "endpoint", None)
            ):
                raise OwnershipError("PARALLEL_HTTP_ROUTES_INVALID")
        for route in routes:
            if (route.path in READ_ONLY_ROUTES
                    and set(route.methods or ()) <= {"GET", "HEAD"}):
                continue

            async def deny_http(_request):
                # A mobile viewer/setup route without its own per-task
                # capability must NEVER be able to access one of five
                # other users' browsers, even when temporarily idle.
                return JSONResponse(
                    {"error": "PARALLEL_HTTP_CAPABILITY_REQUIRED"},
                    status_code=403,
                    headers={"cache-control": "no-store"},
                )

            route.endpoint = deny_http
            route.app = request_response(deny_http)

    async def start(self, fn, args):
        profile = args.get("profile")
        if not isinstance(profile, str) or not 1 <= len(profile) <= 64:
            raise OwnershipError("PARALLEL_PROFILE_REQUIRED")
        async with self.admission:
            self._assess()
            if self.quarantined:
                raise OwnershipError("PARALLEL_PROVIDER_RECONCILIATION_REQUIRED")
            if profile in self.by_profile:
                raise OwnershipError("PARALLEL_PROFILE_BUSY")
            if len(self.leases) >= self.capacity:
                raise OwnershipError("PARALLEL_CAPACITY_FULL")
            if self.sessions():
                for session in self.sessions().values():
                    if getattr(session, "profile", None) == profile:
                        self.quarantined = True
                        raise OwnershipError("PARALLEL_PROFILE_UNMANAGED")
            prior = set(self.sessions())
            pending = self.pending_start.set(profile)
            try:
                result = await fn(**args)
            except BaseException:
                if set(self.sessions()) - prior:
                    self.quarantined = True
                raise
            finally:
                self.pending_start.reset(pending)
            sid = result.get("session_id") if isinstance(result, dict) else None
            if (not isinstance(sid, str) or not 1 <= len(sid) <= 128
                    or set(self.sessions()) - prior != {sid}
                    or getattr(self.sessions()[sid], "profile", None) != profile):
                self.quarantined = True
                raise OwnershipError("PARALLEL_START_NOT_VERIFIED")
            handle = "aib_" + secrets.token_urlsafe(32)
            lease = Lease(
                internal_session_id=sid,
                capability_digest=hashlib.sha256(handle.encode("ascii")).digest(),
                profile=profile,
                started_at=self.clock(),
            )
            self.leases[sid] = lease
            self.by_profile[profile] = sid
            self.session_locks[sid] = asyncio.Lock()
            if self.watchdog_enabled:
                task = asyncio.create_task(self.watchdog(lease))
                self.watchdogs.add(task)
                task.add_done_callback(self.watchdogs.discard)
            return scrub_result(result, sid, handle)

    def _complete(self, lease):
        sid = lease.internal_session_id
        self.leases.pop(sid, None)
        self.session_locks.pop(sid, None)
        if self.by_profile.get(lease.profile) == sid:
            self.by_profile.pop(lease.profile, None)

    async def action(self, name, fn, args):
        handle = args.get("session_id")
        lease = self.authorize(
            handle, allow_expired_stop=(name in {"browser_stop", "profile_flush"}))
        sid = lease.internal_session_id
        lock = self.session_locks.get(sid)
        if lock is None:
            raise OwnershipError("SESSION_RECOVERY_REQUIRED")
        async with lock:
            if self.authorize(
                handle, allow_expired_stop=(name in {"browser_stop", "profile_flush"})
            ) is not lease:
                raise OwnershipError("SESSION_CHANGED")
            if lease.recovery_required and name not in {
                "browser_stop", "profile_flush"
            }:
                raise OwnershipError("SESSION_RECOVERY_REQUIRED")
            if sid not in self.sessions():
                lease.recovery_required = True
                self.quarantined = True
                raise OwnershipError("SESSION_DISAPPEARED")
            actor = self.actor_session.set(sid)
            try:
                result = await fn(**{**args, "session_id": sid})
                if name == "browser_stop":
                    if (isinstance(result, dict)
                            and result.get("profile_saved") is True
                            and result.get("full_profile_saved") is True
                            and sid not in self.sessions()):
                        self._complete(lease)
                    else:
                        lease.recovery_required = True
                        self.quarantined = True
                elif sid not in self.sessions():
                    lease.recovery_required = True
                    self.quarantined = True
                    raise OwnershipError("SESSION_DISAPPEARED")
                return scrub_result(result, sid, handle)
            except BaseException:
                if name == "browser_stop":
                    lease.recovery_required = True
                    self.quarantined = True
                raise
            finally:
                self.actor_session.reset(actor)

    async def watchdog(self, lease):
        try:
            await asyncio.sleep(780)
            sid = lease.internal_session_id
            lock = self.session_locks.get(sid)
            if lock is None:
                return
            async with lock:
                if self.leases.get(sid) is not lease:
                    return
                if sid not in self.sessions():
                    lease.recovery_required = True
                    self.quarantined = True
                    return
                actor = self.actor_session.set(sid)
                try:
                    result = await self.manager.stop(sid)
                    if (isinstance(result, dict)
                            and result.get("profile_saved") is True
                            and result.get("full_profile_saved") is True
                            and sid not in self.sessions()):
                        self._complete(lease)
                    else:
                        lease.recovery_required = True
                        self.quarantined = True
                except BaseException:
                    lease.recovery_required = True
                    self.quarantined = True
                    raise
                finally:
                    self.actor_session.reset(actor)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Do not emit raw user URLs, profile state or provider exceptions.
            pass

    def safe_sessions(self):
        # Directly use the manager metadata, not page.title() or page
        # screenshots. A closed Chromium tab must not break all chats.
        self._assess()
        items = []
        for sid, session in self.sessions().items():
            lease = self.leases.get(sid)
            if lease is None:
                raise OwnershipError("UNMANAGED_SESSION_QUARANTINED")
            items.append({
                "session_id": "[redacted]",
                "profile": lease.profile,
                "mode": getattr(session, "mode", "unknown"),
                "state": "recovery_required" if lease.recovery_required else "active",
            })
        return {"result": items, "capacity": self.capacity,
                "active": len(items), "available": max(0, self.capacity-len(self.leases)),
                "quarantined": self.quarantined}

    def install(self):
        if self.installed:
            raise OwnershipError("PARALLEL_GUARD_ALREADY_INSTALLED")
        # Validate all 51 MCP endpoints and all custom routes before any
        # mutation. Never enable under an altered, unreviewed SDK contract.
        preflight({"mcp": self.mcp, "manager": self.manager})
        if self.sessions():
            raise OwnershipError("PARALLEL_INSTALL_REQUIRES_IDLE")
        if self.capacity != getattr(self.manager, "max_sessions", None):
            raise OwnershipError("PARALLEL_MANAGER_CAPACITY_MISMATCH")
        if not isinstance(self.mcp._tool_manager._tools, dict):
            raise OwnershipError("PARALLEL_TOOL_CATALOG_INVALID")
        self.guard_routes()
        self.wrap_manager()
        for name, tool in self.mcp._tool_manager._tools.items():
            fn = tool.fn
            if name == "browser_start":
                async def start_tool(*a, _fn=fn, **kw):
                    if a:
                        raise OwnershipError("POSITIONAL_ARGS_UNSUPPORTED")
                    return await self.start(_fn, kw)
                tool.fn = start_tool
            elif name in OWNED:
                async def own_tool(*a, _fn=fn, _name=name, **kw):
                    if a:
                        raise OwnershipError("POSITIONAL_ARGS_UNSUPPORTED")
                    return await self.action(_name, _fn, kw)
                tool.fn = own_tool
            elif name == "browser_sessions":
                if tool.is_async:
                    async def list_sessions(*a, **kw):
                        if a or kw:
                            raise OwnershipError("POSITIONAL_ARGS_UNSUPPORTED")
                        return self.safe_sessions()
                else:
                    def list_sessions(*a, **kw):
                        if a or kw:
                            raise OwnershipError("POSITIONAL_ARGS_UNSUPPORTED")
                        return self.safe_sessions()
                tool.fn = list_sessions
            elif name == "browser_recent_audit":
                async def read_audit(*a, _fn=fn, **kw):
                    if a:
                        raise OwnershipError("POSITIONAL_ARGS_UNSUPPORTED")
                    handle = kw.get("session_id")
                    if not handle:
                        return {"result": [], "require_owned_session": True}
                    lease = self.authorize(handle)
                    return await self.action(
                        "browser_recent_audit", _fn, {**kw, "session_id": handle})
                tool.fn = read_audit
            elif name == "profile_list":
                pass
            else:
                # Direct login setup/viewer, profile deletion and generic
                # unowned staged-file operations are not authorized in
                # owner-parallel beta. Real mobile viewer needs BFF scope.
                async def deny(*a, **kw):
                    raise OwnershipError("PARALLEL_UNSCOPED_TOOL_DISABLED")
                tool.fn = deny
        self.installed = True
        return len(self.mcp._tool_manager._tools)


def install(ns):
    import os
    if ns.get("_AIB_OWNER_PARALLEL_GUARD") is not None:
        return
    if os.environ.get("AI_BROWSER_PARALLEL_OWNER_BETA") != "1":
        raise OwnershipError("PARALLEL_BETA_FLAG_REQUIRED")
    manager = ns.get("manager")
    if manager is None:
        raise OwnershipError("PARALLEL_MANAGER_MISSING")
    capacity = getattr(manager, "max_sessions", None)
    guard = MultiCapabilityGuard(ns["mcp"], manager, capacity=capacity)
    count = guard.install()
    ns["_AIB_OWNER_PARALLEL_GUARD"] = guard
    print("AI_BROWSER_OWNER_PARALLEL_GUARD_READY "
          + VERSION + " tools=" + str(count), flush=True)
