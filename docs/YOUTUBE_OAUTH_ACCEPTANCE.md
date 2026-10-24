# YouTube OAuth / Data API — implementation checkpoint, 24 October 2026

Status: **BACKEND IMPLEMENTED AND OFFLINE-TESTED; NOT WIRED, NOT DEPLOYED,
NOT AUTHORIZED.** This is part of issue #160 in the existing AI Browser,
not a new app and not a claim that Google login now works.

## Added backend

`youtube_oauth.py` implements authorization-code OAuth with PKCE S256,
10-minute state, one-time state consumption before exchanging the code,
browser-cookie binding, offline consent, exact-channel verification using
`channels.list(mine=true)`, refresh-token handling and a dedicated AES-GCM
credential envelope bound to owner, OAuth client and channel. No browser
cookies, passwords, Google connector tokens or private account data are used.

The Data API client can read an existing video, prepare/execute/verify approved
metadata updates and set an approved PNG/JPEG thumbnail. It preserves other
writable fields in each updated resource part and uses an operation journal
with atomic insert/CAS. An ambiguous result is not automatically resubmitted.
Thumbnail receipt means provider acceptance, NOT exact-pixel readback.
The local thumbnail limit is deliberately conservative (2 MiB); it is not a
claim about Google's current maximum. No video insert/upload/delete methods,
comments, billing changes or automatic publication are exposed.

The backend does NOT itself authenticate HTTP users or expose MCP tools. The
`DurableCAS` interface is an integration contract, not an implemented production
store. The in-memory `Store` in the test file is explicitly a TEST DOUBLE.
A boolean `durable` marker is a fail-closed configuration guard, not proof of
storage durability. No import/startup/Docker/Render changes were made.

## Verified offline

Command: `python -m unittest -v test_youtube_oauth`
35 tests passed with synthetic fixtures and httpx.MockTransport.
Includes wrong browser/state/channel/scope, expiry/replay, encrypted storage,
owner isolation, CAS conflicts, token refresh and revoked grant handling,
fixed-code errors, redirect refusal, metadata preservation, exact approval,
write timeout/read-only reconciliation, duplicate operation refusal and
thumbnail acceptance semantics. Scheduling includes the Europe/Warsaw DST
transition: 25 October 2026 at 08:30 is 07:30 UTC. No real film was changed.

## Current external blockers

A fresh Floot administrative call returned the daily build limit on
24 October at 00:16 UTC. Its stated reset is **24 October 2026 13:00 UTC /
15:00 Europe/Warsaw**. No paid action, alternate account, endpoint or purchase
was used to circumvent it. Normal existing vault runtime was not changed.
Opera reported disconnected. Google Cloud configuration for this YouTube
integration has not been verified; do not infer that no existing client exists.

## Required before deployment

1. Inspect the EXISTING Google Cloud project/client used by the owner. Reuse
   the approved configuration where appropriate; preserve all existing redirect
   URIs and Search Console grants. Enable YouTube Data API v3 and register the
   EXACT chosen HTTPS callback `/youtube/oauth/callback`. Client secret goes
   only into a private server-side secret facility, never chat, repo or logs.
   Request only `youtube.force-ssl`, required for the requested update methods.
   Verify consent-screen publishing status: External/Testing refresh tokens
   can expire after seven days. Do not promise permanent authorization and do
   not change application publishing/verification status without checking impact.
2. Implement a separate credential/pending-state/operation namespace in the
   existing private vault. Implement `DurableCAS.read/write` using atomic INSERT
   and revision CAS in the actual database, with authenticated server-side owner
   binding, access controls, retention/cleanup and bounded input sizes. Do not
   put OAuth credentials into browser-profile or aib_task records. Derive a
   separate 32-byte key using a dedicated label; no reuse of browser keys.
3. Add authenticated MCP connect/status/read/prepare/update/verify/thumbnail
   wrappers to the existing server and plugin. Do not expose tokens or secrets.
   `approved_digest` must come from the exact user-approved channel/video/values,
   not be treated as user authorization merely because an agent computes it.
4. Implement the SYSTEM-BROWSER handoff: owner-authorized single-use invitation,
   a first-party Secure/HttpOnly/SameSite=Lax random cookie, CSRF/origin checks,
   durable state persisted before redirect, exact callback URI, fixed safe errors,
   no-store/no-referrer headers, no open redirects. Strip callback query strings
   from all access/proxy/error logs before enabling the route. The callback must
   consume state once before code exchange. Do not open Google consent in Steel.
5. Add bounded flow limits and cleanup; validate real CAS under concurrent workers
   and restarts. Add callback/HTTP/MCP/security tests and staged-file ownership
   checks. Review provider response shape validation and real conditional-write
   behavior. Add token disconnect/revocation through an explicit authorized flow.
6. Before deploy check current sessions/tasks/provider recovery gates and finish
   only owned work. Do not restart others' sessions. Run full production-image CI,
   deploy exact reviewed SHA only when idle, then perform actual owner consent.
7. Confirm channel with `channels.list(mine=true)`. Read an existing authorized
   private video without modifying it. Verify token refresh and persisted access
   after a safe restart. Only a separately approved exact mutation may test writes.
   Do not close #160 or say "connected" until the real readback succeeds.

The remaining storage and handoff steps are necessary implementation work,
not merely a missing user click. No usable OAuth connection link is issued yet.

## Primary references

- https://developers.google.com/identity/protocols/oauth2/web-server
- https://developers.google.com/identity/protocols/oauth2#expiration
- https://developers.google.com/youtube/data/reference/rest/v3/channels/list
- https://developers.google.com/youtube/data/reference/rest/v3/videos/update
- https://developers.google.com/youtube/data/reference/rest/v3/thumbnails/set
