"""Server-only task reattachment after BFF identity and live Steel recheck.

This is a pure orchestration layer, NOT an existing ChatGPT MCP tool. Live
provider verification and a durable BFF session are mandatory inputs; absent
one of them this component refuses to issue a ticket. No browser launch,
provider release, or private profile state is performed here.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from tenant_security.bff.gate import Principal
from tenant_security.recovery.tickets import (
    TaskResumeTickets, TicketClaims, ResumeTicketError,
)


class RecoveryRejected(ValueError):
    """Only stable error codes, no provider exception text."""


class RecoveryRepository(Protocol):
    def list_own(self, session_digest: str, csrf_digest: str) -> list[tuple]: ...
    def reattach(self, session_digest: str, csrf_digest: str,
                 task_id: UUID, attempt_id: UUID) -> tuple: ...
    def cancel(self, session_digest: str, csrf_digest: str, task_id: UUID) -> str: ...
    def can_execute(self, tenant_id: UUID, task_id: UUID, slot_no: int,
                    generation: int, attachment_epoch: int) -> bool: ...


class ProviderProbe(Protocol):
    def verify_active(self, tenant_id: UUID, principal_id: UUID,
                      task_id: UUID, slot_no: int, generation: int) -> bool: ...


class NoProviderProbe:
    """Safe default until independently authenticated Steel adapter exists."""
    def verify_active(self, tenant_id, principal_id, task_id, slot_no, generation):
        return False


@dataclass(frozen=True, repr=False)
class ResumeReady:
    task_id: UUID
    ticket: str
    attachment_epoch: int
    expires_in_seconds: int

    def __repr__(self):
        return "<ResumeReady redacted>"


class ReattachmentService:
    def __init__(self, repository: RecoveryRepository,
                 provider: ProviderProbe,
                 tickets: TaskResumeTickets):
        if repository is None or provider is None or not isinstance(
            tickets, TaskResumeTickets
        ):
            raise RecoveryRejected("REATTACH_CONFIGURATION_INVALID")
        self.repo, self.provider, self.tickets = repository, provider, tickets

    @staticmethod
    def _owner(principal: Principal, task_id: UUID | None = None):
        if (not isinstance(principal, Principal)
            or not isinstance(principal.tenant_id, UUID)
            or not isinstance(principal.user_id, UUID)
            or principal.access_role not in {"operator","admin"}
            or (task_id is not None and not isinstance(task_id, UUID))):
            raise RecoveryRejected("REATTACH_NOT_AUTHORIZED")

    def list_tasks(self, *, principal: Principal,
                   session_digest: str, csrf_digest: str) -> list[dict]:
        self._owner(principal)
        try:
            entries=self.repo.list_own(session_digest,csrf_digest)
            if len(entries)>20:
                raise ValueError("too many rows")
            result=[]
            for task,state,cancel,epoch in entries:
                if (not isinstance(task,UUID) or not isinstance(state,str)
                    or type(cancel) is not bool or type(epoch) is not int
                    or epoch<0):
                    raise ValueError("bad repository response")
                result.append({
                    "task_id":str(task),
                    "state":state,
                    "cancel_pending":cancel,
                    "attachment_epoch":epoch,
                })
            return result
        except Exception:
            raise RecoveryRejected("REATTACH_BACKEND_UNAVAILABLE") from None

    def resume(self, *, principal: Principal, session_digest: str,
               csrf_digest: str, task_id: UUID, attempt_id: UUID) -> ResumeReady:
        self._owner(principal,task_id)
        if not isinstance(attempt_id,UUID):
            raise RecoveryRejected("REATTACH_INVALID_ATTEMPT")
        try:
            row=self.repo.reattach(session_digest,csrf_digest,task_id,attempt_id)
        except Exception:
            raise RecoveryRejected("REATTACH_BACKEND_UNAVAILABLE") from None
        if not isinstance(row,tuple) or len(row)!=4:
            raise RecoveryRejected("REATTACH_BACKEND_UNAVAILABLE")
        status,slot,gen,epoch=row
        if status=="not_authorized":
            raise RecoveryRejected("REATTACH_NOT_AUTHORIZED")
        if status=="not_available":
            raise RecoveryRejected("REATTACH_TASK_NOT_FOUND")
        if status=="provider_recheck_required":
            raise RecoveryRejected("REATTACH_PROVIDER_RECHECK_REQUIRED")
        if status not in {"reattach_epoch_issued","already_attached"}:
            raise RecoveryRejected("REATTACH_NOT_AVAILABLE")
        if not (type(slot) is int and 1<=slot<=32767
                and type(gen) is int and gen>0
                and type(epoch) is int and epoch>0):
            raise RecoveryRejected("REATTACH_BACKEND_UNAVAILABLE")
        try:
            # An SQL attestation alone is not enough. A trusted independent
            # provider adapter must verify current Steel profile binding.
            if self.provider.verify_active(
                principal.tenant_id,principal.user_id,task_id,slot,gen
            ) is not True:
                raise RecoveryRejected("REATTACH_PROVIDER_RECHECK_REQUIRED")
            # Concurrency fence: another authenticated chat may have rotated
            # the epoch while this provider check was in flight.
            if self.repo.can_execute(
                principal.tenant_id,task_id,slot,gen,epoch
            ) is not True:
                raise RecoveryRejected("REATTACH_LEASE_CHANGED")
            ticket=self.tickets.issue(
                tenant_id=principal.tenant_id,
                principal_id=principal.user_id,
                task_id=task_id,
                slot_no=slot,
                generation=gen,
                attachment_epoch=epoch,
                ttl=30,
            )
        except RecoveryRejected:
            raise
        except Exception:
            raise RecoveryRejected("REATTACH_PROVIDER_RECHECK_REQUIRED") from None
        return ResumeReady(task_id,ticket,epoch,30)

    def authorize_ticket(self, ticket: str, *, principal: Principal,
                         task_id: UUID) -> TicketClaims:
        self._owner(principal,task_id)
        try:
            claims=self.tickets.verify(ticket,tenant_id=principal.tenant_id,
                principal_id=principal.user_id,task_id=task_id)
            if not self.provider.verify_active(principal.tenant_id,
                principal.user_id,task_id,claims.slot_no,claims.generation):
                raise RecoveryRejected("REATTACH_PROVIDER_RECHECK_REQUIRED")
            if self.repo.can_execute(principal.tenant_id,task_id,claims.slot_no,
                claims.generation,claims.attachment_epoch) is not True:
                raise RecoveryRejected("REATTACH_LEASE_CHANGED")
            return claims
        except ResumeTicketError:
            raise RecoveryRejected("REATTACH_TICKET_REJECTED") from None
        except RecoveryRejected:
            raise
        except Exception:
            raise RecoveryRejected("REATTACH_PROVIDER_RECHECK_REQUIRED") from None

    def cancel_task(self, *, principal: Principal, session_digest: str,
                    csrf_digest: str, task_id: UUID) -> str:
        self._owner(principal,task_id)
        try:
            code=self.repo.cancel(session_digest,csrf_digest,task_id)
        except Exception:
            raise RecoveryRejected("REATTACH_BACKEND_UNAVAILABLE") from None
        if code in {"cancel_requested","already_requested"}:
            # This is NOT a remote provider stop or a saved-profile receipt.
            return "stop_requested_provider_not_released"
        if code=="not_authorized":
            raise RecoveryRejected("REATTACH_NOT_AUTHORIZED")
        if code=="not_available":
            raise RecoveryRejected("REATTACH_TASK_NOT_FOUND")
        raise RecoveryRejected("REATTACH_NOT_AVAILABLE")
