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
import math
import secrets
import time

from starlette.responses import JSONResponse
from starlette.routing import request_response

from capability_guard import (
    TOOLS, OWNED, START_TOOLS, WRAPPED_ASYNC,
    Lease, OwnershipError, preflight, scrub_result,
)
from owner_mobile_handoff import OwnerMobileHandoff

VERSION = "2026-10-10.multi-beta.1"
READ_ONLY_ROUTES = frozenset({"/health", "/health/context", "/health/steel"})
AUTO_SAVE_CLOSE_SECONDS = 780
CAPABILITY_LIFETIME_SECONDS = 850
UPSTREAM_SAVE_MARGIN_SECONDS = 90
START_CLEANUP_TIMEOUT_SECONDS = 90


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
        self.close_deadlines: dict[str, float] = {}
        # A stop may remove the manager record before profile READY/registry
        # acknowledgement returns. Keep its exact record until that receipt;
        # an in-flight close is neither a lost session nor a free slot.
        self.closing: dict[str, object] = {}
        # ContextVars authorize the start task, but an inventory task cannot
        # see them. This admission-scoped phase explains at most one new
        # manager record until the start result is checked and leased.
        self.starting: tuple[str, frozenset[str]] | None = None
        self.start_cleanups: dict[str, object] = {}
        self.cleanup_tasks: set[asyncio.Task] = set()
        self.pending_start = contextvars.ContextVar(
            "aib_multi_pending_start_profile", default=None)
        self.actor_session = contextvars.ContextVar(
            "aib_multi_current_session", default=None)
        self.internal_save = contextvars.ContextVar(
            "aib_multi_internal_autosave", default=None)
        self.watchdogs: set[asyncio.Task] = set()
        self.quarantined = False
        self.installed = False
        self.mobile_handoff = OwnerMobileHandoff(self)

    def sessions(self):
        return self.manager._sessions

    def _starting_session_ids(self):
        if self.starting is None:
            return set()
        profile, before = self.starting
        candidates = set(self.sessions()) - before - set(self.leases)
        if (len(candidates) == 1
                and getattr(self.sessions()[next(iter(candidates))],
                            "profile", None) == profile):
            return candidates
        return set()

    def _assess(self) -> None:
        actual = set(self.sessions())
        owned = set(self.leases)
        cleaning = {sid for sid, record in self.start_cleanups.items()
                    if self.sessions().get(sid) is record}
        if actual - owned - self._starting_session_ids() - cleaning:
            self.quarantined = True
            raise OwnershipError("UNMANAGED_SESSION_QUARANTINED")
        for sid in owned - actual:
            if sid in self.closing:
                continue
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
        if (not allow_expired_stop
                and self.clock() - found.started_at > CAPABILITY_LIFETIME_SECONDS):
            raise OwnershipError("SESSION_CAPABILITY_EXPIRED")
        return found

    def with_lifecycle(self, output, lease):
        """Describe this task's actual deadline, not just Steel's later timeout.

        No extension, renewal, or durable recovery is implied. The owner guard
        keeps its 90-second save margin before the upstream close, including
        time already spent starting the browser. Reading never renews it.
        """
        if not isinstance(output, dict):
            return output
        age = max(0, self.clock() - lease.started_at)
        deadline = self.close_deadlines.get(
            lease.internal_session_id, lease.started_at + AUTO_SAVE_CLOSE_SECONDS)
        auto_close = max(0, int(deadline - self.clock()))
        upstream = output.get("remaining_seconds")
        remaining = auto_close
        if (type(upstream) in (int, float) and math.isfinite(upstream)):
            remaining = min(auto_close, max(0, int(upstream)))
        return {
            **output,
            "remaining_seconds": remaining,
            "auto_save_close_in_seconds": auto_close,
            "capability_expires_in_seconds": max(
                0, int(CAPABILITY_LIFETIME_SECONDS - age)),
            "durable_resume_supported": False,
        }

    @staticmethod
    def _start_budget(result):
        upstream = result.get("remaining_seconds")
        if type(upstream) in (int, float) and math.isfinite(upstream):
            return max(0, min(AUTO_SAVE_CLOSE_SECONDS,
                              upstream - UPSTREAM_SAVE_MARGIN_SECONDS))
        return AUTO_SAVE_CLOSE_SECONDS

    async def _cleanup_started_record(self, profile, prior):
        """Save-close only the unambiguous new record from this admission.

        The caller still holds admission. Repeated request cancellations may
        interrupt the wait, but cannot cancel or lose the tracked cleanup.
        An uncertain timeout stays quarantined even if cleanup later ends.
        """
        created = set(self.sessions()) - prior
        if not created:
            return
        if len(created) != 1:
            self.quarantined = True
            return
        sid = next(iter(created))
        record = self.sessions()[sid]
        if sid in self.leases or getattr(record, "profile", None) != profile:
            self.quarantined = True
            return
        self.start_cleanups[sid] = record
        self.closing[sid] = record

        async def saved_close():
            actor = self.actor_session.set(sid)
            try:
                # The task starts at a later event-loop turn. Never close a
                # replacement object, a prior session, or an ambiguous delta.
                if (self.sessions().get(sid) is not record
                        or getattr(record, "profile", None) != profile
                        or set(self.sessions()) - prior != {sid}
                        or sid in self.leases):
                    self.quarantined = True
                    return False
                result = await self.manager.stop(sid)
                confirmed = (isinstance(result, dict)
                             and result.get("profile_saved") is True
                             and result.get("full_profile_saved") is True
                             and sid not in self.sessions())
                if not confirmed:
                    self.quarantined = True
                return confirmed
            except BaseException:
                self.quarantined = True
                raise
            finally:
                self.actor_session.reset(actor)
                if self.closing.get(sid) is record:
                    self.closing.pop(sid, None)
                if self.start_cleanups.get(sid) is record:
                    self.start_cleanups.pop(sid, None)

        task = asyncio.create_task(saved_close())
        self.cleanup_tasks.add(task)

        def consume(done):
            self.cleanup_tasks.discard(done)
            if not done.cancelled():
                done.exception()  # Also retrieve failures after a timed-out caller.

        task.add_done_callback(consume)
        deadline = asyncio.get_running_loop().time() + START_CLEANUP_TIMEOUT_SECONDS
        while not task.done():
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                self.quarantined = True
                task.cancel()
                return
            try:
                await asyncio.wait_for(asyncio.shield(task), remaining)
            except asyncio.CancelledError:
                # The original request can be cancelled more than once. The
                # exact record remains accounted for until cleanup finishes.
                continue
            except Exception:
                if task.done():
                    break
                self.quarantined = True
                task.cancel()
                return
        if task.cancelled():
            self.quarantined = True
        else:
            try:
                task.result()
            except Exception:
                self.quarantined = True

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
            self.starting = (profile, frozenset(prior))
            try:
                try:
                    result = await fn(**args)
                except BaseException:
                    await self._cleanup_started_record(profile, prior)
                    raise
                sid = result.get("session_id") if isinstance(result, dict) else None
                if (not isinstance(sid, str) or not 1 <= len(sid) <= 128
                        or set(self.sessions()) - prior != {sid}
                        or getattr(self.sessions()[sid], "profile", None) != profile):
                    self.quarantined = True
                    raise OwnershipError("PARALLEL_START_NOT_VERIFIED")
                budget = self._start_budget(result)
                if budget <= 0:
                    await self._cleanup_started_record(profile, prior)
                    raise OwnershipError("START_SESSION_BUDGET_EXHAUSTED")
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
                self.close_deadlines[sid] = lease.started_at + budget
                if self.watchdog_enabled:
                    task = asyncio.create_task(self.watchdog(lease))
                    self.watchdogs.add(task)
                    task.add_done_callback(self.watchdogs.discard)
                return scrub_result(self.with_lifecycle(result, lease), sid, handle)
            finally:
                self.starting = None
                self.pending_start.reset(pending)

    def _complete(self, lease):
        sid = lease.internal_session_id
        self.leases.pop(sid, None)
        self.close_deadlines.pop(sid, None)
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
            if name == "browser_stop":
                self.closing[sid] = self.sessions()[sid]
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
                if name == "browser_status":
                    result = self.with_lifecycle(result, lease)
                return scrub_result(result, sid, handle)
            except BaseException:
                if name == "browser_stop":
                    lease.recovery_required = True
                    self.quarantined = True
                raise
            finally:
                if name == "browser_stop":
                    self.closing.pop(sid, None)
                self.actor_session.reset(actor)

    async def watchdog(self, lease):
        try:
            deadline = self.close_deadlines.get(
                lease.internal_session_id, lease.started_at + AUTO_SAVE_CLOSE_SECONDS)
            await asyncio.sleep(max(0, deadline - self.clock()))
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
                self.closing[sid] = self.sessions()[sid]
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
                    self.closing.pop(sid, None)
                    self.actor_session.reset(actor)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Do not emit raw user URLs, profile state or provider exceptions.
            pass

    def safe_sessions(self):
        # Directly use the manager metadata, not page.title() or page
        # screenshots. A closed Chromium tab must not break all chats.
        try:
            self._assess()
        except OwnershipError as exc:
            # An interrupted browser_start may leave a manager session with
            # no capability. Do not crash the read-only inventory: report the
            # existence of a quarantined session without its profile, mode,
            # URL, page title, internal handle or provider reference.
            if str(exc) != "UNMANAGED_SESSION_QUARANTINED":
                raise
        items = []
        starting_ids = self._starting_session_ids()
        for sid, session in self.sessions().items():
            lease = self.leases.get(sid)
            if lease is None:
                if self.start_cleanups.get(sid) is session:
                    items.append({
                        "session_id": "[redacted]",
                        "profile": getattr(session, "profile", "[redacted]"),
                        "mode": getattr(session, "mode", "unknown"),
                        "state": "recovery_required" if self.quarantined else "closing",
                    })
                    continue
                if sid in starting_ids:
                    items.append({
                        "session_id": "[redacted]",
                        "profile": self.starting[0],
                        "mode": getattr(session, "mode", "unknown"),
                        "state": "starting",
                    })
                    continue
                self.quarantined = True
                items.append({
                    "session_id": "[redacted]",
                    "profile": "[redacted]",
                    "mode": "unknown",
                    "state": "unmanaged_quarantined",
                })
                continue
            # Expired per-chat capabilities must never appear as healthy
            # active sessions. Do not auto-stop, renew or reveal the handle.
            state = ("recovery_required" if lease.recovery_required
                     else "closing" if sid in self.closing
                     else "capability_expired"
                     if self.clock() - lease.started_at > CAPABILITY_LIFETIME_SECONDS
                     else "active")
            item = {
                "session_id": "[redacted]",
                "profile": lease.profile,
                "mode": getattr(session, "mode", "unknown"),
                "state": state,
            }
            items.append(self.with_lifecycle(item, lease)
                         if state == "active" else item)
        if self.starting is not None and not starting_ids and not self.start_cleanups:
            # A provider request can be in flight before a local record exists.
            # Do not return an idle-looking [] during that admission window.
            items.append({
                "session_id": "[redacted]",
                "profile": self.starting[0],
                "mode": "unknown",
                "state": "starting",
            })
        for sid, record in self.start_cleanups.items():
            if sid not in self.sessions():
                items.append({
                    "session_id": "[redacted]",
                    "profile": getattr(record, "profile", "[redacted]"),
                    "mode": getattr(record, "mode", "unknown"),
                    "state": "recovery_required" if self.quarantined else "closing",
                })
        # A failed saved-stop may remove the manager record before returning
        # an unverified receipt. The lease deliberately remains quarantined;
        # hiding it would make [] look like permission to deploy/restart.
        # Never infer provider closure or release a slot from a missing record.
        for sid, lease in self.leases.items():
            if sid not in self.sessions():
                if sid in self.closing and not lease.recovery_required:
                    items.append({
                        "session_id": "[redacted]",
                        "profile": lease.profile,
                        "mode": getattr(self.closing[sid], "mode", "unknown"),
                        "state": "closing",
                    })
                    continue
                lease.recovery_required = True
                self.quarantined = True
                items.append({
                    "session_id": "[redacted]",
                    "profile": "[redacted]",
                    "mode": "unknown",
                    "state": "missing_session_quarantined",
                })
        # The provider engine can outlive both manager records and leases
        # after a cancelled start or an unconfirmed release. Its quarantine
        # is independent of this guard's flag. Never report [] for that
        # state, and never expose provider IDs or connection credentials.
        engine = getattr(self.manager, "_steel_engine", None)
        provider_unconfirmed = False
        if engine is not None:
            remote = getattr(engine, "remote", None)
            bound = {id(getattr(session, "browser", None))
                     for session in (*self.sessions().values(),
                                     *self.closing.values())}
            provider_unconfirmed = (
                bool(getattr(engine, "_quarantined", False))
                or not isinstance(remote, dict)
                or any(id(browser) not in bound for browser in remote.values())
            )
        # An unmatched remote may also be in a normal start/close transition.
        # This is an incomplete-inventory observation, not authority to mutate
        # engine/guard flags, free a lease, or stop a remote browser.
        # Quarantine can outlive all local records. Keep a redacted control
        # row even then (or beside healthy tasks), not a false empty/healthy
        # inventory. This row is NOT a claim that a remote browser is active.
        blocked_states = {"unmanaged_quarantined", "recovery_required",
                          "missing_session_quarantined"}
        if (self.quarantined or provider_unconfirmed) and not any(
                item["state"] in blocked_states for item in items):
            items.append({
                "session_id": "[redacted]",
                "profile": "[redacted]",
                "mode": "unknown",
                "state": "provider_reconciliation_required",
            })
        # The production ChatGPT connector's browser_sessionsOutput.result
        # schema is a LIST, not a dictionary with {result, capacity, ...}.
        # Return a list directly. A wrapped dict passed the MCP SDK unit
        # tests but failed the real mobile connector's response validation.
        return items

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
        self.mobile_handoff.original_start = self.mcp._tool_manager._tools["browser_start"].fn
        self.mobile_handoff.original_stop = self.mcp._tool_manager._tools["browser_stop"].fn
        # Register only NEW profile-scoped routes; the legacy unscoped mobile
        # endpoints above remain denied even when every slot is idle.
        self.mcp._custom_starlette_routes.extend(self.mobile_handoff.routes())
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
                async def list_sessions(*a, **kw):
                    if a or kw:
                        raise OwnershipError("POSITIONAL_ARGS_UNSUPPORTED")
                    return self.safe_sessions()
                # SDK versions dispatch sync tools in a worker thread. Keep
                # this non-awaiting snapshot on the same event loop as lease
                # transitions, including when the original tool was sync.
                tool.is_async = True
                tool.fn = list_sessions
            elif name == "browser_recent_audit":
                # The legacy audit endpoint may aggregate records from all
                # sessions. Until it is provably scoped by opaque capability,
                # never read or return a different chat's browsing history.
                if tool.is_async:
                    async def read_audit(*a, **kw):
                        if a:
                            raise OwnershipError("POSITIONAL_ARGS_UNSUPPORTED")
                        if kw.get("session_id"):
                            self.authorize(kw["session_id"])
                        return []  # browser_recent_auditOutput.result is a list
                else:
                    def read_audit(*a, **kw):
                        if a:
                            raise OwnershipError("POSITIONAL_ARGS_UNSUPPORTED")
                        if kw.get("session_id"):
                            self.authorize(kw["session_id"])
                        return []  # browser_recent_auditOutput.result is a list
                tool.fn = read_audit
            elif name == "profile_list":
                pass
            elif name == "profile_start_setup":
                async def setup_tool(*a, **kw):
                    if a:
                        raise OwnershipError("POSITIONAL_ARGS_UNSUPPORTED")
                    return await self.mobile_handoff.create(kw)
                tool.fn = setup_tool
            elif name == "profile_cancel_setup":
                async def cancel_setup_tool(*a, **kw):
                    if a:
                        raise OwnershipError("POSITIONAL_ARGS_UNSUPPORTED")
                    return await self.mobile_handoff.cancel(kw)
                tool.fn = cancel_setup_tool
            else:
                # Legacy unscoped login viewers, profile
                # deletion and generic staged-file operations stay blocked.
                # Only the new owner-initiated, single-profile setup above
                # can create a short-lived, capability-scoped handoff.
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
