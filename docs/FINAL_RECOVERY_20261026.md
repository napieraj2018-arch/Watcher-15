# Owner pilot acceptance — 26 October 2026

This is a production observation plus targeted recovery patch, not a new project.
Always check current deployment/session state before acting. Private identities,
aliases, provider IDs and authentication material belong in the encrypted task,
never this public repository.

## Verified baseline

- Production branch and Render LIVE: `c6618599ea45842ac8624ee91dc83a24ed26cae3`,
  deploy `dep-dbe673avcj2c73brjj20`, autoDeploy off, Free plan unchanged.
- Actual MCP reads and six sequential owned browser starts succeeded. Public
  `/health` reports version 0.4.1; owned runtime receipts report 0.5.2. Neither
  version string identifies the deployed Git commit; use the Render receipt.
- Floot authenticated database read: 62 profiles, 1116 archived versions,
  61 hydrated native bindings, recovery gate pending=false, zero unresolved
  durable tasks at observation. This is not proof of provider-wide idleness.
- All five authorized Meta profiles were opened independently and saved closed
  with `stopped=true`, `profile_saved=true`, `full_profile_saved=true`.
  Four showed the actual login form: REAUTH_REQUIRED. One restored a protected
  feed, active comment identity and own-profile navigation after saved close
  and a new start: AUTHENTICATED. Private per-profile evidence and stable aliases
  are in main task `8031c768-62dc-4e75-969e-74d98f26b179`.
- Another Work was actively writing WordPress. Its capability was never adopted
  or stopped. Deployment requires a new idle check; do not restart over it.

## Targeted patch and tests

1. Durable `starting` intent is written under the owner guard admission lock,
   after profile/capacity refusals and before provider creation. A race losing
   admission no longer creates a false unfinished task that globally blocks
   subsequent work. Unknown provider starts still require recovery.
2. Durable start optionally accepts `{"mode":"read_only","headless":true}`.
   Existing write-mode callers retain their default. Invalid modes fail before
   checkpoint/provider mutation.
3. Startup URL navigation reads fresh owned status instead of returning the
   earlier about:blank URL/authentication. Failed readback retains capability,
   reports unverified status and never navigates/logs in again automatically.
4. Existing `aib_route_operation(service="facebook", operation=<command>)`
   recognizes the bounded Polish preview command below. It returns alias and
   ordinal requirements, not authentication, publication or fabricated group
   access. `meta_command.py` validates trusted private bindings, current actor,
   membership/comment permission, an ordered list of unique exact permalinks,
   freshness, immutable preview digest and stable operation ID. The existing
   durable journal remains mandatory for a real write. A click receipt alone
   cannot confirm publication. There is no automatic social publisher here.

Example command: “Użyj konta Meta 1, znajdź piąty wpis w wybranej grupie Spotted,
przygotuj odpowiedź i pokaż ją do publikacji”. Resolve the actual group explicitly
before browsing; freeze the selected permalink before approval. Private binding
observations must come from the authorized operator's protected UI readback,
not client-submitted booleans.

## Release and rollback

Run exact-head owner mobile Docker/Chromium/WebKit CI and all included regression
tests. Local runtime tests alone are not sufficient. Before manual deployment:
all owned tests saved closed, no competing browser writer, no unresolved task
or recovery state, no other deployment, and fresh authenticated provider
inventory when the prior provider/save outcome is uncertain. A new unknown
provider state blocks rollout even if browser_sessions is empty.

Rollback target is the exact prior LIVE commit above. No database/schema,
encryption, profile key, native context policy, OAuth config or vault migration
changes occur in this patch. Rollback must use the same idle/reconciliation
gate; never roll back over an active login/write. Preserve private task state
and all archives. A rollback does not resolve a failed save or lost lease.

## Acceptance still open

- Four owner authentications, then actual identity + saved-close/reopen tests.
- Actual chosen group permissions, ordered fifth post and approved publication.
  Synthetic preview tests cannot establish these.
- Physical iPhone keyboard/touch, application background/return: NOT_TESTED.
  Chromium/WebKit simulation must be reported separately.
- Active-session process-crash drill: not performed on shared production.
  Uncertain active sessions still fail closed and require provider reconciliation.
- Local Windows C: files: NOT_TESTED / no mounted local host demonstrated.
- YouTube OAuth #170 remains separate, draft and unintegrated.
- The existing hourly automation continues the same main task; it is not proof
  of a continuously running worker, ten live identities or commercial readiness.

READY is false until the real acceptance gates pass. Reuse the existing task
and operation receipts; never replay an uncertain mutation.
