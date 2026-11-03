# AI Browser — Neon Fresh (independent clean start)

This is a **new** browser worker and data vault, not a migration of the 68 archived Floot profiles.

- Render: independent `ai-browser-neon-fresh` (Frankfurt), on branch `aib/neon-fresh-20261029`.
- Neon: independent project `ai-browser-neon-fresh` (`withered-voice-97497155`) in Frankfurt, database `browser_fresh`, `fresh_browser.profiles` table.
- Existing Floot production Render `ai-browser-cloud` and mobile login helper `ai-browser-login` are untouched. Existing Neon migration project and immutable 7833-record backup are untouched.
- Do not reuse Floot ADMIN, MASTER, PROFILE, Steel session IDs or cookies in the new instance. Never configure a fallback to Floot.
- Dedicated environment secrets: `AIB_FRESH_DATABASE_URL` for new project/role only, `AIB_FRESH_DATA_KEY` a new CSPRNG-generated 32-byte base64 key, `AIB_FRESH_ADMIN_TOKEN` a new unique random string of >=32 characters. Store only in Render environment.
- The browser starts with zero logins. The owner signs in manually to each external site via the mobile panel. Profiles are encrypted (AES-GCM) before insertion into Neon, with monotonic revision compare-and-swap.
- Saved state includes Playwright cookies, localStorage and supported IndexedDB (not guaranteed to replicate all native Chromium storage, browser extensions or hardware-bound passkeys).
- One browser profile active per Render worker; state saved after each browser operation and on close/shutdown. No delete endpoint. If Neon save fails or revisions diverge, fail closed.
- The mobile screen is a remote Chromium screenshot with touch-to-click and keyboard controls. It is not automatically connected to the ChatGPT MCP connector; connecting it to ChatGPT is an additional, verified integration step.
- The old Floot instance can be selected using its own URL, but it remains unavailable while Floot hosting is suspended. Never claim the old profile logins were transferred.
- Watch Render/Neon free limits; having two services is not enough for true high availability if both share common upstream services.
- Account credentials: user enters on target login screen; API logs, server logs and GitHub do not contain them. Do not put private keys or connection strings in this repository.
- `GET /health` returns 200 only when database credentials work, 503 otherwise. Never expose writable profile data anonymously.
- Build executes `server.py` self-test. After deploy, test with fresh synthetic profile, restart the service and verify encryption readback; then confirm one real account with explicit owner login.

## Scope

This is a fresh browser service, not the full feature parity of the pre-existing AI Browser connector (task CAS, audit archive, native Steel recovery). Do not point the existing connector at it until feature parity or an explicit separate MCP connection is verified.
