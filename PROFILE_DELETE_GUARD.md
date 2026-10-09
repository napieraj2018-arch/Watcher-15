# AI Browser — legacy profile_delete safety interlock

Status: staged for production review (2026-10-09). No profile deleted.

## Why this change is necessary

The saved-profile vault currently refuses a partial deletion with HTTP 409,
but the legacy MCP `profile_delete` tool still exists. A tool must not delete
part of the data, or report success, while native Steel Cloud profiles,
encrypted snapshots, archival versions, staged files or recordings have not
been independently erased and verified.

## Implemented

- The bootstrap installs an unconditional guard on the MCP registry's exact
  `profile_delete` entry during the existing mobile repair path.
- An invocation fails immediately with the fixed
  `PROFILE_ERASURE_PAUSED_PROVIDER_UNVERIFIED` error.
- The original callback is not invoked, and the response does not include
  the profile name, its payload, provider ID or user data.
- If the expected destructive tool is missing or changes its async contract,
  startup fails closed. Other tools remain untouched.
- 7 offline tests cover denials, missing/mismatched tool schema, idempotency
  and no accidental deletion; tests run in the exact Docker image.

## What it deliberately does NOT claim

This is an MCP-entrypoint guard, not a complete API-wide data-erasure
solution. The encrypted controller may expose additional mobile HTTP routes,
and the provider may retain independently stored profile data. Before
commercial release all routes and background jobs must enforce durable
per-tenant tombstones, validated MFA/step-up and receipt-backed full erasure.

The guard must NOT be removed to let a user delete only local state.
Continue to use issue #94 and the independent Steel deletion/retention
confirmation process. No automatic test should attempt deletion of a real
profile.

This patch does not modify customer profiles, sessions, Floot data, Steel
credentials, encryption keys, HTTP API routes or billing.
