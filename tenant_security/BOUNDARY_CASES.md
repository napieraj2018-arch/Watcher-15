# Tenant boundary regression plan

These cases use only synthetic, non-customer inputs. The candidate module is not connected to production.

- Resource kind supplied as an array or object must return a stable denial, never an unexpected exception.
- Action and filter kind supplied as an array, object or number must fail closed.
- Malformed bearer capability containing non-ASCII characters must be denied without leaking any input value.
- Boolean token version must be rejected even though it compares equal to integer one in Python.
- Authenticated context must come only from trusted backend middleware. A client-supplied claim of backend verification is not sufficient.
- Tests must run in CI on the isolated branch before any merge.

This note documents candidate requirements; it does not claim that these are currently fixed.
