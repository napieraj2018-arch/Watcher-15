# AI Browser — Neon Free staging vault (28 October 2026)

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
- No actual profiles, history, Steel UUID bindings, tokens, master encryption keys, owner claims,
  authentication data or cookies were transferred by this setup.

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

## Private shadow transfer (unapplied, not executed)
- The source shape was verified by count-only source metadata on 28 October:
  66 profile names, 1216 archived revisions, 67 Steel profile bindings, 9
  checkpoints; no source name fails the Neon name constraint.
- `bridge/transfer.mjs` now enumerates all four categories under one
  repeatable-read source snapshot, preserving microsecond source timestamps.
- `003_shadow_ciphertext_inbox.sql` remains **unapplied**. It defines a separate
  restricted, immutable Steel-binding inbox; no real provider UUIDs are copied
  through a chat, source repository or CI.
- The one-shot runner needs source-only read DB credentials, a restricted Neon
  import role and short-lived owner-signed freeze proof, all provisioned
  directly in a trusted runtime (not sent through ChatGPT).
- This is only an import candidate. Config, exact private manifest comparison,
  original R158 three-store reconciliation, neutral readback and rollback
  are **NOT DONE**. Cutover remains blocked.

## Free limits
Neon Free provides up to 100 CU-hours per project/month, 1GB data and
automatic scale-to-zero. A quota can pause compute. It is NOT unlimited.
Neon Functions Free has its own invocation/runtime ceilings and does not
run a continuously polling job. Existing ChatGPT/Work and Steel limits remain.

## Local CI
node --check migration/neon/staging/index.mjs
node --test migration/neon/*.test.mjs

## Status
Schema applied: yes. Source staged: yes. Historical profiles copied: no.
Auth API implemented: no. Database public writer: prohibited by constraint.
Production switched: no. READY=false.
