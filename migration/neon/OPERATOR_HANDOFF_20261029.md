# AI Browser — Neon owner migration takeover (29.10.2026)

## Verified live position
- Existing application only: GitHub `napieraj2018-arch/Watcher-15`, production branch `ai-browser-cloud`, PR #180 `migration/neon-free-staging-20261028` **DRAFT**.
- Current Render production service remains on Floot-backed code. Never assume GitHub draft or staged Neon Function is production.
- Original Floot owner DB: 68 profiles, 1292 profile versions, 69 Steel engine bindings, 11 task checkpoints, 3 config rows, 6390 events. No active DB leases and no changed profiles since the private 01:14 UTC snapshot at last verification.
- The full 7833-record consistent encrypted snapshot exists in **PRIVATE** Neon Storage and has passed byte-integrity, aggregate and R158 20-rolling/21-protected proof in trusted runtime. This is a backup, not operational access.
- Neon STAGING PostgreSQL: all four import inboxes EMPTY; immutable cold receipt = 1; `vault_migration_guard.mode=staging_read_only`, `write_enabled=false`. Current role inventory contains `neondb_owner` only. The restricted import role is not created.
- Neon private runtime assets: bucket `aib-runtime-recovery`, core-v041 (48104 bytes, pinned SHA256), repair-v042 (12150 bytes, pinned SHA256); independent download/readback SHA256 PASS and anonymous GET 403. These contain encrypted **application code**, not account profiles.
- Neon Function `aibbootassets` deployed on existing project and tested: `GET /health` 200, without configured owner digest `GET /v1/core` and `GET /v1/repair` 503; other methods/paths rejected. No production customer access and no plaintext is served.
- Source code for `bridge/cold_restore_plan.mjs`, `private_stage_writer.mjs`, `cold_restore_run.mjs`, `assets/core.mjs` and tests is on the same PR180 branch. Synthetic positive/negative checks and exact-head CI pass. **No real PostgreSQL import was executed.**

## Non-negotiable blocking gates
1. **Restricted import role:** An earlier role-creation write was refused by tool safety. Do NOT call the same SQL through a different API/interface or substitute the privileged `neondb_owner` role. The owner/provider must resolve legitimate least-privilege provisioning before execution. Do not paste any password/Neon DATABASE_URL into chats, files or GitHub.
2. **Fresh provider/saved-close freeze:** A stale `browser_sessions=[]` is not sufficient. Obtain authenticated complete paginated Steel session inventory, exact unknown/quarantined session reconciliation, source vault/backup readback and no active/new admissions. Fresh HMAC-signed receipt valid at most 900s is required for the importer.
3. **Actual import and readback:** Execute the reviewed CLI in a trusted, isolated private environment with a restricted role and a short-lived private Neon Storage GET URL. Import each complete category into immutable shadow inboxes; compare all bytes, versions, IDs and timestamps against source. The CLI never activates the primary Neon writer.
4. **Current source delta:** The cold snapshot is from 01:14 UTC. At cutover the source must be frozen, its CURRENT full state compared with the snapshot, and any approved delta included; never claim source freeze from earlier metadata.
5. **Neon API parity:** Existing production core still expects Floot JSON and unguarded POST saves; new Neon writer requires CAS expected profile SHA. Implement and test authenticated protocol-compatible controller client, task claims, provider recovery, archive/replay and asset bootstrap before changing Render `AI_BROWSER_PROFILE_STORE_URL`. No silent fallback to Floot on failure.
6. **Neutral native state and real accounts:** Original R158 cookie/localStorage/IndexedDB coherent saved-close/new-controller test must PASS without reseeding a failed marker. After that independently verify real account identities and only required owner MFA.
7. **Single active writer:** Preserve old writer until source freeze. Deploy only a verified commit with source and Neon cutover fences, new monotonic epoch and rollback, after independent Steel check. Never run two unconstrained writable vaults. Keep old copies unchanged.

## Next legitimate operator action
Request *properly authorized, provider-supported* creation of a restricted importer role in Neon. Privileges must be limited to SELECT of the immutable backup receipt + STAGING guards, SELECT/INSERT on the four STAGING inboxes, and EXECUTE of four guarded append functions, with **no INSERT/UPDATE/DELETE on live-shaped profile/task/engine/config tables and no permission to alter `vault_migration_guard`**. Test the privileges using read-only `has_table_privilege` / `has_function_privilege` before importing.

The user already approved migration of their own accounts, but approval is not permission to bypass a blocked privileged tool operation. No further changes to real profiles, passwords, session cookies or production environment before the above gates.

## Recovery and rollback
Backup source and encrypted application boot assets are privately retained in Neon; original Floot data remains unchanged. Stop on uncertainty; do not retry writes with different IDs, skip identity rechecks or reset/clear provider quarantine to make a test pass. The current staging is intentionally not production-ready.

**Status: PRIVATE_BACKUP_VERIFIED, ASSETS_MIRRORED, OFFLINE_RESTORE_TESTS_PASS, STAGING_API_DENY_TESTS_PASS; POSTGRES_IMPORTED=false, ACCOUNTS_RESTORED=false, PRODUCTION_SWITCHED=false.**

## Additional implementation — 29 October 2026, user explicitly requested full import

**Fresh read-only evidence:** At 09:50 UTC source Floot reported 68 profiles,
1292 archives, 69 engine bindings, 11 tasks, 0 active leases, 0 unresolved
checkpoints and 0 changed profiles/tasks since the protected snapshot.
Neon SQL reported exactly 0 operational profiles and 0 encrypted/config/event
shadow inbox rows, while the immutable private backup receipt still exists.
Neon roles: only `neondb_owner` (not a restricted importer). Browser MCP
`browser_sessions` and `profile_list` returned internal errors, so an
independent current Steel full inventory/saved-close proof is UNAVAILABLE.

**Actual implementation after that read:**
- `bridge/private_batch_stage.mjs` performs bounded JSONB set-based writes
  through ONLY four existing guarded STAGING append functions. Maximum
  48 records / 2 MiB serialized JSON per call; actual largest source profile
  is 1,342,052 bytes and fits this limit.
- The full 7,833-record REAL private backup was verified, mapped into
  176 bounded batch requests, then assembled back and compared to the
  source byte-for-byte in a trusted offline mock. PASS on all eight categories.
  This **did not insert real data into Neon PostgreSQL**.
- All four SQL batch forms passed live Neon PostgreSQL 17 `EXPLAIN`.
  A separate synthetic real-SQL transaction inserted one fixture into each
  of the four STAGING inboxes, verified all four receipts, then ROLLED BACK
  completely. Real inbox count remains zero and writer guard unchanged.
- `bridge/import_role_gate.mjs` checks the actual connected role grants:
  disallows owner membership, role creation, schema CREATE, any write privilege
  to operational vault tables, and UPDATE/DELETE/TRUNCATE against STAGING.
  Requires limited SELECT/INSERT plus four append function EXECUTE grants.
  The read-only query was actually run in Neon and correctly identified the
  current `neondb_owner` as TOO PRIVILEGED. No role creation retried.
- Private `bridge/cold_restore_run.mjs` now uses batch staging and mandatory
  privilege attestation. All new synthetic batch/role tests PASS and the
  entire PR test workflow is green at the corresponding exact head.

**P0 remaining beyond importer privilege:** The actual Render controller
still hardcodes Floot provider recovery and task-vault origins, and
`bootstrap.py` still downloads its two encrypted packages from Floot.
The private copies of these two packages are safe in Neon Storage but
production bootstrap has NOT been switched; the Neon asset endpoint is still
fail-closed without an owner-configured digest. Protocol-compatible controller
and CAS changes plus a safe current Steel session state must be verified
before choosing Neon as the sole operational writer.

**Do not claim import complete:** `POSTGRES_IMPORTED=false`,
`LIVE_ACCOUNTS_REOPENED=false`, `SINGLE_WRITER_CUTOVER=false`.
A previous tool rejected restricted role provisioning. Do not evade that
restriction by using an owner connection or a different endpoint. Provider
authorization for truly limited import access is required first.


## Continuation at 29 Oct 2026 ~11:40 Europe/Warsaw: new compatibility work, NO cutover

Read-only, freshly verified:
- At 10:40 UTC Floot source still had **68 profiles, 1292 archives,
  69 Steel bindings and 11 tasks**, zero control leases, zero unresolved
  tasks, and zero updated profiles/archive revisions/tasks since the
  original private 01:14 UTC snapshot.
- Neon STAGING has one immutable backup receipt; **zero** live profiles,
  zero ciphertext/engine/config/event inbox rows, staging_read_only,
  write_enabled=false. list_postgres_roles: neondb_owner only.
- Render LIVE still exact SHA f759faa353e5de5e7392c4aceb3bbe70e6263524,
  not a Neon backend; AutoDeploy previously off. Browser sessions tool
  again returned The tool failed internally, not evidence of provider idle.
- The Floot source tool next returned Daily build limit reached (100/100)
  with reset **2026-10-29 13:00:00 UTC / 14:00 Warsaw**. No repeated quota
  calls or attempts to evade the limit were made.

Newly implemented in the existing draft PR180:
- migration/neon/api/primary_core.mjs: separate, **UNDEPLOYED**
  owner-authenticated future Neon primary JSON protocol candidate for
  profile/engine read/write and durable task list/get/claim/checkpoint/release,
  compulsory expected_sha256 profile-save CAS and fail-closed cutover
  admission. Disabled/missing admission refuses all private API calls;
  profile deletion refused; unverified DB errors redacted.
- migration/neon/api/recovery_protocol.mjs: strict read-only recovery
  inspect compatibility, requiring a configured/verified imported gate
  before reporting pending:false. Pending attest action remains blocked
  until a separately verified safe transaction is implemented. No
  provider release, reset or unknown-session adoption.
- New primary_core.test.mjs and recovery_protocol.test.mjs include
  bearer auth, CAS, revision, task partition, forbidden operations,
  absent recovery, quota/untrusted-data denial tests. Exact-head
  GitHub Actions run **40860597158 PASS** (Node22+24); prior run
  **40860199546 PASS** recorded **147 tests passed** on Node24.
- The primary API modules are not wired into a new active Neon Function,
  never deployed on Render and cannot presently store any user profile.
  The already deployed staging API/boot-assets Fn remain fail-closed.

A **single one-time continuation automation** was created for
**2026-10-29 14:10 Europe/Warsaw**, after the account's reported build
limit reset. It must recheck actual Floot/Steel/Neon/Render state once,
honor all rate limits, never retry previously refused role provisioning
via another tool/privilege, and perform only explicitly safe next work.
This scheduling is not an import, saved-close certificate or LIVE cutover.

Hard blockers unchanged: legitimate **restricted** aib_import_* credential
was previously denied by tool safety; role does not exist. Do not bypass
with neondb_owner or different API. Live Steel inventory/save receipt
unavailable. Original neutral three-store R158 live saved-close/reopen,
full data transfer, fresh signed source freeze, one-writer fence,
controller bootstrap cutover and rollback acceptance remain absent.

**COLD_BACKUP_VERIFIED=true; PRIVATE_OFFLINE_REPLAY_PASS=true;
NEON_BOOT_ASSET_COPY_VERIFIED=true; CANDIDATE_JSON_API_CI_PASS=true;
ACTIVE_DB_PROFILE_ROWS=0; RESTRICTED_ROLE=false;
REAL_ACCOUNT_AUTH_RESTORED=false; PRODUCTION_CUTOVER=false.**

## Execution checkpoint — 29 October 2026, 11:04–11:15 UTC

This is a newly verified checkpoint under the owner's explicit migration order.
No real profile mutation, role provisioning, release, deployment or store switch
was performed.

### Actual private backup verification
- Downloaded the existing private Neon Storage object again through a 900-second
  authorized download link, inside the private local verification process.
- Exact compressed length 28,701,566 bytes and pinned SHA-256 PASS.
- Ran the existing PR180 cold_backup.mjs and row_mapper.mjs validators from
  exact code HEAD 663007d878949838fb6bb8844f5304804079c7b1 against the actual bytes
  and the independently fetched immutable database receipt.
- All 7,833 records verified: 68 profiles, 1,292 archives, 69 engine bindings,
  11 task checkpoints, 3 config values, 6,390 events, zero source leases and
  zero source account attempts. Record-stream digest, duplicate checks,
  timestamps and mappings PASS.
- R158: 20 rolling + 20 forensic + 1 pre-verified protected archive, no other
  protected R158 rows. Total protected archives 78.
- Temporary downloaded bytes and receipt-bearing runner were deleted after
  validation. No private rows, signed URL, provider UUIDs or credentials were
  committed or returned to model output.
- This confirms the retained snapshot's integrity ONLY. It is not a fresh
  Floot delta, source freeze, operational import or browser authentication test.

### Fresh operational observations
- Neon SQL at 2026-10-29T11:04:25Z: operational profiles=0, archives=0, tasks=0;
  all four staging inboxes=0; immutable receipt=1;
  mode=staging_read_only; write_enabled=false.
- Postgres role inventory still contains neondb_owner only. No aib_import_*
  role exists. No previously refused role creation was retried through any
  tool, identity or alternate interface.
- Inspected the Neon plugin permission setting: app-specific setting already
  **Allow all actions**. Therefore another generic owner consent or toggling
  this setting is not an established remedy for the earlier safety refusal.
  The retained reports do not contain its detailed rejection rationale.
  No exposed tool in this execution provides an appeal/authorization action
  for that historical refusal. Resolve the original operation through the
  platform's authorized review; do not substitute owner import or manual SQL
  to evade it.
- browser_sessions again returned an internal MCP error, not an idle receipt.
- The explicitly requested Cloud Browser opened the Steel dashboard, but its
  visible account/team identity did not match the expected project identity.
  No provider inventory, API keys, private sessions or profile data were
  accessed under that identity; no sign-out/cookie deletion was performed.
  The correct owner identity must be verified before inspecting sessions.
- Render service: AutoDeploy=no; one configured instance; LIVE deploy
  dep-dbh95gon74is73cmpek0, commit
  f759faa353e5de5e7392c4aceb3bbe70e6263524.
- Latest matching app log at 2026-10-29T11:01:32Z still reports
  RECOVERY_HTTP_429 and maintenance due to provider rate limiting.
  No restart or production configuration change was attempted.
- No additional Floot quota calls were made before the previously reported
  reset. Do not infer current source integrity or freeze from the cold backup.

### Next permitted execution, not another audit loop
1. Resolve the original importer permission refusal through authorized review.
   Verify a legitimately limited importer on the actual import connection.
2. Verify the intended Steel account/project and complete exact-session
   saved-close reconciliation plus full inventory; obtain a fresh source freeze.
3. Run the existing private importer and independent per-record database readback.
4. Complete actual neutral three-store restore and real-account identity checks.
5. Only then permit one epoch-fenced Neon writer and execute the validated
   rollback/cutover procedure.

**REAL_PROFILES_IMPORTED=0; CONFIRMED_LOGINS_AFTER_NEON_REOPEN=0;
PRODUCTION_NEON_PRIMARY=false; ROLLBACK_EXECUTION_TESTED=false.
Floot remains the configured production store; private backup retained.**
