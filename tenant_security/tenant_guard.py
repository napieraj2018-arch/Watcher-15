"""Experimental tenant authorization and envelope isolation primitives.

NOT integrated with the running AI Browser. The product's trusted
authentication middleware must construct Principal; never accept a Principal
dict directly from a browser or tool arguments.

No account cookies, profiles, master keys or customer data are embedded here.
"""
from __future__ import annotations
from dataclasses import dataclass
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from uuid import UUID

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.exceptions import InvalidTag

ROLE_SET = frozenset({"viewer", "operator", "admin", "billing"})
KIND_SET = frozenset({"profile", "session", "file", "job", "log", "billing"})
ACTIONS = frozenset({"view", "operate", "export", "delete", "share", "billing_edit"})
SENSITIVE = frozenset({"export", "delete", "share", "billing_edit"})
CAP_PREFIX = "aibcap1"
VAULT_PREFIX = "aibvault1"
MAX_TOKEN_LENGTH = 2048
MAX_BLOB_LENGTH = 4_000_000


class TenantAccessError(RuntimeError):
    """Return only stable codes without user/resource identifiers."""


def canonical_uuid(value: str) -> str:
    if not isinstance(value, str) or len(value) != 36:
        raise TenantAccessError("INVALID_RESOURCE_IDENTIFIER")
    try:
        identifier = UUID(value)
    except (ValueError, AttributeError, TypeError):
        raise TenantAccessError("INVALID_RESOURCE_IDENTIFIER") from None
    if str(identifier) != value:
        raise TenantAccessError("INVALID_RESOURCE_IDENTIFIER")
    return value


@dataclass(frozen=True)
class Principal:
    tenant_id: str
    user_id: str
    roles: frozenset[str]
    verified_by_backend: bool
    mfa: bool = False

    def __post_init__(self):
        canonical_uuid(self.tenant_id)
        canonical_uuid(self.user_id)
        if (not isinstance(self.roles, frozenset) or not self.roles
                or not self.roles <= ROLE_SET or type(self.verified_by_backend) is not bool
                or type(self.mfa) is not bool):
            raise TenantAccessError("INVALID_PRINCIPAL")


@dataclass(frozen=True)
class Resource:
    tenant_id: str
    resource_id: str
    kind: str

    def __post_init__(self):
        canonical_uuid(self.tenant_id)
        canonical_uuid(self.resource_id)
        if self.kind not in KIND_SET:
            raise TenantAccessError("INVALID_RESOURCE_KIND")


def authorize(principal: Principal, resource: Resource, action: str) -> None:
    """Fail closed for every object operation. UI-supplied tenant IDs are ignored."""
    if not isinstance(principal, Principal) or not principal.verified_by_backend:
        raise TenantAccessError("BACKEND_IDENTITY_REQUIRED")
    if not isinstance(resource, Resource) or action not in ACTIONS:
        raise TenantAccessError("INVALID_AUTHORIZATION_REQUEST")
    if principal.tenant_id != resource.tenant_id:
        raise TenantAccessError("RESOURCE_NOT_ACCESSIBLE")
    if resource.kind == "billing":
        if action not in {"view", "billing_edit"}:
            raise TenantAccessError("RESOURCE_ACTION_MISMATCH")
    elif action == "billing_edit":
        raise TenantAccessError("RESOURCE_ACTION_MISMATCH")
    roles = principal.roles
    if action == "view":
        allowed = (bool(roles & {"billing", "admin"}) if resource.kind == "billing"
                   else bool(roles & {"viewer", "operator", "admin"}))
    elif action == "operate":
        allowed = bool(roles & {"operator", "admin"}) and resource.kind in {"profile", "session", "job", "file"}
    elif action == "billing_edit":
        allowed = bool(roles & {"admin", "billing"})
    else:
        allowed = "admin" in roles
    if not allowed:
        raise TenantAccessError("INSUFFICIENT_ROLE")
    if action in SENSITIVE and not principal.mfa:
        raise TenantAccessError("STEP_UP_AUTHENTICATION_REQUIRED")


def scoped_filter(principal: Principal, kind: str) -> dict[str, str]:
    """Server must use this filter at query time AND enforce database RLS."""
    if not isinstance(principal, Principal) or not principal.verified_by_backend:
        raise TenantAccessError("BACKEND_IDENTITY_REQUIRED")
    if kind not in KIND_SET:
        raise TenantAccessError("INVALID_RESOURCE_KIND")
    return {"tenant_id": principal.tenant_id, "kind": kind}


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise TenantAccessError("INVALID_CAPABILITY")
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _sign(key: bytes, message: bytes) -> bytes:
    if not isinstance(key, bytes) or len(key) < 32:
        raise TenantAccessError("CAPABILITY_KEY_NOT_CONFIGURED")
    return hmac.new(key, message, hashlib.sha256).digest()


def issue_read_capability(principal: Principal, resource: Resource, *,
                          key: bytes, now: int, ttl_seconds: int = 180) -> str:
    """Short-lived READ ONLY bearer capability. No write-capability issuance here."""
    authorize(principal, resource, "view")
    if type(now) is not int or type(ttl_seconds) is not int or not 30 <= ttl_seconds <= 900:
        raise TenantAccessError("INVALID_CAPABILITY_LIFETIME")
    payload = {
        "v": 1, "action": "view", "tenant": principal.tenant_id,
        "subject": principal.user_id, "resource": resource.resource_id,
        "kind": resource.kind, "iat": now, "exp": now + ttl_seconds,
        "nonce": _b64(secrets.token_bytes(16))
    }
    encoded = _b64(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    signature = _b64(_sign(key, (CAP_PREFIX + "." + encoded).encode("ascii")))
    return CAP_PREFIX + "." + encoded + "." + signature


def verify_read_capability(token: str, principal: Principal, resource: Resource,
                           *, key: bytes, now: int) -> None:
    authorize(principal, resource, "view")
    if not isinstance(token, str) or len(token) > MAX_TOKEN_LENGTH:
        raise TenantAccessError("INVALID_CAPABILITY")
    pieces = token.split(".")
    if len(pieces) != 3 or pieces[0] != CAP_PREFIX:
        raise TenantAccessError("INVALID_CAPABILITY")
    body, signature = pieces[1], pieces[2]
    candidate = _unb64(signature)
    required = _sign(key, (CAP_PREFIX + "." + body).encode("ascii"))
    if not hmac.compare_digest(candidate, required):
        raise TenantAccessError("INVALID_CAPABILITY")
    try:
        data = json.loads(_unb64(body), object_pairs_hook=_reject_duplicates)
    except (ValueError, UnicodeError, json.JSONDecodeError, TenantAccessError):
        raise TenantAccessError("INVALID_CAPABILITY") from None
    expected_keys = {"v", "action", "tenant", "subject", "resource", "kind", "iat", "exp", "nonce"}
    if not isinstance(data, dict) or set(data) != expected_keys or data["v"] != 1 or data["action"] != "view":
        raise TenantAccessError("INVALID_CAPABILITY")
    if any(data[k] != expected for k, expected in (
        ("tenant", principal.tenant_id),
        ("subject", principal.user_id),
        ("resource", resource.resource_id),
        ("kind", resource.kind))):
        raise TenantAccessError("CAPABILITY_SCOPE_MISMATCH")
    if (type(now) is not int or type(data["iat"]) is not int or type(data["exp"]) is not int
            or data["exp"] <= now or data["iat"] > now or data["exp"] - data["iat"] > 900
            or data["exp"] - data["iat"] < 30):
        raise TenantAccessError("CAPABILITY_EXPIRED_OR_INVALID")
    if not isinstance(data["nonce"], str) or len(_unb64(data["nonce"])) != 16:
        raise TenantAccessError("INVALID_CAPABILITY")


def _reject_duplicates(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise TenantAccessError("INVALID_CAPABILITY")
        obj[key] = value
    return obj


def _derive_key(master: bytes, tenant: str, resource: str) -> bytes:
    canonical_uuid(tenant)
    canonical_uuid(resource)
    if not isinstance(master, bytes) or len(master) < 32:
        raise TenantAccessError("VAULT_MASTER_KEY_REQUIRED")
    context = ("profile:" + tenant + "/" + resource).encode("ascii")
    return HKDF(algorithm=hashes.SHA256(), length=32,
                salt=b"AIB-TENANT-PROFILE-KDF-v1", info=context).derive(master)


def seal_profile(plain: bytes, tenant: str, resource: str, *, master: bytes) -> str:
    """Reference tenant-scoped encryption design; NOT connected to storage."""
    if not isinstance(plain, bytes) or not 0 < len(plain) <= MAX_BLOB_LENGTH:
        raise TenantAccessError("VAULT_PAYLOAD_SIZE_INVALID")
    secret = _derive_key(master, tenant, resource)
    nonce = os.urandom(12)
    aad = (VAULT_PREFIX + ":" + tenant + ":" + resource).encode("ascii")
    encrypted = AESGCM(secret).encrypt(nonce, plain, aad)
    return VAULT_PREFIX + "." + _b64(nonce + encrypted)


def open_profile(blob: str, tenant: str, resource: str, *, master: bytes) -> bytes:
    secret = _derive_key(master, tenant, resource)
    if not isinstance(blob, str) or len(blob) > 8_000_000 or not blob.startswith(VAULT_PREFIX + "."):
        raise TenantAccessError("VAULT_ENVELOPE_INVALID")
    data = _unb64(blob.split(".", 1)[1])
    if len(data) < 29 or len(data) > MAX_BLOB_LENGTH + 28:
        raise TenantAccessError("VAULT_ENVELOPE_INVALID")
    nonce, ciphertext = data[:12], data[12:]
    aad = (VAULT_PREFIX + ":" + tenant + ":" + resource).encode("ascii")
    try:
        return AESGCM(secret).decrypt(nonce, ciphertext, aad)
    except (InvalidTag, ValueError):
        raise TenantAccessError("VAULT_AUTHENTICATION_FAILED") from None
