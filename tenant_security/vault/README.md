# Tenant-bound encrypted profile vault — isolated proof (2026-10-09)

**NOT PRODUCTION.** Only synthetic test data and ephemeral keys are used.
This feature is **not** connected to the existing Floot `browserProfiles`
table, Steel profiles, saved cookies, Render, MFA, or real customer accounts.

## Storage and authorization rules

- `003_encrypted_profile_vault.sql` creates immutable PostgreSQL revisions
  linked through composite `(tenant_id, workspace_id, profile_id)` foreign keys.
  It uses FORCE RLS and `session_user`→tenant authentication inherited from
  PR #83/#98/#100. It does **not** trust a UI-selected tenant ID.
- Only the separately provisioned `browser_vault_worker` role may read
  encrypted bytes. The tenant's ordinary BFF role has NO SELECT on ciphertext.
  Vault workers cannot directly INSERT, UPDATE or DELETE history.
- `append_encrypted_profile` checks a ready profile, expected revision and
  size/key/nonce shape under a per-profile transaction advisory lock. Concurrent
  writers must retry after a revision conflict. A UNIQUE constraint rejects
  accidental AES-GCM nonce reuse under the same tenant key identifier.
- `profile_envelope.py` uses AES-256-GCM from the audited `cryptography`
  library, with freshly generated 96-bit nonces and authenticated additional
  data binding the ciphertext to tenant + workspace + profile + revision.
  A cross-tenant or stale revision substitution fails closed. No plaintext,
  ciphertext or keys appear in exception messages or `repr`.
- Rotation produces a **new encrypted revision** under a different key
  identifier. It never silently rewrites a previously stored version.
  The example keyring is in-memory test infrastructure; production keys
  require a scoped KMS/HSM and a verified rotation/recovery policy.

## Verification on disposable PostgreSQL 16 only

Workflow `.github/workflows/tenant-rls-ci.yml` runs in order:
1. Existing tenant RLS and negative privilege tests.
2. Atomic per-tenant queue quotas and 16-way concurrency.
3. Existing BFF session, CSRF, Origin, retry idempotency and 16-way requests.
4. This vault schema + SQL A/B role isolation, immutability, denial after
   revocation and denial of direct ciphertext access from BFF roles.
5. Synthetic AES-GCM tamper, key swap, revision, rotation and replay tests,
   real PostgreSQL encrypted roundtrip and a 16-connection revision race.

The encrypted fixtures are intentionally synthetic and do not contain actual
cookies or localStorage.

## STILL BLOCKED before commercial launch

1. Actual multi-tenant identity provider and customer session issuance.
2. KMS with envelope DEKs per tenant, auditability, key rotation, backup and
   disaster recovery. Never store plaintext key material in the database.
3. Migration/rewrapping of the existing global Floot profile vault,
   provider-native Steel profile references and backup copies. No automated
   migration of real user data without validated rollback and independent review.
4. Coherent cookies + localStorage restore verified through real Chromium and
   WebKit restarts with synthetic technical accounts; session ownership and
   quarantine must protect every restore/save.
5. Secure erasure of every old revision, backups, provider storage, logs and
   retention snapshots, with external deletion evidence and RODO review.
6. Authenticated user-facing interfaces, tenant quotas/billing, production
   monitoring and independent penetration testing.

**Never deploy this proof to the current shared Floot vault.**
