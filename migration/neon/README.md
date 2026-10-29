# AI Browser — Neon owner migration staging (29 October 2026)

This is a real, isolated owner Neon staging database and a fail-closed API
candidate. It is **NOT** a replacement for live Floot, not a profile migration,
and not proof of authenticated Meta accounts.

## Existing, verified resources
- Neon Free project: proud-glade-77868350, branch:
  br-ancient-firefly-baqgm1x0, PostgreSQL 17 (Frankfurt).
- The previously empty Neon DB now has the tables/indices in
  001_staging_schema.sql, plus the archive-on-change trigger.
- The database-level migration guard is staging_read_only with
  write_enabled=false and CHECK(NOT write_enabled).
- Existing Floot remains the ONLY production source; Render currently uses
  its existing encrypted state; all 5 Meta profiles remain there.
- A private encrypted cold backup is now stored in Neon **Storage**, not in the operational PostgreSQL tables.
  No plaintext cookies, credentials or encryption keys are stored in the repo, passed through ChatGPT, or exposed by Neon HTTP.

## Why Neon Functions instead of adding Cloudflare immediately
Neon Functions runs on the existing Neon Free plan and has an owner-connected
deployment tool. It can provide the same request-response interface without
adding another provider right now. It is NOT a persistent background worker
or queue. Cloudflare Workers is a possible future option if an account is
connected and its limits permit the expected workload.

## Security, nonnegotiable
1. One production writer: Floot only until a separate accepted cutover.
   Never independently write the same profile in Floot AND Neon.
2. No master keys, raw bearer tokens, cookie values, decrypted profile state,
   provider capabilities, or ciphertext are sent to ChatGPT, source, or CI.
3. Staging function provides GET/HEAD /health only. All profile/task/engine/
   recovery/MCP and mobile login operations return HTTP 503 fail-closed.
4. Archive trigger saves PREVIOUS ciphertext when the value changes and
   never prunes rolling/protected archives (storage limit fails closed).
5. Before any real migration: compare source and destination encrypted
   row counts and protected-history manifests, using a trusted authorized
   private service-to-service path; never pull encrypted rows through chat.
6. An owner-authenticated API replacement must be separately reviewed:
   bounded request reads, constant-time token-digest check, parameterized
   queries, atomic task claim/revision CAS, identity fences, provider recovery.
7. A real cutover requires a saved-close freeze, provider inventory, no
   competing owner sessions, full protected-archive retention, signed
   migration receipt, staged replica readback and explicit rollback.
8. No real login, MFA, CAPTCHA or identity assertion follows from a
   successful schema or synthetic test.

## Private shadow transfer (staging schema applied; restore not activated)
- New live source readback 29 October: 68 profiles, 1292 archived revisions,
  69 Steel profile bindings, 11 checkpoints, 0 control leases and 0 interrupted tasks.
  An immutable private Neon Storage object contains a full snapshot: 7,833 records
  across all eight source tables. Private readback passed complete SHA-256 and
  row-manifest checks; the original Floot database was not changed.
- `bridge/transfer.mjs` now enumerates all four categories under one
  repeatable-read source snapshot, preserving microsecond source timestamps.
- `003_shadow_ciphertext_inbox.sql` **was applied** in Neon staging; both immutable
  import inboxes remain empty and the LIVE-shaped tables remain write-fenced.
- `005_cold_backup_receipts.sql` defines the immutable metadata-only receipt table,
  applied 29 October. It records verified backup size, counts and SHA-256 without
  secrets or profile ciphertext. The exact receipts themselves are kept privately
  in Neon, not committed as source data.
- The one-shot runner needs source-only read DB credentials, a restricted Neon
  import role and short-lived owner-signed freeze proof, all provisioned
  directly in a trusted runtime (not sent through ChatGPT).
- `bridge/restore_parity.mjs` checks exact copies of encrypted states, timestamps,
  large history IDs, task revisions, engine bindings, events and configuration.
  It reconciles neutral R158 as **20 rolling + 21 protected**, the latter being
  **20 forensic + 1 pre-verified**. Offline private replay of all **7,833** real
  backup rows PASS; one deliberately corrupted copy was rejected. This is not
  PostgreSQL import or a live-browser test.
- Creating a restricted importer role was refused by the tool safety layer.
  Do not bypass the refusal through the owner role, another endpoint or a
  credential pasted into chat. Authorization of a genuinely limited import role,
  a real restricted DB import, fresh source/provider freeze, native three-store
  readback and rollback are **NOT DONE**. Cutover remains blocked.

## Free limits
Neon Free provides up to 100 CU-hours per project/month, 1GB data and
automatic scale-to-zero. A quota can pause compute. It is NOT unlimited.
Neon Functions Free has its own invocation/runtime ceilings and does not
run a continuously polling job. Existing ChatGPT/Work and Steel limits remain.

## Local CI
node --check migration/neon/staging/index.mjs
node --test migration/neon/*.test.mjs

## Status
Schema applied: yes. Full private Storage backup copied and verified: yes.
Encrypted PostgreSQL profiles imported: NO (0). Restricted importer role: NO.
Auth API production-ready: NO. Database public writer: prohibited by constraint.
Live Render/Floot production switched: NO. READY=false.


## 29 October takeover implementation, still STAGING ONLY

- The owner Neon Storage object is a verified immutable cold source of all
  **7,833** rows across eight source tables. Its SHA-256 and source row digest
  are registered in the private immutable aib_cold_backup_receipts table.
- 005_cold_backup_receipts.sql is the reproducible receipt DDL.
- 006_shadow_config_events.sql is applied: immutable per-batch private
  config and event inboxes, preserving the 3 config values and 6,390 event
  rows that the original draft transfer omitted. SQL synthetic success and
  mutation-denial test fixtures have been rolled back.
- bridge/transfer.mjs now validates and can stage all eight sources under a
  single source snapshot after a real signed provider freeze, and will refuse
  any non-empty active lease or login-attempt table. This runner was NOT
  executed with the real source/destination secrets. No Neon database import
  role currently exists or has been provisioned.
- bridge/restore_parity.mjs compares original and restored private records
  at exact byte precision including bigint IDs, timestamps and encrypted
  payloads, and confirms neutral R158 20 rolling + 21 protected provenance.
  Real private backup -> isolated in-memory rehearsal PASS. A deliberately
  changed profile is denied. This is NOT actual PostgreSQL restore or browser
  authentication verification.
- The staging guard remains mode=staging_read_only, write_enabled=false,
  all four import inboxes have zero real rows, and Render still uses Floot.
  The role-provisioning safety refusal must not be sidestepped. Before any
  production cutover: legitimately limited import role, full import parity,
  fresh source/protected-history manifest, full Steel saved-close inventory,
  neutral three-store/new-controller PASS, single fenced writer and rollback.
