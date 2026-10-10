"""Safe, owner-beta-only Steel Credentials / CAPTCHA / dedicated-IP session policy.

This module NEVER reads or handles account passwords. Credentials live in
Steel's encrypted Credentials API, keyed by exact origin and a deterministic,
profile-specific HMAC namespace. The profile must be explicitly allowed by
owner-controlled server configuration. No credential is injected by default.

CAPTCHA auto-solving can incur provider charges: explicit profile allowlist +
billing approval are REQUIRED, and provider handling never proves a signed-in
account. MFA/passkeys/SMS/device-approval still require the account owner.

This is NOT per-tenant auth. Public commercial users must use server-bound
tenant+profile identity and independent key/namespace before enabling.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from collections.abc import Mapping


class SessionPolicyError(ValueError):
    """Fixed error code only: never echo environment values or provider data."""


_NAMESPACE_VERSION = b"ai-browser-steel-credential-namespace-v1\x00"
_PROFILE_NAME_RE = re.compile(r"^[^\x00-\x1f\x7f]{1,64}$")
_IP_ID_RE = re.compile(r"^fixed:[A-Za-z0-9_-]{3,64}$")
_MAX_LIST_BYTES = 4096
_MAX_PROFILE_COUNT = 20

def _parse_profiles(raw: object) -> frozenset[str]:
    if raw is None or raw == "":
        return frozenset()
    if not isinstance(raw, str) or len(raw) > _MAX_LIST_BYTES:
        raise SessionPolicyError("STEEL_AUTH_PROFILE_CONFIG_INVALID")
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        raise SessionPolicyError("STEEL_AUTH_PROFILE_CONFIG_INVALID") from None
    if (not isinstance(value, list) or len(value) > _MAX_PROFILE_COUNT
        or any(not isinstance(p, str) or not _PROFILE_NAME_RE.fullmatch(p)
               or p != p.strip() for p in value)
        or len(value) != len(set(value))):
        raise SessionPolicyError("STEEL_AUTH_PROFILE_CONFIG_INVALID")
    return frozenset(value)

def _parse_fixed_ips(raw: object) -> dict[str, str]:
    if raw is None or raw == "":
        return {}
    if not isinstance(raw, str) or len(raw) > _MAX_LIST_BYTES:
        raise SessionPolicyError("STEEL_FIXED_IP_CONFIG_INVALID")
    def no_duplicate_keys(pairs):
        d = {}
        for key, value in pairs:
            if key in d:
                raise ValueError("duplicate")
            d[key] = value
        return d
    try:
        value = json.loads(raw, object_pairs_hook=no_duplicate_keys)
    except (ValueError, TypeError):
        raise SessionPolicyError("STEEL_FIXED_IP_CONFIG_INVALID") from None
    if (not isinstance(value, dict) or len(value) > _MAX_PROFILE_COUNT
        or any(not isinstance(p, str) or not _PROFILE_NAME_RE.fullmatch(p)
               or p != p.strip() or not isinstance(ip, str)
               or not _IP_ID_RE.fullmatch(ip) for p, ip in value.items())):
        raise SessionPolicyError("STEEL_FIXED_IP_CONFIG_INVALID")
    return value

def _namespace_key(encoded: object) -> bytes:
    if not isinstance(encoded, str) or len(encoded) not in (43, 44):
        raise SessionPolicyError("STEEL_CREDENTIAL_NAMESPACE_KEY_MISSING")
    try:
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}=?", encoded):
            raise ValueError("invalid key encoding")
        raw = base64.urlsafe_b64decode(encoded + "=" * ((-len(encoded)) % 4))
        if (len(raw) != 32 or
            base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
            != encoded.rstrip("=")):
            raise ValueError("noncanonical key encoding")
    except (ValueError, TypeError):
        raise SessionPolicyError("STEEL_CREDENTIAL_NAMESPACE_KEY_MISSING") from None
    return raw

def profile_namespace(profile: str, encoded_seed: str) -> str:
    if not isinstance(profile, str) or not _PROFILE_NAME_RE.fullmatch(profile):
        raise SessionPolicyError("STEEL_AUTH_PROFILE_CONFIG_INVALID")
    seed = _namespace_key(encoded_seed)
    digest = hmac.new(seed, _NAMESPACE_VERSION + profile.encode("utf-8"),
                      hashlib.sha256).hexdigest()
    # It is intentionally NOT a credential or a reusable browser session ID.
    # Steel Credentials API must be provisioned in this same namespace.
    return "aib-owner-" + digest[:32]

def _flag(v: object, code: str) -> bool:
    if v in (None, ""):
        return False
    if v == "0":
        return False
    if v == "1":
        return True
    raise SessionPolicyError(code)

def configured_session_payload(
    profile: str, payload: dict, env: Mapping[str, str]
) -> dict:
    """Add vendor-supported options without ever handling login secrets.

    Existing caller owns payload and should pass it only to the exact Steel
    sessions/create endpoint after obtaining an exclusive per-profile lease.
    """
    if not isinstance(profile, str) or not _PROFILE_NAME_RE.fullmatch(profile):
        raise SessionPolicyError("STEEL_AUTH_PROFILE_CONFIG_INVALID")
    if not isinstance(payload, dict) or not isinstance(env, Mapping):
        raise SessionPolicyError("STEEL_AUTH_INVALID_INPUT")

    credential_profiles = _parse_profiles(
        env.get("AI_BROWSER_STEEL_CREDENTIAL_PROFILES"))
    detect_profiles = _parse_profiles(
        env.get("AI_BROWSER_STEEL_CAPTCHA_DETECT_PROFILES"))
    auto_profiles = _parse_profiles(
        env.get("AI_BROWSER_STEEL_CAPTCHA_AUTO_PROFILES"))
    fixed_ips = _parse_fixed_ips(env.get("AI_BROWSER_STEEL_FIXED_IP_PROFILES"))

    # No hidden type coercion / accidental billing from "true", "yes" etc.
    auto_login = _flag(env.get("AI_BROWSER_STEEL_CREDENTIAL_AUTOSUBMIT"),
                       "STEEL_AUTOLOGIN_FLAG_INVALID")
    captcha_approval = _flag(env.get("AI_BROWSER_STEEL_CAPTCHA_BILLING_APPROVED"),
                             "STEEL_CAPTCHA_BILLING_FLAG_INVALID")

    if detect_profiles & auto_profiles:
        raise SessionPolicyError("STEEL_CAPTCHA_POLICY_CONFLICT")
    if auto_profiles and not captcha_approval:
        raise SessionPolicyError("STEEL_CAPTCHA_COST_APPROVAL_REQUIRED")

    # Even if the whole environment is unconfigured, don't mutate it.
    updated = dict(payload)

    if profile in credential_profiles:
        if "namespace" in updated or "credentials" in updated:
            raise SessionPolicyError("STEEL_CREDENTIAL_OPTIONS_CONFLICT")
        namespace = profile_namespace(
            profile, env.get("AI_BROWSER_STEEL_CREDENTIAL_NAMESPACE_SEED", ""))
        updated["namespace"] = namespace
        updated["credentials"] = {
            "autoSubmit": auto_login,
            "blurFields": True,
            "exactOrigin": True,
        }

    if profile in auto_profiles:
        # Exact Steel API documented option. Does NOT imply that all CAPTCHA
        # types or Meta verification/checkpoint challenges can be solved.
        if updated.get("stealthConfig") is not None:
            raise SessionPolicyError("STEEL_CAPTCHA_OPTIONS_CONFLICT")
        updated["solveCaptcha"] = True
    elif profile in detect_profiles:
        if updated.get("stealthConfig") is not None:
            raise SessionPolicyError("STEEL_CAPTCHA_OPTIONS_CONFLICT")
        updated["solveCaptcha"] = True
        updated["stealthConfig"] = {"autoCaptchaSolving": False}

    if profile in fixed_ips:
        if updated.get("useProxy") not in (None, False):
            raise SessionPolicyError("STEEL_PROXY_OPTIONS_CONFLICT")
        updated["useProxy"] = {
            "type": "fixed",
            "id": fixed_ips[profile],
        }

    # Never claim a login. No page, cookie or credential content readback.
    return updated
