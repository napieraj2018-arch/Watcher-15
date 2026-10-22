# AI Browser — verified capabilities and gaps (2026-10-23)

The live baseline for this update is merged PR #153, commit `648963ab`.
Its production smoke test finished on 23 October at 00:28 Europe/Warsaw.
Code changes described below still require their own CI and matching live
deploy before being reported as deployed. Historical account checks retain
their original dates; they are not today's authentication evidence.

| Capability | Reality | Evidence/limitation |
| --- | --- | --- |
| Saved profiles | LIVE (28 at the #153 smoke test) | All 27 existing profiles preserved plus one neutral test profile; name ≠ active logged-in account |
| Remote browser | LIVE (owner beta 5 distinct profiles at a time) | Render ai-browser-cloud, controller 0.5.2, Steel provider 0.4.5, 5 separate owner-beta sessions verified |
| Save profile | LIVE, neutral persistence verified | #153: flush, full saved close, new session, cookie/localStorage PASS before any second write. This does not certify every real account or every restart path. |
| Login detection | Cautious | browser status/auth probe; must verify correct account and content live |
| Mobile/iPhone | LIVE scoped controller; physical-device validation remains limited | Eight fixed service entrypoints, owner-authenticated touch and keyboard. Real Chromium/WebKit CI is distinct from an actual iPhone login. |
| DOM extraction | LIVE | `browser_snapshot`, frames, tabs, scroll and downloads |
| Visual capture | LIVE tool, not automated full workflow | `browser_screenshot` delivers image for visual reading. 8/8 historical Instagram Highlight has NOT been verified |
| Google reviews Anita | VERIFIED via official connected API | 20 reviews at GBP locations/17588627068282939119 retrieved 10.10.2026; 15 with text; private Sheet ledger (no review text in public repo) |
| Meta/Instagram official data | CONNECTED for Anita | Read some owned profile/media insights through authorized connector; no guarantee historical Highlight frames available |
| Persistent workflow memory | Partial | Private user Google Sheets contains review ledger; no tenant-safe MCP backend write/read binding yet |
| Multiple tasks at once | LIVE owner-beta for one owner only | 5 simultaneous real Steel sessions tested; separate tenant-safe PostgreSQL BFF remains offline PRs #116/#117/#129 |
| Tenant isolation | Offline draft | BFF/RLS/vault #83–#105 not installed on Render/Floot |
| Full profile deletion | BLOCKED | Steel native provider deletion unverified issue #94; legacy profile_delete fails closed |
| Payment controls | Offline draft | Stripe webhooks #106 and readback #107, not live |
| Egress SSRF | Offline draft | #89, not deployed |
| Actionable error on closed page | LIVE error classification | PR #119 merged; no automatic repair of closed remote page |
| VPN/static IP | Not configured | Not a substitute for stable browser identity, correct cookies, authorized OAuth and Meta security checks |

**Production specifics:** GitHub branch `ai-browser-cloud`, Render `srv-db34e6ks728c73bae4sg`, autoDeploy disabled. Recheck newest SHA, CI and session occupancy before deployment; static document status can age quickly.

## What our work cannot yet claim
- Screenshot existence does not prove image text has been read.
- 20 Google reviews do not prove 8 Highlight quotes are matched.
- Profile `Meta - Anita` exists but current Instagram authentication was not confirmed; the first attempt encountered a closed remote page.
- Documentation alone does not expose tools to ChatGPT; packaged MCP hooks and a trusted checkpoint backend are still required.
- No current commercial release. Multi-client segregation, secure erasure, reliable Meta login, fixed egress and recovery remain P0.

## Daily-use fixes in the 23 October code

- Normal start/close transitions are distinct from orphaned sessions (#153).
- A cancelled start cleans up only its exact newly created record, with a
  bounded verified saved close; ambiguous results remain blocked.
- Slow startup consumes the provider budget. The owner watchdog and status
  share one fixed deadline with a 90-second save margin.
- CDP close and provider release have separate completion states. Cancellation
  before release must not permanently skip it; uncertain releases do not free
  capacity or silently turn into successful repeated closes.
- The mobile controller accepts textarea, sends unsent text before Enter, and
  provides real Back/Forward/Reload actions within the existing origin scope.

These changes do not turn a saved profile into a resumable task or permit
adopting another conversation's capability. Ordinary browser tools for tabs,
history, navigation, text input and screenshots remain the existing tools.
