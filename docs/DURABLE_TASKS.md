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
