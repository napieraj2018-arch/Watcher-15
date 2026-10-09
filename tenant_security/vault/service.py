"""Server-internal encrypted vault adapter for isolated PostgreSQL proof only.

No HTTP routes, customer credential issuance, Steel API calls or Floot changes.
Only trusted server callers may supply the authenticated tenant UUID. All DB
connections use a separately provisioned vault-worker login for that tenant.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable
from uuid import UUID

from .profile_envelope import (
    EnvelopeError, ProfileEnvelope, ProfileEnvelopeCipher,
)


class VaultOperationError(RuntimeError):
    """Fixed status only; never contains SQL, ciphertext or plaintext."""


@dataclass(frozen=True, repr=False)
class VaultState:
    revision: int
    plaintext: bytes

    def __repr__(self):
        return "<VaultState redacted>"


class PgTenantVaultConnection:
    def __init__(self, dsn: str):
        if not isinstance(dsn, str) or not dsn:
            raise VaultOperationError("vault_backend_unavailable")
        self._dsn = dsn
        self._db = None

    def __repr__(self):
        return "<PgTenantVaultConnection redacted>"

    def __enter__(self):
        import psycopg
        self._db = psycopg.connect(self._dsn, connect_timeout=5, autocommit=False)
        return self

    def __exit__(self, typ, value, tb):
        try:
            if self._db is not None:
                if typ is None:
                    self._db.commit()
                else:
                    self._db.rollback()
        finally:
            if self._db is not None:
                self._db.close()
                self._db = None

    def authenticated_tenant(self) -> UUID | None:
        row = self._db.execute(
            "SELECT browser_product.authenticated_tenant()"
        ).fetchone()
        return row[0] if row else None

    def latest(self, tenant: UUID, workspace: UUID, profile: UUID):
        row = self._db.execute(
            "SELECT tenant_id,workspace_id,profile_id,revision,key_id,nonce,encrypted_state "
            "FROM browser_product.profile_versions_secure "
            "WHERE tenant_id=%s AND workspace_id=%s AND profile_id=%s "
            "ORDER BY revision DESC LIMIT 1",
            (tenant,workspace,profile)
        ).fetchone()
        return ProfileEnvelope(*row) if row else None

    def append(self, envelope: ProfileEnvelope, expected_previous: int):
        row = self._db.execute(
            "SELECT status_code,stored_revision FROM "
            "browser_product.append_encrypted_profile(%s,%s,%s,%s,%s,%s)",
            (envelope.workspace_id,envelope.profile_id,expected_previous,
             envelope.key_id,envelope.nonce,envelope.ciphertext)
        ).fetchone()
        return tuple(row) if row else ("unavailable", None)


class ServerVaultConnections:
    """Immutable mapping of tenant UUID -> dedicated server vault-role DSN."""
    def __init__(self, tenant_dsns: dict[UUID,str]):
        if not isinstance(tenant_dsns, dict) or any(
            not isinstance(t, UUID) or not isinstance(d, str) or not d
            for t,d in tenant_dsns.items()
        ):
            raise VaultOperationError("vault_backend_unavailable")
        self._tenants = dict(tenant_dsns)

    def __repr__(self):
        return "<ServerVaultConnections redacted>"

    def __call__(self, tenant: UUID) -> PgTenantVaultConnection:
        dsn = self._tenants.get(tenant)
        if not dsn:
            raise VaultOperationError("vault_backend_unavailable")
        return PgTenantVaultConnection(dsn)


class ProfileVaultService:
    """BFF/agent-internal service; never expose its plaintext via public API.

    RLS + an independent SESSION_USER identity check prevent misrouted pools.
    Returns success only after the PostgreSQL transaction commits.
    """

    def __init__(
        self,
        connections: Callable[[UUID], PgTenantVaultConnection],
        cipher: ProfileEnvelopeCipher,
    ):
        if not isinstance(cipher, ProfileEnvelopeCipher):
            raise VaultOperationError("vault_backend_unavailable")
        self._connections = connections
        self._cipher = cipher

    def __repr__(self):
        return "<ProfileVaultService redacted>"

    def save(
        self, *, tenant: UUID, workspace: UUID, profile: UUID,
        expected_previous: int, key_id: str, plaintext: bytes,
    ) -> int:
        if type(expected_previous) is not int or not 0 <= expected_previous < 2**63 - 1:
            raise VaultOperationError("invalid_expected_revision")
        # Encryption is performed locally; no secret reaches SQL as plaintext.
        envelope = self._cipher.seal(
            tenant_id=tenant,workspace_id=workspace,profile_id=profile,
            revision=expected_previous + 1,key_id=key_id,plaintext=plaintext
        )
        try:
            with self._connections(tenant) as db:
                if db.authenticated_tenant() != tenant:
                    raise VaultOperationError("tenant_binding_unavailable")
                code, revision = db.append(envelope, expected_previous)
                if code == "created" and revision == expected_previous + 1:
                    pass
                elif code in {"revision_conflict", "profile_not_available", "unauthorized"}:
                    raise VaultOperationError(code)
                else:
                    raise VaultOperationError("vault_write_unavailable")
            return expected_previous + 1
        except VaultOperationError:
            raise
        except Exception:
            raise VaultOperationError("vault_backend_unavailable") from None

    def load(
        self, *, tenant: UUID, workspace: UUID, profile: UUID
    ) -> VaultState | None:
        try:
            with self._connections(tenant) as db:
                if db.authenticated_tenant() != tenant:
                    raise VaultOperationError("tenant_binding_unavailable")
                envelope = db.latest(tenant, workspace, profile)
            if envelope is None:
                return None
            plaintext = self._cipher.open(
                envelope, tenant_id=tenant, workspace_id=workspace,
                profile_id=profile, revision=envelope.revision
            )
            return VaultState(revision=envelope.revision, plaintext=plaintext)
        except (EnvelopeError, VaultOperationError):
            # Do not include a key name, SQL statement or any profile bytes.
            raise VaultOperationError("vault_read_unavailable") from None
        except Exception:
            raise VaultOperationError("vault_backend_unavailable") from None
