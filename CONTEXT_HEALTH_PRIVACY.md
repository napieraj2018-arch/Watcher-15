# Context health metadata privacy (2026-10-10)

The public `/health/context` used to expose `credentials_configured`,
`native_profiles`, controller memory and Chromium process count. These
values are internal runtime diagnostics, not an anonymous liveness contract.

This change makes both `/health/context` and `/health/steel` behave
consistently:
- Anonymous request: ONLY `status`, `runtime`, `version`.
- Admin Bearer verified in constant time by the existing server-side helper:
  internal diagnostic fields, without any raw secret or session ID.
- Quarantined Steel state: `degraded` rather than falsely claiming `ok`.
- Missing or invalid admin secret: fail closed with public fields only.
- Automated public perimeter test denies disclosure, while isolated tests
  verify both public and owner response paths.

Public readiness monitors may continue using the `status` field.
Internal monitors that previously relied on credentials/memory details must
be updated to use properly authenticated diagnostics. No keys are placed
in URLs, logs or repository history.

No production credential rotation, profile deletion or Steel session start
occurs in these tests.
