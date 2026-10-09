# Vault ingress release prerequisites

The public Floot deployment serves an owner-only API. It authenticates before reading JSON bodies, but the profile save handler currently buffers the entire HTTP request before checking its payload length. A valid bearer token can therefore submit an arbitrarily large body and put pressure on the server or database connection pool.

The required correction is streaming size enforcement *before* JSON parsing, strict media type validation, and no-store error responses. Preserve the existing authenticated owner workflow and the existing fail-closed deletion response. Do not add tenant access to this API until server-side customer identity and RLS are integrated.

This branch is a design checkpoint only, not a live Floot patch. No production deployment, profile access, credential use, or billing actions are authorized by this document.
