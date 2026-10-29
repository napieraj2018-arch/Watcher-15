# Neon Fresh acceptance — 29 October 2026

## Current deployed runtime

Runtime code: `d5b46cf56d080feee0c054d34e27a262151cbbe7`.
Render: `srv-dbhlboe7bikc73eu7v9g`, deployment `dep-dbhoosvb9u1s73fd1ks0`, confirmed LIVE at `2026-10-29T18:13:32.870015Z` (19:13 Warsaw).
Branch remains `aib/neon-fresh-20261029`, PR #184. Auto-deploy is off. This acceptance-document update is documentation only; it does not require another runtime deployment.

The reviewed deployment changed the mobile panel and acceptance documentation only, not backend Python or the database schema. It clears stale screenshots on profile selection, disables profile selection during actions, rejects empty navigation addresses, and distinguishes a completed command from a failed screenshot refresh.

Scope remains independent Neon Fresh with newly saved profiles. Legacy Floot, old Render, PR #180, the old 68 profiles and the 7833-record backup were not changed. Legacy import gates are not prerequisites for ordinary Fresh operations.

## Newly verified through the connected ChatGPT Fresh tool

- The actual `fresh_browser` action tool is exposed and works in this conversation. Its earlier schema-availability gate is now closed here; this does not prove that every older Work conversation has refreshed its schema.
- Dedicated synthetic profile `acceptance-work-recovery-20261029`: form fill and click, encrypted state save, and close succeeded before deployment.
- After runtime replacement, `acceptance` verification returned `cookie=true`, `localStorage=true`, `indexedDB=true`, `history=true`, `all_passed=true`, `saved_closed=true`. A repeated read was used after the first response was interrupted; the seed was not recreated or overwritten.
- Task checkpoint `fresh-recovery-20261029`, revision 1, was read successfully after deployment and retained its completed steps. Later revisions record this completed verification.
- Ordinary connected browser actions opened `https://weterynarz.radom.pl/`, read the real page, dismissed optional cookies, clicked the observed contact link, and read the contact page.
- A real browser screenshot at the configured 390x844 mobile viewport was returned. This tests remote rendering, not physical iPhone touch or keyboard behavior.
- Save/close/open restored the clinic contact page and its content. The owned test profile was saved and closed after the test; no real-account profile was opened or changed.
- No error-level Render logs were returned for the deployment interval queried.

## Frontend checks

On the exact deployed HTML: JavaScript syntax passed; all 23 buttons had handlers; no duplicate element IDs or missing referenced elements were found.
Executing that HTML's JavaScript against a synthetic DOM/API verified stale-screen cleanup and object-URL revocation on profile change (zero POSTs), plus command-success/screenshot-503 handling (one action POST, one screenshot GET, no automatic write retry, controls reenabled). These are mocked behavior checks, not physical-device acceptance.

## Owner panel and bridge

Existing owner-facing URL: `https://ai-browser.xrhb2h65pm.chatgpt.site`.
Sites project `appgprj_6ac65a5b3ad08191ae49e821d236562f`, published version 14, deployment `appgdep_6ae384ecd7288191876ea7cfa152cdc6` succeeded, source `0f2426fb2dc1398a21031e1d6f63e50ff6d464a8`. Access remains limited to the owner, with no external visitors/editors/groups.
MCP binding remains on the existing site's `/mcp`. Historical bridge documentation describes a Fresh proxy at `/fresh`; its current trailing-slash redirect was not independently checked. Use the exact published root URL rather than promising an unverified deep link.

## Remaining limits — do not claim universal acceptance

- Google previously refused the real `google-youtube` sign-in with "This browser or app may not be secure". This deployment does not fix that external website refusal. Do not repeat rejected login attempts, change fingerprints/IPs, import authenticated cookies or weaken account protection to get around it.
- The existing YouTube connector again identified `architekt.radom@gmail.com` and channel `UC7EQ32QjfKQ7bFiVdGAhB-A` (Nasz Kamper Wymiata). An additional authorization-renewal check was rejected by automatic approval review as outside the browser deployment task. No renewal was completed and no alternative route was used to bypass the rejection. Earlier separately recorded private-read verification remains historical evidence, not a new private-read result.
- Real iPhone panel touch/keyboard/upload and a supported-site real-account save-close-reopen remain unaccepted. Synthetic persistence does not establish a real authenticated account.
- A preliminary `go` to example.com reported a generic navigation error although a subsequent snapshot showed its page. The observed page was inspected before any further action, and an explicit save succeeded. Clinic navigation and contact-link actions then succeeded. The precise cause of that first navigation error is not established; do not treat unknown action failures as permission to retry writes.
- The service still uses Render Free. Idle spin-down and cold starts remain possible; no purchase, upgrade or 24/7 guarantee was made.

## Previously recorded security and architecture checks

The earlier acceptance recorded a restricted SQL runtime (no role/database creation, BYPASSRLS, inherited memberships, schema CREATE or profile DELETE), eight security/ownership tests, and fifteen bridge/proxy tests. Those security tests and grant queries were not rerun for this frontend-only deployment.

One live browser workspace; per-profile PostgreSQL advisory lock plus CAS; 15-second periodic saves and saves after actions. Process termination can lose changes after the last successful save. Persisted state is Playwright cookies/localStorage/IndexedDB plus URL history, not a full native Chromium user directory. Checkpoints are durable records, not a background worker or permission to replay uncertain external writes. Encrypted versions in the same database are recovery copies, not independent disaster recovery.
