# Neon Fresh — zero-cost resource and persistence recovery
Date: 2026-10-30 (Europe/Warsaw)
Scope: `fresh_browser/` only, existing Render Free service ai-browser-neon-fresh, Neon Free vault.
Budget: no purchases, no paid upgrades, no payment method changes.

## Changes
1. Saves compute a SHA-256 fingerprint of the canonical (plaintext in server RAM only) profile JSON and skip the SQL version write if it matches the last successfully persisted state. Lease verification is still performed every time. Failed SQL writes do not update this fingerprint.
2. Profile opening initializes the fingerprint from successfully decrypted saved state; switching/closing clears it. Encrypted AES-GCM, monotonic CAS and ownership locks remain unchanged.
3. Mobile UI receives JPEG screenshots at quality 80; the MCP screenshot tool still receives PNG. Both owner and admin mobile screen routes return an ETag bound to pixels plus tab/navigation metadata, with a 304 response for an unchanged frame. Authorization is checked *before* conditional responses.
4. The panel sends If-None-Match only for its currently displayed image. Selecting a different profile clears the ETag. On an unchanged view, refresh intervals increase gradually from 2 to 10 seconds; user actions reset the interval to 2 seconds.
5. After non-idempotent document navigations (e.g. login POST), tab persistence uses the previous committed GET address or a safe public origin, never the POST form target. No automatic form replay.
6. Production Docker build runs test_free_efficiency in addition to existing Chromium/security/form regressions.
7. When no API action, screenshot, tab listing or diagnostics request arrives, the active browser profile is encrypted-and-saved then closed after 30 minutes (agent mode) or 60 minutes (manual owner mode). This releases its DB advisory lock and allows Neon's standard idle scale-to-zero. These intervals do not interrupt an action holding the workspace lock. The next agent request may reopen a saved profile; owner handoff links bound to the closed context need a fresh grant.
8. Neon Free's endpoint setting `suspend_timeout_seconds: 0` uses Neon's default inactivity setting; it is not a request for always-on compute.


## Safety
- No modification to the Floot installation, 68 legacy profiles, the 7833-record migration archive or PR #180.
- No removal/retention pruning of existing Neon profile versions until independent verified backups exist.
- No account passwords, cookies, bearer tokens or confidential URLs in GitHub.
- No changing or bypassing account security, CAPTCHA, MFA, proxy or browser fingerprints.
- No paid plan upgrades, credits, billing changes, or keep-alive tricks to evade provider limits.

## Acceptance gates
- Docker build must complete full test suite (including actual Chromium test).
- Render deployment must be LIVE at the matching commit; `/health` must report database ready.
- Must confirm no active owner profile before deployment. Read-only database/version count before/after if available.
- Synthetic profile persistence and one non-sensitive browser navigation/screenshot after deployment.
- Real Facebook/Google sign-in is a separate owner-driven acceptance and not implied by synthetic tests.
- Render Free can sleep or stop at usage limits. Nothing here guarantees always-on service or unlimited usage.

## Recovery
If image handling or restored profiles regress, redeploy the previous known good commit on the same service. Do not reset Neon, delete profile versions, or migrate Floot while diagnosing.
