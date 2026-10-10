"""PostgreSQL auth-role + tenant-worker role adapter; staging ONLY.

Connection DSNs MUST be provisioned by the server, never HTTP/user body.
The session resolver already authenticates high-entropy cookie digests.
The DB functions independently verify actor+tenant+CSRF again.
"""
from __future__ import annotations

from uuid import UUID
from tenant_security.recovery.service import RecoveryRejected


class PgRecoveryRepository:
    def __init__(self, auth_dsn: str, worker_dsns: dict[UUID,str]):
        if not isinstance(auth_dsn,str) or not auth_dsn.strip():
            raise RecoveryRejected("REATTACH_AUTH_DB_UNAVAILABLE")
        if not isinstance(worker_dsns,dict) or not worker_dsns:
            raise RecoveryRejected("REATTACH_WORKER_DB_UNAVAILABLE")
        if any(not isinstance(k,UUID) or not isinstance(v,str)
               or not v.strip() for k,v in worker_dsns.items()):
            raise RecoveryRejected("REATTACH_WORKER_DB_UNAVAILABLE")
        self._auth_dsn=auth_dsn
        self._worker_dsns=dict(worker_dsns)

    def _auth_connection(self):
        import psycopg
        return psycopg.connect(self._auth_dsn,connect_timeout=5,autocommit=True)

    def _worker_connection(self, tenant_id: UUID):
        import psycopg
        dsn=self._worker_dsns.get(tenant_id)
        if not dsn:
            raise RecoveryRejected("REATTACH_WORKER_DB_UNAVAILABLE")
        return psycopg.connect(dsn,connect_timeout=5,autocommit=True)

    def list_own(self, session_digest: str, csrf_digest: str):
        with self._auth_connection() as cx:
            return cx.execute(
                "SELECT * FROM browser_recovery.list_own_tasks(%s,%s)",
                (session_digest,csrf_digest)
            ).fetchall()

    def register(self, session_digest: str, csrf_digest: str, task_id: UUID):
        with self._auth_connection() as cx:
            return cx.execute(
                "SELECT browser_recovery.register_own_task(%s,%s,%s)",
                (session_digest,csrf_digest,task_id)
            ).fetchone()[0]

    def bind(self, session_digest: str, csrf_digest: str, task_id: UUID,
             slot_no: int, lease_id: UUID, generation: int):
        with self._auth_connection() as cx:
            return cx.execute(
                "SELECT browser_recovery.bind_reserved_lease(%s,%s,%s,%s,%s,%s)",
                (session_digest,csrf_digest,task_id,slot_no,lease_id,generation)
            ).fetchone()[0]

    def reattach(self, session_digest: str, csrf_digest: str,
                 task_id: UUID, attempt_id: UUID):
        with self._auth_connection() as cx:
            return cx.execute(
                "SELECT * FROM browser_recovery.reattach_own_task(%s,%s,%s,%s)",
                (session_digest,csrf_digest,task_id,attempt_id)
            ).fetchone()

    def cancel(self, session_digest: str, csrf_digest: str, task_id: UUID):
        with self._auth_connection() as cx:
            return cx.execute(
                "SELECT browser_recovery.request_cancel_own(%s,%s,%s)",
                (session_digest,csrf_digest,task_id)
            ).fetchone()[0]

    def can_create(self, tenant_id: UUID, task_id: UUID, slot_no: int,
                   lease_id: UUID, generation: int) -> bool:
        with self._worker_connection(tenant_id) as cx:
            row=cx.execute("SELECT browser_product.authenticated_tenant()").fetchone()
            if not row or row[0]!=tenant_id:
                raise RecoveryRejected("REATTACH_WRONG_TENANT_WORKER")
            return cx.execute(
                "SELECT browser_recovery.can_create_provider(%s,%s,%s,%s)",
                (task_id,lease_id,slot_no,generation)
            ).fetchone()[0] is True

    def can_execute(self, tenant_id: UUID, task_id: UUID, slot_no: int,
                    generation: int, attachment_epoch: int) -> bool:
        # Can only authenticate via the CURRENT per-tenant DB login.
        # No service superuser/SET ROLE fallback, even on connection errors.
        with self._worker_connection(tenant_id) as cx:
            row=cx.execute("SELECT browser_product.authenticated_tenant()").fetchone()
            if not row or row[0]!=tenant_id:
                raise RecoveryRejected("REATTACH_WRONG_TENANT_WORKER")
            return cx.execute(
                "SELECT browser_recovery.can_execute_owned_epoch(%s,%s,%s,%s)",
                (task_id,slot_no,generation,attachment_epoch)
            ).fetchone()[0] is True
