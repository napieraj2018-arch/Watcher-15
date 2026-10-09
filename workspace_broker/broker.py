"""Tenant-aware automatic session broker — offline proof of concept only.

Not installed in production. An authenticated backend must supply Principal,
an isolated WorkspaceCatalog, database-backed leases and an authenticated BFF.
This code does not request passwords, change websites, or access real Steel.
"""
from __future__ import annotations

import asyncio
import ipaddress
import re
import secrets
import time
from collections import deque
from dataclasses import dataclass,field
from urllib.parse import urlsplit
from typing import Any,Protocol

ID=re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,79}$")
PROFILE=re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,63}$")
REQUEST=re.compile(r"^[A-Za-z0-9._-]{12,96}$")
HOST=re.compile(r"^[a-z0-9][a-z0-9.-]{2,250}[a-z0-9]$")

class BrokerError(RuntimeError):
    """Fixed code only; raw user input is never included in errors."""

@dataclass(frozen=True)
class Principal:
    tenant_id:str
    user_id:str
    task_id:str

@dataclass(frozen=True)
class Workspace:
    tenant_id:str
    workspace_id:str
    profile:str
    allowed_hosts:frozenset[str]

@dataclass
class Pending:
    principal:Principal
    workspace_id:str
    request_id:str
    target:str
    created_at:float
    state:str="queued"
    tab_id:str|None=None
    error:str|None=None

@dataclass
class Active:
    principal:Principal
    workspace_id:str
    remote_session_id:str
    tab_ids:set[str]=field(default_factory=set)
    quarantine:bool=False

class BrowserAdapter(Protocol):
    async def sessions(self)->list[dict[str,Any]]:...
    async def start(self,profile:str,url:str,mode:str)->dict[str,Any]:...
    async def new_tab(self,session_id:str,url:str)->dict[str,Any]:...
    async def stop(self,session_id:str)->dict[str,Any]:...

def validate_identity(p:Principal):
    if not isinstance(p,Principal):
        raise BrokerError("TRUSTED_PRINCIPAL_REQUIRED")
    for v in (p.tenant_id,p.user_id,p.task_id):
        if not isinstance(v,str) or not ID.fullmatch(v):
            raise BrokerError("INVALID_PRINCIPAL")

def safe_origin_target(raw:str,allowed_hosts:frozenset[str])->str:
    if not isinstance(raw,str) or len(raw)>2048 or not raw:
        raise BrokerError("INVALID_TARGET")
    if re.search(r"[\s\\\x00-\x1f\x7f]",raw):
        raise BrokerError("INVALID_TARGET")
    try:
        u=urlsplit(raw)
        host=u.hostname or ""
        if (u.scheme!="https" or not host or u.username or u.password
            or u.port not in (None,443) or not HOST.fullmatch(host)
            or ".." in host or host.endswith((".local",".localhost",".internal",".invalid"))):
            raise BrokerError("INVALID_TARGET")
        try:ipaddress.ip_address(host)
        except ValueError:pass
        else:raise BrokerError("INVALID_TARGET")
        # Exact match; never suffix-match "evil.example.com.facebook.com".
        if host not in allowed_hosts:
            raise BrokerError("DESTINATION_OUT_OF_SCOPE")
        return raw
    except (TypeError,ValueError):
        raise BrokerError("INVALID_TARGET") from None

class Broker:
    """FIFO proof of automatic session start after user opens a card.

    One process only. In production, replace internal lock/queue with a
    durable transactional lease and enforce the same boundaries across routes.
    """
    def __init__(self,adapter:BrowserAdapter,workspaces:list[Workspace], *,
                 clock=time.monotonic,max_queue:int=20,max_tabs:int=12):
        self.adapter=adapter
        self.clock=clock
        self.max_queue=max_queue
        self.max_tabs=max_tabs
        self.lock=asyncio.Lock()
        self.workspaces={}
        seen_profiles=set()
        for w in workspaces:
            if not isinstance(w,Workspace):
                raise BrokerError("INVALID_WORKSPACE")
            for v in (w.tenant_id,w.workspace_id):
                if not isinstance(v,str) or not ID.fullmatch(v):
                    raise BrokerError("INVALID_WORKSPACE")
            if not isinstance(w.profile,str) or not PROFILE.fullmatch(w.profile):
                raise BrokerError("INVALID_WORKSPACE")
            if not isinstance(w.allowed_hosts,frozenset) or not w.allowed_hosts:
                raise BrokerError("INVALID_ALLOWLIST")
            for h in w.allowed_hosts:
                if not isinstance(h,str) or not HOST.fullmatch(h) or h!=h.lower():
                    raise BrokerError("INVALID_ALLOWLIST")
            key=(w.tenant_id,w.workspace_id)
            if key in self.workspaces:
                raise BrokerError("DUPLICATE_WORKSPACE")
            if w.profile in seen_profiles:
                # A profile name is a persistent browser identity, not merely
                # a label. Sharing it across workspaces could mix credentials.
                raise BrokerError("PROFILE_REUSED_BETWEEN_WORKSPACES")
            seen_profiles.add(w.profile)
            self.workspaces[key]=w
        self.active:Active|None=None
        # An uncertain provider start must be reconciled by an operator.
        # Do not hand out another tenant context while its outcome is unknown.
        self.quarantined=False
        self.queue:deque[Pending]=deque()
        self.requests:dict[tuple[str,str,str,str],Pending]={}

    def _workspace(self,p,workspace_id):
        validate_identity(p)
        if not isinstance(workspace_id,str) or not ID.fullmatch(workspace_id):
            raise BrokerError("INVALID_WORKSPACE")
        workspace=self.workspaces.get((p.tenant_id,workspace_id))
        if not workspace:
            raise BrokerError("WORKSPACE_NOT_FOUND")
        return workspace

    def _request_key(self,p:Principal,request_id:str):
        return (p.tenant_id,p.user_id,p.task_id,request_id)

    def _expire_old_queue(self):
        now=self.clock()
        while self.queue and now-self.queue[0].created_at>=900:
            expired=self.queue.popleft()
            expired.state="expired"
            expired.error="REQUEST_EXPIRED_RESTART_MANUALLY"

    def _receipt(self,job:Pending)->dict[str,Any]:
        out={"status":job.state,"request_id":job.request_id}
        if job.tab_id:out["tab_id"]=job.tab_id
        if job.state=="queued":
            out["queue_position"]=next((i+1 for i,w in enumerate(self.queue) if w is job),0)
            out["user_message"]="Czeka w kolejce. Nie trzeba uruchamiać sesji ręcznie."
        if job.error:out["code"]=job.error
        return out

    async def _available(self)->bool:
        try:return not await self.adapter.sessions()
        except Exception:raise BrokerError("BROWSER_AVAILABILITY_UNKNOWN") from None

    async def _start(self,job:Pending,w:Workspace)->None:
        try:
            reply=await self.adapter.start(w.profile,job.target,"read_only")
            sid=reply.get("session_id") if isinstance(reply,dict) else None
            if not isinstance(sid,str) or not sid:
                raise BrokerError("START_UNCONFIRMED")
            if self.active is not None:
                raise BrokerError("EXCLUSIVE_OWNERSHIP_CONFLICT")
            observed=await self.adapter.sessions()
            if (not isinstance(observed,list) or len(observed)!=1
                    or not isinstance(observed[0],dict)
                    or observed[0].get("session_id")!=sid
                    or observed[0].get("profile",w.profile)!=w.profile
                    or observed[0].get("mode","read_only")!="read_only"):
                raise BrokerError("START_SESSION_IDENTITY_NOT_VERIFIED")
            tab=secrets.token_urlsafe(18)
            self.active=Active(job.principal,job.workspace_id,sid,{tab})
            job.tab_id=tab;job.state="ready"
        except Exception:
            # Provider may have created a native session before its response
            # failed. Isolate the entire controller until explicit reconciliation.
            self.quarantined=True
            job.state="paused"
            job.error="START_UNCONFIRMED_NO_AUTOMATIC_RETRY"

    async def open(self,p:Principal,workspace_id:str,url:str,request_id:str):
        w=self._workspace(p,workspace_id)
        target=safe_origin_target(url,w.allowed_hosts)
        if not isinstance(request_id,str) or not REQUEST.fullmatch(request_id):
            raise BrokerError("INVALID_REQUEST_ID")
        async with self.lock:
            self._expire_old_queue()
            key=self._request_key(p,request_id)
            if key in self.requests:
                old=self.requests[key]
                if (old.principal!=p or old.workspace_id!=workspace_id
                    or old.target!=target):
                    raise BrokerError("IDEMPOTENCY_KEY_CONFLICT")
                return self._receipt(old)
            if self.quarantined or (self.active and self.active.quarantine):
                raise BrokerError("BROWSER_REQUIRES_RECOVERY")
            job=Pending(p,workspace_id,request_id,target,self.clock())
            self.requests[key]=job
            # Reuse only for the same user, tenant, task and workspace.
            if (self.active and self.active.principal==p
                    and self.active.workspace_id==workspace_id):
                if len(self.active.tab_ids)>=self.max_tabs:
                    self.requests.pop(key,None)
                    raise BrokerError("WORKSPACE_TAB_LIMIT")
                try:
                    resp=await self.adapter.new_tab(self.active.remote_session_id,target)
                    if not isinstance(resp,dict) or resp.get("ok") is not True:
                        raise BrokerError("TAB_UNCONFIRMED")
                    tab=secrets.token_urlsafe(18)
                    self.active.tab_ids.add(tab)
                    job.tab_id=tab;job.state="ready"
                except Exception:
                    job.state="paused";job.error="TAB_UNCONFIRMED_NO_RETRY"
                return self._receipt(job)
            if len(self.queue)>=self.max_queue:
                self.requests.pop(key,None)
                raise BrokerError("QUEUE_FULL")
            if not self.active and not self.queue and await self._available():
                await self._start(job,w)
            else:
                self.queue.append(job)
            return self._receipt(job)

    async def poll(self,p:Principal,request_id:str):
        validate_identity(p)
        async with self.lock:
            if self.quarantined or (self.active and self.active.quarantine):
                raise BrokerError("BROWSER_REQUIRES_RECOVERY")
            self._expire_old_queue()
            job=self.requests.get(self._request_key(p,request_id))
            if not job or job.principal!=p:
                raise BrokerError("REQUEST_NOT_FOUND")
            if job.state!="queued":
                return self._receipt(job)
            if self.clock()-job.created_at>=900:
                self.queue.remove(job)
                job.state="expired";job.error="REQUEST_EXPIRED_RESTART_MANUALLY"
                return self._receipt(job)
            if self.active or not self.queue or self.queue[0] is not job:
                return self._receipt(job)
            if not await self._available():
                return self._receipt(job)
            self.queue.popleft()
            w=self._workspace(p,job.workspace_id)
            await self._start(job,w)
            return self._receipt(job)

    async def cancel(self,p:Principal,request_id:str):
        validate_identity(p)
        async with self.lock:
            job=self.requests.get(self._request_key(p,request_id))
            if not job or job.principal!=p:
                raise BrokerError("REQUEST_NOT_FOUND")
            if job.state!="queued":
                raise BrokerError("CANNOT_CANCEL_RUNNING_TAB")
            self.queue.remove(job);job.state="cancelled"
            return self._receipt(job)

    async def close(self,p:Principal):
        validate_identity(p)
        async with self.lock:
            if self.quarantined:
                raise BrokerError("BROWSER_REQUIRES_RECOVERY")
            active=self.active
            if active is None or active.principal!=p:
                raise BrokerError("TASK_NOT_OWNER")
            if active.quarantine:
                raise BrokerError("BROWSER_REQUIRES_RECOVERY")
            try:
                result=await self.adapter.stop(active.remote_session_id)
                if (not isinstance(result,dict) or result.get("profile_saved") is not True
                    or result.get("full_profile_saved") is not True
                    or not await self._available()):
                    raise BrokerError("SAVE_NOT_CONFIRMED")
            except Exception:
                active.quarantine=True
                raise BrokerError("BROWSER_REQUIRES_RECOVERY") from None
            self.active=None
            return {"closed":True,"profile_saved":True,"next_request_pending":bool(self.queue)}

    async def summary(self,p:Principal):
        validate_identity(p)
        async with self.lock:
            mine=bool(self.active and self.active.principal==p)
            pending=sum(1 for w in self.queue if w.principal==p)
            return {"my_task_active":mine,"my_queue_items":pending,
                    "other_task_busy":bool(self.active and not mine),
                    "technical_session_id_disclosed":False}
