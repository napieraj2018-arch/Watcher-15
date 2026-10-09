-- AI Browser commercial tenant isolation: PostgreSQL prototype ONLY.
-- Not applied to the current Floot profile vault. Run in isolated CI database.
-- This proof uses a separate DB login role PER tenant. RLS identity is derived
-- from session_user, not a spoofable custom GUC or HTTP-provided tenant_id.
BEGIN;
CREATE SCHEMA IF NOT EXISTS browser_product;

CREATE ROLE browser_product_client NOLOGIN;

CREATE TABLE browser_product.tenants(
    tenant_id uuid PRIMARY KEY,
    state text NOT NULL DEFAULT 'active'
      CHECK(state IN('active','paused','deleted')),
    created_at timestamptz NOT NULL DEFAULT now()
);

-- NO grant to browser_product_client. Only the database administrator may
-- bind a database login to a tenant. Changing this map requires an audited,
-- privileged provisioning workflow.
CREATE TABLE browser_product.login_tenant_bindings(
    db_role name PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES browser_product.tenants(tenant_id),
    enabled boolean NOT NULL DEFAULT true
);
REVOKE ALL ON browser_product.tenants FROM PUBLIC;
REVOKE ALL ON browser_product.login_tenant_bindings FROM PUBLIC;

CREATE FUNCTION browser_product.authenticated_tenant()
RETURNS uuid
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, browser_product
AS $body$
 SELECT bindings.tenant_id
 FROM browser_product.login_tenant_bindings AS bindings
 JOIN browser_product.tenants AS tenants USING (tenant_id)
 WHERE bindings.db_role::text = session_user::text
   AND bindings.enabled IS TRUE
   AND tenants.state = 'active'
 LIMIT 1
$body$;
REVOKE ALL ON FUNCTION browser_product.authenticated_tenant() FROM PUBLIC;
GRANT USAGE ON SCHEMA browser_product TO browser_product_client;
GRANT EXECUTE ON FUNCTION browser_product.authenticated_tenant()
  TO browser_product_client;

CREATE TABLE browser_product.workspaces(
    tenant_id uuid NOT NULL REFERENCES browser_product.tenants(tenant_id),
    workspace_id uuid NOT NULL,
    display_name text NOT NULL CHECK(length(display_name) BETWEEN 1 AND 120),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(tenant_id,workspace_id)
);

CREATE TABLE browser_product.profiles(
    tenant_id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    profile_id uuid NOT NULL,
    display_name text NOT NULL CHECK(length(display_name) BETWEEN 1 AND 120),
    status text NOT NULL DEFAULT 'new'
      CHECK(status IN('new','ready','paused','deleting','deleted')),
    -- Strictly server-side; not readable, insertable or modifiable by clients.
    provider_profile_ref uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(tenant_id,profile_id),
    UNIQUE(tenant_id,workspace_id,profile_id),
    UNIQUE(tenant_id,workspace_id,display_name),
    FOREIGN KEY(tenant_id,workspace_id)
      REFERENCES browser_product.workspaces(tenant_id,workspace_id)
);
CREATE UNIQUE INDEX profiles_provider_ref_internal_unique
 ON browser_product.profiles(provider_profile_ref)
 WHERE provider_profile_ref IS NOT NULL;

CREATE TABLE browser_product.browser_tasks(
    tenant_id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    task_id uuid NOT NULL,
    profile_id uuid NOT NULL,
    state text NOT NULL DEFAULT 'queued'
      CHECK(state IN('queued','running','paused','done','cancelled')),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(tenant_id,task_id),
    FOREIGN KEY(tenant_id,workspace_id)
      REFERENCES browser_product.workspaces(tenant_id,workspace_id),
    FOREIGN KEY(tenant_id,workspace_id,profile_id)
      REFERENCES browser_product.profiles(tenant_id,workspace_id,profile_id)
);

-- Force even accidental owner pathways to be reviewed. PostgreSQL superusers
-- and BYPASSRLS roles remain outside the tenant-data threat model and must not
-- be used as client connections.
ALTER TABLE browser_product.workspaces ENABLE ROW LEVEL SECURITY;
ALTER TABLE browser_product.workspaces FORCE ROW LEVEL SECURITY;
ALTER TABLE browser_product.profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE browser_product.profiles FORCE ROW LEVEL SECURITY;
ALTER TABLE browser_product.browser_tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE browser_product.browser_tasks FORCE ROW LEVEL SECURITY;

CREATE POLICY workspaces_owner_only ON browser_product.workspaces
 FOR ALL TO browser_product_client
 USING(tenant_id=browser_product.authenticated_tenant())
 WITH CHECK(tenant_id=browser_product.authenticated_tenant());
CREATE POLICY profiles_owner_only ON browser_product.profiles
 FOR ALL TO browser_product_client
 USING(tenant_id=browser_product.authenticated_tenant())
 WITH CHECK(tenant_id=browser_product.authenticated_tenant());
CREATE POLICY tasks_owner_only ON browser_product.browser_tasks
 FOR ALL TO browser_product_client
 USING(tenant_id=browser_product.authenticated_tenant())
 WITH CHECK(tenant_id=browser_product.authenticated_tenant());

-- A customer connection never sees provider IDs or encryption material,
-- and cannot change tenant/workspace keys of rows already created.
GRANT SELECT(tenant_id,workspace_id,display_name)
  ON browser_product.workspaces TO browser_product_client;
GRANT INSERT(tenant_id,workspace_id,display_name)
  ON browser_product.workspaces TO browser_product_client;
GRANT UPDATE(display_name)
  ON browser_product.workspaces TO browser_product_client;

GRANT SELECT(tenant_id,workspace_id,profile_id,display_name,status)
  ON browser_product.profiles TO browser_product_client;
GRANT INSERT(tenant_id,workspace_id,profile_id,display_name)
  ON browser_product.profiles TO browser_product_client;
GRANT UPDATE(display_name)
  ON browser_product.profiles TO browser_product_client;

GRANT SELECT(tenant_id,workspace_id,task_id,profile_id,state)
  ON browser_product.browser_tasks TO browser_product_client;
-- Customer-facing connections can ONLY enqueue with DEFAULT state='queued'.
-- Lifecycle state (running/done/cancelled/paused) is controlled by a separate
-- authenticated BFF worker with auditable transitions. A client may not spoof
-- success, cancel another actor's job or hide running provider usage.
-- No direct task INSERT or UPDATE for a client. Both quota and
-- idempotency MUST execute atomically within a server-authenticated
-- tenant role. The session_user role is bound by privileged provisioning.
CREATE FUNCTION browser_product.enqueue_task(
  p_workspace uuid, p_profile uuid, p_task uuid
) RETURNS TABLE(status_code text,current_state text)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = pg_catalog,browser_product,pg_temp
AS $body$
DECLARE v_tenant uuid;
        v_workspace uuid;
        v_profile uuid;
        v_state text;
        v_pending integer;
BEGIN
  v_tenant := browser_product.authenticated_tenant();
  IF v_tenant IS NULL THEN
    RETURN QUERY SELECT 'unauthorized'::text,NULL::text; RETURN;
  END IF;
  IF p_workspace IS NULL OR p_profile IS NULL OR p_task IS NULL THEN
    RETURN QUERY SELECT 'invalid_request'::text,NULL::text; RETURN;
  END IF;

  -- Transactions for the SAME tenant serialize queue inserts, including
  -- across processes. Collisions in the 64-bit lock only reduce throughput.
  PERFORM pg_advisory_xact_lock(hashtextextended(v_tenant::text, 4149));

  SELECT t.workspace_id,t.profile_id,t.state
    INTO v_workspace,v_profile,v_state
  FROM browser_product.browser_tasks AS t
  WHERE t.tenant_id=v_tenant AND t.task_id=p_task;

  IF FOUND THEN
    IF v_workspace=p_workspace AND v_profile=p_profile THEN
      RETURN QUERY SELECT 'existing'::text,v_state; RETURN;
    END IF;
    RETURN QUERY SELECT 'idempotency_conflict'::text,NULL::text; RETURN;
  END IF;

  IF NOT EXISTS(
    SELECT 1 FROM browser_product.profiles AS p
    WHERE p.tenant_id=v_tenant AND p.workspace_id=p_workspace
      AND p.profile_id=p_profile AND p.status='ready'
  ) THEN
    RETURN QUERY SELECT 'profile_not_available'::text,NULL::text; RETURN;
  END IF;

  SELECT count(*) INTO v_pending
  FROM browser_product.browser_tasks AS t
  WHERE t.tenant_id=v_tenant AND t.state IN ('queued','running');

  IF v_pending>=10 THEN
    RETURN QUERY SELECT 'quota_reached'::text,NULL::text; RETURN;
  END IF;

  INSERT INTO browser_product.browser_tasks(
    tenant_id,workspace_id,profile_id,task_id
  ) VALUES(v_tenant,p_workspace,p_profile,p_task);
  RETURN QUERY SELECT 'created'::text,'queued'::text;
END
$body$;
REVOKE ALL ON FUNCTION browser_product.enqueue_task(uuid,uuid,uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION browser_product.enqueue_task(uuid,uuid,uuid)
  TO browser_product_client;

COMMIT;
