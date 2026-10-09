-- Isolated follow-on proof: bind the durable slot to an authenticated tenant
-- and an already queued task; NO customer DB or Steel provider operations.
-- Requires tenant_security/001_tenant_isolation.sql and
-- commercial/leases/001_durable_slot.sql in the SAME THROWAWAY PostgreSQL.
BEGIN;
CREATE ROLE aib_slot_tenant_worker NOLOGIN;

-- Revoke broad slot capability: a worker must not choose arbitrary tenant_id
-- or interact with bare slot functions after this upgrade.
REVOKE EXECUTE ON FUNCTION browser_slot_guard.claim_slot(uuid,uuid,uuid,integer),
  browser_slot_guard.activate_slot(uuid,uuid,uuid,bigint),
  browser_slot_guard.extend_slot(uuid,uuid,uuid,bigint,integer),
  browser_slot_guard.begin_close(uuid,uuid,uuid,bigint),
  browser_slot_guard.quarantine_expired(),
  browser_slot_guard.finish_slot(uuid,uuid,uuid,bigint)
FROM aib_slot_worker;

GRANT USAGE ON SCHEMA browser_product TO aib_slot_tenant_worker;
GRANT EXECUTE ON FUNCTION browser_product.authenticated_tenant()
  TO aib_slot_tenant_worker;

CREATE FUNCTION browser_product.claim_guarded_slot(
  p_task uuid, p_lease uuid, p_ttl integer
) RETURNS TABLE(granted boolean,should_start boolean,lease_generation bigint,status_code text)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = pg_catalog,browser_product,browser_slot_guard,pg_temp
AS $body$
DECLARE v_tenant uuid;
BEGIN
  v_tenant := browser_product.authenticated_tenant();
  IF v_tenant IS NULL THEN
    RETURN QUERY SELECT false,false,NULL::bigint,'unauthorized'::text; RETURN;
  END IF;
  IF p_task IS NULL OR p_lease IS NULL OR p_ttl IS NULL
    OR p_ttl NOT BETWEEN 60 AND 870 THEN
    RETURN QUERY SELECT false,false,NULL::bigint,'invalid_request'::text; RETURN;
  END IF;

  -- A real QUEUED task under this tenant AND ready profile is mandatory.
  -- Neither tenant nor profile reference comes from the worker's request.
  IF NOT EXISTS (
    SELECT 1 FROM browser_product.browser_tasks t
    JOIN browser_product.profiles p
      ON (t.tenant_id=p.tenant_id AND t.workspace_id=p.workspace_id
          AND t.profile_id=p.profile_id)
    WHERE t.tenant_id=v_tenant AND t.task_id=p_task
      AND t.state='queued' AND p.status='ready'
  ) THEN
    RETURN QUERY SELECT false,false,NULL::bigint,'task_not_available'::text; RETURN;
  END IF;

  RETURN QUERY SELECT x.granted,x.should_start,x.lease_generation,x.status_code
   FROM browser_slot_guard.claim_slot(v_tenant,p_task,p_lease,p_ttl) AS x;
END $body$;

CREATE FUNCTION browser_product.activate_guarded_slot(
  p_task uuid,p_lease uuid,p_generation bigint
) RETURNS boolean
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = pg_catalog,browser_product,browser_slot_guard,pg_temp
AS $body$
DECLARE v_tenant uuid; changed integer;
BEGIN
  v_tenant := browser_product.authenticated_tenant();
  IF v_tenant IS NULL OR p_task IS NULL OR p_lease IS NULL
     OR p_generation IS NULL THEN RETURN false; END IF;

  -- Do not use the captured slot unless tenant, task, epoch and profile
  -- are current and the profile has not been paused or revoked.
  IF NOT EXISTS (
    SELECT 1 FROM browser_product.browser_tasks t
    JOIN browser_product.profiles p
      ON t.tenant_id=p.tenant_id AND t.workspace_id=p.workspace_id
       AND t.profile_id=p.profile_id
    WHERE t.tenant_id=v_tenant AND t.task_id=p_task
      AND t.state='queued' AND p.status='ready'
  ) THEN RETURN false; END IF;

  IF NOT browser_slot_guard.activate_slot(v_tenant,p_task,p_lease,p_generation)
  THEN RETURN false; END IF;

  UPDATE browser_product.browser_tasks
    SET state='running'
    WHERE tenant_id=v_tenant AND task_id=p_task AND state='queued';
  GET DIAGNOSTICS changed=ROW_COUNT;
  IF changed<>1 THEN
    -- Abort the whole transaction; rollback the slot activation.
    RAISE EXCEPTION 'TASK_ACTIVATION_INCONSISTENT' USING ERRCODE='P0001';
  END IF;
  RETURN true;
END $body$;

CREATE FUNCTION browser_product.extend_guarded_slot(
  p_task uuid,p_lease uuid,p_generation bigint,p_ttl integer
) RETURNS boolean
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = pg_catalog,browser_product,browser_slot_guard,pg_temp
AS $body$
DECLARE v_tenant uuid;
BEGIN
  v_tenant := browser_product.authenticated_tenant();
  IF v_tenant IS NULL OR NOT EXISTS (
     SELECT 1 FROM browser_product.browser_tasks
     WHERE tenant_id=v_tenant AND task_id=p_task AND state='running'
  ) THEN RETURN false; END IF;
  RETURN browser_slot_guard.extend_slot(v_tenant,p_task,p_lease,p_generation,p_ttl);
END $body$;

CREATE FUNCTION browser_product.begin_close_guarded_slot(
  p_task uuid,p_lease uuid,p_generation bigint
) RETURNS boolean
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = pg_catalog,browser_product,browser_slot_guard,pg_temp
AS $body$
DECLARE v_tenant uuid;
BEGIN
  v_tenant := browser_product.authenticated_tenant();
  IF v_tenant IS NULL OR NOT EXISTS (
    SELECT 1 FROM browser_product.browser_tasks
    WHERE tenant_id=v_tenant AND task_id=p_task AND state='running'
  ) THEN RETURN false; END IF;
  RETURN browser_slot_guard.begin_close(v_tenant,p_task,p_lease,p_generation);
END $body$;

CREATE FUNCTION browser_product.finish_guarded_slot(
  p_task uuid,p_lease uuid,p_generation bigint
) RETURNS boolean
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = pg_catalog,browser_product,browser_slot_guard,pg_temp
AS $body$
DECLARE v_tenant uuid; previous_state text; changed integer;
BEGIN
  v_tenant := browser_product.authenticated_tenant();
  IF v_tenant IS NULL OR p_task IS NULL THEN RETURN false; END IF;
  SELECT t.state INTO previous_state FROM browser_product.browser_tasks t
    WHERE t.tenant_id=v_tenant AND t.task_id=p_task FOR UPDATE;
  IF previous_state NOT IN ('queued','running') THEN RETURN false; END IF;

  -- Finish is forbidden without a separate verifier-generated release receipt.
  IF NOT browser_slot_guard.finish_slot(v_tenant,p_task,p_lease,p_generation)
  THEN RETURN false; END IF;

  -- Closing a provider does NOT prove that the user job has completed.
  -- Never forge 'done'. A separate audited executor must confirm completion.
  UPDATE browser_product.browser_tasks SET
    state=CASE WHEN previous_state='queued' THEN 'cancelled' ELSE 'paused' END
    WHERE tenant_id=v_tenant AND task_id=p_task AND state=previous_state;
  GET DIAGNOSTICS changed=ROW_COUNT;
  IF changed<>1 THEN
    RAISE EXCEPTION 'TASK_RELEASE_INCONSISTENT' USING ERRCODE='P0001';
  END IF;
  RETURN true;
END $body$;

REVOKE ALL ON FUNCTION browser_product.claim_guarded_slot(uuid,uuid,integer),
  browser_product.activate_guarded_slot(uuid,uuid,bigint),
  browser_product.extend_guarded_slot(uuid,uuid,bigint,integer),
  browser_product.begin_close_guarded_slot(uuid,uuid,bigint),
  browser_product.finish_guarded_slot(uuid,uuid,bigint)
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION browser_product.claim_guarded_slot(uuid,uuid,integer),
  browser_product.activate_guarded_slot(uuid,uuid,bigint),
  browser_product.extend_guarded_slot(uuid,uuid,bigint,integer),
  browser_product.begin_close_guarded_slot(uuid,uuid,bigint),
  browser_product.finish_guarded_slot(uuid,uuid,bigint)
TO aib_slot_tenant_worker;
COMMIT;
