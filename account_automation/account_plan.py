"""Read-only account routing and preflight checks for AI Browser.

This module does not launch browsers, log in, import credentials or modify any
website. Decisions are advisory: a caller must enforce them in the controller.
Evidence must come from a trusted, current browser observation, not page prose.
Python 3.11+, standard library only.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import math
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

VERSION = "account-plan-1.0"
MAX_FILE_BYTES = 131_072
MAX_EVIDENCE_AGE = 60.0
ID_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z")
PROFILE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._ -]{0,63}\Z")
SERVICES = {"google", "facebook", "instagram", "wordpress", "metricool", "ads", "gsc", "gbp", "hosting"}
STATUSES = {"verified_previously", "login_required", "not_tested", "mapping_required"}
STAGES = {"authenticated", "login_form", "not_authenticated", "verification_required", "unverified", "session_present_unverified", "temporarily_unavailable", "expired"}


class ConfigError(ValueError):
    """Only fixed codes; never echo untrusted input or private account details."""


def _keys(data: Any, allowed: set[str], required: set[str] | None = None) -> dict:
    if not isinstance(data, dict) or set(data) - allowed or not (required or allowed) <= set(data):
        raise ConfigError("INVALID_FIELDS")
    return data


def _string(value: Any, max_length: int = 512, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or len(value) > max_length or (not allow_empty and not value):
        raise ConfigError("INVALID_STRING")
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ConfigError("CONTROL_CHARACTER")
    return value


def https_origin(url: Any) -> str:
    """Strict URL syntax only. This function performs no DNS or network access."""
    try:
        text = _string(url, 2048)
        if re.search(r"\s|\\", text):
            raise ConfigError("INVALID_URL")
        p = urlsplit(text)
        host = p.hostname or ""
        if p.scheme != "https" or p.username is not None or p.password is not None or p.port not in (None, 443):
            raise ConfigError("HTTPS_ORIGIN_REQUIRED")
        if not host or not host.isascii() or host.endswith("."):
            raise ConfigError("INVALID_HOST")
        labels = host.split(".")
        if len(labels) < 2 or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", x) for x in labels):
            raise ConfigError("INVALID_HOST")
        if host.endswith((".localhost", ".local", ".internal", ".invalid")):
            raise ConfigError("NON_PUBLIC_HOST")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ConfigError("IP_ADDRESS_NOT_ALLOWED")
        return "https://" + host
    except (ValueError, TypeError, UnicodeError) as exc:
        if isinstance(exc, ConfigError):
            raise
        raise ConfigError("INVALID_URL") from None


def _identity(raw: Any) -> tuple[str | None, str | None]:
    if raw is None:
        return None, None
    _keys(raw, {"kind", "expected"})
    if not isinstance(raw["kind"], str) or raw["kind"] not in {"email", "username", "account_id"}:
        raise ConfigError("INVALID_IDENTITY_KIND")
    return raw["kind"], _string(raw["expected"], 254)


@dataclass(frozen=True)
class Account:
    account_id: str
    workspace: str
    service: str
    profile: str | None
    entry_url: str | None
    allowed_origins: tuple[str, ...]
    identity_kind: str | None
    expected_identity: str | None
    resource_kind: str | None
    expected_resource: str | None
    previous_status: str

    @classmethod
    def from_dict(cls, raw: dict) -> "Account":
        _keys(raw, {"account_id", "workspace", "service", "profile", "entry_url", "allowed_origins", "identity", "resource", "previous_status"})
        for field in ("account_id", "workspace"):
            if not isinstance(raw[field], str) or not ID_RE.fullmatch(raw[field]):
                raise ConfigError("INVALID_ACCOUNT_ID")
        if (not isinstance(raw["service"], str) or raw["service"] not in SERVICES or
                not isinstance(raw["previous_status"], str) or raw["previous_status"] not in STATUSES):
            raise ConfigError("INVALID_ACCOUNT_CATEGORY")
        profile = raw["profile"]
        if profile is not None and (not isinstance(profile, str) or not PROFILE_RE.fullmatch(profile)):
            raise ConfigError("INVALID_PROFILE")
        origins = raw["allowed_origins"]
        if (not isinstance(origins, list) or len(origins) > 20 or
                any(not isinstance(x, str) for x in origins) or len(set(origins)) != len(origins)):
            raise ConfigError("INVALID_ORIGINS")
        if any(https_origin(x) != x for x in origins):
            raise ConfigError("ORIGINS_MUST_BE_CANONICAL")
        entry = raw["entry_url"]
        if entry is not None:
            if https_origin(entry) not in origins:
                raise ConfigError("ENTRY_ORIGIN_NOT_ALLOWED")
            # Do not store login redirects, access tokens or capability fragments.
            if urlsplit(entry).query or urlsplit(entry).fragment:
                raise ConfigError("ENTRY_QUERY_OR_FRAGMENT_NOT_ALLOWED")
        identity_kind, identity_value = _identity(raw["identity"])
        resource_kind = resource_value = None
        if raw["resource"] is not None:
            _keys(raw["resource"], {"kind", "expected"})
            resource_kind = _string(raw["resource"]["kind"], 64)
            resource_value = _string(raw["resource"]["expected"], 256)
        return cls(raw["account_id"], raw["workspace"], raw["service"], profile, entry,
                   tuple(origins), identity_kind, identity_value, resource_kind, resource_value,
                   raw["previous_status"])


def load_registry(data: dict) -> dict[str, Account]:
    _keys(data, {"schema_version", "accounts"})
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ConfigError("UNSUPPORTED_SCHEMA")
    rows = data["accounts"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= 100:
        raise ConfigError("INVALID_ACCOUNT_COUNT")
    result: dict[str, Account] = {}
    profile_workspaces: dict[str, str] = {}
    for row in rows:
        account = Account.from_dict(row)
        if account.account_id in result:
            raise ConfigError("DUPLICATE_ACCOUNT")
        if account.profile:
            previous = profile_workspaces.setdefault(account.profile, account.workspace)
            if previous != account.workspace:
                raise ConfigError("PROFILE_SHARED_BETWEEN_WORKSPACES")
        result[account.account_id] = account
    return result


@dataclass(frozen=True)
class Decision:
    account_id: str
    next_action: str
    reason: str
    profile: str | None = None
    entry_url: str | None = None
    allow_read: bool = False
    allow_write: bool = False
    login_attempts: int = 0


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def plan(account: Account, sessions: list[dict], *, owned_session_id: str | None = None,
         observation: dict | None = None, now: float, operation: str = "read") -> Decision:
    """Choose a non-destructive next step; NEVER execute it here.

    `owned_session_id` must be assigned by the orchestrator, not guessed from
    the profile name. An observation is bound to that session and current URL.
    No historical status grants access. For now, all writes require a separate
    authorized workflow. This is not a distributed lease or security boundary.
    """
    def answer(action: str, reason: str, **kwargs: Any) -> Decision:
        return Decision(account.account_id, action, reason, **kwargs)

    if not _finite(now):
        return answer("stop", "INVALID_CLOCK")
    if operation != "read":
        return answer("stop", "SEPARATE_WRITE_AUTHORIZATION_REQUIRED")
    if not account.profile or not account.entry_url or not account.allowed_origins:
        return answer("complete_mapping", "ACCOUNT_MAPPING_INCOMPLETE")
    if not isinstance(sessions, list) or any(not isinstance(s, dict) for s in sessions):
        return answer("stop", "SESSION_STATE_INVALID")
    # This controller is currently capped at one browser session.
    if not sessions:
        if owned_session_id is not None:
            return answer("reconcile_session", "OWNED_SESSION_DISAPPEARED")
        return answer("start_read_only", "INSPECT_SAVED_PROFILE_FIRST", profile=account.profile,
                      entry_url=account.entry_url)
    if len(sessions) != 1:
        return answer("wait", "SESSION_CAPACITY_OR_STATE_CONFLICT")
    current = sessions[0]
    if not owned_session_id or current.get("session_id") != owned_session_id:
        return answer("wait", "ANOTHER_TASK_OWNS_BROWSER")
    if current.get("profile") != account.profile:
        return answer("stop", "PROFILE_MISMATCH")
    if current.get("mode") != "read_only":
        return answer("stop", "READ_ONLY_SESSION_REQUIRED")
    try:
        current_origin = https_origin(current.get("url"))
    except ConfigError:
        return answer("inspect_page", "CURRENT_PAGE_NOT_VERIFIED")
    if current_origin not in account.allowed_origins:
        return answer("stop", "CURRENT_ORIGIN_MISMATCH")
    if observation is None:
        return answer("inspect_page", "FRESH_ACCOUNT_EVIDENCE_REQUIRED")
    required = {"session_id", "url", "observed_at", "stage", "authenticated", "identity_kind", "identity", "resource_kind", "resource", "proof"}
    try:
        _keys(observation, required)
    except ConfigError:
        return answer("stop", "OBSERVATION_FIELDS_INVALID")
    stamp = observation["observed_at"]
    if not _finite(stamp) or not 0 <= now - stamp <= MAX_EVIDENCE_AGE:
        return answer("inspect_page", "STALE_OR_INVALID_EVIDENCE")
    if observation["session_id"] != owned_session_id or observation["url"] != current.get("url"):
        return answer("inspect_page", "EVIDENCE_SESSION_OR_PAGE_CHANGED")
    if (not isinstance(observation["stage"], str) or observation["stage"] not in STAGES or
            (observation["authenticated"] is not None and type(observation["authenticated"]) is not bool)):
        return answer("stop", "OBSERVATION_AUTH_INVALID")
    if observation["stage"] == "verification_required":
        return answer("pause", "VERIFICATION_REQUIRED_NO_AUTOMATIC_RETRY")
    if observation["stage"] in {"login_form", "not_authenticated"}:
        return answer("pause", "LOGIN_COMPONENT_NOT_CONNECTED")
    if observation["stage"] != "authenticated" or observation["authenticated"] is not True:
        return answer("inspect_page", "AUTHENTICATION_UNCONFIRMED_NO_LOGIN_RETRY")
    if observation["proof"] != "protected_page_and_identity":
        return answer("inspect_identity", "STRONG_ACCOUNT_EVIDENCE_REQUIRED")
    if not account.identity_kind or not account.expected_identity:
        return answer("complete_identity", "EXPECTED_IDENTITY_NOT_CONFIGURED")
    expected, actual = account.expected_identity, observation["identity"]
    if not isinstance(actual, str):
        return answer("inspect_identity", "ACTUAL_IDENTITY_NOT_FOUND")
    if account.identity_kind == "email":
        expected, actual = expected.casefold(), actual.casefold()
    if observation["identity_kind"] != account.identity_kind or actual != expected:
        return answer("stop", "ACCOUNT_IDENTITY_MISMATCH")
    if account.service in {"ads", "gsc", "gbp", "metricool"} and account.expected_resource is None:
        return answer("complete_resource", "EXPECTED_BUSINESS_RESOURCE_NOT_CONFIGURED")
    if account.expected_resource is not None:
        if (observation["resource_kind"] != account.resource_kind or
                observation["resource"] != account.expected_resource):
            return answer("inspect_resource", "BUSINESS_RESOURCE_NOT_CONFIRMED")
    return answer("reuse_read_only", "CORRECT_ACCOUNT_AND_RESOURCE_VERIFIED", profile=account.profile,
                  allow_read=True)


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict:
    output = {}
    for key, value in pairs:
        if key in output:
            raise ConfigError("DUPLICATE_JSON_KEY")
        output[key] = value
    return output


def read_json(path: Path) -> Any:
    with path.open("rb") as stream:
        data = stream.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise ConfigError("FILE_TOO_LARGE")
    try:
        return json.loads(data, object_pairs_hook=_reject_duplicates,
                          parse_constant=lambda _: (_ for _ in ()).throw(ConfigError("INVALID_NUMBER")))
    except (UnicodeError, json.JSONDecodeError):
        raise ConfigError("INVALID_JSON") from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate AI Browser metadata. No browser or login actions.")
    parser.add_argument("registry", type=Path)
    args = parser.parse_args(argv)
    try:
        registry = load_registry(read_json(args.registry))
        configured = sum(bool(a.profile and a.entry_url) for a in registry.values())
        result = {"ok": True, "version": VERSION, "accounts": len(registry),
                  "routing_configured": configured, "mapping_required": len(registry) - configured,
                  "credentials_imported": 0, "browser_actions_executed": 0}
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (ConfigError, TypeError, OSError):
        print(json.dumps({"ok": False, "error": "REGISTRY_VALIDATION_FAILED"}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
