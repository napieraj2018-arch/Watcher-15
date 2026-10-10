# AI Browser — provider cost guard (offline proof, 2026-10-09)

This prototype is not a subscription service. It does not connect to the
customer database, Steel, Stripe or a real billing account. CI uses only
fake tenants, mock receipts and a disposable PostgreSQL 16 container.

## Why it matters

One user can open many tabs or retry a failed request. Charging for browser
time without atomic limits can turn a fixed-price subscription into an
unbounded loss. The vendor-cost ledger reserves enough headroom BEFORE a job
is authorized, then settles only from separately verified provider usage.

## Tested controls

- Database-backed tenant identity is derived from a trusted login role, not
  a browser-supplied tenant ID, header or JSON field.
- Each job has an opaque UUID. Retrying the same ID can never authorize
  another paid browser start.
- The amount to reserve is fixed by a server-side policy and checked against
  monthly actual spending plus still-reserved job costs.
- Locking the tenant's policy row serializes concurrent admission from
  multiple processes, with a separate open-job concurrency limit.
- The worker cannot directly read or modify accounting tables or invent
  evidence. A separate verifier role holds the only settlement grants.
- Settlement must reference a unique receipt. Replays with different amounts
  are rejected. A vendor cost above the reserve is recorded and pauses that
  tenant without interfering with another tenant's budget.
- Releasing unused reserves requires independent proof that the provider
  never started the session, not merely a cancellation button.
- All raw customer cookies and profiles are absent from this repository.
- Sixteen concurrent independent PostgreSQL clients race for four slots;
  at most four admissions are permitted.

## Why this is still NOT ready to sell

1. All metering evidence is fake. A production verifier must confirm actual
   provider charges through an authenticated source. Never accept evidence,
   amount, provider ID or boolean confirmations supplied by a customer.
2. Reservations and creating a Steel session occur in two different systems.
   A durable outbox, verified session ownership, lease fencing and crash
   reconciliation are required before connecting this to a real browser.
3. The reserved unit is illustrative USD cents. It MUST be greater than the
   worst-case vendor expenditure for a chosen task (browser, proxy, CAPTCHA,
   LLM tokens, storage and retries). Unknown cost => reject the job.
4. The total monthly cap limits provider spend, NOT the customer's payments.
   Stripe subscriptions, entitlement checks, invoice/tax handling, refunds,
   failed billing and signed idempotent webhooks remain unimplemented.
5. A crash leaves an unverified reservation held: intentionally fail-closed.
   There is no automatic timeout that silently refunds or makes a session
   available. An independently verified recovery procedure is mandatory.
6. No test for end-of-month jobs, real invoices, network failures, price
   changes, large numbers of tenants, RODO erasure or a provider billing
   correction has yet completed.
7. The PostgreSQL CI service runs with trust authentication on a throwaway
   runner only. Never deploy these roles or this schema directly to Floot
   or Render production.

Test: GitHub Actions workflow commercial-usage-guard.yml.
Commercial release gate: still NO-GO.
