"""Fail-closed entitlement policy on trusted Stripe API readback ONLY.

NO webhook snapshot, redirect URL, checkout metadata or user JSON is a
verified subscription. This is a synthetic policy candidate, not a Stripe
client, login system, producer of entitlements, or production deployment.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping
from uuid import UUID

FRESH_SECONDS = 300


@dataclass(frozen=True)
class CustomerBinding:
    tenant_id: UUID
    stripe_customer_id: str
    stripe_account_id: str
    livemode: bool
    enabled: bool


@dataclass(frozen=True)
class Subscription:
    customer_id: str
    stripe_id: str
    status: str
    prices: frozenset[str]
    period_end: int
    latest_invoice_paid: bool
    trial_end: int | None = None


@dataclass(frozen=True)
class VerifiedReadback:
    customer_id: str
    stripe_account_id: str
    livemode: bool
    retrieved_at: int
    entitlement_features: frozenset[str]
    subscriptions: tuple[Subscription, ...]


@dataclass(frozen=True)
class Plan:
    code: str
    stripe_price_id: str
    access_feature: str
    allow_trial: bool = False


@dataclass(frozen=True)
class Decision:
    allowed: bool
    code: str
    plan: str | None = None
    expires_at: int | None = None


class EntitlementPolicy:
    """Plans and price IDs are configured ONLY by the trusted server."""
    def __init__(self, plans: Mapping[str, Plan], *,
                 freshness_seconds=FRESH_SECONDS):
        if not plans or not 1 <= freshness_seconds <= 900:
            raise ValueError("invalid_policy")
        if any(k != plan.stripe_price_id or not plan.code
               or not plan.access_feature for k, plan in plans.items()):
            raise ValueError("invalid_plan_map")
        self.plans = dict(plans)
        self.freshness_seconds = freshness_seconds

    def evaluate(self, *, tenant_id: UUID, binding: CustomerBinding,
                 readback: VerifiedReadback | None, now: int) -> Decision:
        if type(now) is not int or not isinstance(tenant_id, UUID):
            return Decision(False, "identity_invalid")
        if binding.tenant_id != tenant_id or not binding.enabled:
            return Decision(False, "tenant_unmapped")
        if readback is None:
            return Decision(False, "provider_unavailable")
        if (readback.customer_id != binding.stripe_customer_id
            or readback.stripe_account_id != binding.stripe_account_id
            or readback.livemode is not binding.livemode):
            return Decision(False, "provider_identity_mismatch")
        if (type(readback.retrieved_at) is not int
            or readback.retrieved_at > now + 30
            or now - readback.retrieved_at > self.freshness_seconds):
            return Decision(False, "provider_evidence_stale")
        if not isinstance(readback.entitlement_features, frozenset):
            return Decision(False, "provider_evidence_invalid")
        if not isinstance(readback.subscriptions, tuple):
            return Decision(False, "provider_evidence_invalid")

        candidates = []
        for subscription in readback.subscriptions:
            if not isinstance(subscription, Subscription):
                return Decision(False, "provider_evidence_invalid")
            if (subscription.customer_id != binding.stripe_customer_id
                or type(subscription.period_end) is not int
                or subscription.period_end <= now
                or not isinstance(subscription.prices, frozenset)):
                continue
            if subscription.status not in {"active", "trialing"}:
                continue
            for price in subscription.prices:
                plan = self.plans.get(price)
                if not plan or plan.access_feature not in readback.entitlement_features:
                    continue
                if (subscription.status == "active"
                    and subscription.latest_invoice_paid is not True):
                    continue
                if subscription.status == "trialing" and (
                    not plan.allow_trial or type(subscription.trial_end) is not int
                    or subscription.trial_end <= now
                ):
                    continue
                expires = min(subscription.period_end, now+self.freshness_seconds)
                if subscription.status == "trialing":
                    expires = min(expires, subscription.trial_end)
                candidates.append(Decision(True, "eligible", plan.code, expires))
        if not candidates:
            return Decision(False, "subscription_not_eligible")
        # Multiple subscriptions: conservatively choose the earliest expiry.
        # Real multi-plan priority would require a separate product policy.
        return min(candidates, key=lambda x: x.expires_at)
