# Autonomous browser — operational contract

This document is a PUBLIC operating contract, not an execution ledger.

For every user task: retrieve a trusted versioned procedure, identify the
server-authenticated tenant and actor, choose the appropriate authorized
profile, acquire its durable single-writer lease, check current identity in
the target service, perform permitted reads/actions, and save evidence and
progress privately. If any gate fails, return a specific status without
repeating the login or submitting an action twice.

A stored profile does not prove that a web account is currently logged in.
Never treat cookies, a successful network request, or a saved session label
as identity verification. A challenge requires human authorization; do
not silently retry it.

A website image is a source. Stories, Highlights, carousels, graphics and
reviews require visual image captures with source IDs, sequence indexes,
timestamps and explicit completeness flags. Text snapshots alone do not
prove that every slide has been read.

Private data belongs in encrypted tenant-scoped storage with row-level
database isolation, retention and deletion handling. Source records,
author names, quotes, screenshots, identity receipts, and generated ZIP
files do NOT belong in this public repository or generic server logs.

A workflow has states queued, running, awaiting_human, paused,
completed, failed or cancelled. Completion requires independently checked
source counts and artifact readback. Retry reads idempotently, never
duplicate publications or payments.

Parallel execution is allowed only for different exclusively leased
profiles and after successful provider and database admission. A second
job requiring the same profile waits. Timeout is not proof that a Steel
session ended; uncertain sessions remain quarantined.

Operating recipes should be available through the MCP workflow catalog,
but a public recipe catalog is NOT a per-user memory of completed tasks.
User-specific workflow bindings, evidence and history require a private
authenticated ledger. Do not announce this goal as deployed until a
real cross-chat readback succeeds.

For an operation requiring draft approval, stop before publication.
No browser task may modify an unrelated account.
