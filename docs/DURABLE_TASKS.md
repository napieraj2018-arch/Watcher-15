# Owner task checkpoints

The existing owner-only MCP can register `aib_task` after its original 51-tool
ownership preflight. The existing Floot PostgreSQL vault stores AES-GCM task
snapshots, separately keyed and bound to owner/task IDs. Backend authorization
uses the existing server-side vault bearer; caller-supplied owner IDs are ignored.
CAS revisions and a private claim prevent stale writers and concurrent claims.
No passwords, connector tokens or live browser capabilities belong in checkpoints.

Use create → start → browser → verify → checkpoint → stop → release. A subsequent
authorized owner conversation uses list/get → resume → start. Resume issues a new
claim and starts a fresh session from the same saved profile. It never adopts a
live session. On interrupted unknown start/save, retain recovery_required and
reconcile the exact provider state instead of retrying. Server crash while a
browser is active is deliberately fail-closed, not automatic session recovery.
The start gate retains this restriction across controller restarts using the
persistent non-resumable checkpoint row.

Stable operation IDs are required for browser mutations. click/fill/press require
readback with verify; tool acknowledgement alone is not proof of the website
outcome. Reusing an ID never repeats its action. Different inputs with the same
ID fail. A pending operation blocks further writes but allows read-only checks.
For official connectors, use begin before an authorized write, confirm only with
its actual receipt, and inspect the object if the connector result is unknown.
The ledger cannot prevent writes deliberately made outside this participating
workflow or establish exactly-once effects on arbitrary third-party services.

Capacity/profile-busy returns a persistent queued checkpoint; the owner caller
retries start when a slot is free. It does not launch a billable browser while
its requesting ChatGPT conversation is absent. Queue is not an unattended worker
or an automatic scheduler. Existing five-slot profile guards remain authoritative.

Keep the distinction: a durable task checkpoint is not a durable capability,
valid site login, automatic 24/7 execution, or commercial tenant isolation.


## Reliability continuation — 29 October 2026

New optional owner-only checkpoint field: `"handoff_after_saved_close": true`.
By default it remains `false` for every pre-existing task and when omitted.
Enable only for a task whose owner wants another ChatGPT conversation to resume
from its last confirmed step after a verified saved close.

- An explicit `aib_task(action="stop")` still requires the *same* live
  opaque capability and an exact `stopped=true`,
  `profile_saved=true`, `full_profile_saved=true` receipt.
  Only after encrypted checkpoint `session_state="saved_closed"` is
  durably saved, the server may release the task's existing claim.
  The returned `claim_released` is the authoritative result, not a guess.
- A watchdog auto-close can perform the same handoff if and only if the
  exact owned session supplied the complete saved-close receipt. It does not
  adopt an orphaned browser or open a new one.
- If the vault refuses the release, the saved-close checkpoint survives but
  the claim is **not** reported released. The next conversation may need to
  wait for the normal claim expiry or a verified explicit release.
- Operations marked started/unverified continue to block any fresh write,
  including after a new claim. This option never retries login, CAPTCHA,
  MFA, payments or publications.
- The existing `release` action is still required for legacy tasks and
  tasks without this flag. Do not call it again after a successfully
  reported automatic release.

The Floot vault now has an in-process, bounded 429 circuit breaker:
the first 429 honors Retry-After or uses a conservative cooldown,
and subsequent concurrent vault operations return the fixed
`TASK_VAULT_RATE_LIMITED` error without more HTTP calls. It does
**not** bypass the Free plan, restore an expired account login,
provide a process-independent scheduler, or certify Steel native /
portable cookie/localStorage/IndexedDB restoration.

The real vault returned HTTP 429 during the neutral end-to-end create test
on 29 October. That test has **not** produced a three-store saved-close
and independent new-controller receipt. Do not use R158's original
protected archive or a real user's Meta/Google profile as an easier fixture.
The next live acceptance after quota recovery is the exact neutral
`/browser-check` fixture with three-store readback, saved close,
fresh claim, and repeat readback after a separate controller boot.
Keep PR #178 (historical R158 forensic evidence) and PR #180 (Neon
shadow migration) separate from this task handoff fix.
