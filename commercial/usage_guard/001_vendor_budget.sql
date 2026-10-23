-- Offline AI Browser cost-accounting proof. Throwaway PostgreSQL 16 ONLY.
-- No Steel, Stripe, Render, Floot, customer billing or live profiles.
BEGIN;
CREATE ROLE aib_meter_worker NOLOGIN;
CREATE ROLE aib_meter_verifier NOLOGIN;
CREATE SCHEMA browser_meter;
REVOKE ALL ON SCHEMA browser_meter FROM PUBLIC;
GRANT USAGE ON SCHEMA browser_meter TO aib_meter_worker,aib_meter_verifier;

CREATE TABLE browser_meter.policies(
  tenant_id uuid PRIMARY KEY,
  status text NOT NULL DEFAULT 'paused' CHECK(status IN ('active','paused')),
  monthly_cap_cents integer NOT NULL CHECK(monthly_cap_cents BETWEEN 0 AND 100000000),
  reserve_per_job_cents integer NOT NULL CHECK(reserve_per_job_cents BETWEEN 1 AND 10000000),
  max_open_jobs integer NOT NULL CHECK(max_open_jobs BETWEEN 1 AND 100),
  changed_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE browser_meter.bindings(
  db_role name PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES browser_meter.policies(tenant_id),
  enabled boolean NOT NULL DEFAULT true
);
CREATE TABLE browser_meter.jobs(
  tenant_id uuid NOT NULL REFERENCES browser_meter.policies(tenant_id),
  job_id uuid NOT NULL,
  period_month date NOT NULL,
  state text NOT NULL CHECK(state IN ('reserved','settled','overage','released')),
  reserved_cents integer NOT NULL CHECK(reserved_cents >= 0),
  actual_cents integer,
  evidence_id uuid,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  changed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY(tenant_id,job_id),
  CHECK(
    (state='reserved' AND actual_cents IS NULL AND evidence_id IS NULL)
    OR (state IN ('settled','overage') AND actual_cents>=0 AND evidence_id IS NOT NULL)
    OR (state='released' AND actual_cents=0 AND evidence_id IS NOT NULL)
  )
);
CREATE UNIQUE INDEX meter_unique_provider_receipt
  ON browser_meter.jobs(evidence_id) WHERE evidence_id IS NOT NULL;
CREATE INDEX meter_jobs_period ON browser_meter.jobs(tenant_id,period_month,state);
REVOKE ALL ON ALL TABLES IN SCHEMA browser_meter FROM PUBLIC;

CREATE FUNCTION browser_meter.verified_tenant()
RETURNS uuid LANGUAGE sql STABLE SECURITY DEFINER
SET search_path=pg_catalog,browser_meter,pg_temp
AS $body$
  SELECT b.tenant_id FROM browser_meter.bindings AS b
  WHERE b.db_role::text=session_user::text AND b.enabled=true LIMIT 1
$body$;

CREATE FUNCTION browser_meter.reserve(p_job uuid)
RETURNS TABLE(code text, may_start boolean)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,browser_meter,pg_temp AS $body$
DECLARE tid uuid;
        policy browser_meter.policies%ROWTYPE;
        existing browser_meter.jobs%ROWTYPE;
        cost_so_far bigint;
        open_count integer;
        current_month date:=date_trunc('month',now() AT TIME ZONE 'UTC')::date;
BEGIN
  tid:=browser_meter.verified_tenant();
  IF tid IS NULL THEN
    RETURN QUERY SELECT 'unauthorized'::text,false; RETURN;
  END IF;
  IF p_job IS NULL THEN
    RETURN QUERY SELECT 'invalid_job'::text,false; RETURN;
  END IF;

  -- Single-tenant mutex across PostgreSQL processes. Reserve, settle and
  -- release all obtain this same row lock before touching any job row.
  SELECT * INTO policy FROM browser_meter.policies AS p
    WHERE p.tenant_id=tid FOR UPDATE;
  IF NOT FOUND THEN
    RETURN QUERY SELECT 'unauthorized'::text,false; RETURN;
  END IF;

  SELECT * INTO existing FROM browser_meter.jobs AS j
    WHERE j.tenant_id=tid AND j.job_id=p_job;
  IF FOUND THEN
    RETURN QUERY SELECT 'already_recorded'::text,false; RETURN;
  END IF;
  IF policy.status<>'active' THEN
    RETURN QUERY SELECT 'account_paused'::text,false; RETURN;
  END IF;

  SELECT count(*)::integer INTO open_count
    FROM browser_meter.jobs AS j
    WHERE j.tenant_id=tid AND j.state='reserved';
  IF open_count>=policy.max_open_jobs THEN
    RETURN QUERY SELECT 'concurrency_cap'::text,false; RETURN;
  END IF;

  SELECT COALESCE(sum(CASE
     WHEN j.state='reserved' THEN j.reserved_cents
     WHEN j.state IN ('settled','overage') THEN j.actual_cents
     ELSE 0 END),0)
    INTO cost_so_far
    FROM browser_meter.jobs AS j
    WHERE j.tenant_id=tid AND j.period_month=current_month;

  IF cost_so_far+policy.reserve_per_job_cents>policy.monthly_cap_cents THEN
    RETURN QUERY SELECT 'monthly_cap'::text,false; RETURN;
  END IF;

  INSERT INTO browser_meter.jobs(
    tenant_id,job_id,period_month,state,reserved_cents
  ) VALUES(tid,p_job,current_month,'reserved',policy.reserve_per_job_cents);
  RETURN QUERY SELECT 'reserved'::text,true;
END $body$;

-- The verifier is a DIFFERENT database role. It must obtain real independent
-- metering evidence from Steel before production use. Fixtures supply mock
-- receipts; caller-supplied booleans and amounts are not proof of vendor usage.
CREATE FUNCTION browser_meter.settle(
  p_tenant uuid,p_job uuid,p_actual_cents integer,p_receipt uuid
) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,browser_meter,pg_temp AS $body$
DECLARE policy browser_meter.policies%ROWTYPE;
        job browser_meter.jobs%ROWTYPE;
        new_state text;
BEGIN
  IF p_tenant IS NULL OR p_job IS NULL OR p_receipt IS NULL
     OR p_actual_cents IS NULL OR p_actual_cents<0 OR p_actual_cents>10000000
  THEN RETURN 'invalid_evidence'; END IF;

  -- Lock order matches reserve() to prevent deadlocks and budget races.
  SELECT * INTO policy FROM browser_meter.policies AS p
    WHERE p.tenant_id=p_tenant FOR UPDATE;
  IF NOT FOUND THEN RETURN 'unknown_tenant'; END IF;

  SELECT * INTO job FROM browser_meter.jobs AS j
    WHERE j.tenant_id=p_tenant AND j.job_id=p_job FOR UPDATE;
  IF NOT FOUND THEN RETURN 'unknown_job'; END IF;

  IF job.state IN ('settled','overage') THEN
    IF job.actual_cents=p_actual_cents AND job.evidence_id=p_receipt
    THEN RETURN 'already_settled'; END IF;
    RETURN 'evidence_conflict';
  END IF;
  IF job.state<>'reserved' THEN RETURN 'not_reservable'; END IF;

  IF EXISTS(SELECT 1 FROM browser_meter.jobs AS j
             WHERE j.evidence_id=p_receipt)
  THEN RETURN 'evidence_conflict'; END IF;

  new_state := CASE WHEN p_actual_cents>job.reserved_cents
                    THEN 'overage' ELSE 'settled' END;
  UPDATE browser_meter.jobs SET state=new_state,
    actual_cents=p_actual_cents,evidence_id=p_receipt,
    changed_at=clock_timestamp()
    WHERE tenant_id=p_tenant AND job_id=p_job;

  IF new_state='overage' THEN
    UPDATE browser_meter.policies SET status='paused',
      changed_at=clock_timestamp() WHERE tenant_id=p_tenant;
  END IF;
  RETURN new_state;
END $body$;

-- Release a reservation only upon independent proof that Steel never started
-- the session and incurred no cost. A user cannot free a billable session.
CREATE FUNCTION browser_meter.release_not_started(
  p_tenant uuid,p_job uuid,p_receipt uuid,p_no_session boolean
) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,browser_meter,pg_temp AS $body$
DECLARE policy browser_meter.policies%ROWTYPE;
        job browser_meter.jobs%ROWTYPE;
BEGIN
  IF p_tenant IS NULL OR p_job IS NULL OR p_receipt IS NULL
     OR p_no_session IS DISTINCT FROM true
  THEN RETURN 'unverified'; END IF;
  SELECT * INTO policy FROM browser_meter.policies AS p
    WHERE p.tenant_id=p_tenant FOR UPDATE;
  IF NOT FOUND THEN RETURN 'unknown_tenant'; END IF;
  SELECT * INTO job FROM browser_meter.jobs AS j
    WHERE j.tenant_id=p_tenant AND j.job_id=p_job FOR UPDATE;
  IF NOT FOUND THEN RETURN 'unknown_job'; END IF;
  IF job.state='released' AND job.evidence_id=p_receipt
  THEN RETURN 'already_released'; END IF;
  IF job.state<>'reserved' THEN RETURN 'not_releasable'; END IF;
  IF EXISTS(SELECT 1 FROM browser_meter.jobs AS j
             WHERE j.evidence_id=p_receipt)
  THEN RETURN 'evidence_conflict'; END IF;
  UPDATE browser_meter.jobs SET state='released',actual_cents=0,
    evidence_id=p_receipt,changed_at=clock_timestamp()
    WHERE tenant_id=p_tenant AND job_id=p_job;
  RETURN 'released';
END $body$;

CREATE FUNCTION browser_meter.my_balance()
RETURNS TABLE(cap_cents integer,spent_cents bigint,held_cents bigint,
              open_jobs bigint,status_code text)
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path=pg_catalog,browser_meter,pg_temp AS $body$
DECLARE tid uuid;
BEGIN
  tid:=browser_meter.verified_tenant();
  IF tid IS NULL THEN RETURN; END IF;
  RETURN QUERY
  SELECT p.monthly_cap_cents,
    COALESCE(sum(j.actual_cents) FILTER(
      WHERE j.period_month=date_trunc('month',now() AT TIME ZONE 'UTC')::date
      AND j.state IN ('settled','overage')),0)::bigint,
    COALESCE(sum(j.reserved_cents) FILTER(
      WHERE j.period_month=date_trunc('month',now() AT TIME ZONE 'UTC')::date
      AND j.state='reserved'),0)::bigint,
    count(j.job_id) FILTER(WHERE j.state='reserved')::bigint,
    p.status
  FROM browser_meter.policies AS p
  LEFT JOIN browser_meter.jobs AS j ON j.tenant_id=p.tenant_id
  WHERE p.tenant_id=tid GROUP BY p.monthly_cap_cents,p.status;
END $body$;

REVOKE ALL ON ALL FUNCTIONS IN SCHEMA browser_meter FROM PUBLIC;
GRANT EXECUTE ON FUNCTION browser_meter.verified_tenant(),
  browser_meter.reserve(uuid),browser_meter.my_balance()
  TO aib_meter_worker;
GRANT EXECUTE ON FUNCTION browser_meter.settle(uuid,uuid,integer,uuid),
  browser_meter.release_not_started(uuid,uuid,uuid,boolean)
  TO aib_meter_verifier;
COMMIT;
