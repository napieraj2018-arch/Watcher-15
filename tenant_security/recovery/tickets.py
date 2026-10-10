"""Short-lived encrypted BFF -> MCP reattach tickets (prototype only).

A ticket is NOT an existing Steel aib_ session handle. Actual exchange
requires an authenticated MCP/BFF worker that independently reconciles Steel
and checks browser_recovery.can_execute_epoch for EVERY browser operation.
No key, provider ID, cookie or raw session state is stored here.
"""
from __future__ import annotations

from base64 import urlsafe_b64decode, urlsafe_b64encode
from dataclasses import dataclass
from json import dumps, loads
from secrets import token_bytes
from time import time
from typing import Callable
from uuid import UUID

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

AAD = b"AI_BROWSER_AUTHENTICATED_TASK_REATTACH_V1"
TOKEN_PREFIX = "aibr_"
MAX_TTL_SECONDS = 45
MAX_TOKEN_LENGTH = 1100


class ResumeTicketError(ValueError):
    """Only fixed error codes are displayed. Never include a ticket or key."""


@dataclass(frozen=True, repr=False)
class TicketClaims:
    tenant_id: UUID
    principal_id: UUID
    task_id: UUID
    slot_no: int
    generation: int
    attachment_epoch: int
    issued_at: int
    expires_at: int

    def __repr__(self):
        return "<TicketClaims redacted>"


class TaskResumeTickets:
    def __init__(self, key: bytes, *, clock: Callable[[], float] = time):
        # 32-byte AES-256 key comes only from a trusted KMS/server setting.
        if type(key) is not bytes or len(key) != 32:
            raise ResumeTicketError("TASK_RECOVERY_KEY_INVALID")
        self._key = key
        self.clock = clock

    @staticmethod
    def _claim_shape(claims: TicketClaims):
        return (isinstance(claims, TicketClaims)
            and all(isinstance(v, UUID) for v in (
                claims.tenant_id, claims.principal_id, claims.task_id))
            and all(type(v) is int and 1 <= v <= 9223372036854775807 for v in (
                claims.slot_no, claims.generation, claims.attachment_epoch)))

    def issue(self, *, tenant_id: UUID, principal_id: UUID,
              task_id: UUID, slot_no: int, generation: int,
              attachment_epoch: int, ttl: int = 30) -> str:
        # Validate before arithmetic; untrusted ttl="30" must never leak
        # a TypeError or become silently coerced into a valid lifetime.
        if type(ttl) is not int or not 1 <= ttl <= MAX_TTL_SECONDS:
            raise ResumeTicketError("TASK_RECOVERY_CLAIMS_INVALID")
        now = int(self.clock())
        claims = TicketClaims(tenant_id,principal_id,task_id,slot_no,
                              generation,attachment_epoch,now,now+ttl)
        if not self._claim_shape(claims) or now<=0:
            raise ResumeTicketError("TASK_RECOVERY_CLAIMS_INVALID")
        body = {
            "v": 1,
            "aud": "authenticated-bff-to-mcp",
            "tenant": str(tenant_id),
            "actor": str(principal_id),
            "task": str(task_id),
            "slot": slot_no,
            "generation": generation,
            "epoch": attachment_epoch,
            "issued": now,
            "expires": now+ttl,
        }
        # AEAD prevents an opaque token from disclosing account/task UUIDs
        # and makes any mutation fail authentication.
        nonce = token_bytes(12)
        plaintext = dumps(body,separators=(",",":"),sort_keys=True).encode("ascii")
        encrypted = AESGCM(self._key).encrypt(nonce, plaintext, AAD)
        return TOKEN_PREFIX + urlsafe_b64encode(nonce+encrypted).decode("ascii").rstrip("=")

    def verify(self, ticket: str, *, tenant_id: UUID,
               principal_id: UUID, task_id: UUID) -> TicketClaims:
        if (not isinstance(ticket, str) or not ticket.startswith(TOKEN_PREFIX)
                or len(ticket) > MAX_TOKEN_LENGTH
                or len(ticket) < 100
                or not all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
                           for c in ticket[len(TOKEN_PREFIX):])):
            raise ResumeTicketError("TASK_RECOVERY_TICKET_INVALID")
        try:
            content=ticket[len(TOKEN_PREFIX):]
            raw=urlsafe_b64decode(content+"="*((4-len(content)%4)%4))
            # Reject noncanonical Base64URL. A different final sextet can
            # change only unused padding bits and decode to identical bytes.
            if urlsafe_b64encode(raw).decode("ascii").rstrip("=")!=content:
                raise ValueError("noncanonical Base64URL")
            if len(raw)<29:
                raise ValueError("invalid AEAD")
            data=loads(AESGCM(self._key).decrypt(raw[:12],raw[12:],AAD))
            if (not isinstance(data,dict)
                or set(data)!={"v","aud","tenant","actor","task","slot",
                               "generation","epoch","issued","expires"}
                or data["v"]!=1 or data["aud"]!="authenticated-bff-to-mcp"):
                raise ValueError("invalid JSON claim shape")
            claims=TicketClaims(
                UUID(data["tenant"]),UUID(data["actor"]),UUID(data["task"]),
                data["slot"],data["generation"],data["epoch"],
                data["issued"],data["expires"])
            if (not self._claim_shape(claims)
                or type(claims.issued_at) is not int
                or type(claims.expires_at) is not int
                or claims.expires_at-claims.issued_at not in range(1,MAX_TTL_SECONDS+1)
                or not isinstance(tenant_id,UUID)
                or not isinstance(principal_id,UUID)
                or not isinstance(task_id,UUID)
                or (claims.tenant_id,claims.principal_id,claims.task_id)
                   != (tenant_id,principal_id,task_id)):
                raise ValueError("invalid ticket binding")
            now=int(self.clock())
            if now<claims.issued_at-3 or now>=claims.expires_at:
                raise ResumeTicketError("TASK_RECOVERY_TICKET_EXPIRED")
            return claims
        except ResumeTicketError:
            raise
        except Exception:
            raise ResumeTicketError("TASK_RECOVERY_TICKET_INVALID") from None
