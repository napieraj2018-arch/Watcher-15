"""Private HTTPS BFF endpoints for enumerating/resuming/cancelling OWN tasks.

This WSGI prototype does NOT implement login, a provider verifier or the
production MCP exchange. A trusted IdP must provision secure session cookies,
and BFF must supply an actual per-tenant DB and Steel verifier. DO NOT expose
without these pieces: the default provider adapter intentionally denies all.
"""
from __future__ import annotations

from hashlib import sha256
from json import loads
import re
from uuid import UUID

from tenant_security.bff.gate import (
    COOKIE_NAME, MAX_COOKIE_HEADER, Principal, _session_token,
    _csrf_valid, _as_uuid, _strict_json_pairs, _reject_nonfinite,
    _response,
)
from tenant_security.recovery.service import (
    ReattachmentService, RecoveryRejected,
)

ROUTE=re.compile(r"^/api/owner/tasks/([0-9a-fA-F-]{36})/(resume|cancel)$")
LIST_PATH="/api/owner/tasks"
MAX_POST_BODY=256


class AuthenticatedTaskRecoveryHTTP:
    """Explicitly opt-in WSGI BFF; no live application mounts this yet."""

    def __init__(self, session_resolver, recovery: ReattachmentService,
                 *, allowed_origin: str):
        if (not callable(session_resolver)
            or not isinstance(recovery,ReattachmentService)
            or not isinstance(allowed_origin,str)
            or not allowed_origin.startswith("https://")
            or not allowed_origin[8:]
            or any(c in allowed_origin[8:] for c in ("/","@","?","#","\\"))):
            raise ValueError("REATTACH_HTTP_CONFIGURATION_INVALID")
        self.resolve=session_resolver
        self.recovery=recovery
        self.origin=allowed_origin

    def __call__(self, environ, start_response):
        if environ.get("wsgi.url_scheme")!="https":
            return _response(start_response,403,{"error":"tls_required"})
        method=environ.get("REQUEST_METHOD")
        path=environ.get("PATH_INFO")
        match=ROUTE.fullmatch(path or "")
        if path==LIST_PATH and method=="GET":
            action="list"
            task_id=None
        elif match and method=="POST":
            action=match.group(2)
            task_id=_as_uuid(match.group(1))
            if task_id is None:
                return _response(start_response,404,{"error":"not_found"})
        else:
            return _response(start_response,404,{"error":"not_found"})

        # The browser Cookie header is never logged, echoed, or used as a
        # caller-controlled tenant. The existing BFF resolver only receives
        # the SHA-256 digest; DB verifies membership, expiry and revocation.
        token=_session_token(environ.get("HTTP_COOKIE"))
        if token is None:
            return _response(start_response,401,{"error":"unauthorized"})
        digest=sha256(token.encode("ascii")).hexdigest()
        try:
            principal=self.resolve(digest)
        except Exception:
            return _response(start_response,503,{"error":"auth_unavailable"})
        if principal is None:
            return _response(start_response,401,{"error":"unauthorized"})
        if (not isinstance(principal,Principal)
            or not isinstance(principal.tenant_id,UUID)
            or not isinstance(principal.user_id,UUID)
            or principal.access_role not in {"viewer","operator","admin"}):
            return _response(start_response,503,{"error":"identity_unavailable"})
        if principal.access_role not in {"operator","admin"}:
            return _response(start_response,403,{"error":"forbidden"})

        raw_csrf=environ.get("HTTP_X_AIB_CSRF")
        if not _csrf_valid(raw_csrf,principal.csrf_digest):
            return _response(start_response,403,{"error":"csrf_rejected"})
        csrf_digest=sha256(raw_csrf.encode("ascii")).hexdigest()

        attempt=None
        if method=="POST":
            if environ.get("HTTP_ORIGIN")!=self.origin:
                return _response(start_response,403,{"error":"origin_rejected"})
            if str(environ.get("CONTENT_TYPE","")).split(";",1)[0].strip().lower()!="application/json":
                return _response(start_response,415,{"error":"unsupported_media_type"})
            try:
                size=int(environ.get("CONTENT_LENGTH","-1"))
                if not 2<=size<=MAX_POST_BODY:
                    return _response(start_response,413,{"error":"invalid_size"})
                payload=environ["wsgi.input"].read(size)
                if len(payload)!=size:
                    return _response(start_response,400,{"error":"invalid_length"})
                body=loads(payload,object_pairs_hook=_strict_json_pairs,
                           parse_constant=_reject_nonfinite)
            except (KeyError,ValueError,TypeError,UnicodeError):
                return _response(start_response,400,{"error":"invalid_json"})
            if not isinstance(body,dict):
                return _response(start_response,400,{"error":"invalid_fields"})
            if action=="resume":
                if set(body)!={"attempt_id"}:
                    return _response(start_response,400,{"error":"invalid_fields"})
                attempt=_as_uuid(body["attempt_id"])
                if attempt is None:
                    return _response(start_response,400,{"error":"invalid_attempt"})
            elif body:
                return _response(start_response,400,{"error":"invalid_fields"})

        try:
            if action=="list":
                rows=self.recovery.list_tasks(principal=principal,
                    session_digest=digest,csrf_digest=csrf_digest)
                return _response(start_response,200,{"tasks":rows})
            if action=="resume":
                result=self.recovery.resume(principal=principal,
                    session_digest=digest,csrf_digest=csrf_digest,
                    task_id=task_id,attempt_id=attempt)
                return _response(start_response,200,{
                    "status":"ticket_issued_mcp_exchange_required",
                    "task_id":str(result.task_id),
                    "attachment_epoch":result.attachment_epoch,
                    "expires_in_seconds":result.expires_in_seconds,
                    "resume_ticket":result.ticket,
                })
            code=self.recovery.cancel_task(principal=principal,
                session_digest=digest,csrf_digest=csrf_digest,task_id=task_id)
            return _response(start_response,202,{
                "status":code,
                "provider_closed":False,
                "profile_saved_verified":False,
            })
        except RecoveryRejected as exc:
            fixed=str(exc)
            if fixed=="REATTACH_TASK_NOT_FOUND":
                return _response(start_response,404,{"error":"not_found"})
            if fixed=="REATTACH_NOT_AUTHORIZED":
                return _response(start_response,403,{"error":"forbidden"})
            if fixed in {"REATTACH_PROVIDER_RECHECK_REQUIRED",
                         "REATTACH_LEASE_CHANGED","REATTACH_NOT_AVAILABLE"}:
                return _response(start_response,409,{"error":"reconciliation_required"})
            return _response(start_response,503,{"error":"backend_unavailable"})
        except Exception:
            return _response(start_response,503,{"error":"backend_unavailable"})
