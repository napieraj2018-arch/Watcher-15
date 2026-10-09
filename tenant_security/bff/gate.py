"""Fail-closed WSGI boundary for synthetic browser tenants.

This module does NOT implement login or issue cookies. A separately audited
identity provider must mint high-entropy, Secure/HttpOnly/SameSite session
cookies after authentication. This BFF only consumes server-backed sessions.
Not wired to Floot, MCP, Steel or Render. Never deploy this prototype as-is.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from hmac import compare_digest
from http import HTTPStatus
from io import BytesIO
from json import dumps, loads
import re
from typing import Callable, Protocol
from uuid import UUID, uuid4

COOKIE_NAME = "__Host-aib_session"
COOKIE_VALUE = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
HEX_DIGEST = re.compile(r"^[a-f0-9]{64}$")
CSRF_VALUE = re.compile(r"^[A-Za-z0-9_-]{24,128}$")
ROUTES = re.compile(r"^/api/workspaces/([0-9a-fA-F-]{36})/(profiles|tasks)$")
MAX_BODY = 2048
MAX_COOKIE_HEADER = 4096
RESPONSE_HEADERS = [
    ("Content-Type", "application/json; charset=utf-8"),
    ("Cache-Control", "no-store, private"),
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "no-referrer"),
]


@dataclass(frozen=True)
class Principal:
    """Only produced by a *server-side* session store, never from HTTP claims."""

    tenant_id: UUID
    user_id: UUID
    access_role: str
    csrf_digest: str


class TenantRepository(Protocol):
    def __enter__(self) -> "TenantRepository": ...
    def __exit__(self, exc_type, exc_value, tb): ...
    def authenticated_tenant(self) -> UUID | None: ...
    def workspace_exists(self, tenant_id: UUID, workspace_id: UUID) -> bool: ...
    def list_profiles(self, tenant_id: UUID, workspace_id: UUID) -> list[dict]: ...
    def enqueue(self, tenant_id: UUID, workspace_id: UUID, profile_id: UUID, task_id: UUID) -> bool: ...


def _response(start_response, code: int, payload: dict):
    status = f"{code} {HTTPStatus(code).phrase}"
    start_response(status, RESPONSE_HEADERS.copy())
    return [dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")]


def _session_token(raw_header: object) -> str | None:
    if not isinstance(raw_header, str) or len(raw_header) > MAX_COOKIE_HEADER:
        return None
    matches = []
    for item in raw_header.split(";"):
        key, marker, value = item.strip().partition("=")
        if marker and key == COOKIE_NAME:
            matches.append(value)
    if len(matches) != 1 or not COOKIE_VALUE.fullmatch(matches[0]):
        return None
    return matches[0]


def _as_uuid(value: object) -> UUID | None:
    if not isinstance(value, str):
        return None
    try:
        result = UUID(value)
    except (ValueError, AttributeError):
        return None
    # Reject noncanonical strings / weird UUID variants, to avoid ambiguous paths.
    return result if str(result) == value.lower() else None


def _csrf_valid(provided: object, expected_digest: str) -> bool:
    if (not isinstance(provided, str) or not CSRF_VALUE.fullmatch(provided)
            or not isinstance(expected_digest, str)
            or not HEX_DIGEST.fullmatch(expected_digest)):
        return False
    return compare_digest(sha256(provided.encode("ascii")).hexdigest(), expected_digest)


class TenantBFF:
    """A constrained BFF; upstream login, credentials and data migration absent.

    session_resolver: callable(digest) -> Principal | None, querying auth DB.
    repository_factory: callable(verified_tenant_uuid) -> context-managed RLS DB
    connection whose *session_user* is bound server-side to that tenant.
    """

    def __init__(
        self,
        session_resolver: Callable[[str], Principal | None],
        repository_factory: Callable[[UUID], TenantRepository],
        *,
        allowed_origin: str,
    ):
        if not (allowed_origin.startswith("https://") and "/" not in allowed_origin[8:]
                and "@" not in allowed_origin[8:] and "?" not in allowed_origin):
            raise ValueError("allowed_origin must be a fixed HTTPS origin")
        self.session_resolver = session_resolver
        self.repository_factory = repository_factory
        self.allowed_origin = allowed_origin

    def __call__(self, environ: dict, start_response):
        # Fail closed if TLS termination isn't explicitly trusted by WSGI server.
        if environ.get("wsgi.url_scheme") != "https":
            return _response(start_response, 403, {"error": "tls_required"})
        method = environ.get("REQUEST_METHOD", "")
        match = ROUTES.fullmatch(environ.get("PATH_INFO", ""))
        if not match:
            return _response(start_response, 404, {"error": "not_found"})
        workspace = _as_uuid(match.group(1))
        resource = match.group(2)
        if workspace is None or (method, resource) not in {("GET", "profiles"), ("POST", "tasks")}:
            return _response(start_response, 405, {"error": "route_unavailable"})
        token = _session_token(environ.get("HTTP_COOKIE"))
        if token is None:
            return _response(start_response, 401, {"error": "unauthorized"})
        try:
            principal = self.session_resolver(sha256(token.encode("ascii")).hexdigest())
        except Exception:
            return _response(start_response, 503, {"error": "auth_unavailable"})
        if principal is None:
            return _response(start_response, 401, {"error": "unauthorized"})
        if not isinstance(principal.tenant_id, UUID) or not isinstance(principal.user_id, UUID):
            return _response(start_response, 503, {"error": "identity_unavailable"})
        if principal.access_role not in {"viewer", "operator", "admin"}:
            return _response(start_response, 403, {"error": "forbidden"})

        payload = None
        if method == "POST":
            if principal.access_role not in {"operator", "admin"}:
                return _response(start_response, 403, {"error": "forbidden"})
            if environ.get("HTTP_ORIGIN") != self.allowed_origin:
                return _response(start_response, 403, {"error": "origin_rejected"})
            if not _csrf_valid(environ.get("HTTP_X_AIB_CSRF"), principal.csrf_digest):
                return _response(start_response, 403, {"error": "csrf_rejected"})
            if str(environ.get("CONTENT_TYPE", "")).split(";", 1)[0].strip().lower() != "application/json":
                return _response(start_response, 415, {"error": "unsupported_media_type"})
            try:
                length = int(environ.get("CONTENT_LENGTH", "-1"))
                if length < 1 or length > MAX_BODY:
                    return _response(start_response, 413, {"error": "invalid_size"})
                raw = environ["wsgi.input"].read(length)
                if len(raw) != length:
                    return _response(start_response, 400, {"error": "invalid_length"})
                payload = loads(raw)
            except (ValueError, UnicodeError, KeyError, TypeError):
                return _response(start_response, 400, {"error": "invalid_json"})
            if not isinstance(payload, dict) or set(payload) != {"profile_id"}:
                # Reject state, tenant_id, workspace_id, provider_profile_id, etc.
                return _response(start_response, 400, {"error": "invalid_fields"})
            profile = _as_uuid(payload["profile_id"])
            if profile is None:
                return _response(start_response, 400, {"error": "invalid_profile"})

        try:
            with self.repository_factory(principal.tenant_id) as repo:
                # Independent database session identity assertion catches a
                # misrouted pool / connection user. Never fall back to admin DB.
                if repo.authenticated_tenant() != principal.tenant_id:
                    result_status, result_payload = 503, {"error": "tenant_binding_unavailable"}
                elif not repo.workspace_exists(principal.tenant_id, workspace):
                    result_status, result_payload = 404, {"error": "not_found"}
                elif resource == "profiles":
                    result = repo.list_profiles(principal.tenant_id, workspace)
                    result_status, result_payload = 200, {"profiles": result}
                else:
                    task_id = uuid4()
                    if not repo.enqueue(principal.tenant_id, workspace, profile, task_id):
                        result_status, result_payload = 404, {"error": "not_found"}
                    else:
                        result_status, result_payload = 202, {"task_id": str(task_id), "state": "queued"}
            # Only emit 202 AFTER transaction COMMIT succeeds.
            return _response(start_response, result_status, result_payload)
        except Exception:
            # No stacktrace, SQL, provider identifiers, tokens or cookies in response.
            return _response(start_response, 503, {"error": "backend_unavailable"})


def exercise_wsgi(app, *, method="GET", path="/", cookie=None, csrf=None,
                  origin=None, body=None, scheme="https", content_type="application/json",
                  extra_headers=None):
    """Offline test helper. Real HTTP/TLS ingress remains unverified."""
    incoming = body if isinstance(body, bytes) else dumps(body or {}).encode("utf-8")
    env = {
        "wsgi.url_scheme": scheme,
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "CONTENT_TYPE": content_type,
        "CONTENT_LENGTH": str(len(incoming)),
        "wsgi.input": BytesIO(incoming),
    }
    if cookie is not None:
        env["HTTP_COOKIE"] = cookie
    if csrf is not None:
        env["HTTP_X_AIB_CSRF"] = csrf
    if origin is not None:
        env["HTTP_ORIGIN"] = origin
    env.update(extra_headers or {})
    record = {}
    def start_response(status, headers):
        record["status"] = int(status.split(" ")[0])
        record["headers"] = dict(headers)
    result = b"".join(app(env, start_response))
    return record["status"], loads(result), record["headers"]
