# Synthetic coherent marker fallback — strictly SteelSelfTest

This experiment responds to issue #111. It does NOT solve the general browser
authentication/storage coherence failure, and does NOT alter Meta, Google,
real customer or paid tenant profiles.

The existing merge defaults to provider-native cookies and supplements missing
localStorage from the encrypted portable copy. When the provider-native cookie
is old but the portable cookie and localStorage contain a consistent pair,
this can create an incoherent mixed state.

In this candidate, ONLY `binding.profile == "SteelSelfTest"` uses a narrowly
scoped repair: if the portable backup's exact dummy cookie and exact dummy
localStorage key are fresh, unique and mutually consistent, while the proposed
merged state is inconsistent, it replaces *just that synthetic cookie and
storage key*. Other cookies, origins and IndexedDB data remain intact.
Test-only inputs are never logged or exposed.

The candidate will be proven first with deterministic offline tests (no live
Steel or account access). Real acceptance additionally requires the new
post-apply readback and actual browser-check DOM result to BOTH report PASS
after save, stop and a fresh remote session. If not, don't enable this behavior
for any real profile.

A preserved backup may be stale even if internally consistent. Because this
test-only page deliberately generates a fresh marker, the acceptance must use
a new marker and a 1-hour cookie lifetime. A successful marker test cannot
certify actual Meta/Google logins or cross-tenant isolation.

Not a Stripe, Floot or production data migration.
