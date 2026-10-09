"""Non-production PostgreSQL adapters for the tenant BFF proof.

RLS connections MUST be dedicated to one per-tenant DB login. No SET ROLE,
custom GUC, session_user override, superuser credential or shared role fallback.
Connection strings and credentials are supplied in server config only.
"""
from __future__ import annotations
from uuid import UUID

from .gate import Principal


class PgSessionResolver:
    def __init__(self, auth_dsn: str):
        if not auth_dsn:
            raise ValueError("missing_auth_dsn")
        self.auth_dsn = auth_dsn

    def __call__(self, session_digest: str) -> Principal | None:
        import psycopg
        with psycopg.connect(self.auth_dsn, connect_timeout=5, autocommit=True) as connection:
            row = connection.execute(
                "SELECT tenant_id, principal_id, access_role, csrf_digest "
                "FROM browser_auth.resolve_session(%s)", (session_digest,)
            ).fetchone()
        return Principal(*row) if row else None


class PgTenantRepository:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self.connection = None

    def __enter__(self):
        import psycopg
        self.connection = psycopg.connect(self.dsn, connect_timeout=5, autocommit=False)
        return self

    def __exit__(self, exc_type, exc_value, tb):
        if self.connection is not None:
            try:
                if exc_type is None:
                    self.connection.commit()
                else:
                    self.connection.rollback()
            finally:
                self.connection.close()
                self.connection = None

    def authenticated_tenant(self):
        row = self.connection.execute("SELECT browser_product.authenticated_tenant()").fetchone()
        return row[0] if row else None

    def workspace_exists(self, tenant_id: UUID, workspace_id: UUID):
        row = self.connection.execute(
            "SELECT 1 FROM browser_product.workspaces "
            "WHERE tenant_id=%s AND workspace_id=%s",
            (tenant_id, workspace_id)
        ).fetchone()
        return row is not None

    def list_profiles(self, tenant_id: UUID, workspace_id: UUID):
        rows = self.connection.execute(
            "SELECT profile_id,display_name,status FROM browser_product.profiles "
            "WHERE tenant_id=%s AND workspace_id=%s ORDER BY display_name",
            (tenant_id, workspace_id)
        ).fetchall()
        return [dict(profile_id=str(r[0]), name=r[1], status=r[2]) for r in rows]

    def enqueue(self, tenant_id: UUID, workspace_id: UUID, profile_id: UUID, task_id: UUID):
        # Never perform direct INSERT: the PostgreSQL role has no INSERT grant.
        # The privileged, tenant-scoped function performs membership checks,
        # serialization, queue quota, ID collision handling and default state.
        # The database derives tenant identity from SESSION_USER, not JSON.
        row = self.connection.execute(
            "SELECT status_code,current_state "
            "FROM browser_product.enqueue_task(%s,%s,%s)",
            (workspace_id, profile_id, task_id)
        ).fetchone()
        return (row[0], row[1]) if row else ("unavailable", None)


class ServerTenantConnections:
    """No tenant id from user input; map controlled by trusted server config."""
    def __init__(self, role_dsns: dict[UUID, str]):
        self._dsns = dict(role_dsns)

    def __call__(self, tenant_id: UUID) -> PgTenantRepository:
        dsn = self._dsns.get(tenant_id)
        if not dsn:
            raise LookupError("tenant_connection_unavailable")
        return PgTenantRepository(dsn)
