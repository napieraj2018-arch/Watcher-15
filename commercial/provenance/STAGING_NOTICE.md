# P0: isolated commercial release provenance gate

This branch is an isolated draft. It must not be merged or deployed until the runtime core payload has a separately controlled Ed25519 signing key, immutable artifact SHA-256, verified build identity and a persistent rollback fence. Never store private signing keys, customer profiles, cookies or tokens in this repository. The existing GitHub Docker smoke test alone does not establish deployed-core provenance.

Status: BLOCKED / NO-GO. This file is documentation only; it does not enable or bypass any release gate.
