# Neon Fresh acceptance — 29 October 2026

Code deployment: `e7bbaffb6545987944481fa011ccf7bf2529d809`, Render `dep-dbhnmtbbc2fs73ev631g` LIVE. Existing PR #184 and isolated Render service retained. No changes to old Render, Floot, 68 archived profiles, PR180 or 7833-record backup.

Verified through authenticated calls to the new backend:
- Neutral form input and click, encrypted save and close.
- Cookie, localStorage, IndexedDB and history readback after service replacement: all true, twice.
- Encrypted task checkpoint revision 1 read after restart; completed step retained.
- Public website navigation, title/text readback and a 390x844 screenshot; saved close.
- Restricted SQL runtime: no role/database creation, no BYPASSRLS, no inherited memberships; no schema CREATE or profile DELETE grants. The previous API-created privileged role could not be altered by the database owner and is no longer configured as the application runtime.
- Eight security/ownership tests and fifteen bridge/proxy tests passed. Browser UI physical-device acceptance is separate.

Private Sites bridge remains owner-only. It proxies the panel at `/fresh` and MCP at `/mcp`, with distinct server-side service credentials. No credentials in repository or client HTML. Sites deployment uses its own source repository and environment secrets.

Open gates — do not claim completion:
- The existing connected ChatGPT tool invocation still reports internal error. Direct authenticated backend RPC works; this is not equivalent to successful host tool execution.
- Owner completed Apple credentials and MFA for panel access, but the cloud browser's subsequent redirect was blocked by its URL policy. No workaround attempted. No external account login inside the new Chromium profile has been verified.
- Real iPhone touch/keyboard/upload and true account save-close-reopen require owner acceptance.
- Free Render is not 24/7 production hosting. No upgrade or purchase made.

Implementation limits: one live browser workspace; per-profile PostgreSQL advisory lock plus CAS; 15-second periodic saves and save after actions; process termination can lose changes after the last successful save. State is Playwright cookies/localStorage/IndexedDB plus saved URL history, not a byte-for-byte native Chromium user directory. Checkpoints are durable records, not an autonomous worker or a guarantee that uncertain external writes can be replayed. Profile versions are encrypted application recovery copies in the same database, not independent disaster recovery.
