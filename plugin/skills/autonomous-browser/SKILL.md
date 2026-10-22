---
name: autonomous-browser
description: Use for AI Browser website tasks, saved account access, Facebook or Instagram work, combined mail/site/social requests, or continuation and diagnosis of this AI Browser project. Prefer connected service APIs before browser login, isolate blocked steps, and verify actual outcomes.
---

# AI Browser — account access and continuation

This skill accompanies the existing AI Browser App connection. It is operating
procedure, NOT an OAuth grant, a new task runner, a provider-recovery endpoint,
or a guarantee that additional MCP tools are visible in this conversation.
Follow the user's current scope and the host's tool permissions. Do not expand
an audit into publication, billing, changing account security, or credential
collection.

## Start with the requested job, not a login screen

Identify the service, exact account/brand, intended read or write, and the
concrete material when writing. Resolve existing account IDs and previous
choices through the connected services and the existing catalogue rather than
asking the user to repeat already available information. Ask only for a
required detail that cannot be resolved safely. Do not equate an Instagram
personal feed, Facebook group, business Page or business analytics.

Use this order for EACH independently executable step:
1. Existing connected provider API/OAuth for the exact requested operation.
2. The explicitly authorized saved browser profile, after current verification.
3. Only actually required one-time authorization, through the provider's secure
   interface. Passwords and verification codes do not belong in chat.

A saved profile, cookie, account listing, advertised action, administrative
role, or successful previous run is not proof of today's full permissions.
Read the current account identity and relevant action schema first; distinguish
metadata reads from upload/publication success. Never create a test social
post or send a test email just to check access.

## Reuse the existing catalogue, do not build another one

The existing catalogue is maintained in repository
`napieraj2018-arch/Watcher-15`, branch `ai-browser-cloud`:
`operator_catalog.py`, `connector_router.py`, `docs/CONNECTED_SERVICES.md`,
`docs/AUTONOMOUS_BROWSER.md`, and the relevant manifest in `workflows/`.

When actually exposed, use `aib_route_operation` and the existing workflow
list/describe tools for route hints. They do not execute connected APIs.
Discover available tools through the host before calling them. When these
catalogue tools are missing, read the catalogue via the connected GitHub tool
and call the real provider connector directly. Never ask for browser login
merely because this chat has an older MCP tool list. Do not invent tools or
claim that server registration refreshed the mobile App binding.

Gmail tasks use the connected Gmail tools; WordPress uses WPVibe after site and
ability checks; supported social and business operations use the connected
Windsor provider. This is selection guidance, not a second account mapping.
The existing catalogue and live provider identity resolve exact accounts.
For unsupported operations, verify the scope of the saved browser account;
never silently replace a requested Reel with a photo post or a Highlight with
an unrelated API metadata response.

Use the eight-service mobile-login path only after confirming that the current
deployment and available tools expose it: Facebook, Instagram, ChatGPT,
Metricool, Canva, Google, WordPress Architekt and WordPress Napieraj i Synowie.
Use the existing owner-authenticated handoff and its server-selected login
origin and SSO scope; never supply a wider origin allowlist or invent a missing
tool. Same-tab login support does not imply support for every OAuth popup or
cross-origin iframe. An origin test or synthetic Chromium test is not a real
login to each service or a successful iPhone test. Confirm the intended account
on the actual site after authorization and again after save, close and reopen.

## Separate access errors from logout

- Empty data: inspect query, account, date range, supported fields and freshness.
  Report an incomplete/unconfirmed read; do not declare the account logged out.
- Timeout or provider outage: at most a bounded read retry where appropriate;
  do not submit login or switch accounts. Respect provider Retry-After.
- Permission denied: check the exact account and operation scope. A write
  permission error does not invalidate an already working read connection.
- Explicit provider reauthorization requirement: confirm the actual response,
  then request authorization only for the affected connection.
- CAPTCHA or required human MFA: pause the affected step for the user and retain
  the last verified checkpoint. Do not work around the challenge.
- Unknown outcome of a write: check receipts or the created object before any
  resubmission; otherwise keep the outcome unconfirmed.
- Browser quarantine: do not clear flags, force-stop, restart or start another
  paid browser to work around it. Continue independent API/offline work that
  neither depends on nor changes the quarantined browser.

These rules never authorize copying OAuth tokens from another connector into
the browser server. Saved-credential support, where separately authorized and
verified, must be server-side, exact-origin and account-scoped. Do not enable
global credential injection or retrieve a user's password into model context.

## Five owner tasks and interrupted chats

Check current session metadata before browser work. Use only the opaque
capability returned for this task's own successful start. A name in the
profile catalogue is not a right to adopt a browser opened by another chat.
Keep one writer per profile; do not clone live authenticated profiles just to
obtain parallelism. Independent API work does not require a Steel slot.

Plan work against the returned `remaining_seconds`, not a nominal provider
session length. The owner watchdog allows at most 780 seconds (13 minutes)
after the session grant, and less when startup has already consumed the
provider's budget. It reserves 90 seconds before the lower runtime deadline
for saved close; status and watchdog use the same fixed deadline. A later
capability expiry gives no extra working time, and a status read does not
extend the deadline. Save the task's private checkpoint before closing starts,
and finish through its own save/close path while ownership remains valid.
Do not promise unattended multi-hour work from one short browser session.

The current runtime has no durable task/capability resume after a process
restart (`durable_resume_supported: false`). A saved browser profile is not a
restored task or a recovered capability. A new authorized task may reuse that
profile only after the previous session's save and closure are accounted for.

An interrupted start can safely close only the exact new record created by
that start, with verified full save; this cleanup is not task recovery or
permission to adopt another chat's session. An exhausted startup budget must
not be reported as a healthy new browser. Inspect the actual outcome before
starting another session, and preserve any unresolved quarantine.

If a start call is interrupted, or the capability is lost, use ONLY a deployed,
verified, owner-authenticated resume mechanism. A draft implementation or SQL
test is not live recovery. Never infer a capability from profile names, logs,
provider IDs or an old chat. No task may cancel another task to free a slot.

Do not report real parallel execution or durable checkpoints based on a plan.
When private checkpoint storage is available, keep source identity, observation
time, completeness, operation result and receipt there, without logging secrets.
Reuse the existing review ledger rather than duplicating it.

## Development / deployment continuation

For changes to AI Browser itself (not every routine mail or WordPress read),
check current GitHub branch HEAD, relevant PRs/CI, Render LIVE commit,
`browser_sessions`, profile metadata and concurrent work. Repo HEAD and deployed
commit are separate facts. Distinguish an old report from a fresh response.

Production service: `srv-db34e6ks728c73bae4sg`, workspace
`tea-db33rcjncjis73ecbbj0`. Auto-deploy has historically been off; verify it.
Reuse the existing code and PRs. Preserve private encrypted profile
checkpoints. For a neutral input or persistence test, use a dedicated new
synthetic profile and neutral fixture, with actual page readback and a verified
save, close and reopen. Do not use the old `SteelSelfTest` with its expired
marker as a neutral smoke test; repair that fixture separately when needed.
Do not experiment on real Meta or Google accounts to validate browser controls.

Treat the historical #148 provider incident as resolved by authenticated
exact-session evidence in [comment 6129272443](https://github.com/napieraj2018-arch/Watcher-15/issues/148#issuecomment-6129272443), not as a permanent
global blockade. That historical resolution does not settle a new
`recovery_required`, `missing_session_quarantined` or
`provider_reconciliation_required` state; verify the affected current session.

An empty browser list is NOT an idle certificate after a failed save, lost
lease, interrupted start or provider-reconciliation error. After such
uncertainty, deployment needs independent authenticated provider state,
reconciled local save/lease state and a safe rollback. Never restart to make
an in-memory quarantine disappear. Work on isolated branches and synthetic
tests while this gate remains unresolved.

When a tool write is refused, record the specific failure and stop that write
path. Do not retry it via another encoding, endpoint, identity or tool to evade
safety controls. A refusal in one scheduled execution does not establish a
permanent GitHub account ban. Verify new authorized work with its real result;
report unknown cause as unknown. Do not generate repeated empty branches or
repeat the same failed write every hour.

A user-approved recurring task must reuse its existing automation, distinguish
read-only monitoring from code mutation, and check live state on every run.
Do not resume a paused automation or silently change its cadence without user
intent. Updating this skill does not start an automation.

## Completion report

State only newly completed work, the supporting provider/CI/commit result,
whether it is deployed, and the next actual blocker. A successful save is not
a verified login restore. A new plugin release is not verified invocation in
all old chats. The commercial multi-customer release remains subject to the
existing independent release gates, not the owner's five-session beta test.
