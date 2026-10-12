-- Experimental cross-process slot fencing; NEVER run on the live Floot vault.
-- Requires a separate Postgres database and a server-authenticated BFF.
BEGIN;
CREATE ROLE aib_slot_worker NOLOGIN;
CREATE ROLE aib_slot_verifier NOLOGIN;
CREATE SCHEMA browser_slot_guard;
REVOKE ALL ON SCHEMA browser_slot_guard FROM PUBLIC;
GRANT USAGE ON SCHEMA browser_slot_guard TO aib_slot_worker,aib_slot_verifier;

CREATE TABLE browser_slot_guard.slots (
  slot_name text PRIMARY KEY CHECK (slot_name = 'steel-main'),
  generation bigint NOT NULL DEFAULT 0 CHECK (generation >= 0),
  state text NOT NULL DEFAULT 'free'
    CHECK (state IN ('free','reserved','active','closing','quarantined')),
  tenant_id uuid,
  task_id uuid,
  lease_id uuid,
  expires_at timestamptz,
  changed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CONSTRAINT slot_shape CHECK (
    (state = 'free' AND tenant_id IS NULL AND task_id IS NULL
      AND lease_id IS NULL AND expires_at IS NULL)
    OR
    (state <> 'free' AND tenant_id IS NOT NULL AND task_id IS NOT NULL
      AND lease_id IS NOT NULL AND expires_at IS NOT NULL)
  )
);
INSERT INTO browser_slot_guard.slots(slot_name) VALUES ('steel-main');

-- Only an independently authenticated verifier may attest BOTH remote
-- session removal AND encrypted profile persistence. No provider IDs/cookies.
CREATE TABLE browser_slot_guard.release_evidence (
  slot_name text NOT NULL REFERENCES browser_slot_guard.slots(slot_name),
  generation bigint NOT NULL,
  lease_id uuid NOT NULL,
  provider_closed boolean NOT NULL,
  profile_saved boolean NOT NULL,
  verified_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY(slot_name,generation,lease_id)
);
REVOKE ALL ON ALL TABLES IN SCHEMA browser_slot_guard FROM PUBLIC;

CREATE FUNCTION browser_slot_guard.claim_slot(
  p_tenant uuid,p_task uuid,p_lease uuid,p_ttl integer
) RETURNS TABLE(granted boolean,should_start boolean,lease_generation bigint,status_code text)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog,browser_slot_guard,pg_temp AS $body$
DECLARE rec browser_slot_guard.slots%ROWTYPE;
  now_at timestamptz := clock_timestamp();
  new_generation bigint;
BEGIN
  IF p_tenant IS NULL OR p_task IS NULL OR p_lease IS NULL
     OR p_ttl IS NULL OR p_ttl NOT BETWEEN 60 AND 870
  THEN RAISE EXCEPTION 'INVALID_SLOT_ARGUMENT' USING ERRCODE='22023'; END IF;
  SELECT * INTO STRICT rec FROM browser_slot_guard.slots
    WHERE slot_name='steel-main' FOR UPDATE;
  IF rec.state IN ('reserved','active','closing') AND rec.expires_at<=now_at THEN
    UPDATE browser_slot_guard.slots SET state='quarantined',changed_at=now_at
    WHERE slot_name='steel-main';
    rec.state:='quarantined';
  END IF;
  IF rec.state='free' THEN
    UPDATE browser_slot_guard.slots SET
      generation=generation+1,state='reserved',tenant_id=p_tenant,
      task_id=p_task,lease_id=p_lease,
      expires_at=now_at+make_interval(secs=>p_ttl),changed_at=now_at
    WHERE slot_name='steel-main'
    RETURNING generation INTO new_generation;
    RETURN QUERY SELECT true,true,new_generation,'new'::text;
  ELSIF rec.state IN ('reserved','active','closing')
        AND rec.expires_at>now_at AND rec.tenant_id=p_tenant
        AND rec.task_id=p_task AND rec.lease_id=p_lease THEN
    -- Idempotent retry does NOT permit another Steel create operation.
    RETURN QUERY SELECT true,false,rec.generation,'existing'::text;
  ELSE
    RETURN QUERY SELECT false,false,NULL::bigint,
      (CASE WHEN rec.state='quarantined' THEN 'quarantined' ELSE 'busy' END)::text;
  END IF;
END $body$;

CREATE FUNCTION browser_slot_guard.activate_slot(
  p_tenant uuid,p_task uuid,p_lease uuid,p_generation bigint
) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog,browser_slot_guard,pg_temp AS $body$
DECLARE changed integer;
BEGIN
  UPDATE browser_slot_guard.slots SET state='active',changed_at=clock_timestamp()
  WHERE slot_name='steel-main' AND state='reserved'
    AND tenant_id=p_tenant AND task_id=p_task AND lease_id=p_lease
    AND generation=p_generation AND expires_at>clock_timestamp();
  GET DIAGNOSTICS changed=ROW_COUNT;
  RETURN changed=1;
END $body$;

CREATE FUNCTION browser_slot_guard.extend_slot(
  p_tenant uuid,p_task uuid,p_lease uuid,p_generation bigint,p_ttl integer
) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog,browser_slot_guard,pg_temp AS $body$
DECLARE changed integer;
BEGIN
  IF p_ttl IS NULL OR p_ttl NOT BETWEEN 60 AND 870 THEN RETURN false; END IF;
  UPDATE browser_slot_guard.slots
  SET expires_at=clock_timestamp()+make_interval(secs=>p_ttl),
      changed_at=clock_timestamp()
  WHERE slot_name='steel-main' AND state IN ('reserved','active','closing')
    AND tenant_id=p_tenant AND task_id=p_task AND lease_id=p_lease
    AND generation=p_generation AND expires_at>clock_timestamp();
  GET DIAGNOSTICS changed=ROW_COUNT;
  RETURN changed=1;
END $body$;

CREATE FUNCTION browser_slot_guard.begin_close(
  p_tenant uuid,p_task uuid,p_lease uuid,p_generation bigint
) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog,browser_slot_guard,pg_temp AS $body$
DECLARE changed integer;
BEGIN
  UPDATE browser_slot_guard.slots SET state='closing',changed_at=clock_timestamp()
  WHERE slot_name='steel-main' AND state='active'
    AND tenant_id=p_tenant AND task_id=p_task AND lease_id=p_lease
    AND generation=p_generation AND expires_at>clock_timestamp();
  GET DIAGNOSTICS changed=ROW_COUNT;
  RETURN changed=1;
END $body$;

CREATE FUNCTION browser_slot_guard.quarantine_expired()
RETURNS integer LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog,browser_slot_guard,pg_temp AS $body$
DECLARE changed integer;
BEGIN
  UPDATE browser_slot_guard.slots SET state='quarantined',changed_at=clock_timestamp()
  WHERE slot_name='steel-main' AND state IN ('reserved','active','closing')
    AND expires_at<=clock_timestamp();
  GET DIAGNOSTICS changed=ROW_COUNT;
  RETURN changed;
END $body$;

CREATE FUNCTION browser_slot_guard.record_verified_release(
  p_lease uuid,p_generation bigint,p_provider_closed boolean,p_profile_saved boolean
) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog,browser_slot_guard,pg_temp AS $body$
DECLARE changed integer;
BEGIN
  IF p_lease IS NULL OR p_generation IS NULL
    OR p_provider_closed IS DISTINCT FROM true OR p_profile_saved IS DISTINCT FROM true
  THEN RETURN false; END IF;
  IF NOT EXISTS (
    SELECT 1 FROM browser_slot_guard.slots
      WHERE slot_name='steel-main' AND lease_id=p_lease
      AND generation=p_generation AND state IN ('closing','quarantined')
  ) THEN RETURN false; END IF;
  INSERT INTO browser_slot_guard.release_evidence(
    slot_name,generation,lease_id,provider_closed,profile_saved
  ) VALUES ('steel-main',p_generation,p_lease,true,true)
  ON CONFLICT DO NOTHING;
  GET DIAGNOSTICS changed=ROW_COUNT;
  RETURN changed=1;
END $body$;

CREATE FUNCTION browser_slot_guard.finish_slot(
  p_tenant uuid,p_task uuid,p_lease uuid,p_generation bigint
) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog,browser_slot_guard,pg_temp AS $body$
DECLARE changed integer;
BEGIN
  -- An operator-authored receipt is required; caller cannot submit booleans.
  UPDATE browser_slot_guard.slots SET state='free',
    tenant_id=NULL,task_id=NULL,lease_id=NULL,expires_at=NULL,
    changed_at=clock_timestamp()
  WHERE slot_name='steel-main' AND state IN ('closing','quarantined')
    AND tenant_id=p_tenant AND task_id=p_task AND lease_id=p_lease
    AND generation=p_generation
    AND EXISTS (SELECT 1 FROM browser_slot_guard.release_evidence e
      WHERE e.slot_name='steel-main' AND e.generation=p_generation
        AND e.lease_id=p_lease AND e.provider_closed AND e.profile_saved
        AND e.verified_at >= clock_timestamp()-interval '15 minutes');
  GET DIAGNOSTICS changed=ROW_COUNT;
  RETURN changed=1;
END $body$;

REVOKE ALL ON ALL FUNCTIONS IN SCHEMA browser_slot_guard FROM PUBLIC;
GRANT EXECUTE ON FUNCTION browser_slot_guard.claim_slot(uuid,uuid,uuid,integer),
 browser_slot_guard.activate_slot(uuid,uuid,uuid,bigint),
 browser_slot_guard.extend_slot(uuid,uuid,uuid,bigint,integer),
 browser_slot_guard.begin_close(uuid,uuid,uuid,bigint),
 browser_slot_guard.quarantine_expired(),
 browser_slot_guard.finish_slot(uuid,uuid,uuid,bigint)
 TO aib_slot_worker;
GRANT EXECUTE ON FUNCTION browser_slot_guard.record_verified_release(uuid,bigint,boolean,boolean)
 TO aib_slot_verifier;
COMMIT;
