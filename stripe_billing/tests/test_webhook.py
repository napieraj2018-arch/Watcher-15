"""Synthetic Stripe webhook security regressions: no credentials or API calls."""
import hashlib
import hmac
import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

from stripe_billing.inbox import (
    MAX_BODY, StripeWebhookIngress, WebhookRejected, verify_signature,
)

SECRET = "whsec_fixture_no_real_keys"
OLD = "whsec_fixture_old_key_not_real"
NOW = 1_800_000_000


def body(event_id="evt_123456ABCDEF", typ="invoice.paid",
         customer="cus_123456ABCDEF", mode=False):
    return json.dumps({
        "id":event_id,"object":"event","type":typ,"livemode":mode,
        "data":{"object":{"id":"in_123456ABCDEF","customer":customer,
                "metadata":{"tenant_id":"not_trusted"}}}
    }, separators=(",", ":")).encode()


def sign(raw, secret=SECRET, timestamp=NOW):
    sig = hmac.new(secret.encode(), str(timestamp).encode()+b"."+raw,
                   hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={sig}"


class FakeInbox:
    def __init__(self, broken=False):
        self.events = {}
        self.known = {"cus_123456ABCDEF"}
        self.entitlements = {}
        self.lock = threading.Lock()
        self.broken = broken

    def insert(self, e):
        if self.broken:
            raise OSError("synthetic db offline")
        with self.lock:
            old = self.events.get(e.id)
            if old is not None:
                return "duplicate" if old == e else "collision"
            self.events[e.id] = e
            return "queued" if e.customer_id in self.known else "unmapped"


def app(inbox=None, secrets=(SECRET,), livemode=False):
    return StripeWebhookIngress(inbox if inbox is not None else FakeInbox(),
            secrets=secrets,livemode=livemode,clock=lambda:NOW)


class WebhookUnitTests(unittest.TestCase):
    def test_valid_and_original_raw_signed_body(self):
        b = body()
        self.assertEqual(verify_signature(b,sign(b),(SECRET,),now=NOW),NOW)
        self.assertEqual(app().accept(b,sign(b))[0],200)

    def test_rotating_endpoint_secret_accepted(self):
        b = body()
        self.assertEqual(app(secrets=(SECRET,OLD)).accept(b,sign(b,OLD))[0],200)

    def test_forged_signature_and_wrong_key_denied(self):
        b = body()
        self.assertEqual(app().accept(b,sign(b,OLD))[0],400)
        self.assertEqual(app().accept(b,b"malformed".decode())[0],400)

    def test_mutated_raw_payload_rejected(self):
        b = body()
        self.assertEqual(app().accept(b.replace(b"invoice.paid",b"invoice.error"),
                                      sign(b))[0],400)

    def test_old_and_future_timestamps_rejected(self):
        b = body()
        for timestamp in [NOW-301,NOW+301]:
            with self.subTest(ts=timestamp):
                self.assertEqual(app().accept(b,sign(b,timestamp=timestamp))[0],400)

    def test_duplicate_timestamps_and_oversize_rejected(self):
        b = body()
        self.assertEqual(app().accept(b,sign(b)+",t="+str(NOW))[0],400)
        self.assertEqual(app().accept(b"x"*(MAX_BODY+1),sign(b))[0],413)

    def test_wrong_environment_not_interchangeable(self):
        b = body(mode=False)
        self.assertEqual(app(livemode=True).accept(b,sign(b))[0],400)

    def test_ignored_event_does_not_create_record(self):
        inbox=FakeInbox()
        b=body(typ="customer.updated")
        self.assertEqual(app(inbox).accept(b,sign(b)),(200,{"status":"ignored"}))
        self.assertEqual(inbox.events,{})

    def test_retries_only_one_event_no_entitlement_grant(self):
        inbox=FakeInbox()
        handler=app(inbox)
        b=body()
        self.assertEqual(handler.accept(b,sign(b))[0],200)
        self.assertEqual(handler.accept(b,sign(b))[0],200)
        self.assertEqual(len(inbox.events),1)
        self.assertEqual(inbox.entitlements,{})

    def test_same_event_id_changed_body_is_conflict(self):
        inbox=FakeInbox()
        handler=app(inbox)
        b=body()
        tampered=body(customer="cus_987654ABCDEF")
        self.assertEqual(handler.accept(b,sign(b))[0],200)
        self.assertEqual(handler.accept(tampered,sign(tampered)),
                         (409,{"error":"event_conflict"}))

    def test_unknown_customer_remains_unmapped(self):
        inbox=FakeInbox()
        b=body(customer="cus_987654ABCDEF")
        self.assertEqual(app(inbox).accept(b,sign(b))[0],200)
        self.assertEqual(inbox.entitlements,{})

    def test_event_order_never_grants_access(self):
        inbox=FakeInbox()
        handler=app(inbox)
        for n,typ in enumerate([
                "customer.subscription.deleted",
                "customer.subscription.created",
                "entitlements.active_entitlement_summary.updated"]):
            b=body(f"evt_ABCDEF12345{n}",typ=typ)
            self.assertEqual(handler.accept(b,sign(b))[0],200)
        self.assertEqual(len(inbox.events),3)
        self.assertEqual(inbox.entitlements,{})

    def test_db_outage_causes_stripe_retry_not_false_success(self):
        b=body()
        self.assertEqual(app(FakeInbox(broken=True)).accept(b,sign(b)),
                         (503,{"error":"storage_unavailable"}))

    def test_duplicate_json_keys_denied(self):
        b=b'{"id":"evt_123456ABCDEF","object":"event","livemode":false,"type":"invoice.paid","data":{"object":{"customer":"cus_123456ABCDEF","customer":"cus_987654ABCDEF"}}}'
        self.assertEqual(app().accept(b,sign(b))[0],400)

    def test_nonfinite_json_denied(self):
        b=b'{"id":"evt_123456ABCDEF","object":"event","livemode":false,"type":"invoice.paid","data":{"object":{"customer":NaN}}}'
        self.assertEqual(app().accept(b,sign(b))[0],400)

    def test_missing_customer_cannot_grant_access(self):
        b=body(customer=None)
        self.assertEqual(app().accept(b,sign(b))[0],200)

    def test_concurrent_duplicate_delivery(self):
        inbox=FakeInbox()
        handler=app(inbox)
        b=body()
        s=sign(b)
        with ThreadPoolExecutor(max_workers=16) as pool:
            statuses=list(pool.map(lambda _i:handler.accept(b,s)[0],range(16)))
        self.assertEqual(statuses,[200]*16)
        self.assertEqual(len(inbox.events),1)
        self.assertEqual(inbox.entitlements,{})


if __name__=="__main__":
    unittest.main(verbosity=2)
