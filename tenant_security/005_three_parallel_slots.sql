-- OFFLINE PROOF ONLY: three independent Steel session reservations in PostgreSQL.
-- Requires tenant_security/001..004 and commercial/leases/001 on THROWAWAY PG16.
-- Do not migrate existing Floot vault or switch AI_BROWSER_MAX_SESSIONS on Render.
-- Worker role: verified DB login -> session_user -> server-maintained tenant binding.
BEGIN;

CREATE ROLE aib_parallel_worker NOLOGIN;
CREATE ROLE aib_parallel_verifier NOLOGIN;
CREATE SCHEMA browser_parallel;
REVOKE ALL ON SCHEMA browser_parallel FROM PUBLIC;
GRANT USAGE ON SCHEMA browser_parallel TO aib_parallel_worker,aib_parallel_verifier;
GRANT USAGE ON SCHEMA browser_product TO aib_parallel_worker;
GRANT EXECUTE ON FUNCTION browser_product.authenticated_tenant()
  TO aib_parallel_worker;

-- Serialize short DB admissions and releases, NEVER perform Steel I/O while
-- holding the row lock. Three remote sessions may run concurrently afterwards.
CREATE TABLE browser_parallel.pool_mutex(
  id smallint PRIMARY KEY CHECK(id=1)
);
INSERT INTO browser_parallel.pool_mutex VALUES (1);

CREATE TABLE browser_parallel.slots(
  slot_no smallint PRIMARY KEY CHECK (slot_no BETWEEN 1 AND 3),
  generation bigint NOT NULL DEFAULT 0 CHECK(generation>=0),
  state text NOT NULL DEFAULT 'free'
    CHECK(state IN('free','reserved','active','closing','quarantined')),
  tenant_id uuid,
  profile_id uuid,
  task_id uuid,
  lease_id uuid,
  expires_at timestamptz,
  changed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CONSTRAINT three_slot_shape CHECK(
    (state='free' AND tenant_id IS NULL AND profile_id IS NULL AND
     task_id IS NULL AND lease_id IS NULL AND expires_at IS NULL)
    OR
    (state<>'free' AND tenant_id IS NOT NULL AND profile_id IS NOT NULL
     AND task_id IS NOT NULL AND lease_id IS NOT NULL AND expires_at IS NOT NULL)),
  FOREIGN KEY(tenant_id,profile_id)
    REFERENCES browser_product.profiles(tenant_id,profile_id),
  FOREIGN KEY(tenant_id,task_id)
    REFERENCES browser_product.browser_tasks(tenant_id,task_id)
);
INSERT INTO browser_parallel.slots(slot_no) VALUES(1),(2),(3);

-- A profile MUST NOT be used in two running Chrome instances at the same time.
-- Quarantine deliberately keeps the profile lock, even after TTL expires.
CREATE UNIQUE INDEX parallel_profile_single_writer
  ON browser_parallel.slots(tenant_id,profile_id)
  WHERE state<>'free';
CREATE UNIQUE INDEX parallel_task_single_start
  ON browser_parallel.slots(tenant_id,task_id)
  WHERE state<>'free';
CREATE UNIQUE INDEX parallel_lease_global_unique
  ON browser_parallel.slots(lease_id)
  WHERE state<>'free';

CREATE TABLE browser_parallel.release_evidence(
  slot_no smallint NOT NULL REFERENCES browser_parallel.slots(slot_no),
  generation bigint NOT NULL,
  lease_id uuid NOT NULL,
  provider_closed boolean NOT NULL CHECK(provider_closed IS TRUE),
  profile_saved boolean NOT NULL CHECK(profile_saved IS TRUE),
  received_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY(slot_no,generation,lease_id)
);

REVOKE ALL ON ALL TABLES IN SCHEMA browser_parallel FROM PUBLIC;

CREATE FUNCTION browser_parallel.claim(
  p_task uuid,p_lease uuid,p_ttl integer
) RETURNS TABLE(granted boolean,should_start boolean,slot_no smallint,
                lease_generation bigint,status_code text)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path=pg_catalog,browser_parallel,browser_product,pg_temp
AS $body$
DECLARE tid uuid; task_profile uuid;
        existing browser_parallel.slots%ROWTYPE;
        selected browser_parallel.slots%ROWTYPE;
        now_at timestamptz := clock_timestamp();
BEGIN
  tid:=browser_product.authenticated_tenant();
  IF tid IS NULL THEN
    RETURN QUERY SELECT false,false,NULL::smallint,NULL::bigint,'unauthorized'::text;
    RETURN;
  END IF;
  IF p_task IS NULL OR p_lease IS NULL OR p_ttl IS NULL
     OR p_ttl NOT BETWEEN 60 AND 870 THEN
    RETURN QUERY SELECT false,false,NULL::smallint,NULL::bigint,'invalid_request'::text;
    RETURN;
  END IF;

  -- Every admission/release receives the same mutex; 16 worker connections
  -- cannot all observe 3 free slots or the same available profile.
  PERFORM 1 FROM browser_parallel.pool_mutex AS m WHERE m.id=1 FOR UPDATE;
  UPDATE browser_parallel.slots AS s SET
     state='quarantined',changed_at=now_at
    WHERE s.state IN ('reserved','active','closing') AND s.expires_at<=now_at;

  SELECT * INTO existing FROM browser_parallel.slots AS s
    WHERE s.tenant_id=tid AND s.task_id=p_task;
  IF FOUND THEN
    IF existing.state='quarantined' THEN
      RETURN QUERY SELECT false,false,NULL::smallint,NULL::bigint,
                          'quarantined'::text;
    ELSIF existing.lease_id=p_lease THEN
      -- A retry NEVER means another billable Steel.create.
      RETURN QUERY SELECT true,false,existing.slot_no,existing.generation,
                          'existing'::text;
    ELSE
      RETURN QUERY SELECT false,false,NULL::smallint,NULL::bigint,
                          'task_busy'::text;
    END IF;
    RETURN;
  END IF;

  SELECT t.profile_id INTO task_profile
    FROM browser_product.browser_tasks AS t
    JOIN browser_product.profiles AS p
      ON p.tenant_id=t.tenant_id AND p.profile_id=t.profile_id
      AND p.workspace_id=t.workspace_id
    WHERE t.tenant_id=tid AND t.task_id=p_task
      AND t.state='queued' AND p.status='ready';
  IF NOT FOUND THEN
    RETURN QUERY SELECT false,false,NULL::smallint,NULL::bigint,
                        'task_not_available'::text; RETURN;
  END IF;

  SELECT * INTO existing FROM browser_parallel.slots AS s
    WHERE s.tenant_id=tid AND s.profile_id=task_profile
    AND s.state<>'free';
  IF FOUND THEN
    RETURN QUERY SELECT false,false,NULL::smallint,NULL::bigint,
       (CASE WHEN existing.state='quarantined'
             THEN 'profile_quarantined' ELSE 'profile_busy' END)::text;
    RETURN;
  END IF;

  SELECT * INTO selected FROM browser_parallel.slots AS s
    WHERE s.state='free' ORDER BY s.slot_no LIMIT 1 FOR UPDATE;
  IF NOT FOUND THEN
    RETURN QUERY SELECT false,false,NULL::smallint,NULL::bigint,
                          'capacity_full'::text; RETURN;
  END IF;
  UPDATE browser_parallel.slots AS s SET
    generation=s.generation+1,state='reserved',tenant_id=tid,
    task_id=p_task,profile_id=task_profile,lease_id=p_lease,
    expires_at=now_at+make_interval(secs=>p_ttl),changed_at=now_at
    WHERE s.slot_no=selected.slot_no
    RETURNING s.slot_no,s.generation INTO selected.slot_no,selected.generation;
  RETURN QUERY SELECT true,true,selected.slot_no,selected.generation,'new'::text;
END $body$;

CREATE FUNCTION browser_parallel.activate(
  p_task uuid,p_lease uuid,p_slot smallint,p_generation bigint
) RETURNS boolean
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path=pg_catalog,browser_parallel,browser_product,pg_temp
AS $body$
DECLARE tid uuid; changed integer;
BEGIN
  tid:=browser_product.authenticated_tenant();
  IF tid IS NULL OR p_task IS NULL OR p_lease IS NULL
     OR p_slot IS NULL OR p_generation IS NULL THEN RETURN false; END IF;

  PERFORM 1 FROM browser_parallel.pool_mutex AS m WHERE m.id=1 FOR UPDATE;
  IF NOT EXISTS(
    SELECT 1 FROM browser_parallel.slots AS s
    JOIN browser_product.browser_tasks AS t
      ON s.tenant_id=t.tenant_id AND s.task_id=t.task_id
    JOIN browser_product.profiles AS p
      ON t.tenant_id=p.tenant_id AND t.profile_id=p.profile_id
    WHERE s.slot_no=p_slot AND s.tenant_id=tid AND s.task_id=p_task
      AND s.lease_id=p_lease AND s.generation=p_generation
      AND s.state='reserved' AND s.expires_at>clock_timestamp()
      AND t.state='queued' AND p.status='ready'
  ) THEN RETURN false; END IF;
  UPDATE browser_parallel.slots SET
    state='active',changed_at=clock_timestamp()
    WHERE slot_no=p_slot AND tenant_id=tid AND task_id=p_task
      AND lease_id=p_lease AND generation=p_generation AND state='reserved'
      AND expires_at>clock_timestamp();
  GET DIAGNOSTICS changed=ROW_COUNT;
  IF changed<>1 THEN RETURN false; END IF;
  UPDATE browser_product.browser_tasks AS t SET state='running'
    WHERE t.tenant_id=tid AND t.task_id=p_task AND t.state='queued';
  GET DIAGNOSTICS changed=ROW_COUNT;
  IF changed<>1 THEN
    RAISE EXCEPTION 'PARALLEL_ACTIVATION_INCONSISTENT' USING ERRCODE='P0001';
  END IF;
  RETURN true;
END $body$;

CREATE FUNCTION browser_parallel.extend(
  p_task uuid,p_lease uuid,p_slot smallint,p_generation bigint,p_ttl integer
) RETURNS boolean LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path=pg_catalog,browser_parallel,browser_product,pg_temp
AS $body$
DECLARE tid uuid; updated integer;
BEGIN
  tid:=browser_product.authenticated_tenant();
  IF tid IS NULL OR p_ttl IS NULL OR p_ttl NOT BETWEEN 60 AND 870
  THEN RETURN false; END IF;
  UPDATE browser_parallel.slots AS s
    SET expires_at=clock_timestamp()+make_interval(secs=>p_ttl),
        changed_at=clock_timestamp()
    WHERE s.slot_no=p_slot AND s.tenant_id=tid AND s.task_id=p_task
      AND s.lease_id=p_lease AND s.generation=p_generation
      AND s.state IN ('reserved','active','closing')
      AND s.expires_at>clock_timestamp()
      AND EXISTS(SELECT 1 FROM browser_product.browser_tasks t
        WHERE t.tenant_id=tid AND t.task_id=p_task
          AND t.state IN ('queued','running'));
  GET DIAGNOSTICS updated=ROW_COUNT;
  RETURN updated=1;
END $body$;

CREATE FUNCTION browser_parallel.begin_close(
  p_task uuid,p_lease uuid,p_slot smallint,p_generation bigint
) RETURNS boolean LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path=pg_catalog,browser_parallel,browser_product,pg_temp
AS $body$
DECLARE tid uuid; updated integer;
BEGIN
  tid:=browser_product.authenticated_tenant();
  IF tid IS NULL THEN RETURN false; END IF;
  UPDATE browser_parallel.slots AS s
    SET state='closing',changed_at=clock_timestamp()
    WHERE s.slot_no=p_slot AND s.tenant_id=tid AND s.task_id=p_task
      AND s.lease_id=p_lease AND s.generation=p_generation
      AND s.state IN ('reserved','active')
      AND s.expires_at>clock_timestamp();
  GET DIAGNOSTICS updated=ROW_COUNT;
  RETURN updated=1;
END $body$;

CREATE FUNCTION browser_parallel.quarantine_expired()
RETURNS integer LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path=pg_catalog,browser_parallel,pg_temp
AS $body$
DECLARE updated integer;
BEGIN
  UPDATE browser_parallel.slots AS s
  SET state='quarantined',changed_at=clock_timestamp()
  WHERE s.state IN ('reserved','active','closing')
    AND s.expires_at<=clock_timestamp();
  GET DIAGNOSTICS updated=ROW_COUNT;
  RETURN updated;
END $body$;

CREATE FUNCTION browser_parallel.record_verified_release(
  p_slot smallint,p_generation bigint,p_lease uuid,
  p_remote_closed boolean,p_profile_saved boolean
) RETURNS boolean LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path=pg_catalog,browser_parallel,pg_temp
AS $body$
DECLARE inserted integer;
BEGIN
  IF p_slot NOT BETWEEN 1 AND 3 OR p_generation IS NULL OR p_lease IS NULL
     OR p_remote_closed IS DISTINCT FROM true
     OR p_profile_saved IS DISTINCT FROM true THEN RETURN false; END IF;
  IF NOT EXISTS(SELECT 1 FROM browser_parallel.slots AS s
    WHERE s.slot_no=p_slot AND s.generation=p_generation
      AND s.lease_id=p_lease AND s.state IN ('closing','quarantined'))
  THEN RETURN false; END IF;
  INSERT INTO browser_parallel.release_evidence
      (slot_no,generation,lease_id,provider_closed,profile_saved)
    VALUES(p_slot,p_generation,p_lease,true,true)
    ON CONFLICT DO NOTHING;
  GET DIAGNOSTICS inserted=ROW_COUNT;
  RETURN inserted=1;
END $body$;

CREATE FUNCTION browser_parallel.finish(
  p_task uuid,p_lease uuid,p_slot smallint,p_generation bigint
) RETURNS boolean LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path=pg_catalog,browser_parallel,browser_product,pg_temp
AS $body$
DECLARE tid uuid; task_state text; updated integer;
BEGIN
  tid:=browser_product.authenticated_tenant();
  IF tid IS NULL THEN RETURN false; END IF;
  PERFORM 1 FROM browser_parallel.pool_mutex AS m WHERE m.id=1 FOR UPDATE;
  SELECT t.state INTO task_state FROM browser_product.browser_tasks t
    WHERE t.tenant_id=tid AND t.task_id=p_task FOR UPDATE;
  IF task_state NOT IN ('queued','running') THEN RETURN false; END IF;
  IF NOT EXISTS(SELECT 1 FROM browser_parallel.slots AS s
    JOIN browser_parallel.release_evidence e
      ON e.slot_no=s.slot_no AND e.generation=s.generation
       AND e.lease_id=s.lease_id
    WHERE s.slot_no=p_slot AND s.tenant_id=tid AND s.task_id=p_task
      AND s.lease_id=p_lease AND s.generation=p_generation
      AND s.state IN ('closing','quarantined')
      AND e.provider_closed AND e.profile_saved
      AND e.received_at>=clock_timestamp()-interval '15 minutes'
  ) THEN RETURN false; END IF;
  UPDATE browser_parallel.slots SET state='free',
    tenant_id=NULL,profile_id=NULL,task_id=NULL,lease_id=NULL,expires_at=NULL,
    changed_at=clock_timestamp()
    WHERE slot_no=p_slot AND tenant_id=tid AND task_id=p_task
      AND lease_id=p_lease AND generation=p_generation;
  GET DIAGNOSTICS updated=ROW_COUNT;
  IF updated<>1 THEN RETURN false; END IF;
  UPDATE browser_product.browser_tasks SET
    state=CASE WHEN task_state='queued' THEN 'cancelled' ELSE 'paused' END
    WHERE tenant_id=tid AND task_id=p_task AND state=task_state;
  GET DIAGNOSTICS updated=ROW_COUNT;
  IF updated<>1 THEN
    RAISE EXCEPTION 'PARALLEL_RELEASE_INCONSISTENT' USING ERRCODE='P0001';
  END IF;
  RETURN true;
END $body$;

CREATE FUNCTION browser_parallel.my_slot_count()
RETURNS TABLE(active_count bigint,quarantined_count bigint)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path=pg_catalog,browser_parallel,browser_product,pg_temp AS $body$
  SELECT count(*) FILTER(WHERE state IN ('reserved','active','closing')),
         count(*) FILTER(WHERE state='quarantined')
  FROM browser_parallel.slots
  WHERE tenant_id=browser_product.authenticated_tenant()
$body$;

REVOKE ALL ON ALL FUNCTIONS IN SCHEMA browser_parallel FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
  browser_parallel.claim(uuid,uuid,integer),
  browser_parallel.activate(uuid,uuid,smallint,bigint),
  browser_parallel.extend(uuid,uuid,smallint,bigint,integer),
  browser_parallel.begin_close(uuid,uuid,smallint,bigint),
  browser_parallel.quarantine_expired(),
  browser_parallel.finish(uuid,uuid,smallint,bigint),
  browser_parallel.my_slot_count()
TO aib_parallel_worker;
GRANT EXECUTE ON FUNCTION
  browser_parallel.record_verified_release(smallint,bigint,uuid,boolean,boolean)
TO aib_parallel_verifier;
COMMIT;
