"""Fail-closed profile erasure protocol (OFFLINE PROTOTYPE, NOT DEPLOYED).

This does not call Steel or the live Floot vault. A commercial BFF must
provide tenant authentication, step-up authorization, transactionally durable
tombstones, and provider deletion + read-after-delete verification.

Never announce irreversible erasure based on removing only local metadata.
"""
from __future__ import annotations
import asyncio
import re
from dataclasses import dataclass
from typing import Protocol, Literal

ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,79}$")
UUID = re.compile(r"^[a-f0-9]{8}-[a-f0-9]{4}-[1-8][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$")
OTHER_SOURCES = (
    "credential_vault", "portable_snapshot", "archived_versions",
    "staged_files", "session_recordings", "native_profile_registry",
)
PROVIDER_ACKS = frozenset({"accepted", "unsupported", "uncertain"})

class ErasureError(ValueError):
    """Fixed code only, no profile ID, tenant identity or provider messages."""

@dataclass(frozen=True)
class Principal:
    tenant_id: str
    user_id: str
    confirmed_step_up: bool

    def __post_init__(self):
        if (not isinstance(self.tenant_id,str) or not ID.fullmatch(self.tenant_id)
            or not isinstance(self.user_id,str) or not ID.fullmatch(self.user_id)
            or type(self.confirmed_step_up) is not bool):
            raise ErasureError("INVALID_PRINCIPAL")

@dataclass(frozen=True)
class Request:
    principal: Principal
    profile_id: str
    confirmation: Literal["erase_permanently"]

    def __post_init__(self):
        if (not isinstance(self.principal,Principal)
                or not isinstance(self.profile_id,str)
                or not UUID.fullmatch(self.profile_id)
                or self.confirmation!="erase_permanently"):
            raise ErasureError("INVALID_ERASURE_REQUEST")

@dataclass(frozen=True)
class Report:
    status: str
    phase: str
    complete: bool = False
    def as_public_json(self):
        return {"status":self.status,"phase":self.phase,"complete":self.complete}

class Backend(Protocol):
    """Every method MUST be durable, tenant-scoped and authenticated by BFF.

    lock_profile MUST atomically prevent new sessions, writes, credentials
    injection and profile resurrection across all workers and routes.
    It must not succeed while a live session is not exclusively stopped.
    """
    async def authorized(self,principal:Principal,profile_id:str)->bool: ...
    async def verify_fresh_step_up(self,principal:Principal,profile_id:str)->bool: ...
    # Must validate a fresh, one-use, backend-issued authorization BOUND TO
    # tenant+user+the precise profile. Principal.confirmed_step_up is not proof.
    async def sessions_state(self,tenant_id:str,profile_id:str)->str: ...
    async def lock_profile(self,tenant_id:str,profile_id:str)->bool: ...
    async def is_locked(self,tenant_id:str,profile_id:str)->bool: ...
    async def provider_profile_id(self,tenant_id:str,profile_id:str)->str|None: ...
    async def provider_delete(self,provider_id:str)->str: ...
    async def provider_exists(self,provider_id:str)->bool|None: ...
    async def purge(self,tenant_id:str,profile_id:str,source:str)->bool: ...
    async def contains(self,tenant_id:str,profile_id:str,source:str)->bool|None: ...
    async def finalize(self,tenant_id:str,profile_id:str)->bool: ...
    async def final_tombstone_verified(self,tenant_id:str,profile_id:str)->bool: ...
    async def erasure_receipts_verified(self,tenant_id:str,profile_id:str)->bool: ...
    # Independent, durable evidence of provider deletion AND all local stores.
    # A lone database tombstone cannot satisfy this; keep signed/audited proof
    # in a restricted retention ledger, never an API response or public log.

class ErasureCoordinator:
    """Single-process proof of the protocol; NOT cross-process locking.

    A production implementation MUST replace this lock with a transactionally
    fenced durable job and stored progress. All writes in that job must use the
    immutable authorized profile binding.
    """
    def __init__(self,backend:Backend):
        self.backend=backend
        self._lock=asyncio.Lock()

    async def execute(self,request:Request)->Report:
        if not isinstance(request,Request):
            raise ErasureError("INVALID_ERASURE_REQUEST")
        principal=request.principal
        if not principal.confirmed_step_up:
            raise ErasureError("STEP_UP_AUTH_REQUIRED")
        try:
            allowed=await self.backend.authorized(principal,request.profile_id)
        except Exception:
            raise ErasureError("AUTHORIZATION_UNVERIFIED") from None
        if allowed is not True:
            # Same error for wrong tenant and missing target to avoid enumeration.
            raise ErasureError("PROFILE_NOT_ACCESSIBLE")
        try:
            step_up=await self.backend.verify_fresh_step_up(principal,request.profile_id)
        except Exception:
            raise ErasureError("STEP_UP_VERIFICATION_UNAVAILABLE") from None
        if step_up is not True:
            raise ErasureError("STEP_UP_NOT_VERIFIED")

        tenant=principal.tenant_id
        profile=request.profile_id
        async with self._lock:
            try:
                return await self._execute_authorized(tenant,profile)
            except ErasureError:
                raise
            except Exception:
                # Never convert a provider/network exception into erasure proof.
                return Report("paused","UNVERIFIED_PROVIDER_OR_STORAGE_RESULT")

    async def _execute_authorized(self,tenant:str,profile:str)->Report:
        # A previous success needs readback. A tombstone in one storage backend
        # alone is not proof that provider / backups were deleted.
        if await self.backend.final_tombstone_verified(tenant,profile) is True:
            # Check independent erasure evidence on EVERY status/retry. A
            # tombstone may outlive provider data and backup resurrection.
            if await self.backend.erasure_receipts_verified(tenant,profile) is not True:
                return Report("paused","ERASURE_RECEIPTS_UNVERIFIED")
            return Report("completed","verified_tombstone_and_receipts",True)

        locked=await self.backend.is_locked(tenant,profile)
        if locked is not True:
            state=await self.backend.sessions_state(tenant,profile)
            if state!="empty":
                return Report("blocked","ACTIVE_OR_UNKNOWN_SESSIONS")
            if await self.backend.lock_profile(tenant,profile) is not True:
                return Report("blocked","COULD_NOT_FENCE_PROFILE")
            if await self.backend.is_locked(tenant,profile) is not True:
                return Report("blocked","LOCK_NOT_VERIFIED")

        # A tombstone is not a substitute for verifying that an earlier
        # running session actually ended. Never delete an in-use profile.
        if await self.backend.is_locked(tenant,profile) is not True:
            return Report("blocked","LOCK_NOT_VERIFIED")
        if await self.backend.sessions_state(tenant,profile)!="empty":
            return Report("blocked","ACTIVE_OR_UNKNOWN_SESSIONS")

        provider=await self.backend.provider_profile_id(tenant,profile)
        if not isinstance(provider,str) or not UUID.fullmatch(provider):
            # A known 'not found' provider profile and a missing mapping are
            # different. An absent mapping must be reconciled before erasure.
            return Report("paused","PROVIDER_MAPPING_UNVERIFIED")

        state=await self.backend.provider_exists(provider)
        if state is None:
            return Report("paused","PROVIDER_STATE_UNKNOWN")
        if state is True:
            acknowledgement=await self.backend.provider_delete(provider)
            if acknowledgement not in PROVIDER_ACKS:
                return Report("paused","PROVIDER_DELETE_UNVERIFIED")
            if acknowledgement=="unsupported":
                return Report("blocked","PROVIDER_ERASURE_UNSUPPORTED")
            if acknowledgement!="accepted":
                return Report("paused","PROVIDER_DELETE_UNVERIFIED")
            # Provider 2xx (accepted) is never enough. Confirm read-after-delete.
            check=await self.backend.provider_exists(provider)
            if check is not False:
                return Report("paused","PROVIDER_DELETION_NOT_VERIFIED")

        # Do not purge our own registry until provider removal is verified,
        # because the registry may be the only remaining binding to that data.
        for source in OTHER_SOURCES:
            present=await self.backend.contains(tenant,profile,source)
            if present is None:
                return Report("paused","STORAGE_VISIBILITY_UNKNOWN")
            if present is True:
                if await self.backend.purge(tenant,profile,source) is not True:
                    return Report("paused","STORAGE_PURGE_NOT_ACKNOWLEDGED")
                if await self.backend.contains(tenant,profile,source) is not False:
                    return Report("paused","STORAGE_PURGE_NOT_VERIFIED")
            if await self.backend.is_locked(tenant,profile) is not True:
                return Report("blocked","LOCK_LOST_DURING_ERASURE")

        if await self.backend.finalize(tenant,profile) is not True:
            return Report("paused","FINAL_TOMBSTONE_NOT_ACKNOWLEDGED")
        if await self.backend.final_tombstone_verified(tenant,profile) is not True:
            return Report("paused","FINAL_TOMBSTONE_NOT_VERIFIED")
        if await self.backend.erasure_receipts_verified(tenant,profile) is not True:
            return Report("paused","ERASURE_RECEIPTS_UNVERIFIED")
        return Report("completed","provider_and_all_snapshots_verified_gone",True)
