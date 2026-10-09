-- PostgreSQL 16: ONLY on an ephemeral CI database, not Floot or Render.
-- Real commercial sign-in and session issuance are deliberately NOT included.
-- This holds server-provisioned hashes of high-entropy opaque sessions and CSRF tokens.
BEGIN;
CREATE ROLE aib_auth_reader LOGIN;
CREATE TABLE browser_product.api_sessions (
  session_sha256 text PRIMARY KEY CHECK(session_sha256 ~ '^[a-f0-9]{64}$'),
  csrf_sha256 text NOT NULL CHECK(csrf_sha256 ~ '^[a-f0-9]{64}$'),
  tenant_id uuid NOT NULL REFERENCES browser_product.tenants(tenant_id),
  user_id uuid NOT NULL,
  expires_at timestamptz NOT NULL,
  revoked_at timestamptz
);
CREATE INDEX api_sessions_tenant_active ON browser_product.api_sessions(tenant_id,expires_at);
REVOKE ALL ON browser_product.api_sessions FROM PUBLIC;
REVOKE ALL ON browser_product.api_sessions FROM aib_auth_reader;
GRANT USAGE ON SCHEMA browser_product TO aib_auth_reader;

-- Fixed query with owner privileges. The reader cannot enumerate session
-- records, enumerate tenant bindings, edit users or issue new sessions.
CREATE FUNCTION browser_product.lookup_api_session(p_hash text)
RETURNS TABLE(tenant_id uuid,user_id uuid,csrf_sha256 text)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog,browser_product,pg_temp
AS $body$
 SELECT s.tenant_id,s.user_id,s.csrf_sha256
 FROM browser_product.api_sessions AS s
 JOIN browser_product.tenants AS t ON t.tenant_id=s.tenant_id
 WHERE p_hash ~ '^[a-f0-9]{64}$'
   AND s.session_sha256=p_hash
   AND s.expires_at>clock_timestamp()
   AND s.revoked_at IS NULL
   AND t.state='active'
 LIMIT 1
$body$;
REVOKE ALL ON FUNCTION browser_product.lookup_api_session(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION browser_product.lookup_api_session(text) TO aib_auth_reader;
COMMIT;
