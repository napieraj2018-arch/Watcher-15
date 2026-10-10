# AI Browser — 2–3 simultaneous browser jobs (PostgreSQL proof)

Status: **DRAFT only** (2026-10-10). The production Steel runtime is still
configured with `manager.max_sessions=1` and `Engine.launch` rejects a
second live remote session. No production settings have been changed.

## Intended UX

The user may queue three independent operations, e.g.:
- watch Facebook groups using `Meta - Monitoring`;
- check Google Ads/GSC using `Google - Architekt`;
- prepare a WordPress article using a separate `WordPress` profile.

Three different profiles can occupy three distinct Chrome/Steel sessions,
with separate tabs and task-bound capabilities. **The same profile always
remains single-writer**, even across different chats and workers. The queued
fourth task must wait; a blocked profile does not block unrelated profiles
unless all three slots are occupied.

## What this experimental schema proves

- Three durable slots (`slot_no` 1/2/3) share one short-lived PostgreSQL
  admission mutex and can remain active concurrently.
- Worker tenant identity comes only from a database-login binding based on
  `session_user`, not a client-provided account id.
- A slot can be reserved only for a real queued task whose encrypted profile
  metadata belongs to that tenant and is in `ready` state.
- A partial unique index forbids any second open slot for the same
  `(tenant_id, profile_id)`, including a quarantined slot.
- The task and lease UUIDs have unique open-slot mappings. Replaying the
  same request returns `should_start=false` and cannot create another
  billable Steel session.
- A generation fencing token prevents stale workers from activating a
  newer occupant's slot.
- `activate` sets the task `running` atomically with slot `active`.
- Expired or uncertain slots become `quarantined`; **timeouts NEVER free
  a provider session automatically**.
- A separate verifier database role must record both provider close and
  profile persistence. The ordinary worker cannot forge the receipt or
  inspect private slot-table rows.
- Releasing a provider does NOT mark a user task `done`. It becomes
  `paused` if running, or `cancelled` if never started.
- The three-slot ledger provides only own-tenant aggregate counts.
- A real PostgreSQL 16 test races **16 independent processes/connections**;
  exactly three can start, thirteen are refused, and a released slot can
  be reused with a newer fencing generation.

## Remaining P0 blockers before use

1. **NOT CONNECTED TO STEEL.** The existing runtime has a deliberately
   serialized singleton and should remain at one session until the real
   provider-capacity contract and the control-plane adapter are verified.
2. The current Floot vault has one global bearer and name-based profiles.
   These DB tables are not a migration and do not protect live profiles.
3. The session owner must pass a *server-bound task capability* to every
   MCP, HTTP, mobile and background callback. Old broad browser tools must
   be retired; a slot number alone is not authorization.
4. A real, durable outbox must connect DB reservations, the billable
   remote session POST, CDP connection, profile load, flush, release and
   independently verified receipts. An ambiguous provider create/release
   must quarantine the slot before another attempt.
5. Integrate per-tenant quotas and verified Stripe entitlements. Three
   concurrent remote browsers cost more than one. Pricing and concurrency
   allowances at Steel must be confirmed against the actual account.
6. A real two-client test with separate identity-provider sessions, profiles,
   provider namespacing, crash/restart drills, SSRF and RODO controls is
   required. **Never copy real cookies or secrets to public GitHub or CI.**
7. A failing profile coherence test (issue #111) means profile restoration
   cannot yet be certified for sale, even if parallel admission works.

## Test

GitHub Actions: `.github/workflows/three-parallel-steel-slots.yml`
runs against disposable PostgreSQL 16 with synthetic UUIDs and fake provider
receipts. No Steel provider, customer accounts, browser sessions or payment
operation is touched.

**Commercial release status: NO-GO.**
