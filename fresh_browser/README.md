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


## On-demand recovery for Render Free cold starts (observed 2026-11-16)

This is an operational recovery protocol for the *existing* installation, not a new browser or an import:

1. If the ChatGPT Site/MCP connector responds HTTP 429 to a **read**, do **not** ask the owner to re-enter credentials, create another profile, reset Neon or replay a form/write. A 429 from the connector does not prove a failed external account login.
2. Independently fetch the unauthenticated `https://ai-browser-neon-fresh.onrender.com/health` **once** to wake an idle Render Free instance. During a cold start, the public Render URL may temporarily respond 503. Allow a bounded, read-only readiness check until HTTP 200 and `{"status":"ready","store":"neon_fresh"}`; never automatically replay an uncertain POST, a login callback or a site mutation.
3. After readiness is confirmed, make one read-only MCP call (prefer `profile_list`), then continue normal work. If it still returns 429 while the origin is ready, investigate the Site/MCP proxy rate limits separately; do not conclude that Render/Neon or saved credentials are broken.
4. If readiness never succeeds, inspect Render instance events/application logs, the deployed revision and Neon connectivity. Preserve encryption keys and `fresh_browser.profiles`, `profile_versions`, `tasks`.
5. Avoid periodic artificial keep-alive pings to force an always-on Free service: it drains shared Free instance hours and cannot guarantee availability. Use official app integrations for work that does not need a browser. A non-sleeping, production-grade browser requires always-on compute, not client-side unlimited retries.

**Verified observations on 2026-11-16 (UTC):** Initially the connected `profile_list` and `browser_sessions` reads each failed with 429, while a separate unauthenticated HTTP request to the Render origin returned 503. A public GET to `/health` induced a start of the existing Render process at 22:37:20; a later health fetch returned `ready`. The exact same connected `profile_list` then succeeded (14 profiles). A synthetic saved profile opened, the website rendered, a snapshot returned, and the session closed normally. Neon held 14 profile rows, 1666 version rows, 33 tasks; no encrypted contents or credentials were accessed. This correlation establishes a working recovery sequence, **not** exclusive proof that every past 429 originated from Render's idle spin-down.

Render's documented Free behavior: idle service spins down after 15 minutes; waking up may take around a minute. Paying for always-on compute removes this source of cold starts, but is not proof of eliminating independent MCP proxy throttling. No billing change, hosting migration or credential rotation is authorized by this note.
