"""Stripe Billing webhook inbox: verify signed raw events, never grant access.

Offline candidate. No Stripe API requests, customer charges, real accounts,
secret values, or browser sessions. Production must separately implement
HTTPS ingress, authenticated provider reconciliation and entitlement mapping.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import hmac
import json
import re
import time
from typing import Protocol, Sequence

MAX_BODY = 131_072
MAX_SIGNATURE_HEADER = 2_048
MAX_CLOCK_SKEW = 300
SIGNATURE = re.compile(r"^[a-f0-9]{64}$")
EVENT_ID = re.compile(r"^evt_[A-Za-z0-9]{6,120}$")
CUSTOMER_ID = re.compile(r"^cus_[A-Za-z0-9]{6,120}$")
OBJECT_ID = re.compile(r"^[a-z_]{2,24}_[A-Za-z0-9]{6,120}$")
WATCHED_TYPES = frozenset({
    "checkout.session.completed",
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
    "customer.subscription.paused",
    "customer.subscription.resumed",
    "invoice.paid",
    "invoice.payment_failed",
    "entitlements.active_entitlement_summary.updated",
})


class WebhookRejected(Exception):
    """Fixed error codes: never echo event payload, signature or secret."""
    def __init__(self, code: str, status: int = 400):
        super().__init__(code)
        self.code = code
        self.status = status


def verify_signature(
    raw: bytes, signature_header: str, endpoint_secrets: Sequence[str], *,
    now: int | None = None, tolerance: int = MAX_CLOCK_SKEW,
) -> int:
    """HMAC of timestamp dot ORIGINAL body; accepts multiple rotation keys."""
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_BODY:
        raise WebhookRejected("invalid_size", 413)
    if (type(signature_header) is not str or not signature_header
            or len(signature_header) > MAX_SIGNATURE_HEADER):
        raise WebhookRejected("invalid_signature")
    if not endpoint_secrets or len(endpoint_secrets) > 3 or any(
        type(s) is not str or not s.startswith("whsec_")
        or not 7 <= len(s) <= 256 for s in endpoint_secrets
    ):
        raise WebhookRejected("server_not_configured", 503)
    if type(tolerance) is not int or not 1 <= tolerance <= 900:
        raise WebhookRejected("server_not_configured", 503)

    timestamps: list[str] = []
    signatures: list[str] = []
    parts = signature_header.split(",")
    if len(parts) > 25:
        raise WebhookRejected("invalid_signature")
    for part in parts:
        key, sep, value = part.strip().partition("=")
        if not sep:
            raise WebhookRejected("invalid_signature")
        if key == "t":
            timestamps.append(value)
        elif key == "v1":
            signatures.append(value)
        elif key != "v0":
            raise WebhookRejected("invalid_signature")
    if len(timestamps) != 1 or not signatures or len(signatures) > 10:
        raise WebhookRejected("invalid_signature")
    value = timestamps[0]
    if not re.fullmatch(r"[1-9][0-9]{8,12}", value) or any(
        not SIGNATURE.fullmatch(s) for s in signatures
    ):
        raise WebhookRejected("invalid_signature")
    received = int(value)
    clock = int(time.time()) if now is None else now
    if type(clock) is not int or abs(received - clock) > tolerance:
        raise WebhookRejected("signature_expired")

    signed = value.encode("ascii") + b"." + raw
    valid = False
    for secret in endpoint_secrets:
        expected = hmac.new(secret.encode("utf-8"), signed, sha256).hexdigest()
        for candidate in signatures:
            valid |= hmac.compare_digest(expected, candidate)
    if not valid:
        raise WebhookRejected("invalid_signature")
    return received


def no_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate_key")
        out[key] = value
    return out


@dataclass(frozen=True)
class ValidatedEvent:
    id: str
    type: str
    customer_id: str | None
    object_id: str | None
    livemode: bool
    digest: str


def parse_event(raw: bytes, expected_livemode: bool) -> ValidatedEvent | None:
    if type(expected_livemode) is not bool:
        raise WebhookRejected("server_not_configured", 503)
    try:
        value = json.loads(
            raw.decode("utf-8"), object_pairs_hook=no_duplicate_keys,
            parse_constant=lambda _s: (_ for _ in ()).throw(ValueError()),
        )
    except (ValueError, UnicodeError):
        raise WebhookRejected("invalid_json") from None
    if (not isinstance(value, dict) or value.get("object") != "event"
            or not isinstance(value.get("id"), str)
            or not EVENT_ID.fullmatch(value["id"])
            or type(value.get("livemode")) is not bool):
        raise WebhookRejected("invalid_event")
    if value["livemode"] is not expected_livemode:
        raise WebhookRejected("wrong_environment")
    event_type = value.get("type")
    if not isinstance(event_type, str):
        raise WebhookRejected("invalid_event")
    if event_type not in WATCHED_TYPES:
        return None
    data = value.get("data")
    resource = data.get("object") if isinstance(data, dict) else None
    if not isinstance(resource, dict):
        raise WebhookRejected("invalid_event")
    customer = resource.get("customer")
    customer_id = (customer if isinstance(customer, str)
                   and CUSTOMER_ID.fullmatch(customer) else None)
    object_id = resource.get("id")
    if not isinstance(object_id, str) or not OBJECT_ID.fullmatch(object_id):
        object_id = None
    return ValidatedEvent(
        id=value["id"], type=event_type, customer_id=customer_id,
        object_id=object_id, livemode=value["livemode"],
        digest=sha256(raw).hexdigest(),
    )


class EventInbox(Protocol):
    """Return queued, unmapped, duplicate or collision only after DB commit."""
    def insert(self, event: ValidatedEvent) -> str: ...


class StripeWebhookIngress:
    def __init__(self, inbox: EventInbox, *, secrets: Sequence[str],
                 livemode: bool, clock=time.time):
        self.inbox = inbox
        self.secrets = tuple(secrets)
        self.livemode = livemode
        self.clock = clock

    def accept(self, raw: bytes, header: str) -> tuple[int, dict[str, str]]:
        try:
            verify_signature(raw, header, self.secrets, now=int(self.clock()))
            event = parse_event(raw, self.livemode)
            if event is None:
                return 200, {"status": "ignored"}
            status = self.inbox.insert(event)
            if status in ("queued", "unmapped", "duplicate"):
                return 200, {"status": "received"}
            if status == "collision":
                raise WebhookRejected("event_conflict", 409)
            raise WebhookRejected("storage_unavailable", 503)
        except WebhookRejected as exc:
            return exc.status, {"error": exc.code}
        except Exception:
            # Failed DB commit must trigger Stripe retry, never false success.
            return 503, {"error": "storage_unavailable"}
