-- TEST-ONLY: immutable encrypted profile revisions isolated by tenant DB login.
-- Requires 001_tenant_isolation.sql; never run against the live Floot vault.
-- No raw cookies, localStorage or real keys in this schema or test fixture.
BEGIN;
CREATE ROLE browser_vault_worker NOLOGIN;
GRANT USAGE ON SCHEMA browser_product TO browser_vault_worker;
GRANT EXECUTE ON FUNCTION browser_product.authenticated_tenant()
  TO browser_vault_worker;

CREATE TABLE browser_product.profile_versions_secure (
    tenant_id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    profile_id uuid NOT NULL,
    revision bigint NOT NULL CHECK (revision BETWEEN 1 AND 9223372036854775807),
    key_id text NOT NULL CHECK (key_id ~ '^[A-Za-z0-9_-]{1,64}$'),
    nonce bytea NOT NULL CHECK (octet_length(nonce)=12),
    encrypted_state bytea NOT NULL
      CHECK (octet_length(encrypted_state) BETWEEN 16 AND 8000016),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id,profile_id,revision),
    -- Fail closed on accidental AES-GCM nonce reuse under the same tenant key.
    UNIQUE (tenant_id,key_id,nonce),
    FOREIGN KEY (tenant_id,workspace_id,profile_id)
      REFERENCES browser_product.profiles(tenant_id,workspace_id,profile_id)
);
REVOKE ALL ON browser_product.profile_versions_secure FROM PUBLIC;
ALTER TABLE browser_product.profile_versions_secure ENABLE ROW LEVEL SECURITY;
ALTER TABLE browser_product.profile_versions_secure FORCE ROW LEVEL SECURITY;
CREATE POLICY encrypted_profile_worker_only
  ON browser_product.profile_versions_secure
  FOR SELECT TO browser_vault_worker
  USING (tenant_id=browser_product.authenticated_tenant());

-- BFF metadata connections have no access to ciphertext. Only an
-- independently provisioned per-tenant vault role can read ciphertext.
-- It cannot UPDATE/DELETE the immutable archive or INSERT bypassing checks.
GRANT SELECT(tenant_id,workspace_id,profile_id,revision,key_id,nonce,
             encrypted_state,created_at)
  ON browser_product.profile_versions_secure TO browser_vault_worker;

CREATE FUNCTION browser_product.append_encrypted_profile(
  p_workspace uuid,p_profile uuid,p_expected_previous bigint,
  p_key_id text,p_nonce bytea,p_encrypted_state bytea
) RETURNS TABLE(status_code text, stored_revision bigint)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = pg_catalog,browser_product,pg_temp
AS $body$
DECLARE v_tenant uuid;
        v_latest bigint;
BEGIN
  v_tenant := browser_product.authenticated_tenant();
  IF v_tenant IS NULL THEN
    RETURN QUERY SELECT 'unauthorized'::text,NULL::bigint; RETURN;
  END IF;
  IF p_workspace IS NULL OR p_profile IS NULL
     OR p_expected_previous IS NULL
     OR p_expected_previous < 0
     OR p_expected_previous >= 9223372036854775807
     OR p_key_id IS NULL OR p_key_id !~ '^[A-Za-z0-9_-]{1,64}$'
     OR p_nonce IS NULL OR octet_length(p_nonce)<>12
     OR p_encrypted_state IS NULL
     OR octet_length(p_encrypted_state) NOT BETWEEN 16 AND 8000016
  THEN
    RETURN QUERY SELECT 'invalid_request'::text,NULL::bigint; RETURN;
  END IF;

  -- Per-profile lock spans the whole transaction. Two workers cannot
  -- both append the same next revision, even across multiple processes.
  PERFORM pg_advisory_xact_lock(
    hashtextextended(v_tenant::text || ':' || p_profile::text, 9172)
  );

  IF NOT EXISTS (
    SELECT 1 FROM browser_product.profiles AS p
    WHERE p.tenant_id=v_tenant
      AND p.workspace_id=p_workspace AND p.profile_id=p_profile
      AND p.status='ready'
  ) THEN
    RETURN QUERY SELECT 'profile_not_available'::text,NULL::bigint; RETURN;
  END IF;

  SELECT COALESCE(max(v.revision),0) INTO v_latest
  FROM browser_product.profile_versions_secure AS v
  WHERE v.tenant_id=v_tenant AND v.profile_id=p_profile;

  IF v_latest <> p_expected_previous THEN
    RETURN QUERY SELECT 'revision_conflict'::text,v_latest; RETURN;
  END IF;

  INSERT INTO browser_product.profile_versions_secure(
    tenant_id,workspace_id,profile_id,revision,key_id,nonce,encrypted_state
  ) VALUES(
    v_tenant,p_workspace,p_profile,v_latest+1,
    p_key_id,p_nonce,p_encrypted_state
  );
  RETURN QUERY SELECT 'created'::text,(v_latest+1)::bigint;
END $body$;

REVOKE ALL ON FUNCTION browser_product.append_encrypted_profile(
  uuid,uuid,bigint,text,bytea,bytea
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION browser_product.append_encrypted_profile(
  uuid,uuid,bigint,text,bytea,bytea
) TO browser_vault_worker;

COMMIT;
