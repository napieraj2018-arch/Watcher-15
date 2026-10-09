-- P0 OFFLINE PROOF: durable profile-erasure admission fence, PostgreSQL 16.
-- NEVER apply to production; requires a separate vetted BFF, MFA verifier,
-- Steel provider deletion & full receipt reconciliation before real erasure.
BEGIN;
CREATE ROLE aib_erasure_client NOLOGIN;
CREATE ROLE aib_erasure_worker NOLOGIN;
CREATE ROLE aib_erasure_verifier NOLOGIN;
CREATE SCHEMA erasure_fence;
REVOKE ALL ON SCHEMA erasure_fence FROM PUBLIC;
GRANT USAGE ON SCHEMA erasure_fence TO
  aib_erasure_client,aib_erasure_worker,aib_erasure_verifier;

-- Only the DB owner/administrator can create bindings and profiles.
-- In production these would be created by trusted tenant onboarding.
CREATE TABLE erasure_fence.bindings(
  db_role name PRIMARY KEY,
  tenant_id uuid NOT NULL,
  principal_id uuid NOT NULL,
  role_kind text NOT NULL CHECK(role_kind IN ('client','worker')),
  enabled boolean NOT NULL DEFAULT true
);
CREATE TABLE erasure_fence.profiles(
  tenant_id uuid NOT NULL,
  profile_id uuid NOT NULL,
  status text NOT NULL DEFAULT 'active'
    CHECK(status IN ('active','erasure_pending')),
  revision bigint NOT NULL DEFAULT 0 CHECK(revision >= 0),
  updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY(tenant_id,profile_id)
);
CREATE TABLE erasure_fence.grants(
  grant_id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL,
  profile_id uuid NOT NULL,
  principal_id uuid NOT NULL,
  issued_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  expires_at timestamptz NOT NULL,
  used_at timestamptz,
  FOREIGN KEY(tenant_id,profile_id)
    REFERENCES erasure_fence.profiles(tenant_id,profile_id),
  CHECK(expires_at>issued_at),
  CHECK(expires_at<=issued_at+interval '5 minutes')
);
CREATE TABLE erasure_fence.tasks(
  tenant_id uuid NOT NULL,
  profile_id uuid NOT NULL,
  task_id uuid NOT NULL,
  status text NOT NULL CHECK(status IN ('queued','running','finished','cancelled')),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY(tenant_id,task_id),
  FOREIGN KEY(tenant_id,profile_id)
    REFERENCES erasure_fence.profiles(tenant_id,profile_id)
);
CREATE INDEX erasure_active_tasks ON erasure_fence.tasks(tenant_id,profile_id,status);
CREATE TABLE erasure_fence.intents(
  tenant_id uuid NOT NULL,
  profile_id uuid NOT NULL,
  grant_id uuid NOT NULL UNIQUE REFERENCES erasure_fence.grants(grant_id),
  requested_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY(tenant_id,profile_id),
  FOREIGN KEY(tenant_id,profile_id)
    REFERENCES erasure_fence.profiles(tenant_id,profile_id)
);
REVOKE ALL ON ALL TABLES IN SCHEMA erasure_fence FROM PUBLIC;

-- An independent service MUST verify real MFA before calling this method.
-- This proof only demonstrates that callers without verifier DB privileges
-- cannot mint a grant or spoof another tenant's authority.
CREATE FUNCTION erasure_fence.issue_step_up(
  p_tenant uuid,p_principal uuid,p_profile uuid
) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,erasure_fence,pg_temp
AS $body$
DECLARE profile_status text;
        new_grant uuid;
BEGIN
  IF p_tenant IS NULL OR p_principal IS NULL OR p_profile IS NULL
  THEN RETURN NULL; END IF;
  SELECT status INTO profile_status FROM erasure_fence.profiles
    WHERE tenant_id=p_tenant AND profile_id=p_profile FOR UPDATE;
  IF NOT FOUND OR profile_status<>'active' THEN RETURN NULL; END IF;
  new_grant:=gen_random_uuid();
  INSERT INTO erasure_fence.grants(grant_id,tenant_id,profile_id,principal_id,expires_at)
    VALUES(new_grant,p_tenant,p_profile,p_principal,clock_timestamp()+interval '5 minutes');
  RETURN new_grant;
END $body$;

-- A user's authenticated DB role maps to the tenant and principal.
-- An HTTP tenant_id, user_id or "step_up": true field is never trusted.
CREATE FUNCTION erasure_fence.request_erasure(
  p_profile uuid,p_grant uuid
) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,erasure_fence,pg_temp
AS $body$
DECLARE tid uuid;
        uid uuid;
        profile_status text;
        proof erasure_fence.grants%ROWTYPE;
BEGIN
  SELECT tenant_id,principal_id INTO tid,uid FROM erasure_fence.bindings
    WHERE db_role::text=session_user::text
      AND role_kind='client' AND enabled=true;
  IF NOT FOUND THEN RETURN 'unauthorized'; END IF;
  IF p_profile IS NULL OR p_grant IS NULL THEN RETURN 'invalid_request'; END IF;

  -- Same profile lock serializes admission, worker start and erasure request
  -- across ALL PostgreSQL processes, not merely one asyncio event loop.
  SELECT status INTO profile_status FROM erasure_fence.profiles
    WHERE tenant_id=tid AND profile_id=p_profile FOR UPDATE;
  IF NOT FOUND THEN RETURN 'profile_unavailable'; END IF;

  SELECT * INTO proof FROM erasure_fence.grants
    WHERE grant_id=p_grant AND tenant_id=tid AND principal_id=uid
      AND profile_id=p_profile FOR UPDATE;
  IF NOT FOUND THEN RETURN 'step_up_unverified'; END IF;

  -- A duplicated network request with the *same already-consumed* grant
  -- returns an idempotent result only when that grant created this intent.
  IF proof.used_at IS NOT NULL THEN
    IF profile_status='erasure_pending' AND EXISTS(
       SELECT 1 FROM erasure_fence.intents
       WHERE tenant_id=tid AND profile_id=p_profile AND grant_id=p_grant)
    THEN RETURN 'already_pending'; END IF;
    RETURN 'step_up_unverified';
  END IF;
  IF proof.expires_at<=clock_timestamp() OR
     proof.issued_at>clock_timestamp()+interval '5 seconds'
  THEN RETURN 'step_up_unverified'; END IF;
  IF profile_status='erasure_pending' THEN RETURN 'already_pending'; END IF;

  UPDATE erasure_fence.grants SET used_at=clock_timestamp()
    WHERE grant_id=p_grant;
  UPDATE erasure_fence.profiles SET status='erasure_pending',
    revision=revision+1,updated_at=clock_timestamp()
    WHERE tenant_id=tid AND profile_id=p_profile;
  -- Unstarted work cannot become a session after the fence is durable.
  UPDATE erasure_fence.tasks SET status='cancelled'
    WHERE tenant_id=tid AND profile_id=p_profile AND status='queued';
  INSERT INTO erasure_fence.intents(tenant_id,profile_id,grant_id)
    VALUES(tid,p_profile,p_grant);
  RETURN 'erasure_pending';
END $body$;

-- The trusted worker has its own per-tenant login role. Customer roles
-- cannot enqueue, claim or finish a task, nor directly read base tables.
CREATE FUNCTION erasure_fence.enqueue(
  p_profile uuid,p_task uuid
) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,erasure_fence,pg_temp
AS $body$
DECLARE tid uuid;
        profile_status text;
BEGIN
  SELECT tenant_id INTO tid FROM erasure_fence.bindings
    WHERE db_role::text=session_user::text
      AND role_kind='worker' AND enabled=true;
  IF NOT FOUND THEN RETURN 'unauthorized'; END IF;
  IF p_profile IS NULL OR p_task IS NULL THEN RETURN 'invalid_request'; END IF;
  SELECT status INTO profile_status FROM erasure_fence.profiles
    WHERE tenant_id=tid AND profile_id=p_profile FOR UPDATE;
  IF NOT FOUND THEN RETURN 'profile_unavailable'; END IF;
  IF EXISTS(SELECT 1 FROM erasure_fence.tasks
      WHERE tenant_id=tid AND task_id=p_task)
  THEN RETURN 'duplicate'; END IF;
  IF profile_status<>'active' THEN RETURN 'erasure_pending'; END IF;
  INSERT INTO erasure_fence.tasks(tenant_id,profile_id,task_id,status)
    VALUES(tid,p_profile,p_task,'queued');
  RETURN 'queued';
END $body$;

CREATE FUNCTION erasure_fence.claim(
  p_profile uuid,p_task uuid
) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,erasure_fence,pg_temp
AS $body$
DECLARE tid uuid;
        profile_status text;
        task_status text;
BEGIN
  SELECT tenant_id INTO tid FROM erasure_fence.bindings
    WHERE db_role::text=session_user::text
      AND role_kind='worker' AND enabled=true;
  IF NOT FOUND THEN RETURN 'unauthorized'; END IF;
  IF p_profile IS NULL OR p_task IS NULL THEN RETURN 'invalid_request'; END IF;
  SELECT status INTO profile_status FROM erasure_fence.profiles
    WHERE tenant_id=tid AND profile_id=p_profile FOR UPDATE;
  IF NOT FOUND THEN RETURN 'profile_unavailable'; END IF;
  IF profile_status<>'active' THEN RETURN 'erasure_pending'; END IF;
  SELECT status INTO task_status FROM erasure_fence.tasks
    WHERE tenant_id=tid AND profile_id=p_profile AND task_id=p_task FOR UPDATE;
  IF NOT FOUND THEN RETURN 'task_unavailable'; END IF;
  IF task_status<>'queued' THEN RETURN 'not_claimable'; END IF;
  UPDATE erasure_fence.tasks SET status='running'
    WHERE tenant_id=tid AND task_id=p_task;
  RETURN 'running';
END $body$;

-- A running job may safely acknowledge completion after the erasure fence;
-- it must NOT renew or start another provider session.
CREATE FUNCTION erasure_fence.finish(
  p_profile uuid,p_task uuid
) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,erasure_fence,pg_temp
AS $body$
DECLARE tid uuid;
        profile_status text;
        task_status text;
BEGIN
  SELECT tenant_id INTO tid FROM erasure_fence.bindings
    WHERE db_role::text=session_user::text
      AND role_kind='worker' AND enabled=true;
  IF NOT FOUND THEN RETURN 'unauthorized'; END IF;
  IF p_profile IS NULL OR p_task IS NULL THEN RETURN 'invalid_request'; END IF;
  SELECT status INTO profile_status FROM erasure_fence.profiles
    WHERE tenant_id=tid AND profile_id=p_profile FOR UPDATE;
  IF NOT FOUND THEN RETURN 'profile_unavailable'; END IF;
  SELECT status INTO task_status FROM erasure_fence.tasks
    WHERE tenant_id=tid AND profile_id=p_profile AND task_id=p_task FOR UPDATE;
  IF NOT FOUND THEN RETURN 'task_unavailable'; END IF;
  IF task_status='finished' THEN RETURN 'already_finished'; END IF;
  IF task_status<>'running' THEN RETURN 'not_running'; END IF;
  UPDATE erasure_fence.tasks SET status='finished'
    WHERE tenant_id=tid AND task_id=p_task;
  RETURN 'finished';
END $body$;

CREATE FUNCTION erasure_fence.my_profile_status(p_profile uuid)
RETURNS text LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path=pg_catalog,erasure_fence,pg_temp
AS $body$
DECLARE tid uuid; outcome text;
BEGIN
  SELECT tenant_id INTO tid FROM erasure_fence.bindings
    WHERE db_role::text=session_user::text
      AND role_kind='client' AND enabled=true;
  IF NOT FOUND OR p_profile IS NULL THEN RETURN 'unavailable'; END IF;
  SELECT status INTO outcome FROM erasure_fence.profiles
    WHERE tenant_id=tid AND profile_id=p_profile;
  RETURN COALESCE(outcome,'unavailable');
END $body$;

-- Merely a *precondition* snapshot for a trusted deletion orchestrator.
-- NOT a Steel deletion receipt; NOT an authorization to delete credentials;
-- NOT a finalized erasure state. No provider calls occur in this module.
CREATE FUNCTION erasure_fence.provider_removal_precondition(
  p_tenant uuid,p_profile uuid
) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
SET search_path=pg_catalog,erasure_fence,pg_temp
AS $body$
  SELECT EXISTS(
    SELECT 1 FROM erasure_fence.profiles p
    WHERE p.tenant_id=p_tenant AND p.profile_id=p_profile
      AND p.status='erasure_pending'
      AND NOT EXISTS(
        SELECT 1 FROM erasure_fence.tasks t
        WHERE t.tenant_id=p_tenant AND t.profile_id=p_profile
          AND t.status IN ('queued','running'))
  )
$body$;

REVOKE ALL ON ALL FUNCTIONS IN SCHEMA erasure_fence FROM PUBLIC;
GRANT EXECUTE ON FUNCTION erasure_fence.request_erasure(uuid,uuid),
  erasure_fence.my_profile_status(uuid) TO aib_erasure_client;
GRANT EXECUTE ON FUNCTION erasure_fence.enqueue(uuid,uuid),
  erasure_fence.claim(uuid,uuid),erasure_fence.finish(uuid,uuid)
  TO aib_erasure_worker;
GRANT EXECUTE ON FUNCTION erasure_fence.issue_step_up(uuid,uuid,uuid),
  erasure_fence.provider_removal_precondition(uuid,uuid)
  TO aib_erasure_verifier;
COMMIT;
