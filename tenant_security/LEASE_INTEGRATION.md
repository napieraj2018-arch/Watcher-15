# Tenant-scoped durable Steel slot — isolated integration (2026-10-09)

**NO-GO / DRAFT / NEVER run this migration on production Floot or Render.**

This proof builds on:
PR #83 RLS → PR #98 server-owned task states → PR #100 queue/quota
→ PR #102 authenticated BFF → PR #103 encrypted profile vault,
plus the independently tested draft PR #97 durable global Steel slot.

It is an integration in **ephemeral PostgreSQL 16** using synthetic UUIDs.
No Steel provider API, real profile, cookie, browser, or paid operation is used.

## What was added

1. `commercial/leases/001_durable_slot.sql` (from PR #97) stores one
   global slot with a generation counter, fencing, quarantines and a
   distinct verifier role for release receipts.
2. `004_tenant_fenced_slot.sql` REVOKES broad `aib_slot_worker` direct
   function grants and introduces restricted `aib_slot_tenant_worker`
   wrappers. Tenant identity comes from a **privileged, server-managed
   PostgreSQL role binding** via `session_user`, never from an arbitrary
   `tenant_id` in the browser request or a custom PostgreSQL GUC.
3. A worker can claim only an existing, QUEUED task for its own tenant
   that references a ready profile in the same tenant/workspace.
   Retrying does not issue a second provider-start instruction.
4. Activating a reserved generation updates its queued task to RUNNING
   **within the same transaction**; a role/lease/epoch mismatch fails.
5. Finishing a lease still requires a receipt authored by a separate
   verifier role. Releasing the remote slot marks the task PAUSED
   (or CANCELLED before start), **never DONE**, because confirmed
   provider closure does not imply the requested user task succeeded.
6. Expired leases are quarantined and cannot be claimed again until
   a separately verified release. A role revoked in the binding table
   cannot claim/extend the lease.

## CI proof

On GitHub Actions a completely fresh PostgreSQL 16 service runs:
- 43 prior BFF/queue Python tests + SQL RLS/queue proof;
- 58 encrypted vault/adapter Python tests + SQL RLS proof;
- PR #97 original lifecycle and 16 independent DB connection tests;
- new tenant-bound task/slot/receipt SQL tests; and
- new 16 real parallel tenant-worker connection test, including forged
  cross-tenant task, stale epochs and fail-closed quarantine.

Passing integrated run:
https://github.com/napieraj2018-arch/Watcher-15/actions/runs/37990960085

CI credentials use PostgreSQL ephemeral `trust` **only in test**.
This is NOT evidence of production credentials or a safe release API.

## P0 still open

- Actual audited and independent readback that Steel truly closed a remote
  session and that its profile and all encrypted state were durably stored.
  The two receipt booleans in CI are synthetic. **Never expose a user API
  that merely submits these booleans.**
- Mapping a real BFF/user/task/lease token to every MCP action, screenshot,
  navigation, and browser-stop control. Prototype has no real Chrome/CDP
  or live Steel calls.
- Rolling this protocol out safely alongside existing live profiles,
  handling partial failures/restarts, restore coherence and zero-overlap.
- Customer login, production credential provisioning and rotation,
  KMS and deletion/retention, GDPR, costs, SLO, WebKit/Chromium and a
  professional independent security review.

**Do not merge the stacked PR chain into production and do not sell the
product based only on these green isolated tests.**
