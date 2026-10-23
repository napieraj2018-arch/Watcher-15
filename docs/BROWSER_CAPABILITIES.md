# AI Browser — verified capabilities and gaps (2026-10-23)

The live baseline for this update is PR #155, commit `47fbb0ce`.
The newer login/save repair is tracked in [PR #156](https://github.com/napieraj2018-arch/Watcher-15/pull/156).
Its Acceptance section records its own CI, exact deployed SHA and live readback;
consult that receipt before treating the baseline below as the latest deployment.
Render deploy `dep-dbddnfd9fdbs73ap9mcg` became live on 23 October at
06:01 Europe/Warsaw. At 06:05, the real Steel acceptance passed restored
cookie/localStorage from before deployment, text/textarea, tabs, reload,
Back/Forward and five isolated simultaneous profiles with full saved close.
CI passed 573 image regressions, 9 Chromium and 10 WebKit checks, 4 external
CDP history checks and three independent profile readback rounds.
Code changes described below still require their own CI and matching live
deploy before being reported as deployed. Historical account checks retain
their original dates; they are not today's authentication evidence.

| Capability | Reality | Evidence/limitation |
| --- | --- | --- |
| Saved profiles | LIVE (35 at the #155 smoke test) | All 30 original profiles preserved plus five neutral test profiles; name ≠ active logged-in account |
| Remote browser | LIVE (owner beta 5 distinct profiles at a time) | Render ai-browser-cloud, controller 0.5.2, Steel provider 0.4.5, 5 separate owner-beta sessions verified |
| Save profile | LIVE, neutral persistence verified | #155: restored a marker saved before its Render deployment, explicit flush and full saved close of five isolated profiles. This does not certify every real account. |
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

## Daily-use repair acceptance — 23 October follow-up

The follow-up repair adds cancellation-resistant saved close, fixed-deadline
mobile invitations, numeric verification fields and selection of trusted login
popup tabs. Each touch action is bound to the observed tab reference; pending
input cannot be redirected to the opener after a popup closes.

Back/forward use Playwright's `commit` wait, following its
[upstream history fix](https://github.com/microsoft/playwright/pull/41153).
The hook applies only to pages in the owned provider-native context and
preserves the existing timeout, return value and exception without retries.
Reload retains its original behavior. A real external Chromium/CDP regression
uses local HTTP pages so ordinary Playwright launch defaults and request
interception cannot hide the production integration path.

Errors before a provider create request no longer trigger speculative release
or quarantine. Uncertain actual create/release operations still remain blocked.
Real Playwright timeouts report an unconfirmed outcome and require status/page
inspection before any retry, because the operation may already have completed.

These changes require the matching production-image CI and a live deployment
receipt. They do not add durable task resume after a process restart, extend
the provider's session budget or prove authentication to a real service.

## Login experience follow-up

The new code adds a single-screen phone controller, focus-kind hints, bounded
frame fetching after phone/app switches, readback of the exact saved-close
receipt, optional provider CAPTCHA automation and an agent-side connected
Gmail route for ordinary confirmation links. See
[the scope and acceptance contract](LOGIN_EXPERIENCE_20261023.md).
Provider CAPTCHA availability must be read from the actual create response;
requesting it is not proof of solving. Email code input remains the secure
owner controller until a dedicated scoped secret-input API is available.

The current Render service is on its Free plan and application logs show
automatic idle shutdown and later startup. Saved profiles use the existing
encrypted external vault; the in-memory task and its capability are separate.
Do not describe an idle cold start as deleted profile data, or promise a
continuous unattended task based on a saved profile alone.
