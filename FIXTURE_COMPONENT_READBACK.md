# Exact fixture restore component readback — diagnostic only

This proof follows a real failure under GitHub issue #111: after saving a
coherent synthetic marker in SteelSelfTest, `portable` and `proposed` were
coherent, but post-`set_storage_state` `resolved` and the browser-check
DOM both disagreed.

The only new production behavior is **additional booleans and counts** under
`synthetic_fixture_evidence` when the saved profile is exactly
`SteelSelfTest`. No changes to merging, persistence, real user profiles,
server secrets, Steel sessions, payments or Floot.

- `apply_comparison.cookie_matches_proposed`: exact test cookie in actual
  Chromium context equals the cookie in proposed merged state.
- `apply_comparison.storage_matches_proposed`: exact test localStorage value
  in actual Chromium context equals proposed.
- `post_navigation_context`: a fresh context storage_state read **after**
  page navigation to exactly the `/browser-check` fixture, with counts and
  boolean pair matching only.
- `page_readback`: existing DOM boolean checks.
- `coherent_pair_selected`: whether the existing SteelSelfTest-only
  proposal code selected a portable pair.
- If readback is unavailable, it returns a fixed status. No raw cookie,
  localStorage, ID, token, hash, provider profile reference or domain from
  other sites is returned.

Tests prove that unequal cookie and storage are distinguished, including
silent failures, invalid shapes and non-fixture pages. DOCKER CI includes the
additional suite.

**This remains diagnostic, not a recovery fix.** If E2E still fails, determine
which component is incorrect. Do not alter real Meta/Google storage by trial
and error; ensure all test sessions are stopped and recorded as synthetic only.
