# Stripe verified entitlement readback — isolated policy proof

This module is deliberately **NOT a connected Stripe client or payment gateway**.

It demonstrates the access decision a trusted backend should make **after**
reading current subscription, invoice and entitlement information through
authenticated Stripe APIs. Inputs in CI are wholly synthetic and cannot grant
browser access, launch Steel, create Checkout, collect a card or charge money.

## Trust rules

- The tenant is established by an independent server-authenticated identity,
  then mapped to an exact Stripe Customer ID AND Stripe Account ID via a
  private administrator-provisioned binding. Neither source comes from a
  request URL, frontend metadata or webhook JSON.
- Subscription status is checked against an exact allowed Stripe Price ID
  list and the customer's **current** active entitlement feature set.
- Active subscriptions require a confirmed paid latest invoice. Explicitly
  permitted trials may work only until verified trial_end.
- Past due, unpaid, canceled, paused, expired, missing entitlements, unknown
  prices or disabled mappings all fail closed.
- API readback evidence older than five minutes cannot authorize new
  browser starts. The decision is bounded by the shorter of the verified
  subscription period, verified trial period or evidence TTL.
- Reordered Stripe events are merely reconciliation hints. They do not
  override a newer, authenticated current-state readback.
- When multiple subscriptions exist, this prototype picks the shortest
  expiry conservatively. A real production plan upgrade policy remains
  necessary.
- This policy only checks eligibility. It does NOT replace the other P0
  gates: tenant RLS, dedicated vault key and role, persistent Steel lease,
  per-tenant vendor budget, allowed egress, user consent and full erasure.

## Remaining before integration

1. A real Stripe app/account connector or backend Stripe SDK with narrowly
   scoped credentials, versioned API, secure secret store and independent
   verification of the Stripe account.
2. A trustworthy adapter that fetches the complete paginated entitlement
   list, all relevant subscriptions, invoice payment status and price IDs.
   The `VerifiedReadback` dataclass must NEVER be constructible directly
   from user input or a webhook, and only a trusted reconciler with separate
   privileges may write a new access state.
3. Monotonic, durable entitlement updates in PostgreSQL so an older fetch
   cannot overwrite a newer revoked subscription.
4. Production treatment of trial billing, dunning, SCA, proration, refunds,
   chargebacks, multiple subscriptions, customer merges and grace periods.
5. Signed webhook inbox PR #106, provider readback, OIDC, security audit,
   actual 2-tenant Steel tests and the commercial release gate.

CI uses only Python standard-library fixtures. No Stripe key or live
transaction is involved. Current result: **NO-GO for selling accounts**.
