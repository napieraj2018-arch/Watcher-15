"""Exclusive read-only browser session controller; not yet wired to the legacy MCP routes.

IMPORTANT: all existing tools and mobile setup endpoints must use this guard or
be denied while it owns a session. Without that integration, this file alone
does not protect sessions from other chats. No credentials or cookies stored.
"""
from __future__ import annotations
import asyncio
import hashlib
import hmac
import re
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlsplit

PROFILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,63}$")
READ_ACTIONS = frozenset({"status", "snapshot", "navigate"})
READ_ONLY = "read_only"

class LeaseError(RuntimeError):
    """Use fixed code only, never raw browser or secret values."""

class BrowserAdapter(Protocol):
    async def sessions(self) -> list[dict[str, Any]]: ...
    async def start(self, *, profile: str, mode: str, start_url: str) -> dict: ...
    async def stop(self, session_id: str) -> dict: ...
    async def navigate(self, session_id: str, url: str) -> Any: ...
    async def snapshot(self, session_id: str, *, max_text_chars: int, max_elements: int) -> Any: ...
    async def status(self, session_id: str) -> Any: ...

def https_origin(url: str) -> str:
    """Syntactic check. Use only trusted, preconfigured origin allowlists."""
    try:
        if not isinstance(url, str) or len(url) > 4096 or re.search(r"[\s\\\x00-\x1f]", url):
            raise LeaseError("INVALID_DESTINATION")
        p = urlsplit(url)
        host = p.hostname or ""
        if p.scheme != "https" or p.username is not None or p.password is not None or p.port not in (None, 443):
            raise LeaseError("INVALID_DESTINATION")
        if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{2,251}[a-z0-9]", host):
            raise LeaseError("INVALID_DESTINATION")
        if ".." in host or "." not in host or host.endswith((".local", ".internal", ".invalid", ".localhost")):
            raise LeaseError("INVALID_DESTINATION")
        if p.query or p.fragment:
            raise LeaseError("DESTINATION_QUERY_NOT_ALLOWED")
        return "https://" + host
    except (TypeError, ValueError):
        raise LeaseError("INVALID_DESTINATION") from None

def fingerprint(token: str) -> bytes:
    if not isinstance(token, str) or not 30 <= len(token) <= 128:
        raise LeaseError("INVALID_LEASE_TOKEN")
    try:
        return hashlib.sha256(token.encode("ascii")).digest()
    except UnicodeError:
        raise LeaseError("INVALID_LEASE_TOKEN") from None

@dataclass
class Lease:
    session_id: str
    profile: str
    token_digest: bytes = field(repr=False)
    allowed_origins: frozenset[str]
    expires_at: float
    sequence: int
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

class SessionCoordinator:
    """One-controller experimental guard. ALL tool paths must be fenced."""

    def __init__(self, adapter: BrowserAdapter, *, clock=time.monotonic):
        self.adapter = adapter
        self.clock = clock
        self.admin_lock = asyncio.Lock()
        self.lease: Lease | None = None
        self.sequence = 0

    def _own(self, capability: str) -> Lease:
        lease = self.lease
        if lease is None:
            raise LeaseError("LEASE_NOT_FOUND")
        try:
            valid = hmac.compare_digest(fingerprint(capability), lease.token_digest)
        except LeaseError:
            valid = False
        if not valid:
            raise LeaseError("LEASE_NOT_OWNED")
        if self.clock() >= lease.expires_at:
            raise LeaseError("LEASE_EXPIRED")
        return lease

    async def open(self, *, profile: str, start_url: str,
                   allowed_origins: tuple[str, ...], lease_seconds: int = 600) -> dict:
        if not isinstance(profile, str) or not PROFILE_RE.fullmatch(profile):
            raise LeaseError("INVALID_PROFILE")
        if type(lease_seconds) is not int or not 60 <= lease_seconds <= 870:
            raise LeaseError("INVALID_LEASE_DURATION")
        if not isinstance(allowed_origins, tuple) or not 1 <= len(allowed_origins) <= 10:
            raise LeaseError("INVALID_ALLOWLIST")
        allowed = frozenset(https_origin(a) for a in allowed_origins)
        if any(a != https_origin(a) for a in allowed_origins):
            raise LeaseError("NON_CANONICAL_ALLOWLIST")
        if https_origin(start_url) not in allowed:
            raise LeaseError("DESTINATION_NOT_ALLOWED")
        async with self.admin_lock:
            # Even a session for the same profile may belong to another task.
            if self.lease is not None or await self.adapter.sessions():
                raise LeaseError("BROWSER_BUSY")
            token = secrets.token_urlsafe(32)
            result = await self.adapter.start(profile=profile, mode=READ_ONLY, start_url=start_url)
            sid = result.get("session_id") if isinstance(result, dict) else None
            if not isinstance(sid, str) or not 1 <= len(sid) <= 100:
                raise LeaseError("START_RESULT_UNCONFIRMED")
            self.sequence += 1
            self.lease = Lease(sid, profile, fingerprint(token), allowed,
                               self.clock() + lease_seconds, self.sequence)
            # Returned token is a capability. Never log or publish it.
            return {"lease_token": token, "lease_sequence": self.sequence,
                    "mode": READ_ONLY, "profile": profile,
                    "expires_in_seconds": lease_seconds, "login_attempts": 0}

    async def run(self, capability: str, action: str, **kwargs: Any) -> Any:
        if action not in READ_ACTIONS:
            raise LeaseError("ACTION_REQUIRES_SEPARATE_AUTHORIZATION")
        lease = self._own(capability)
        async with lease.lock:
            if self._own(capability) is not lease:
                raise LeaseError("LEASE_CHANGED")
            ss = await self.adapter.sessions()
            if len(ss) != 1 or ss[0].get("session_id") != lease.session_id:
                raise LeaseError("SESSION_CHANGED_OUTSIDE_COORDINATOR")
            if ss[0].get("mode") != READ_ONLY or ss[0].get("profile") != lease.profile:
                raise LeaseError("SESSION_PRIVILEGE_CHANGED_OUTSIDE_COORDINATOR")
            if https_origin(ss[0].get("url")) not in lease.allowed_origins:
                raise LeaseError("CURRENT_ORIGIN_NOT_ALLOWED")
            if action == "navigate":
                if set(kwargs) != {"url"} or https_origin(kwargs["url"]) not in lease.allowed_origins:
                    raise LeaseError("DESTINATION_NOT_ALLOWED")
                response = await self.adapter.navigate(lease.session_id, kwargs["url"])
                after = await self.adapter.sessions()
                if (len(after) != 1 or after[0].get("session_id") != lease.session_id or
                    https_origin(after[0].get("url")) not in lease.allowed_origins):
                    raise LeaseError("REDIRECT_OUTSIDE_ALLOWED_ORIGINS")
                return response
            if action == "snapshot":
                if set(kwargs) - {"max_text_chars", "max_elements"}:
                    raise LeaseError("INVALID_ARGUMENT")
                text_cap, element_cap = kwargs.get("max_text_chars", 4000), kwargs.get("max_elements", 20)
                if (type(text_cap) is not int or not 1 <= text_cap <= 10000 or
                    type(element_cap) is not int or not 1 <= element_cap <= 80):
                    raise LeaseError("INVALID_OUTPUT_LIMIT")
                return await self.adapter.snapshot(lease.session_id,
                     max_text_chars=text_cap, max_elements=element_cap)
            if kwargs:
                raise LeaseError("INVALID_ARGUMENT")
            return await self.adapter.status(lease.session_id)

    async def renew(self, capability: str, lease_seconds: int = 300) -> dict:
        if type(lease_seconds) is not int or not 60 <= lease_seconds <= 870:
            raise LeaseError("INVALID_LEASE_DURATION")
        async with self.admin_lock:
            lease = self._own(capability)
            ss = await self.adapter.sessions()
            if (len(ss) != 1 or ss[0].get("session_id") != lease.session_id or
                ss[0].get("profile") != lease.profile or ss[0].get("mode") != READ_ONLY):
                raise LeaseError("SESSION_CHANGED_OUTSIDE_COORDINATOR")
            lease.expires_at = self.clock() + lease_seconds
            return {"renewed": True, "expires_in_seconds": lease_seconds}

    async def close(self, capability: str) -> dict:
        async with self.admin_lock:
            lease = self._own(capability)
            async with lease.lock:
                if self._own(capability) is not lease:
                    raise LeaseError("LEASE_CHANGED")
                ss = await self.adapter.sessions()
                if (len(ss) != 1 or ss[0].get("session_id") != lease.session_id or
                    ss[0].get("profile") != lease.profile or ss[0].get("mode") != READ_ONLY):
                    raise LeaseError("SESSION_CHANGED_OUTSIDE_COORDINATOR")
                result = await self.adapter.stop(lease.session_id)
                if (not isinstance(result, dict) or result.get("profile_saved") is not True or
                    result.get("full_profile_saved") is not True):
                    raise LeaseError("PERSISTENCE_NOT_CONFIRMED")
                self.lease = None
                return {"released": True, "profile_saved": True, "full_profile_saved": True}

    async def reconcile(self) -> dict:
        async with self.admin_lock:
            if self.lease is None:
                return {"status": "free"}
            if self.clock() < self.lease.expires_at:
                return {"status": "leased"}
            if await self.adapter.sessions():
                return {"status": "expired_but_live_needs_manual_resolution"}
            self.lease = None
            return {"status": "expired_and_empty_released", "saved": "unverified"}
