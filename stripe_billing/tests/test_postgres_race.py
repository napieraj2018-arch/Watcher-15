"""Exactly one persisted event across 16 signed webhook deliveries."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import hashlib
import hmac
import json
import psycopg

from stripe_billing.inbox import StripeWebhookIngress
from stripe_billing.postgres import PgEventInbox

DB = dict(host="127.0.0.1",port=5432,dbname="postgres",
          user="fixture_stripe_ingest",autocommit=False)
SECRET = "whsec_fixture_not_real"
NOW = 1_800_000_000
raw=json.dumps({
    "id":"evt_555555EEEEEE","object":"event",
    "type":"customer.subscription.updated","livemode":False,
    "data":{"object":{"id":"sub_555555EEEEEE","customer":"cus_111111AAAAAA"}}
},separators=(",",":")).encode()
signed=str(NOW).encode()+b"."+raw
sig="t="+str(NOW)+",v1="+hmac.new(SECRET.encode(),signed,hashlib.sha256).hexdigest()
barrier=Barrier(16)

def deliver(_):
    ingress=StripeWebhookIngress(
        PgEventInbox(lambda:psycopg.connect(**DB)),
        secrets=(SECRET,),livemode=False,clock=lambda:NOW,
    )
    barrier.wait(timeout=20)
    return ingress.accept(raw,sig)

with ThreadPoolExecutor(max_workers=16) as pool:
    results=list(pool.map(deliver,range(16)))
assert all(status==200 for status,_ in results),results
with psycopg.connect(host="127.0.0.1",port=5432,dbname="postgres",
                     user="postgres",autocommit=True) as conn:
    rows=conn.execute(
        "SELECT state,tenant_id FROM stripe_billing.webhook_events "
        "WHERE event_id='evt_555555EEEEEE'"
    ).fetchall()
    assert len(rows)==1,rows
    assert rows[0][0]=="pending_reconcile",rows
    assert str(rows[0][1])=="11111111-1111-4111-8111-111111111111",rows
print("SIGNED_STRIPE_INBOX_16_CONCURRENT_DELIVERIES_PASS")
