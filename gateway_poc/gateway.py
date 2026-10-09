"""Isolated authenticated, tenant-scoped BFF proof. NEVER attach to live Steel.

Only loopback HTTP, disposable Postgres, no real sessions or logins.
The synthetic worker is not reachable via HTTP and makes no provider calls.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from hmac import compare_digest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import psycopg


COOKIE_NAME = "__Host-aib_session"
TOKEN_RE = re.compile(r"^[a-zA-Z0-9_-]{43}$")
ID_RE = re.compile(r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$")
GET_TASK = re.compile(r"^/api/tasks/([a-f0-9-]{36})$")
POST_TASK = re.compile(r"^/api/workspaces/([a-f0-9-]{36})/tasks$")


class Rejection(Exception):
    def __init__(self, status: int, code: str):
        super().__init__(code)
        self.status = status
        self.code = code


@dataclass(frozen=True)
class Principal:
    """Constructed by the server only, never from request-body tenant_id."""
    tenant_id: UUID
    user_id: UUID
    csrf_sha256: str = field(repr=False)


def canonical_uuid(value: str) -> UUID:
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise Rejection(400, "invalid_identifier")
    try:
        result = UUID(value)
    except (ValueError, AttributeError):
        raise Rejection(400, "invalid_identifier") from None
    if str(result) != value:
        raise Rejection(400, "invalid_identifier")
    return result


def strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate field")
        out[key] = value
    return out


def read_cookie(raw: str | None) -> str:
    if not isinstance(raw, str) or len(raw) > 1024:
        raise Rejection(401, "session_required")
    found = []
    for part in raw.split(";"):
        key, separator, value = part.strip().partition("=")
        if separator and key == COOKIE_NAME:
            found.append(value)
    if len(found) != 1 or not TOKEN_RE.fullmatch(found[0]):
        raise Rejection(401, "session_required")
    return found[0]


def token_hash(raw: str) -> str:
    return sha256(raw.encode("ascii")).hexdigest()


@dataclass
class Gateway:
    """Two separate DB connection identities: auth reader and tenant role.

    Production needs an audited issuer, real TLS and securely provisioned
    per-tenant DB credentials. PostgreSQL trust is CI-only.
    """
    host: str
    port: int
    tenant_roles: dict[UUID, str]
    auth_role: str = "aib_auth_reader"

    def _connect(self, role: str):
        if not re.fullmatch(r"[a-z][a-z_0-9]{1,62}", role):
            raise Rejection(503, "database_unavailable")
        return psycopg.connect(
            host=self.host, port=self.port, dbname="postgres",
            user=role, connect_timeout=3, autocommit=True
        )

    def authenticate(self, raw_cookie: str | None) -> Principal:
        value = read_cookie(raw_cookie)
        try:
            with self._connect(self.auth_role) as db:
                row = db.execute(
                    "SELECT tenant_id,user_id,csrf_sha256 "
                    "FROM browser_product.lookup_api_session(%s)",
                    (token_hash(value),)
                ).fetchone()
        except (psycopg.Error, OSError):
            raise Rejection(503, "identity_service_unavailable") from None
        if row is None:
            raise Rejection(401, "session_required")
        tenant, user, csrf = row
        if not isinstance(tenant, UUID) or not isinstance(user, UUID):
            raise Rejection(503, "identity_service_unavailable")
        if tenant not in self.tenant_roles:
            raise Rejection(403, "workspace_not_allowed")
        return Principal(tenant, user, csrf)

    def tenant_connection(self, p: Principal):
        role = self.tenant_roles.get(p.tenant_id)
        if not role:
            raise Rejection(403, "workspace_not_allowed")
        try:
            conn = self._connect(role)
            own = conn.execute(
                "SELECT browser_product.authenticated_tenant()"
            ).fetchone()
            if not own or own[0] != p.tenant_id:
                conn.close()
                raise Rejection(503, "database_identity_mismatch")
            return conn
        except psycopg.Error:
            raise Rejection(503, "database_unavailable") from None

    def list_workspaces(self, p: Principal) -> list[dict]:
        with self.tenant_connection(p) as db:
            rows = db.execute(
                "SELECT workspace_id,display_name "
                "FROM browser_product.workspaces ORDER BY display_name LIMIT 100"
            ).fetchall()
        return [{"workspace_id": str(w), "name": name} for w, name in rows]

    def get_task(self, p: Principal, task_id: UUID) -> dict:
        with self.tenant_connection(p) as db:
            row = db.execute(
                "SELECT workspace_id,profile_id,state "
                "FROM browser_product.browser_tasks WHERE task_id=%s",
                (task_id,)
            ).fetchone()
        if not row:
            raise Rejection(404, "task_not_found")
        workspace, profile, state = row
        return {"task_id": str(task_id), "workspace_id": str(workspace),
                "profile_id": str(profile), "status": state}

    def queue(self, p: Principal, workspace: UUID, profile: UUID, task: UUID):
        with self.tenant_connection(p) as db:
            # RLS filters profile IDs and workspace ownership. A BFF may not
            # resolve provider_profile_ref or display another tenant's IDs.
            row = db.execute(
                "SELECT profile_id FROM browser_product.profiles "
                "WHERE workspace_id=%s AND profile_id=%s",
                (workspace, profile)
            ).fetchone()
            if not row:
                raise Rejection(404, "profile_not_found")
            inserted = db.execute(
                "INSERT INTO browser_product.browser_tasks "
                "(tenant_id,workspace_id,profile_id,task_id) "
                "VALUES (%s,%s,%s,%s) "
                "ON CONFLICT (tenant_id,task_id) DO NOTHING "
                "RETURNING task_id",
                (p.tenant_id, workspace, profile, task)
            ).fetchone()
            existing = db.execute(
                "SELECT workspace_id,profile_id,state "
                "FROM browser_product.browser_tasks WHERE task_id=%s",
                (task,)
            ).fetchone()
        if not existing or existing[0] != workspace or existing[1] != profile:
            raise Rejection(409, "task_conflict")
        return ({"task_id": str(task), "status": existing[2]}, 201 if inserted else 200)


class BffHttpServer(ThreadingHTTPServer):
    """No production environment integration, deliberately loopback-only."""
    def __init__(self, gateway: Gateway):
        super().__init__(("127.0.0.1", 0), BffHandler)
        self.gateway = gateway
        self.origin = "http://127.0.0.1:" + str(self.server_port)


class BffHandler(BaseHTTPRequestHandler):
    server: BffHttpServer

    def log_message(self, *_args):
        # Do not log cookies, paths, CSRF, content or third-party errors.
        pass

    def reply(self, status: int, data: dict | list):
        encoded = json.dumps(data, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        for k, v in {
            "Content-Type": "application/json",
            "Content-Length": str(len(encoded)),
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "Content-Security-Policy": "default-src 'none'",
        }.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(encoded)

    def _validate_host(self):
        raw = self.headers.get_all("Host", [])
        expected = "127.0.0.1:" + str(self.server.server_port)
        if raw != [expected]:
            raise Rejection(403, "request_rejected")
        if any(k.lower() in {
            "forwarded", "x-forwarded-host", "x-forwarded-proto",
            "x-original-host", "x-real-ip",
        } for k in self.headers.keys()):
            raise Rejection(403, "request_rejected")

    def _principal(self):
        self._validate_host()
        cookies = self.headers.get_all("Cookie", [])
        if len(cookies) != 1:
            raise Rejection(401, "session_required")
        return self.server.gateway.authenticate(cookies[0])

    def _path(self):
        if len(self.path) > 512:
            raise Rejection(404, "not_found")
        parsed = urlsplit(self.path)
        if parsed.query or parsed.fragment or parsed.path != self.path:
            raise Rejection(404, "not_found")
        return parsed.path

    def _run(self, method: str):
        try:
            path = self._path()
            if method == "GET":
                if path != "/api/workspaces" and not GET_TASK.fullmatch(path):
                    raise Rejection(404, "not_found")
                p = self._principal()
                if path == "/api/workspaces":
                    self.reply(200, {"workspaces": self.server.gateway.list_workspaces(p)})
                else:
                    match = GET_TASK.fullmatch(path)
                    task = canonical_uuid(match.group(1))
                    self.reply(200, self.server.gateway.get_task(p, task))
                return

            match = POST_TASK.fullmatch(path) if method == "POST" else None
            if not match:
                raise Rejection(404, "not_found")
            p = self._principal()
            origin = self.headers.get_all("Origin", [])
            if origin != [self.server.origin]:
                raise Rejection(403, "csrf_rejected")
            if self.headers.get("Sec-Fetch-Site", "same-origin") not in ("same-origin", "none"):
                raise Rejection(403, "csrf_rejected")
            csrf = self.headers.get_all("X-AIB-CSRF", [])
            if len(csrf) != 1 or not TOKEN_RE.fullmatch(csrf[0]):
                raise Rejection(403, "csrf_rejected")
            if not compare_digest(token_hash(csrf[0]), p.csrf_sha256):
                raise Rejection(403, "csrf_rejected")
            if self.headers.get_all("Content-Type", []) != ["application/json"]:
                raise Rejection(415, "json_required")
            sizes = self.headers.get_all("Content-Length", [])
            if len(sizes) != 1 or not sizes[0].isdigit():
                raise Rejection(400, "body_required")
            size = int(sizes[0])
            if size < 2 or size > 2048 or self.headers.get("Transfer-Encoding"):
                raise Rejection(413, "invalid_body_size")
            raw = self.rfile.read(size)
            if len(raw) != size:
                raise Rejection(400, "invalid_json")
            try:
                payload = json.loads(raw.decode("utf-8"), object_pairs_hook=strict_object,
                                     parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            except (ValueError, UnicodeError):
                raise Rejection(400, "invalid_json") from None
            if not isinstance(payload, dict) or set(payload) != {"profile_id", "task_id"}:
                raise Rejection(400, "invalid_fields")
            workspace = canonical_uuid(match.group(1))
            profile = canonical_uuid(payload["profile_id"])
            task = canonical_uuid(payload["task_id"])
            data, code = self.server.gateway.queue(p, workspace, profile, task)
            self.reply(code, data)
        except Rejection as e:
            self.reply(e.status, {"error": e.code})
        except (psycopg.Error, OSError, OverflowError, TypeError):
            self.reply(503, {"error": "service_unavailable"})

    def do_GET(self):
        self._run("GET")

    def do_POST(self):
        self._run("POST")

    def do_HEAD(self):
        self.reply(405, {"error": "method_not_allowed"})
