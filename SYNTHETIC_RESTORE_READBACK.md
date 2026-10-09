# Synthetic profile restoration — distinguish intended from observed

This patch addresses P0 issue #111. It changes **diagnostics only** for the
test profile `SteelSelfTest`; never modifies cookies, profile priority, user
credentials, provider profiles, Meta/Google accounts, authentication or storage
persistence algorithms.

Previous diagnostics labeled the *intended merged state* as `resolved`
before `context.set_storage_state(merged)`. A successful call does NOT prove
the new state was actually installed, persisted, or visible to JavaScript
after navigation. In a real Steel test, the UI showed mismatch after a
freshly saved exact synthetic marker despite `resolved exact_pair=true`.

New behavior:
- `synthetic_fixture_evidence.proposed`: the intended merge before applying.
- `synthetic_fixture_evidence.resolved`: a **fresh Playwright
  `context.storage_state(indexed_db=True)` readback after applying**, not a
  computed prediction.
- `exact_marker.proposed`: same intended-vs-observed distinction.
- `post_apply_readback_available=false` if the independent context readback
  fails. Never misreport as PASS.
- `page_readback`: only when the current URL is EXACTLY
  `https://ai-browser-vault.floot.app/browser-check`, evaluate the page's
  own test cookie and test localStorage pair entirely inside Chromium, then
  return only three booleans, never any cookie/storage values or keys.

Seven offline unit tests, including simulated silent
`set_storage_state` failure, non-fixture pages and malformatted readbacks.

**Still not fixed:** actual provider-native + portable state precedence, the
Floot/Renders backup overwrite risk or post-navigation cookie divergence. Do
not automatically clear cookie storage or force portable priority on real
profiles. Keep release gate NO-GO until a fresh test marker passes save →
stop → new Steel session → page PASS and independent readback.
