"""Internal synthetic handoff from authenticated queued task to durable slot.

Never exposed as an HTTP endpoint. Does NOT implement real provider access.
The sole purpose is an end-to-end integration test of authorization/fencing.
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from gateway import Gateway, Principal, Rejection


@dataclass(frozen=True)
class VerifiedTask:
    tenant_id: UUID
    task_id: UUID
    workspace_id: UUID
    profile_id: UUID


class SyntheticSlotWorker:
    def __init__(self, gateway: Gateway):
        self.gateway = gateway
        self.worker_role = "fixture_slot_worker"
        self.verifier_role = "fixture_slot_verifier"

    def resolve(self, principal: Principal, task_id: UUID) -> VerifiedTask:
        item = self.gateway.get_task(principal, task_id)
        if item["status"] != "queued":
            raise Rejection(409, "task_not_queued")
        return VerifiedTask(principal.tenant_id, task_id,
                            UUID(item["workspace_id"]), UUID(item["profile_id"]))

    def reserve(self, verified: VerifiedTask, lease_id: UUID, provider) -> dict:
        with self.gateway._connect(self.worker_role) as db:
            row = db.execute(
                "SELECT * FROM browser_slot_guard.claim_slot(%s,%s,%s,%s)",
                (verified.tenant_id, verified.task_id, lease_id, 300)
            ).fetchone()
            granted, should_start, generation, status = row
            if not granted:
                return {"state": status, "generation": None}
            if not should_start:
                return {"state": "already_reserved", "generation": generation}
            # Synthetic provider only. A real Steel call would require a
            # durable outbox and timeout reconciliation before calling.
            provider.start(verified)
            active = db.execute(
                "SELECT browser_slot_guard.activate_slot(%s,%s,%s,%s)",
                (verified.tenant_id, verified.task_id, lease_id, generation)
            ).fetchone()[0]
            if active is not True:
                # The record stays reserved/quarantined; never launch again.
                raise Rejection(409, "slot_activation_unconfirmed")
            return {"state": "reserved", "generation": generation}

    def complete(self, verified: VerifiedTask, lease_id: UUID,
                 generation: int, provider) -> bool:
        with self.gateway._connect(self.worker_role) as worker:
            started = worker.execute(
                "SELECT browser_slot_guard.begin_close(%s,%s,%s,%s)",
                (verified.tenant_id, verified.task_id, lease_id, generation)
            ).fetchone()[0]
            if started is not True:
                return False
        # All of these calls are local, deterministic synthetic substitutes.
        closed = provider.close(verified) is True
        saved = provider.profile_saved(verified) is True
        if not closed or not saved:
            return False
        # A separate DB login role is essential: the normal worker cannot
        # forge its own "Steel closed / encrypted state saved" receipt.
        with self.gateway._connect(self.verifier_role) as verifier:
            proof = verifier.execute(
                "SELECT browser_slot_guard.record_verified_release(%s,%s,%s,%s)",
                (lease_id, generation, closed, saved)
            ).fetchone()[0]
        if proof is not True:
            return False
        with self.gateway._connect(self.worker_role) as worker:
            released = worker.execute(
                "SELECT browser_slot_guard.finish_slot(%s,%s,%s,%s)",
                (verified.tenant_id, verified.task_id, lease_id, generation)
            ).fetchone()[0]
        return released is True
