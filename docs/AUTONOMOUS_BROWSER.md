# AI Browser — Autonomous Browser Workflow

## User goal
One user instruction in ChatGPT launches a named workflow with correct stored account routing, source evidence, private durable checkpoints, visual analysis and finished artifact. Never require screen recording, manual transcription, new prompts to Work, or repeated logins while the authorized session genuinely remains valid.

## Current continuation baseline — 2026-10-23

The latest recorded deployment is [#154](https://github.com/napieraj2018-arch/Watcher-15/pull/154), commit `975117f1f0766648ef57af1595f452c98029b6a0`, live on 23 October at 05:40 Europe/Warsaw. Its neutral smoke test passed input, textarea/Enter, tabs, reload and full saved close, preserving all 30 pre-test profiles. Back/forward changed pages but produced a DOMContentLoaded timeout; the current follow-up repairs that specific defect and requires its own CI/live receipt. The earlier #153 test confirmed matching cookie/localStorage after a new session; #138 also covered a synthetic restore after a Render restart. See `docs/BROWSER_CAPABILITIES.md` and the latest merged PR for subsequent acceptance evidence.

Historical #111 failures are not evidence that every current profile is broken. The exact remote session from #148 was [independently confirmed Completed](https://github.com/napieraj2018-arch/Watcher-15/issues/148#issuecomment-6129272443); its expired-marker regression remains separate. Do not use the old `SteelSelfTest` marker for a neutral control test. Recheck live deployment and session state; neither an old successful test nor a newer merged PR proves today's deployed behavior.

Previously granted user authorization remains valid for its exact scope. Continue authorized repository repair and safe deployment without asking again. This does not authorize unrelated publication, account-security changes or spending. New uncertain provider/save/lease state still requires reconciliation; never restart or clear flags to hide it, adopt another task, or infer idle state from an empty list after a failure.

## Execution contract
1. Resolve workflow from a versioned manifest; verify tenant and account ID server-side, not from client headers or URLs alone.
2. Check the current provider account via official OAuth connector/API if it supports the exact data requested. Google GBP reviews can be retrieved without browser login; older Instagram Highlights require a separate visual source unless an authorized API actually returns them.
3. Use exactly one per-profile lock/lease and only the capability issued to this task. The production owner-beta allows five distinct profiles. Durable queue, cross-chat task recovery and commercial tenant isolation remain separate offline work; a saved profile does not restore a task or capability. Use the returned remaining budget and save the private checkpoint before the owner's automatic saved close.
4. Auth states: `connected_api`, `browser_authenticated_verified`, `needs_user_auth`, `verification_required`, `session_ended`, `provider_unavailable`. A saved profile alone is never `authenticated`.
5. On Instagram Stories/Highlights, store each encountered slide with stable media ID if provided, otherwise a strict source+position reference; capture the visual frame privately, inspect text in pixels and record completeness. Do not assume eight slides were read because a highlight is labeled eight.
6. Dedupe review author and text across Google/Instagram. Retain the exact original quote and source review ID. Group short comments only while keeping authors distinct. If similarity is ambiguous, status = `requires_review`; don't declare unused.
7. Save checkpoints privately after each source and step, with `tenant_id`, `workflow_id`, `run_id`, `step`, `source_id`, `observed_at`, `status`, `completeness`, `private_evidence_ref`. Use idempotent updates, keep run history, protect via ACL/RLS, audit, encryption and deletion.
8. Allowed safe retry: a small bounded retry for a GET that has not submitted anything. Never retry a login, 2FA, payment, deletion or publication blindly. Unknown Steel create/release requires quarantine.
9. For the Anita reviews preparation workflow, deliver a private ZIP containing only confirmed unused quotes and stop at `ready_for_approval`. Publication requires explicit user authorization for the exact material and target account; honor that authorization if already granted, otherwise obtain it only after the complete package is ready to review. A browser repair request does not authorize social publication.

## Private progress
The user's own connected Google Sheet already holds the 20 Google Business reviews of Anita, with Aldona Gurtat marked used and 8 empty Instagram checkpoints. This is **private user storage**, distinct from the public code repository. The current MCP server does not yet have an authenticated adapter to that Sheet; agents can access it only through the separate authorized Google Drive connector. A production BFF must provide tenant-scoped private storage and allow MCP tools to read and write checkpoints with authenticated actor identity. Do not paste Sheet IDs or review texts in public Issues, logs or code.

## Remaining limits

Synthetic persistence evidence does not confirm authentication to a real Meta/Google account or every restart path. Verify the intended identity on the actual site, including after reopening when checking login persistence. The #153 baseline provides an owner-scoped mobile controller for eight fixed services; Chromium/WebKit CI does not establish a physical-iPhone login to each service. When human authentication is actually needed, use the deployed owner-authenticated handoff; never ask for credentials in chat or expand its origin scope.

LIVE owner-beta supports five separate sessions for one owner, with memory-only task capabilities and no durable resume after process restart. Multi-tenant BFF/RLS/vault/slot/resume modules #83/#98/#100/#102/#103/#105/#116/#117/#129 are offline proofs, not an alternative production recovery path. Persistent website login may expire due to session age/device checks; no VPN guarantees account recognition. Commercial release remains subject to the independent gates in #101. See `docs/BROWSER_CAPABILITIES.md` and `docs/LOGIN_STABILITY.md` for current scope and operational limits.

## MVP acceptance: Anita reviews
All 8 Highlight frames verified, all 20 GBP review IDs mapped, used quotes deduped (including Aldona), imagery matched to real approved brand kit, private result ZIP, no social publication and verified run history accessible in a new chat. If any item is missing, report precisely `partial` with missing source and blocker; never declare complete.
