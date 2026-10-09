-- EXPERIMENTAL BFF login session registry: fresh throwaway PostgreSQL ONLY.
-- Apply AFTER 001_tenant_isolation.sql. Not a Floot vault migration.
-- No public signup/login, no Steel access, no credential fixtures here.
BEGIN;
CREATE ROLE browser_bff_auth NOLOGIN;
CREATE SCHEMA browser_auth;
REVOKE ALL ON SCHEMA browser_auth FROM PUBLIC;
GRANT USAGE ON SCHEMA browser_auth TO browser_bff_auth;

CREATE TABLE browser_auth.memberships (
  principal_id uuid NOT NULL,
  tenant_id uuid NOT NULL REFERENCES browser_product.tenants(tenant_id),
  access_role text NOT NULL CHECK (access_role IN ('viewer','operator','admin')),
  enabled boolean NOT NULL DEFAULT true,
  PRIMARY KEY(principal_id, tenant_id)
);
CREATE TABLE browser_auth.sessions (
  session_digest text PRIMARY KEY CHECK (session_digest ~ '^[a-f0-9]{64}$'),
  principal_id uuid NOT NULL,
  tenant_id uuid NOT NULL,
  csrf_digest text NOT NULL CHECK (csrf_digest ~ '^[a-f0-9]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL,
  revoked_at timestamptz,
  FOREIGN KEY(principal_id,tenant_id)
     REFERENCES browser_auth.memberships(principal_id,tenant_id),
  CHECK (expires_at > created_at)
);
CREATE INDEX sessions_validity ON browser_auth.sessions(expires_at)
  WHERE revoked_at IS NULL;
REVOKE ALL ON ALL TABLES IN SCHEMA browser_auth FROM PUBLIC;

-- Never use app.tenant_id / X-Tenant-ID, or read unsigned browser claims.
-- The BFF auth DB role can only resolve a digest of a high-entropy cookie.
CREATE FUNCTION browser_auth.resolve_session(p_digest text)
RETURNS TABLE(tenant_id uuid,principal_id uuid,access_role text,csrf_digest text)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog,browser_auth,pg_temp AS $body$
 SELECT s.tenant_id, s.principal_id, m.access_role, s.csrf_digest
 FROM browser_auth.sessions AS s
 JOIN browser_auth.memberships AS m
   ON m.principal_id=s.principal_id AND m.tenant_id=s.tenant_id
 JOIN browser_product.tenants AS t ON t.tenant_id=s.tenant_id
 WHERE s.session_digest=p_digest
   AND s.revoked_at IS NULL AND s.expires_at > now()
   AND m.enabled AND t.state='active'
 LIMIT 1
$body$;
REVOKE ALL ON FUNCTION browser_auth.resolve_session(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION browser_auth.resolve_session(text) TO browser_bff_auth;
COMMIT;
