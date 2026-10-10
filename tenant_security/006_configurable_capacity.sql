-- AI Browser: configurable simultaneous sessions, fixture capacity 5.
-- Run ONLY after tenant_security/005_three_parallel_slots.sql in a throwaway
-- PostgreSQL 16 database. No changes to Render, Floot or Steel Cloud.
-- Provider Launch publicly allows up to 10, but THIS ACCOUNT'S tier must
-- be verified independently before activating 5 in the real API.
BEGIN;

ALTER TABLE browser_parallel.slots
  DROP CONSTRAINT slots_slot_no_check;
ALTER TABLE browser_parallel.slots
  ADD CONSTRAINT slots_positive_number CHECK(slot_no>0);

-- Admin-only provider ceiling is not derived from a user-selected plan or
-- Stripe redirect. Real billing must verify the account's tier first.
CREATE TABLE browser_parallel.capacity(
  id smallint PRIMARY KEY CHECK(id=1),
  active_limit integer NOT NULL CHECK(active_limit>=1 AND active_limit<=32767),
  provider_limit integer NOT NULL CHECK(provider_limit>=1 AND provider_limit<=32767),
  changed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CHECK(active_limit<=provider_limit)
);
INSERT INTO browser_parallel.capacity(id,active_limit,provider_limit)
VALUES(1,5,10);

-- Reserve extra *physical* slot rows before increasing active_limit.
-- A future Scale/Enterprise upgrade only needs a privileged SQL migration
-- to insert more rows and raise the independently verified provider_limit.
INSERT INTO browser_parallel.slots(slot_no)
SELECT i::smallint FROM generate_series(4,10) AS i;

REVOKE ALL ON browser_parallel.capacity FROM PUBLIC;

CREATE OR REPLACE FUNCTION browser_parallel.claim(
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
        allowed_capacity integer;
        currently_held integer;
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

  -- All workers serialize short database admissions on the mutex row.
  -- Provider I/O must happen only AFTER committing this transaction.
  PERFORM 1 FROM browser_parallel.pool_mutex AS m WHERE m.id=1 FOR UPDATE;
  -- Capacity is an administrator-owned fixture setting, never user JSON.
  SELECT c.active_limit INTO allowed_capacity
    FROM browser_parallel.capacity AS c WHERE c.id=1;
  IF allowed_capacity IS NULL THEN
    RETURN QUERY SELECT false,false,NULL::smallint,NULL::bigint,
      'capacity_unavailable'::text; RETURN;
  END IF;
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

  -- Count quarantined and closing reservations: these can still be
  -- billable or hold profile locks until independent provider readback.
  SELECT count(*)::integer INTO currently_held
    FROM browser_parallel.slots AS s WHERE s.state<>'free';
  IF currently_held>=allowed_capacity THEN
    RETURN QUERY SELECT false,false,NULL::smallint,NULL::bigint,
      'capacity_full'::text; RETURN;
  END IF;

  SELECT * INTO selected FROM browser_parallel.slots AS s
    WHERE s.state='free' AND s.slot_no<=allowed_capacity
    ORDER BY s.slot_no LIMIT 1 FOR UPDATE;
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

CREATE OR REPLACE FUNCTION browser_parallel.record_verified_release(
  p_slot integer,p_generation bigint,p_lease uuid,
  p_remote_closed boolean,p_profile_saved boolean
) RETURNS boolean LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path=pg_catalog,browser_parallel,pg_temp
AS $body$
DECLARE inserted integer;
BEGIN
  IF p_slot IS NULL OR p_slot<1 OR p_generation IS NULL OR p_lease IS NULL
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
COMMIT;
