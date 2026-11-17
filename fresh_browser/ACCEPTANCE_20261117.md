# AI Browser 2.0.3 — live acceptance, 17 November 2026 (Warsaw)

## Actual deployed code

- Runtime commit: `b2f7d05f7b7e9a1f3868b30c82a669cb7f29f779`.
- Existing Render: `srv-dbhlboe7bikc73eu7v9g`; deployment `dep-dbtovhou01pc73clqj3g`.
- Render confirmed LIVE at `2026-11-16T23:22:19.776433Z` (17 November, 00:22 Warsaw).
- A real authenticated `fresh_browser(runtime_status)` independently returned version 2.0.3, that exact commit and `command_admission.lock_wait_timeout_seconds=5.0`.
- Runtime was deployed only after a fresh observation showed no open profile, no human control and no busy operation. Earlier unrelated audit activity was not closed or adopted by this repair task.
- This document is a later documentation-only commit. Auto-deploy remains off; do not mistake its HEAD for the deployed runtime.

## What changed

New `command_admission.py` and `admission_runtime.py` bound the first foreground wait for the existing workspace lock to five seconds. A command which cannot enter is rejected with `browser_busy_before_start`, `outcome:not_started`, `queued:false`; it cannot execute later from a hidden queue. There is no automatic command retry. Commands which already entered a critical section are not cancelled by this admission timeout. Autosave and shutdown keep their original maintenance locking.

The actual entrypoint is `admission_runtime:app`. Existing authentication, owner handoff, per-profile leases, encrypted state, CAS, WordPress REST/CSS rules and cooldowns are preserved. No provider rate limits were removed. This changes application command admission, not the upstream ChatGPT Site gateway.

## Build verification

The existing Render Docker build executed and passed 152 baseline regressions, 24 new concurrency tests and 4 tests against the actual runtime/router: **180 tests total**. The 24 local tests are a repeated run, not 24 additional distinct cases. A separate GitHub Actions run was not observed; the verified full gate was the Render image build. Production was not used for fault injection.

## Real WordPress acceptance through the connected AI Browser

- Opened saved profile `wordpress-klinika` and reached the live WordPress dashboard without asking for credentials.
- Authenticated same-origin REST confirmed owner slug `edycjanapieraj`.
- Independently read existing technical page 2288 and confirmed `status:draft` before any change.
- Changed only its excerpt under operation `aib203-2288-test-20261117`, with the fresh exact record hash and an encrypted backup.
- Independently read the changed excerpt back. It remained a draft.
- Restored the exact original excerpt with `aib203-2288-restore-20261117` and a fresh precondition hash.
- Saved/closed and reopened the same profile. A new authenticated REST read confirmed the owner, the original restored excerpt and draft status.
- Restoration receipt: `wp-op-970cb1551a82db8b6674edcd33aea08a`, revision 4, `phase:verified`, `external_write_replayed:false`, `requires_readback:false`.
- The two writes naturally changed WordPress modification metadata/revision history; only the original content was restored. No public page, SEO content or CSS was published.
- Closed the owned test session after verification so it does not block another task. Final catalog still contained all 15 existing profiles.

Durable private task checkpoint: `aib-runtime-203-20261117`, initial revision 1. It contains no passwords, tokens, cookies or signed URLs.

## Operating procedure and remaining boundaries

Use the existing plugin 1.0.10 startup procedure before work after idle or a connection failure: bounded public readiness, then the real runtime observation; respect all cooldowns. A ready HTML/loading page or cached health excerpt is not proof of live MCP.

Before browser edits inspect the active profile and human-control state. Do not switch or close an unrelated session. For `browser_busy_before_start`, inspect state and coordinate sequential work; do not spin or automatically replay. After an unknown write use its original operation receipt and independent readback. For supported authorized clinic edits use the existing `wordpress_rest` and bounded CSS actions, not WPVibe.

There is still one live browser workspace. The existing ChatGPT Site gateway code was not edited, and Render Free cold starts were not eliminated. No paid plan, new service, cron, keepalive, account-security change, credential export or limit bypass was introduced. No all-account audit or physical iPhone interaction test was completed. Do not claim zero future 429/502 errors, parallel independent browser workspaces, automatic cross-chat execution or 24/7 availability.
