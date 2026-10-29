# Cold recovery checkpoint — 29 October 2026

## Actual work completed

- Floot owner metadata identifies the current 429 outage as the published application's Free daily hosting budget pause, ending at 2026-10-29 13:00 UTC. Repeated requests, republishing, or restarting Render do not reset that budget.
- The pre-existing Neon PostgreSQL staging instance now contains `aib_shadow_ciphertext_inbox`, `aib_shadow_engine_bindings`, two guarded append functions, and immutable-update/delete triggers. PUBLIC access to these new tables/functions was revoked. Positive insert, identical retry, wrong-hash, conflicting-state, mutation-denial, binding idempotency/conflict and rollback checks passed on synthetic rows; fixtures rolled back.
- A separate PRIVATE Neon Storage bucket contains a real consistent cold backup taken at 2026-10-29 01:14:48.986868 UTC using one PostgreSQL REPEATABLE READ, READ ONLY snapshot. Portable states were never decrypted or passed through chat or GitHub.
- Contents: 68 profiles; 1,292 historical versions (78 non-update protected records; 20 with explicit forensic_r158 reason); 69 engine bindings; 11 task checkpoints; 3 configuration rows; 6,390 profile events; 0 leases; 0 account-attempt rows. Preserve all records, IDs, reasons and original timestamp precision. An old reference to 21 R158 records must be reconciled by original record identity, not silently changed into a completed acceptance.
- Independent private download returned HTTP 200; anonymous access returned 403. GZIP, total byte length, whole-object SHA-256, row-manifest SHA-256 and all table counts match the export receipt. Receipt and object location remain private; do not paste signed URLs, account identifiers or ciphertext here.
- Source-side export was authorized by an owner-provisioned, target-bound, expiring single-use capability. No token was embedded in source code. Unauthorized request returned 401; consumed-capability replay returned 409. Temporary secrets and local copies were removed after verification. The endpoint exists in the development project checkpoint, not a newly published Floot backend.
- `bridge/cold_backup.mjs` validates an independently pinned receipt before parsing/import preparation. It rejects altered bytes/manifests, duplicates, unknown tables, count mismatch, unsupported provenance and promotion claims; it preserves 64-bit record IDs and timestamp microseconds. It NEVER grants migration permission.
- Exact source commit `8f9ef0bb36219d62472c0ee88ebd4a2555c9ca4d`: `node --test migration/neon/test-cold-backup.mjs` passed 12/12 on Node 22. The same exact-source validator passed on the real privately downloaded backup. This is a trusted-process test, not a claim that an unexamined CI workflow executed it.

## Explicitly not completed

- No rows imported into the PostgreSQL inbox: both import tables are currently empty. A restricted importer-role provisioning transaction was blocked by the tool's permission/safety layer. Readback confirmed zero new roles and no partial receipt-table creation. Do not bypass that restriction with a privileged existing role, another endpoint, or a copied owner password.
- No Neon production promotion, no Render environment change, no reset of a browser session, and no deletion of cookies, original profiles, history or task state. Floot remains the sole production writer.
- `vault_migration_guard` is still `staging_read_only`, `write_enabled=false`. A private cold backup is not a fresh source-freeze receipt, not proof of current site authentication, and not proof that provider sessions have been reconciled.
- BOAS R3 was not published in this checkpoint: the public canonical path returned 404 and WordPress public REST returned no published page with slug `boas`. The existing parent `/uslugi/` is page 12. Private drafts still require authenticated inspection. A separately approved bounded publication task is scheduled after the hosting reset, with existing WPVibe fallback after its separate rolling quota resets.

## Next safe release boundary

1. Obtain an authorized restricted import transport; do not weaken the source/destination guards. Use the already verified private backup for a restore rehearsal, not as a silently current production snapshot.
2. Finish the protocol-compatible Neon API and controller CAS/expected-state handling. Preserve engine bindings, original encrypted formats, configuration, protected history and stable operation IDs.
3. Before actual cutover, freeze new admission, finish own saved-close work, obtain independent current full provider inventory, and reconcile every local/vault/provider session and task lease. Acquire a new complete snapshot/delta and independently verify bytes and records against the frozen source.
4. Test neutral cookie/localStorage/IndexedDB restore on a new controller; validate exact account identity separately. Do not reset a failed marker to manufacture a PASS.
5. Promote one writer with a monotonic fencing epoch. Keep the old writer fenced; do not automatically switch back on the first successful Floot request. Test rollback with the same operation journal so already-confirmed publications cannot replay.
6. Only after these checks may Neon replace Floot for normal work. Prefer a controlled permanent primary migration over ad-hoc switching between two independent writable free-tier databases.

**PRIVATE_BACKUP_VERIFIED=true. OPERATIONAL_RESTORE=false. AUTOMATIC_FAILOVER_READY=false. PRODUCTION_CUTOVER=false.**
