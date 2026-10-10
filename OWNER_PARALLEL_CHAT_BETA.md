# AI Browser — 5 równoległych prac z różnych rozmów ChatGPT

**Tryb OWNER BETA, OFF by default. NIE SaaS / nie gotowy do sprzedaży.**

User intent: ChatGPT chat A controls Facebook, chat B controls Google,
chat C controls WordPress, and D/E can use their own different profiles
at the same time, without either chat stopping or altering another.

## Included code
- `steel_runtime.Engine` can create 1–5 *distinct* remote Steel
  sessions. Creation remains serialized to avoid provider duplicates;
  browser actions across created sessions are NOT globally serialized.
- `session_ownership/multi_capability_guard.py` issues one opaque,
  random, short-lived `aib_...` capability **per session**. Each chat
  receives its own handle from `browser_start`.
- A profile is exclusive even if unused session slots remain: the same
  Google/Facebook profile cannot be opened by two independent chats.
- Each session has its own lock. Actions for **different sessions**
  may run concurrently, including via the *same* MCP 2.3 server.
- The old `browser_sessions` endpoint returns only counts, profiles,
  mode and health; no provider session IDs, handles or sensitive URLs;
  it does not call `page.title()` on a closed remote page.
- `browser_stop` removes the lease **only** after the browser profile
  and provider have reported a saved stop and the internal session is
  gone. Failed or ambiguous stops quarantine further launches.
- Each session gets a watchdog to stop near 13 minutes; underlying
  Steel Launch sessions are capped at ~15 minutes. A long task needs
  its own checkpoints and safe resume.
- Prior mobile setup/viewer custom HTTP routes are deliberately denied
  in owner-multi mode because they do not carry scoped task capabilities.
  This mode works through ChatGPT MCP on iPhone, but DOES NOT give
  five independently usable human-viewer windows.

## Explicit opt-in and staged rollout
Deploying this code **does not increase the production limit**.
By default `AI_BROWSER_PARALLEL_SESSIONS` remains 1 and legacy
`AI_BROWSER_SESSION_GUARD` mode remains unchanged.

Before owner-beta launch confirm:
1. Render has exactly one active instance, `autoDeploy=no`, no active
   sessions from any chat, one connected owner's private MCP bearer,
   no public multi-tenant clients and a tested rollback commit.
2. Running Green **real Docker image CI**, including 51 existing MCP
   schemas, five-session SDK tests, fake provider releases, cross-chat
   denial, old HTTP route denial and old singleflight regressions.
3. Provider account capacity and remaining balance, not merely the
   advertised Steel Launch plan. Five 15-minute sessions use provider
   resources and are billed by usage.
4. Temporarily use
   `AI_BROWSER_SESSION_GUARD=multi`
   `AI_BROWSER_PARALLEL_OWNER_BETA=1`
   `AI_BROWSER_PARALLEL_SESSIONS=2`.
   Test **two isolated synthetic profiles**, never existing Meta/Google
   sessions first; ensure concurrent start, separate URL, foreign
   handle denied, close + full_profile_saved and zero leaked sessions.
5. Only after 2-pass smoke, raise `AI_BROWSER_PARALLEL_SESSIONS`
   to 3, then 5 (on idle service; env update may restart/deploy).
   No blind repeated login or CAPTCHA/MFA.
6. If startup, provider release, profile-state restore or direct-route
   authorization fails: disable multi, restore 1-slot release, retain
   the last good profiles, and reconcile provider sessions.
7. Note issue #111: consistent re-login after a fresh provider restart
   is still a NO-GO condition. Never infer login from profile_saved.

## Beta operation from ChatGPT
In each chat call `browser_start` with a DIFFERENT saved profile.
Use the returned `session_id` capability for only that chat's
`browser_snapshot`, `browser_navigate`, etc. Do not pass it to
another chat. A fifth profile can work in parallel; a sixth receives
`PARALLEL_CAPACITY_FULL`. Two chats choosing the SAME profile receive
`PARALLEL_PROFILE_BUSY` rather than sharing the logged-in browser.
Always call `browser_stop` when done; check full_profile_saved.

This is a capability model, not a durable across-conversation task
queue. Continuation beyond a session lifetime still needs the
separately authenticated BFF and durable Postgres ledger (#102/#105),
and commercial multi-tenancy requires complete RLS/encrypted vault
(#83/#103), authenticated actor identity and egress/SSRF defenses.
Neither an owner bearer nor a private chat handle alone provides safe
isolation for unrelated paying customers.

**Current commercial release gate #101: NO-GO.**
