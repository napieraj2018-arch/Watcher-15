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
GRANT INSERT(tenant_id,workspace_id,task_id,profile_id,state)
  ON browser_product.browser_tasks TO browser_product_client;
GRANT UPDATE(state)
  ON browser_product.browser_tasks TO browser_product_client;

COMMIT;
