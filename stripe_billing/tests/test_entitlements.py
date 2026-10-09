"""Synthetic Stripe entitlement decisions. Never grants from webhook fields."""
from dataclasses import replace
import unittest
from uuid import UUID
from stripe_billing.entitlements import (
    CustomerBinding, Subscription, VerifiedReadback, Plan, EntitlementPolicy,
)

NOW=1_800_000_000
TENANT=UUID("11111111-1111-4111-8111-111111111111")
OTHER=UUID("22222222-2222-4222-8222-222222222222")
BIND=CustomerBinding(TENANT,"cus_123456ABCDEF","acct_123456ABCDEF",True,True)
POLICY=EntitlementPolicy({
    "price_123456ABCDEF":Plan("solo","price_123456ABCDEF","ai_browser_access"),
    "price_987654ABCDEF":Plan("trial","price_987654ABCDEF","ai_browser_access",True),
})
SUB=Subscription("cus_123456ABCDEF","sub_123456ABCDEF","active",
                 frozenset({"price_123456ABCDEF"}),NOW+3600,True)
FRESH=VerifiedReadback("cus_123456ABCDEF","acct_123456ABCDEF",True,NOW,
                       frozenset({"ai_browser_access"}),(SUB,))


class EntitlementSecurity(unittest.TestCase):
    def decide(self, readback=FRESH, binding=BIND, tenant=TENANT):
        return POLICY.evaluate(tenant_id=tenant,binding=binding,
                               readback=readback,now=NOW)

    def test_verified_paid_active_readback_grants_only_bounded_access(self):
        decision=self.decide()
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.plan,"solo")
        self.assertLessEqual(decision.expires_at,NOW+300)

    def test_no_provider_readback_denied(self):
        self.assertFalse(self.decide(readback=None).allowed)

    def test_old_readback_denied(self):
        self.assertEqual(self.decide(replace(FRESH,retrieved_at=NOW-301)).code,
                         "provider_evidence_stale")

    def test_future_readback_denied(self):
        self.assertFalse(self.decide(replace(FRESH,retrieved_at=NOW+31)).allowed)

    def test_foreign_tenant_denied(self):
        self.assertFalse(self.decide(tenant=OTHER).allowed)

    def test_disabled_mapping_denied(self):
        self.assertFalse(self.decide(binding=replace(BIND,enabled=False)).allowed)

    def test_wrong_stripe_account_denied(self):
        self.assertFalse(self.decide(
            replace(FRESH,stripe_account_id="acct_999999ABCDEF")).allowed)

    def test_wrong_customer_denied(self):
        self.assertFalse(self.decide(
            replace(FRESH,customer_id="cus_999999ABCDEF")).allowed)

    def test_wrong_environment_denied(self):
        self.assertFalse(self.decide(replace(FRESH,livemode=False)).allowed)

    def test_unpaid_subscription_denied(self):
        self.assertFalse(self.decide(replace(
            FRESH,subscriptions=(replace(SUB,latest_invoice_paid=False),))).allowed)

    def test_bad_statuses_denied(self):
        for status in ("canceled","incomplete","past_due","unpaid","paused"):
            with self.subTest(status=status):
                self.assertFalse(self.decide(replace(
                    FRESH,subscriptions=(replace(SUB,status=status),))).allowed)

    def test_expired_billing_period_denied(self):
        self.assertFalse(self.decide(replace(
            FRESH,subscriptions=(replace(SUB,period_end=NOW),))).allowed)

    def test_missing_feature_denied_despite_paid_invoice(self):
        self.assertFalse(self.decide(
            replace(FRESH,entitlement_features=frozenset())).allowed)

    def test_unrecognized_price_denied(self):
        self.assertFalse(self.decide(replace(
            FRESH,subscriptions=(replace(
                SUB,prices=frozenset({"price_UNKNOWN123456"})),))).allowed)

    def test_trial_requires_explicit_opt_in(self):
        eligible_trial=replace(
            SUB,status="trialing",prices=frozenset({"price_987654ABCDEF"}),
            trial_end=NOW+80,latest_invoice_paid=False)
        decision=self.decide(replace(FRESH,subscriptions=(eligible_trial,)))
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.expires_at,NOW+80)

    def test_unapproved_trial_denied(self):
        trial=replace(SUB,status="trialing",trial_end=NOW+120,
                      latest_invoice_paid=False)
        self.assertFalse(self.decide(
            replace(FRESH,subscriptions=(trial,))).allowed)

    def test_malformed_entitlement_list_denied(self):
        self.assertFalse(self.decide(
            replace(FRESH,entitlement_features=["ai_browser_access"])).allowed)


if __name__=="__main__":
    unittest.main(verbosity=2)
