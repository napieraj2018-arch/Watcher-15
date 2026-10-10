# Browser capabilities — verified vs planned

The assistant must query LIVE state each time; this file is a release-gate
reference, not a health probe.

| Area | State | Limitations |
| --- | --- | --- |
| Existing AI Browser MCP browse tools | LIVE | Single production Steel session; tool errors possible |
| Persistent browser profile names | LIVE | Saved does not mean authenticated |
| Steel native profile and portable state backup | PARTIAL | Restoring matching cookie/localStorage after restart not reliable; issue #111 |
| Three concurrent slots in PostgreSQL | OFFLINE PROOF | PR #116, synthetic provider receipt |
| Configurable 5–10 concurrent slots | OFFLINE PROOF | PR #117; not deployed to controller |
| Server-authenticated tenant and profile isolation | OFFLINE PROOF | Separate draft chain, no production migration |
| Instagram sequence visual reader | TODO | Browser screenshot exists, automated verified sequences not implemented |
| Durable private task result ledger | TODO | No production tenant-scoped job history API |
| Versioned procedure catalog | STAGED | Source-controlled definitions only until MCP tool and production readback verified |
| Error diagnostics | PARTIAL | Closed-page and busy variants staged; no complete provider reconciliation |
| Private profile deletion | BLOCKED | No confirmed full native-provider erasure |
| Stripe subscriptions | STAGED | No live billing entitlement enforcement |
| Commercial release | NO-GO | Security and operational gates remain |

A direct iPhone Facebook/Instagram app login does not supply a Steel browser
login. A dedicated fixed egress IP can improve consistency but cannot fix
corrupt cookies or localStorage and does not guarantee the provider will
avoid MFA. First verify restoration; then evaluate stable network egress.

For each change: code review, synthetic tests, actual Docker build, live
readback, rollback, and do not restart while another task owns a session.
