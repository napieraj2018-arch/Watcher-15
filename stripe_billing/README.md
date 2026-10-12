# AI Browser — Stripe Billing webhook inbox (draft, not deployed)

**Date: 2026-10-09. Commercial launch still NO-GO.**

Stripe is installed in ChatGPT, but operations on the connected Stripe
account were not exposed to this chat during development. This module uses
**synthetic** event payloads, a fake signing secret, and an ephemeral PostgreSQL
16 test database. It has never charged a customer, created a real product,
issued an invoice, or changed access to a live browser.

## What this proof DOES

1. Accept only an original raw, at most 128 KiB Stripe event body signed by
   a configured `whsec_` endpoint secret. Require correct HMAC SHA-256 and
   a 5-minute timestamp window; allow a carefully bounded secret rotation.
2. Parse JSON after signature verification, rejecting duplicate nested keys,
   malformed IDs, non-finite values and test/live environment mismatches.
3. Admit only specific subscriptions, invoices, Checkout and Stripe
   Entitlements event types, without exposing raw payloads or signatures.
4. Insert each event by its ID atomically into PostgreSQL. Parallel webhook
   retries return HTTP 200 only after commit; the same event with a changed
   digest is a collision rather than silently overwriting data.
5. Resolve Stripe `customer` to tenant ONLY from an independently provisioned,
   private database mapping. Customers absent from that mapping are
   quarantined as `unmapped`. Event `metadata.tenant_id` is NEVER trusted.
6. Grant the webhook-ingestion DB role only `EXECUTE stripe_billing.ingest`,
   not read access to tenant mappings, raw event tables, or any permission
   to change subscriptions, payments or browser profiles.
7. Failed persistence returns HTTP 503, allowing a retry rather than
   acknowledging a lost payment event.
8. **NO PATH in this code grants browser access.** Events merely schedule a
   future server-side reconciliation. This avoids trusting out-of-order
   webhook snapshots.

## How real subscriptions would be enabled (NOT implemented)

- User authenticates to AI Browser via independent IdP/OIDC and verified
  ownership of a tenant. A trusted server creates Checkout or Payment Link
  for a server-owned price and a new/verified Stripe Customer ID.
- When Stripe creates or updates a subscription, a signed webhook enters
  this inbox and triggers a durable reconciliation job.
- An isolated reconciler, using credentials NOT reachable by the webhook
  endpoint, fetches current Stripe subscription status and Stripe
  Entitlements through authenticated Stripe APIs. Reconciliation must check
  the pre-provisioned customer->tenant mapping and plan entitlement before
  updating access atomically. A single `checkout.session.completed` or
  `invoice.paid` event is **not** proof of a valid active browser subscription.
- Each new task requires an unexpired entitlement, tenant isolation,
  per-tenant quota, cost reserve, allowed site and exclusive Steel session.
  Suspension prevents new starts; it must not discard active user data.
- Signed Stripe event ingestion must have rotating webhook secrets, provider
  signature validation, ingress rate limiting, non-public DB connectivity,
  redacted audit logs, dead-letter alerts and recovery of undelivered events.
- Failed payments, cancellation dates, trial transitions, refunds, disputes,
  invoices, taxes, billing portal, downgrade/upgrade and duplicate customer
  mappings need additional explicit state-machine and integration tests.

## What is missing for commercial release

Real Stripe account access; verified products/prices, entitlement mapping and
checkout/portal; webhook endpoint hosted over HTTPS; authenticated worker
readback from Stripe API; production IdP/OIDC; KMS; Postgres tenant RLS;
live Steel integration, delete/retention receipts, SSRF egress and pentest.
Do not deploy this prototype by copying a SQL migration into Floot.

## Run the isolated tests

- Unit: `python -m unittest discover -s stripe_billing/tests -p test_webhook.py -v`.
- PostgreSQL 16: see `.github/workflows/stripe-billing-webhook-proof.yml`.
  The CI job uses only fixture data and 16 parallel connections.
- Do not use real webhook secrets in CI; do not print secrets, signed URLs,
  customer-identifying data, or raw webhook bodies to production logs.

Official reference:
- https://docs.stripe.com/events/manage-webhook-endpoints
- https://docs.stripe.com/billing/entitlements
- https://docs.stripe.com/api/events/types

The existing commercial release gate remains a **NO-GO** until independent
security and legal sign-off.
