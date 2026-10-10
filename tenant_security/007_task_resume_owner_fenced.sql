-- OFFLINE / THROWAWAY POSTGRESQL 16 ONLY. Never apply to Floot or Render.
-- Depends on 001_tenant_isolation, 002_bff_session_auth, commercial/leases/001,
-- 004_tenant_fenced_slot, 005_three_parallel_slots, 006_configurable_capacity.
--
-- A new ChatGPT chat may resume ONLY the authenticated principal's task,
-- and only after independently verified provider readback and slot fencing.
-- No raw Steel ID, browser capability, password, cookie or provider storage
-- is written here. This proof DOES NOT integrate live MCP browser handles.
BEGIN;
CREATE SCHEMA browser_recovery;
REVOKE ALL ON SCHEMA browser_recovery FROM PUBLIC;
GRANT USAGE ON SCHEMA browser_recovery TO browser_bff_auth,aib_parallel_verifier;

CREATE TABLE browser_recovery.owned_tasks (
  tenant_id uuid NOT NULL,
  task_id uuid NOT NULL,
  principal_id uuid NOT NULL,
  slot_no integer,
  generation bigint,
  lease_id uuid,
  attachment_epoch bigint NOT NULL DEFAULT 0 CHECK(attachment_epoch>=0),
  last_resume_attempt uuid,
  cancel_requested boolean NOT NULL DEFAULT false,
  recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  last_resume_at timestamptz,
  PRIMARY KEY(tenant_id,task_id),
  FOREIGN KEY(tenant_id,task_id)
    REFERENCES browser_product.browser_tasks(tenant_id,task_id),
  FOREIGN KEY(principal_id,tenant_id)
    REFERENCES browser_auth.memberships(principal_id,tenant_id),
  CONSTRAINT recovery_slot_link_shape CHECK(
    (slot_no IS NULL AND generation IS NULL AND lease_id IS NULL)
    OR (slot_no IS NOT NULL AND slot_no>0 AND generation IS NOT NULL
        AND generation>0 AND lease_id IS NOT NULL))
);
CREATE INDEX recovery_owned_principal_lookup
  ON browser_recovery.owned_tasks(tenant_id,principal_id,recorded_at DESC);

-- Separate provider verifier attests fresh provider-visible state.
-- A FALSE receipt invalidates an older TRUE receipt for the same generation.
-- This stores only boolean facts; no session IDs or sensitive browser state.
CREATE TABLE browser_recovery.provider_readback (
  slot_no integer NOT NULL,
  generation bigint NOT NULL,
  lease_id uuid NOT NULL,
  provider_alive boolean NOT NULL,
  same_profile_binding boolean NOT NULL,
  verified_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY(slot_no,generation,lease_id),
  FOREIGN KEY(slot_no) REFERENCES browser_parallel.slots(slot_no)
);
REVOKE ALL ON ALL TABLES IN SCHEMA browser_recovery FROM PUBLIC;

CREATE FUNCTION browser_recovery.register_own_task(
  p_session_digest text,p_csrf_digest text,p_task uuid
) RETURNS text LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path=pg_catalog,browser_recovery,browser_auth,browser_product,pg_temp
AS $body$
DECLARE actor record; existing uuid; task_valid boolean;
BEGIN
  IF p_task IS NULL OR p_session_digest IS NULL OR p_csrf_digest IS NULL THEN
    RETURN 'not_authorized';
  END IF;
  SELECT a.tenant_id,a.principal_id INTO actor
    FROM browser_auth.resolve_session(p_session_digest) AS a
    WHERE a.csrf_digest=p_csrf_digest
      AND a.access_role IN ('operator','admin');
  IF NOT FOUND THEN RETURN 'not_authorized'; END IF;
  SELECT EXISTS(
    SELECT 1 FROM browser_product.browser_tasks t
    JOIN browser_product.profiles p
      ON p.tenant_id=t.tenant_id AND p.workspace_id=t.workspace_id
         AND p.profile_id=t.profile_id
    WHERE t.tenant_id=actor.tenant_id AND t.task_id=p_task
      AND t.state='queued' AND p.status='ready'
  ) INTO task_valid;
  IF NOT task_valid THEN RETURN 'not_available'; END IF;

  INSERT INTO browser_recovery.owned_tasks(tenant_id,task_id,principal_id)
    VALUES(actor.tenant_id,p_task,actor.principal_id)
    ON CONFLICT(tenant_id,task_id) DO NOTHING;

  SELECT o.principal_id INTO existing FROM browser_recovery.owned_tasks o
    WHERE o.tenant_id=actor.tenant_id AND o.task_id=p_task;
  IF existing=actor.principal_id THEN
    RETURN 'registered';
  END IF;
  RETURN 'not_available';
END $body$;

CREATE FUNCTION browser_recovery.bind_reserved_lease(
  p_session_digest text,p_csrf_digest text,p_task uuid,
  p_slot integer,p_lease uuid,p_generation bigint
) RETURNS text LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path=pg_catalog,browser_recovery,browser_auth,browser_parallel,browser_product,pg_temp
AS $body$
DECLARE actor record; own browser_recovery.owned_tasks%ROWTYPE;
BEGIN
  SELECT a.tenant_id,a.principal_id INTO actor
    FROM browser_auth.resolve_session(p_session_digest) AS a
    WHERE a.csrf_digest=p_csrf_digest
      AND a.access_role IN ('operator','admin');
  IF NOT FOUND OR p_task IS NULL OR p_slot IS NULL OR p_lease IS NULL
    OR p_generation IS NULL THEN RETURN 'not_authorized'; END IF;
  SELECT * INTO own FROM browser_recovery.owned_tasks o
    WHERE o.tenant_id=actor.tenant_id AND o.principal_id=actor.principal_id
      AND o.task_id=p_task FOR UPDATE;
  IF NOT FOUND OR own.cancel_requested THEN RETURN 'not_available'; END IF;

  IF own.lease_id IS NOT NULL THEN
    IF own.lease_id=p_lease AND own.generation=p_generation
       AND own.slot_no=p_slot
    THEN RETURN 'already_bound'; END IF;
    RETURN 'binding_conflict';
  END IF;

  IF NOT EXISTS(
    SELECT 1 FROM browser_parallel.slots s
    JOIN browser_product.browser_tasks t
      ON s.tenant_id=t.tenant_id AND s.task_id=t.task_id
         AND s.profile_id=t.profile_id
    WHERE s.tenant_id=actor.tenant_id AND s.task_id=p_task
      AND s.lease_id=p_lease AND s.generation=p_generation
      AND s.slot_no=p_slot AND s.state='reserved'
      AND s.expires_at>clock_timestamp() AND t.state='queued'
  ) THEN RETURN 'lease_not_confirmed'; END IF;

  UPDATE browser_recovery.owned_tasks o SET
    slot_no=p_slot,lease_id=p_lease,generation=p_generation
    WHERE o.tenant_id=actor.tenant_id AND o.task_id=p_task
      AND o.principal_id=actor.principal_id;
  RETURN 'bound';
END $body$;

CREATE FUNCTION browser_recovery.record_provider_readback(
  p_slot integer,p_lease uuid,p_generation bigint,
  p_provider_alive boolean,p_profile_binding_matches boolean
) RETURNS boolean LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path=pg_catalog,browser_recovery,browser_parallel,pg_temp
AS $body$
BEGIN
  IF p_slot IS NULL OR p_lease IS NULL OR p_generation IS NULL
     OR p_provider_alive IS NULL OR p_profile_binding_matches IS NULL
  THEN RETURN false; END IF;

  -- The verifier is the ONLY caller that can report provider readback.
  -- A real verifier must independently contact Steel before this call.
  IF NOT EXISTS(SELECT 1 FROM browser_parallel.slots s
    WHERE s.slot_no=p_slot AND s.lease_id=p_lease
      AND s.generation=p_generation
      AND s.state IN ('active','closing','quarantined'))
  THEN RETURN false; END IF;

  INSERT INTO browser_recovery.provider_readback(
    slot_no,generation,lease_id,provider_alive,same_profile_binding,verified_at)
  VALUES (p_slot,p_generation,p_lease,p_provider_alive,
          p_profile_binding_matches,clock_timestamp())
  ON CONFLICT(slot_no,generation,lease_id) DO UPDATE SET
    provider_alive=EXCLUDED.provider_alive,
    same_profile_binding=EXCLUDED.same_profile_binding,
    verified_at=clock_timestamp();
  RETURN true;
END $body$;

-- A private BFF supplies the digest of a pre-validated HTTPS auth cookie
-- and CSRF, not a tenant ID from request body. The owner may resume their
-- own named task from another authenticated chat; different principal or
-- tenant cannot. DB returns ONLY fencing epochs, never bearer secrets.
CREATE FUNCTION browser_recovery.reattach_own_task(
  p_session_digest text,p_csrf_digest text,p_task uuid,p_attempt uuid
) RETURNS TABLE(status_code text,slot_no integer,
                lease_generation bigint,attachment_epoch bigint)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path=pg_catalog,browser_recovery,browser_auth,browser_parallel,browser_product,pg_temp
AS $body$
DECLARE actor record; own browser_recovery.owned_tasks%ROWTYPE;
       valid_provider boolean;
       fresh_at timestamptz:=clock_timestamp();
       new_epoch bigint;
BEGIN
  SELECT a.tenant_id,a.principal_id INTO actor
    FROM browser_auth.resolve_session(p_session_digest) AS a
    WHERE a.csrf_digest=p_csrf_digest
      AND a.access_role IN ('operator','admin');
  IF NOT FOUND OR p_task IS NULL OR p_attempt IS NULL THEN
    RETURN QUERY SELECT 'not_authorized'::text,NULL::integer,
      NULL::bigint,NULL::bigint; RETURN;
  END IF;

  SELECT * INTO own FROM browser_recovery.owned_tasks o
    WHERE o.tenant_id=actor.tenant_id AND o.principal_id=actor.principal_id
      AND o.task_id=p_task FOR UPDATE;
  IF NOT FOUND OR own.cancel_requested OR own.lease_id IS NULL THEN
    RETURN QUERY SELECT 'not_available'::text,NULL::integer,
      NULL::bigint,NULL::bigint; RETURN;
  END IF;

  SELECT EXISTS(
    SELECT 1 FROM browser_parallel.slots s
    JOIN browser_product.browser_tasks t
      ON t.tenant_id=s.tenant_id AND t.task_id=s.task_id
         AND t.profile_id=s.profile_id
    JOIN browser_recovery.provider_readback p
      ON p.slot_no=s.slot_no AND p.generation=s.generation
         AND p.lease_id=s.lease_id
    WHERE s.tenant_id=own.tenant_id AND s.task_id=own.task_id
      AND s.slot_no=own.slot_no AND s.generation=own.generation
      AND s.lease_id=own.lease_id AND s.state='active'
      AND s.expires_at>fresh_at AND t.state='running'
      AND p.provider_alive IS TRUE AND p.same_profile_binding IS TRUE
      -- A stale provider receipt is NOT proof that the browser still lives.
      AND p.verified_at>=fresh_at-interval '15 seconds'
  ) INTO valid_provider;

  IF NOT valid_provider THEN
    RETURN QUERY SELECT 'provider_recheck_required'::text,
      NULL::integer,NULL::bigint,NULL::bigint; RETURN;
  END IF;

  IF own.last_resume_attempt=p_attempt THEN
    RETURN QUERY SELECT 'already_attached'::text,own.slot_no,
      own.generation,own.attachment_epoch; RETURN;
  END IF;
  IF own.attachment_epoch >= 9223372036854775807 THEN
    RETURN QUERY SELECT 'epoch_exhausted'::text,
      NULL::integer,NULL::bigint,NULL::bigint; RETURN;
  END IF;

  UPDATE browser_recovery.owned_tasks o SET
      attachment_epoch=o.attachment_epoch+1,
      last_resume_attempt=p_attempt,last_resume_at=fresh_at
    WHERE o.tenant_id=own.tenant_id AND o.task_id=own.task_id
    RETURNING o.attachment_epoch INTO new_epoch;

  -- A trusted BFF MUST next perform live provider readback, then issue a
  -- new signed ephemeral MCP capability, scoped to THIS tenant/task/epoch.
  -- Old capabilities must be rejected on every operation.
  RETURN QUERY SELECT 'reattach_epoch_issued'::text,own.slot_no,
    own.generation,new_epoch;
END $body$;

-- An actual Steel POST /sessions is billable. A tenant-scoped worker
-- must verify this EXACT bound/uncancelled reservation immediately before
-- provider create; a missing owner binding or user cancellation fails closed.
CREATE FUNCTION browser_recovery.can_create_provider(
  p_task uuid,p_lease uuid,p_slot integer,p_generation bigint
) RETURNS boolean LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path=pg_catalog,browser_recovery,browser_parallel,browser_product,pg_temp
AS $body$
DECLARE tid uuid;
BEGIN
  tid:=browser_product.authenticated_tenant();
  IF tid IS NULL OR p_task IS NULL OR p_lease IS NULL
     OR p_slot IS NULL OR p_generation IS NULL THEN RETURN false; END IF;
  RETURN EXISTS(
    SELECT 1 FROM browser_recovery.owned_tasks o
    JOIN browser_parallel.slots s
      ON s.tenant_id=o.tenant_id AND s.task_id=o.task_id
    JOIN browser_product.browser_tasks t
      ON t.tenant_id=s.tenant_id AND t.task_id=s.task_id
         AND t.profile_id=s.profile_id
    WHERE o.tenant_id=tid AND o.task_id=p_task
      AND o.slot_no=p_slot AND o.lease_id=p_lease
      AND o.generation=p_generation AND o.cancel_requested IS FALSE
      AND s.slot_no=p_slot AND s.lease_id=p_lease
      AND s.generation=p_generation AND s.state='reserved'
      AND s.expires_at>clock_timestamp() AND t.state='queued'
  );
END $body$;

-- Called by the scoped worker on EVERY action, not only at session start.
-- Reattachment rotates attachment_epoch, immediately invalidating all
-- previously issued app capabilities. A different tenant's DB role fails.
-- This is DB policy only; the live MCP must be wired to this verification.
CREATE FUNCTION browser_recovery.can_execute_epoch(
  p_task uuid,p_lease uuid,p_slot integer,p_generation bigint,p_epoch bigint
) RETURNS boolean LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path=pg_catalog,browser_recovery,browser_parallel,browser_product,pg_temp
AS $body$
DECLARE tid uuid;
BEGIN
  tid:=browser_product.authenticated_tenant();
  IF tid IS NULL OR p_task IS NULL OR p_lease IS NULL
     OR p_slot IS NULL OR p_generation IS NULL OR p_epoch IS NULL
     OR p_epoch<1 THEN RETURN false; END IF;
  RETURN EXISTS(
    SELECT 1 FROM browser_recovery.owned_tasks o
    JOIN browser_parallel.slots s
      ON s.tenant_id=o.tenant_id AND s.task_id=o.task_id
    JOIN browser_product.browser_tasks t
      ON t.tenant_id=s.tenant_id AND t.task_id=s.task_id
    JOIN browser_recovery.provider_readback p
      ON p.slot_no=s.slot_no AND p.generation=s.generation
         AND p.lease_id=s.lease_id
    WHERE o.tenant_id=tid AND o.task_id=p_task
      AND o.lease_id=p_lease AND o.slot_no=p_slot
      AND o.generation=p_generation AND o.attachment_epoch=p_epoch
      AND o.cancel_requested IS FALSE
      AND s.slot_no=p_slot AND s.generation=p_generation
      AND s.lease_id=p_lease AND s.state='active'
      AND s.expires_at>clock_timestamp() AND t.state='running'
      AND p.provider_alive IS TRUE AND p.same_profile_binding IS TRUE
      AND p.verified_at>=clock_timestamp()-interval '15 seconds'
  );
END $body$;

-- Never delete provider sessions from SQL. Requesting cancellation only
-- revokes old attachment epochs and marks intent for the trusted worker.
-- Release requires separate provider close + full_profile_saved attestation.
CREATE FUNCTION browser_recovery.request_cancel_own(
  p_session_digest text,p_csrf_digest text,p_task uuid
) RETURNS text LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path=pg_catalog,browser_recovery,browser_auth,pg_temp
AS $body$
DECLARE actor record; own browser_recovery.owned_tasks%ROWTYPE;
BEGIN
  SELECT a.tenant_id,a.principal_id INTO actor
    FROM browser_auth.resolve_session(p_session_digest) AS a
    WHERE a.csrf_digest=p_csrf_digest
      AND a.access_role IN ('operator','admin');
  IF NOT FOUND OR p_task IS NULL THEN RETURN 'not_authorized'; END IF;
  SELECT * INTO own FROM browser_recovery.owned_tasks o
    WHERE o.tenant_id=actor.tenant_id AND o.principal_id=actor.principal_id
      AND o.task_id=p_task FOR UPDATE;
  IF NOT FOUND THEN RETURN 'not_available'; END IF;
  IF own.cancel_requested THEN RETURN 'already_requested'; END IF;
  IF own.attachment_epoch>=9223372036854775807 THEN RETURN 'epoch_exhausted'; END IF;

  UPDATE browser_recovery.owned_tasks o SET
    cancel_requested=true,attachment_epoch=attachment_epoch+1
    WHERE o.tenant_id=own.tenant_id AND o.task_id=own.task_id;
  RETURN 'cancel_requested';
END $body$;

-- Safe private discoverability for an owner's new chat: show only task UUID,
-- state and flags; NO provider session IDs, raw handles or origin URLs.
CREATE FUNCTION browser_recovery.list_own_tasks(
  p_session_digest text,p_csrf_digest text
) RETURNS TABLE(task_id uuid,task_state text,cancel_pending boolean,
                attachment_epoch bigint)
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path=pg_catalog,browser_recovery,browser_auth,browser_product,pg_temp
AS $body$
DECLARE actor record;
BEGIN
  SELECT a.tenant_id,a.principal_id INTO actor
    FROM browser_auth.resolve_session(p_session_digest) AS a
    WHERE a.csrf_digest=p_csrf_digest
      AND a.access_role IN ('operator','admin');
  IF NOT FOUND THEN RETURN; END IF;
  RETURN QUERY SELECT t.task_id,t.state,o.cancel_requested,o.attachment_epoch
    FROM browser_recovery.owned_tasks o
    JOIN browser_product.browser_tasks t
      ON t.tenant_id=o.tenant_id AND t.task_id=o.task_id
    WHERE o.tenant_id=actor.tenant_id AND o.principal_id=actor.principal_id
    ORDER BY o.recorded_at DESC LIMIT 20;
END $body$;

REVOKE ALL ON ALL FUNCTIONS IN SCHEMA browser_recovery FROM PUBLIC;
GRANT EXECUTE ON FUNCTION browser_recovery.register_own_task(text,text,uuid),
  browser_recovery.bind_reserved_lease(text,text,uuid,integer,uuid,bigint),
  browser_recovery.reattach_own_task(text,text,uuid,uuid),
  browser_recovery.request_cancel_own(text,text,uuid),
  browser_recovery.list_own_tasks(text,text)
TO browser_bff_auth;
GRANT USAGE ON SCHEMA browser_recovery TO aib_parallel_worker;
GRANT EXECUTE ON FUNCTION browser_recovery.can_create_provider(
  uuid,uuid,integer,bigint)
TO aib_parallel_worker;
GRANT EXECUTE ON FUNCTION browser_recovery.can_execute_epoch(
  uuid,uuid,integer,bigint,bigint)
TO aib_parallel_worker;
GRANT EXECUTE ON FUNCTION browser_recovery.record_provider_readback(
  integer,uuid,bigint,boolean,boolean)
TO aib_parallel_verifier;
COMMIT;
