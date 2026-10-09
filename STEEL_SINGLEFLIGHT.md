# Steel launch singleflight — 2026-10-09

**Scope:** production adapter `steel_runtime.py`; change is staged only and
does not activate deployments, change credentials, log into services, or spend
Steel browser minutes during CI.

**Failure mode:** two calls reaching `Engine.launch` at the same time can both
observe `engine.remote` as empty before awaiting the Steel API. Either call
can create a separate remote browser even though the controller is configured
for a single session. During close, `RemoteBrowser.closed=True` is set before
the remote release finishes, so testing only `not remote.closed` can permit an
early replacement.

**Change:** use an asyncio lock across remote creation, CDP connection and
failed-start cleanup; reject a second start whenever any remote is still
registered, including the period waiting for provider release. Keep the
existing fixed error `STEEL_SESSION_LIMIT_1` and do not expose identifiers.

**Offline tests:** six synthetic, async, deterministic cases: racing starts,
release in progress, reopening after successful close, CDP error cleanup,
provider ID mismatch, and concurrent idempotent close. They stub all HTTP
calls and use a fake CDP browser, so no account or Steel key is involved.

**Boundary / remaining risk:** Steel remote release returning an uncertain
result can still leave an orphaned provider session. A durable quarantine
and authenticated reconciliation mechanism is needed before paid customers.
This patch is one-process singleflight, NOT a cross-instance lease, tenant
authorization, or a complete answer to the commercial release gate.

**Rollout:** do not merge or deploy without a green Docker test run. A
production deploy needs a separate session-free maintenance window and
verification of existing `AI_BROWSER_SESSION_GUARD=probe` behavior; Steel
self-test and real account login must remain separate acceptance stages.
