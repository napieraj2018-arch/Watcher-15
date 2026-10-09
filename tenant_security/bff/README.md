# AI Browser — tenant-scoped BFF proof (2026-10-09)

**Prototype only, not running in Render or Floot, not a production deployment.**
This branch is stacked on PR #98, which itself depends on PR #83. Do not merge
directly into ai-browser-cloud or migrate any live profile/cookie database.

## Security boundary and deliberately limited scope

- `002_bff_session_auth.sql` stores opaque-session and CSRF **digests**, an
  authenticated server-side tenant membership, expiry, revocation and role.
  Only `browser_bff_auth` may invoke the security-definer resolver; no
  customer database role may read raw session records.
- `bff/gate.py` consumes a `__Host-aib_session` cookie, resolves the account
  in PostgreSQL and ignores spoofed `X-Tenant-ID` or request-selected state.
  It never issues a session, handles passwords or processes real MFA.
- `bff/postgres.py` selects **server-configured, per-tenant database logins**
  and asserts `browser_product.authenticated_tenant()` before every access.
  It never falls back to superuser or a shared tenant role. Existing RLS and
  composite foreign keys are independently enforced by PostgreSQL.
- Supported proof endpoints only: `GET /api/workspaces/:id/profiles`
  (filtered metadata, no provider references) and
  `POST /api/workspaces/:id/tasks` (enqueues with DB-owned `queued`
  state, explicit Origin+CSRF and operator/admin role).
- All responses are noncacheable. Backend failures return a generic 503.
  No cookies, access tokens or other customer data are copied into CI.

## Test evidence

CI: `Browser product tenant RLS and BFF proof` on ephemeral PostgreSQL 16,
with synthetic tenant A/B users and no external logins or browser sessions.

- 27 positive/negative Python boundary tests: anonymous/forged tenant/
  duplicate cookies/role mismatch/CSRF/Origin/state injection, and fail-closed
  behavior when the database COMMIT fails.
- 8 PostgreSQL-backed integration tests: tenant A/B isolation via actual
  RLS roles, cross-tenant profile rejection, real enqueue state, session
  revocation, permission-denied session table, bad tenant DSN and viewer denial.
- Earlier SQL test suites from PRs #98 and #100, including quota, direct-INSERT blocking, and 16 PostgreSQL connections, run before BFF tests.

Previous BFF-only verified run (31/31, SQL quota not integrated):
https://github.com/napieraj2018-arch/Watcher-15/actions/runs/37983230546

The CI-only PostgreSQL service uses a disposable test-only trust mode.
**Never use trust authentication in production.**

## Known commercial P0 blockers still open

1. Real customer identity provider, secure login, verified cookie issuance,
   CSRF-token bootstrap, recovery, phishing and MFA handoff.
2. Credential provisioning/rotation and pool isolation for per-tenant DB roles;
   separately auditable auth-db role and key management.
3. Safely migrating from Floot's current single shared bearer token and
   global profile-name vault, without ever exposing those records to tenants.
4. Integration with Steel, the MCP permission model, durable lease receipts,
   the job queue, per-tenant quotas and independent provider readbacks.
5. Revocation concurrency, replay resistance, request/audit logging with
   redaction, egress isolation, rate limits, backups, deletion and RODO.
6. Independent penetration and legal reviews, sustained WebKit/Chromium
   end-to-end tests, production load/availability testing and disaster drills.

**CI green means only that the synthetic test boundary worked, NOT that
the application is safe to sell. Product launch remains NO-GO.**

## Incremental quota-BFF integration

Stack on draft PR #100 (atomic queue + tenant quota). The BFF no longer writes
`browser_tasks` directly; it invokes `browser_product.enqueue_task` through
its least-privileged, tenant-bound DB login. Database-returned quota and
idempotency states determine HTTP responses. The same CI now exercises quota
SQL, 16-way DB concurrency, then BFF with actual PostgreSQL.

Do not conflate green CI with a production queue: authentic cookie issuance,
request retry idempotency, cross-service session leasing and spending limits
remain pending. The code remains non-production.
