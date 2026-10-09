# AI Browser — authenticated BFF proof (NOT DEPLOYED)

This is an **isolated, loopback HTTP proof with real PostgreSQL 16 RLS**,
two independently provisioned test customers and a synthetic slot worker.
It MUST NOT be published to Render, Floot or external customers. It does not
log in to Facebook, Google or Steel; it never reads an existing browser profile.

## What it demonstrates

- A 256-bit server-provisioned opaque session is looked up as SHA-256 via
  a narrowly granted SECURITY DEFINER function. A tenant or user id in an
  HTTP header or JSON does not grant access.
- Server derives an internal Postgres login role from a previously verified
  tenant id, then independently confirms the identity that Postgres derives
  from `session_user`. The actual SELECT and INSERT run with RLS on.
- `GET /api/workspaces`, `GET /api/tasks/<id>` and
  `POST /api/workspaces/<id>/tasks` operate only on that tenant.
- POST requires strict same-origin and a session-bound CSRF proof. Duplicate
  cookies, body fields and malformed UUIDs are rejected. No CORS, no URL
  bearer token, no raw Steel profile ID, no customer data in errors.
- Identical tenant/task UUID is idempotent: exactly one queued task row.
  A conflicting task UUID cannot point to another profile.
- A test-only worker can receive a task that was read through the tenant's
  own DB identity; then it claims the durable Steel slot (another isolated
  SQL module), without contacting Steel. One tenant waits while another
  holds it. The test verifier independently confirms fake provider close
  and fake profile persistence before the slot is released.

## Explicit blockers: NOT a commercial auth system

1. Sessions are inserted only by test provisioning. **No real OAuth,
   passkeys, session rotation, login, logout, password reset, MFA or
   provisioning administration exists.** Production cookies must be issued
   with Secure+HttpOnly+SameSite=Strict on HTTPS.
2. Roles and connection parameters are preconfigured in the trusted process.
   CI uses PostgreSQL `trust` **only on an ephemeral local database**.
   Production requires per-tenant credentials or another audited RLS
   identity mechanism and connection-pool isolation.
3. No external Steel calls, no real screenshots, downloads, uploads, vault
   read, payments or user-generated work are involved.
4. The existing durable slot SQL accepts a tenant-id parameter from a
   privileged worker. The BFF uses a server-verified DB record, but true
   authorization/fencing must also be enforced at the worker boundary.
5. A simulated provider receipt is not real independently signed provider
   evidence. Unexpected timeouts remain quarantined.
6. No production frontend is connected. No quota/replay retention cleanup
   is implemented. A queued database row is not an executed action.
7. PostgreSQL 16 test results do not prove application security without a
   subsequent external pentest and real two-customer end-to-end exercises.

CI launches only a local loopback HTTP server and an ephemeral PostgreSQL
instance with two fixture users, no customer data or cloud keys.
