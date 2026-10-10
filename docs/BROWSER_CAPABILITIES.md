# AI Browser — verified capabilities and gaps (2026-10-10)

| Capability | Reality | Evidence/limitation |
| --- | --- | --- |
| Saved profiles | LIVE (10) | `profile_list`; name ≠ active logged-in account |
| Remote browser | LIVE (one at a time) | Render ai-browser-cloud, engine 0.5.2, Steel; provider runtime 0.4.5 |
| Save profile | Partial | `profile_flush` and `browser_stop` return success; restored cookie/localStorage can still disagree (issue #111) |
| Login detection | Cautious | browser status/auth probe; must verify correct account and content live |
| Mobile/iPhone | Partial | Mobile viewer, scrolling, buttons and manual MFA setup; previous WebKit keyboard/refresh bugs |
| DOM extraction | LIVE | `browser_snapshot`, frames, tabs, scroll and downloads |
| Visual capture | LIVE tool, not automated full workflow | `browser_screenshot` delivers image for visual reading. 8/8 historical Instagram Highlight has NOT been verified |
| Google reviews Anita | VERIFIED via official connected API | 20 reviews at GBP locations/17588627068282939119 retrieved 10.10.2026; 15 with text; private Sheet ledger (no review text in public repo) |
| Meta/Instagram official data | CONNECTED for Anita | Read some owned profile/media insights through authorized connector; no guarantee historical Highlight frames available |
| Persistent workflow memory | Partial | Private user Google Sheets contains review ledger; no tenant-safe MCP backend write/read binding yet |
| Multiple tasks at once | Offline verified only | PRs #116 and #117: 3–10 PG slots, locks and fencing; real Steel remains limit 1 |
| Tenant isolation | Offline draft | BFF/RLS/vault #83–#105 not installed on Render/Floot |
| Full profile deletion | BLOCKED | Steel native provider deletion unverified issue #94; legacy profile_delete fails closed |
| Payment controls | Offline draft | Stripe webhooks #106 and readback #107, not live |
| Egress SSRF | Offline draft | #89, not deployed |
| Actionable error on closed page | DRAFT | Issue #118, `TargetClosedError` surfaced generic Error executing tool during read-only Meta - Anita |
| VPN/static IP | Not configured | Not a substitute for stable browser identity, correct cookies, authorized OAuth and Meta security checks |

**Production specifics:** GitHub branch `ai-browser-cloud`, Render `srv-db34e6ks728c73bae4sg`, autoDeploy disabled. Recheck newest SHA, CI and session occupancy before deployment; static document status can age quickly.

## What our work cannot yet claim
- Screenshot existence does not prove image text has been read.
- 20 Google reviews do not prove 8 Highlight quotes are matched.
- Profile `Meta - Anita` exists but current Instagram authentication was not confirmed; the first attempt encountered a closed remote page.
- Documentation alone does not expose tools to ChatGPT; packaged MCP hooks and a trusted checkpoint backend are still required.
- No current commercial release. Multi-client segregation, secure erasure, reliable Meta login, fixed egress and recovery remain P0.
