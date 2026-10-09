"""Experimental per-tenant AES-256-GCM profile envelopes.

No real customer state, Steel profiles or Floot vault are handled here.
Supply tenant-scoped keys from an authenticated KMS in a future deployment.
Never log plaintext, envelope ciphertext or tenant keys.
"""
from __future__ import annotations

from dataclasses import dataclass
from re import fullmatch
from secrets import token_bytes
from typing import Mapping
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAX_PLAINTEXT_BYTES = 8_000_000
NONCE_BYTES = 12
SCHEMA_TAG = b"AI_BROWSER_PROFILE_V1"


class EnvelopeError(ValueError):
    """Fixed public error; deliberately excludes profile data and key IDs."""


@dataclass(frozen=True, repr=False)
class ProfileEnvelope:
    tenant_id: UUID
    workspace_id: UUID
    profile_id: UUID
    revision: int
    key_id: str
    nonce: bytes
    ciphertext: bytes

    def __repr__(self) -> str:
        return "<ProfileEnvelope redacted>"


class TenantKeyring:
    """In-memory test adapter only; production needs a KMS with audited scopes."""

    def __init__(self, tenant_keys: Mapping[UUID, Mapping[str, bytes]]):
        self._keys: dict[UUID, dict[str, bytes]] = {}
        for tenant, bundle in tenant_keys.items():
            if not isinstance(tenant, UUID) or not isinstance(bundle, Mapping):
                raise EnvelopeError("key_configuration_invalid")
            self._keys[tenant] = {}
            for kid, key in bundle.items():
                if not isinstance(kid, str) or fullmatch(r"[A-Za-z0-9_-]{1,64}", kid) is None:
                    raise EnvelopeError("key_configuration_invalid")
                if type(key) is not bytes or len(key) != 32:
                    raise EnvelopeError("key_configuration_invalid")
                self._keys[tenant][kid] = key

    def __repr__(self):
        return "<TenantKeyring redacted>"

    def fetch(self, tenant_id: UUID, key_id: str) -> bytes:
        try:
            return self._keys[tenant_id][key_id]
        except (KeyError, TypeError):
            raise EnvelopeError("key_unavailable") from None


def _aad(tenant: UUID, workspace: UUID, profile: UUID, revision: int) -> bytes:
    if (not all(isinstance(value, UUID) for value in (tenant, workspace, profile))
            or type(revision) is not int or revision < 1 or revision >= 2**63):
        raise EnvelopeError("invalid_profile_binding")
    return (SCHEMA_TAG + tenant.bytes + workspace.bytes
            + profile.bytes + revision.to_bytes(8, "big"))


class ProfileEnvelopeCipher:
    def __init__(self, keyring: TenantKeyring):
        if not isinstance(keyring, TenantKeyring):
            raise EnvelopeError("key_configuration_invalid")
        self._keyring = keyring

    def seal(
        self, *,
        tenant_id: UUID,
        workspace_id: UUID,
        profile_id: UUID,
        revision: int,
        key_id: str,
        plaintext: bytes,
    ) -> ProfileEnvelope:
        binding = _aad(tenant_id, workspace_id, profile_id, revision)
        if type(plaintext) is not bytes or not 1 <= len(plaintext) <= MAX_PLAINTEXT_BYTES:
            raise EnvelopeError("invalid_state_size")
        key = self._keyring.fetch(tenant_id, key_id)
        nonce = token_bytes(NONCE_BYTES)
        ciphertext = AESGCM(key).encrypt(nonce, plaintext, binding)
        return ProfileEnvelope(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            profile_id=profile_id,
            revision=revision,
            key_id=key_id,
            nonce=nonce,
            ciphertext=ciphertext,
        )

    def open(
        self,
        envelope: ProfileEnvelope,
        *,
        tenant_id: UUID,
        workspace_id: UUID,
        profile_id: UUID,
        revision: int,
    ) -> bytes:
        if not isinstance(envelope, ProfileEnvelope):
            raise EnvelopeError("invalid_envelope")
        binding = _aad(tenant_id, workspace_id, profile_id, revision)
        if ((envelope.tenant_id, envelope.workspace_id, envelope.profile_id,
             envelope.revision) != (tenant_id, workspace_id, profile_id, revision)):
            raise EnvelopeError("envelope_authentication_failed")
        if (not isinstance(envelope.nonce, bytes)
                or len(envelope.nonce) != NONCE_BYTES
                or not isinstance(envelope.ciphertext, bytes)
                or not 16 <= len(envelope.ciphertext) <= MAX_PLAINTEXT_BYTES + 16):
            raise EnvelopeError("invalid_envelope")
        key = self._keyring.fetch(tenant_id, envelope.key_id)
        try:
            return AESGCM(key).decrypt(envelope.nonce, envelope.ciphertext, binding)
        except (InvalidTag, ValueError):
            raise EnvelopeError("envelope_authentication_failed") from None

    def reencrypt_next_revision(
        self, envelope: ProfileEnvelope, *, new_key_id: str
    ) -> ProfileEnvelope:
        """Safe key rotation creates a NEW immutable DB revision, not an UPDATE."""
        if not isinstance(envelope, ProfileEnvelope):
            raise EnvelopeError("invalid_envelope")
        if envelope.key_id == new_key_id:
            raise EnvelopeError("rotation_key_unchanged")
        plaintext = self.open(
            envelope, tenant_id=envelope.tenant_id,
            workspace_id=envelope.workspace_id,
            profile_id=envelope.profile_id, revision=envelope.revision,
        )
        return self.seal(
            tenant_id=envelope.tenant_id, workspace_id=envelope.workspace_id,
            profile_id=envelope.profile_id, revision=envelope.revision + 1,
            key_id=new_key_id, plaintext=plaintext,
        )
