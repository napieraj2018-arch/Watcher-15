# Local Playwright Chromium 1.59 storage reconstruction test

This is a controlled diagnostic for issue #111: in real Steel, a compatible
portable snapshot was computed, but the provider-managed Chromium context
failed to expose matching test cookie/localStorage after restart.

The test launches **local Chromium only**, using the exact production image,
temporary userDataDir profiles and a loopback HTTP fixture. It never calls
Steel, Floot, Stripe, Render or any customer website and does not read
personal profiles.

The test separately checks:
1. `browser.new_context()` (non-persistent), then
   `context.set_storage_state(portable)`.
2. `chromium.launch_persistent_context(temp_dir)` with an old test cookie and
   **no native localStorage**, close, reopen, apply portable snapshot, verify
   immediate storageState and page DOM, close, reopen a third time and verify
   Chromium persisted the pair.
3. The same persistent test with **old native localStorage present**.

The only state consists of fictional deterministic markers under
`127.0.0.1`, deliberately using port-scoped same-origin localStorage and a
cookie path matching `/browser-check`. The test reports booleans/pass codes,
not cookies or profile data.

Outcomes:
- If all local tests PASS and Steel E2E fails, investigate Steel's native
  persistent profile lifecycle, CDP-connected context timing, backup races and
  profileRegistry binding, not Playwright syntax alone.
- If local tests FAIL, first correct our Playwright usage/version/contract
  before experimenting on user data.
- Local PASS is not a guarantee of remote persistence or login success.

No commercial release claims. Never run against an actual userDataDir.
