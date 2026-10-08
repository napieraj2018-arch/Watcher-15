# Facebook access and Watcher — verified limits (2026-10-08)

## Operational truth
- **Facebook/Instagram business profiles:** available through separately authorized, platform-supported API connectors. This is not a Facebook web-login session.
- **WordPress direct Meta bridge:** `WPCode` snippet 101 on the architectural guide site is active and has an encrypted token stored in WordPress options. Its independent Meta Graph API live connectivity has NOT yet been verified by a safe, nonpublishing test. Do not assume it works because the token exists.
- **Steel remote Chrome:** browser works, but Facebook repeatedly shows `Confirm you are human` / CAPTCHA and has not issued a verified authenticated session. Do not ask the user to keep re-entering passwords or running CAPTCHA.
- **iPhone Facebook app:** the native app's authenticated state cannot be silently imported into server-side Chromium. Do not claim that a cloud browser has inherited that session.
- **Groups API:** do not assume standard Meta Page API grants access to personal-account groups or members-only posts.

## Current Watcher
- GitHub Actions workflow: `.github/workflows/facebook-local-monitor-15m.yml`.
- Source configuration: `config/facebook_local_monitor.json`.
- The monitor polls **two public Facebook pages**, not the user's groups. Both may return partial preview data or a login wall.
- The group entries are **disabled by default** because unauthorized GitHub Actions browsers are redirected to login; a private group also requires membership.
- Success of a GitHub job is NOT proof that a page was readable or that there were no new posts. Check the `Facebook Watcher — rzeczywiste pokrycie` job summary, `COVERAGE_REPORT`, and `SOURCE` lines.
- Health issue deduplication: public GitHub issue marker `fbwatch:health-v1`; avoid duplicate alerts.
- Never put text from private groups, browser cookies, secrets, access tokens, or private group post bodies in public GitHub Issues or Actions logs.

## Safe route forward
1. Keep active API access to authorized business Pages and Instagram separate from remote browser auth.
2. For personal/group content on iPhone, use the Facebook app's own authenticated UI and user-authorized sharing/notifications. An on-device companion would require explicit iOS setup and cannot automatically read another app's private storage.
3. If planning an ingestion endpoint for user-shared posts, make it authenticated and private, with clear retention and no automatic posting to Facebook.
4. Do not change budgets, organic schedules, publication settings, or existing encrypted profiles while diagnosing login.

## Last checks
- 2026-10-08: GitHub Actions run 37789954274 succeeded and printed `COVERAGE_REPORT total=2 readable=2 disabled_groups=4 state=PODGLAD PUBLICZNY`. Readability was less than complete in an earlier run; coverage may fluctuate.
- 2026-10-08: authorized social API read returned Facebook and Instagram media for the architectural business accounts; these reads do not prove remote browser login.
- 2026-10-08: the latest Steel login displayed Meta's human-verification screen and was closed with its profile saved.

**Security:** No credentials or auth-session material should be placed in this document.