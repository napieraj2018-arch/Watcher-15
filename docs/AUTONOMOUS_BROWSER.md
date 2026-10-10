# AI Browser — Autonomous Browser Workflow

## User goal
One user instruction in ChatGPT launches a named workflow with correct stored account routing, source evidence, private durable checkpoints, visual analysis and finished artifact. Never require screen recording, manual transcription, new prompts to Work, or repeated logins while the authorized session genuinely remains valid.

## Execution contract
1. Resolve workflow from a versioned manifest; verify tenant and account ID server-side, not from client headers or URLs alone.
2. Check the current provider account via official OAuth connector/API if it supports the exact data requested. Google GBP reviews can be retrieved without browser login; older Instagram Highlights require a separate visual source unless an authorized API actually returns them.
3. Use exactly one per-profile lock/lease. Active 5–10 browser jobs must use different profiles and a durable task queue with release acknowledgements; the production owner-beta allows 5 distinct profiles, but commercial tenant isolation remains offline.
4. Auth states: `connected_api`, `browser_authenticated_verified`, `needs_user_auth`, `verification_required`, `session_ended`, `provider_unavailable`. A saved profile alone is never `authenticated`.
5. On Instagram Stories/Highlights, store each encountered slide with stable media ID if provided, otherwise a strict source+position reference; capture the visual frame privately, inspect text in pixels and record completeness. Do not assume eight slides were read because a highlight is labeled eight.
6. Dedupe review author and text across Google/Instagram. Retain the exact original quote and source review ID. Group short comments only while keeping authors distinct. If similarity is ambiguous, status = `requires_review`; don't declare unused.
7. Save checkpoints privately after each source and step, with `tenant_id`, `workflow_id`, `run_id`, `step`, `source_id`, `observed_at`, `status`, `completeness`, `private_evidence_ref`. Use idempotent updates, keep run history, protect via ACL/RLS, audit, encryption and deletion.
8. Allowed safe retry: a small bounded retry for a GET that has not submitted anything. Never retry a login, 2FA, payment, deletion or publication blindly. Unknown Steel create/release requires quarantine.
9. Stop at `ready_for_approval` with a private ZIP containing only confirmed unused quotes. Publishing without new approval is forbidden.

## Private progress
The user's own connected Google Sheet already holds the 20 Google Business reviews of Anita, with Aldona Gurtat marked used and 8 empty Instagram checkpoints. This is **private user storage**, distinct from the public code repository. The current MCP server does not yet have an authenticated adapter to that Sheet; agents can access it only through the separate authorized Google Drive connector. A production BFF must provide tenant-scoped private storage and allow MCP tools to read and write checkpoints with authenticated actor identity. Do not paste Sheet IDs or review texts in public Issues, logs or code.

## Technical limits as of 2026-10-10
Real Steel profile coherence issue #111 remains unverified. LIVE owner-beta uses 5 separate sessions; tenant-isolated BFF remains offline. Multi-tenant BFF/RLS/vault/slot modules #83/#98/#100/#102/#103/#105/#116/#117 are offline proofs. Persistent official login may expire due to session age/device checks, and no VPN can guarantee Meta recognizes an account. iPhone app OAuth/2FA handoff is preferred when login is truly required.

## MVP acceptance: Anita reviews
All 8 Highlight frames verified, all 20 GBP review IDs mapped, used quotes deduped (including Aldona), imagery matched to real approved brand kit, private result ZIP, no social publication and verified run history accessible in a new chat. If any item is missing, report precisely `partial` with missing source and blocker; never declare complete.
