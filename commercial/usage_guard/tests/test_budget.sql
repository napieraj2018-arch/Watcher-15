-- Tests use disposable PostgreSQL 16 only. No real profiles or payments.
\set ON_ERROR_STOP on
CREATE ROLE fixture_meter_a LOGIN IN ROLE aib_meter_worker;
CREATE ROLE fixture_meter_b LOGIN IN ROLE aib_meter_worker;
CREATE ROLE fixture_meter_c LOGIN IN ROLE aib_meter_worker;
CREATE ROLE fixture_meter_verifier LOGIN IN ROLE aib_meter_verifier;

INSERT INTO browser_meter.policies
  (tenant_id,status,monthly_cap_cents,reserve_per_job_cents,max_open_jobs)
VALUES
  ('11111111-1111-4111-8111-111111111111','active',100,30,2),
  ('22222222-2222-4222-8222-222222222222','active',60,20,1),
  ('33333333-3333-4333-8333-333333333333','active',45,30,3);
INSERT INTO browser_meter.bindings(db_role,tenant_id) VALUES
  ('fixture_meter_a','11111111-1111-4111-8111-111111111111'),
  ('fixture_meter_b','22222222-2222-4222-8222-222222222222'),
  ('fixture_meter_c','33333333-3333-4333-8333-333333333333');

SET SESSION AUTHORIZATION fixture_meter_a;
DO $test$
DECLARE r record;
BEGIN
  SELECT * INTO r FROM browser_meter.reserve('aaaaaaaa-aaaa-4aaa-8aaa-000000000001');
  IF r.code<>'reserved' OR r.may_start IS DISTINCT FROM true
  THEN RAISE EXCEPTION 'FIRST_RESERVE_DENIED'; END IF;
  SELECT * INTO r FROM browser_meter.reserve('aaaaaaaa-aaaa-4aaa-8aaa-000000000001');
  IF r.code<>'already_recorded' OR r.may_start IS DISTINCT FROM false
  THEN RAISE EXCEPTION 'IDEMPOTENCY_FAILED'; END IF;
  SELECT * INTO r FROM browser_meter.reserve('aaaaaaaa-aaaa-4aaa-8aaa-000000000002');
  IF r.code<>'reserved' OR r.may_start IS DISTINCT FROM true
  THEN RAISE EXCEPTION 'SECOND_RESERVE_DENIED'; END IF;
  SELECT * INTO r FROM browser_meter.reserve('aaaaaaaa-aaaa-4aaa-8aaa-000000000003');
  IF r.code<>'concurrency_cap' OR r.may_start IS DISTINCT FROM false
  THEN RAISE EXCEPTION 'CONCURRENCY_CAP_BYPASS'; END IF;

  BEGIN
    PERFORM * FROM browser_meter.jobs;
    RAISE EXCEPTION 'WORKER_READ_RAW_JOB_LEDGER';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
  BEGIN
    PERFORM browser_meter.settle(
      '11111111-1111-4111-8111-111111111111',
      'aaaaaaaa-aaaa-4aaa-8aaa-000000000001',10,
      'dddddddd-dddd-4ddd-8ddd-000000000001');
    RAISE EXCEPTION 'WORKER_FORGED_SETTLEMENT';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;

  SELECT * INTO r FROM browser_meter.my_balance();
  IF r.held_cents<>60 OR r.open_jobs<>2 OR r.spent_cents<>0
  THEN RAISE EXCEPTION 'A_BALANCE_INCORRECT'; END IF;
END $test$;
RESET SESSION AUTHORIZATION;

SET SESSION AUTHORIZATION fixture_meter_b;
DO $test$
DECLARE r record;
BEGIN
  SELECT * INTO r FROM browser_meter.reserve('bbbbbbbb-bbbb-4bbb-8bbb-000000000001');
  IF r.code<>'reserved' OR r.may_start IS DISTINCT FROM true
  THEN RAISE EXCEPTION 'TENANT_B_BUDGET_NOT_INDEPENDENT'; END IF;
  SELECT * INTO r FROM browser_meter.my_balance();
  IF r.held_cents<>20 OR r.open_jobs<>1 OR r.spent_cents<>0
  THEN RAISE EXCEPTION 'TENANT_B_BALANCE_LEAK'; END IF;
END $test$;
RESET SESSION AUTHORIZATION;

SET SESSION AUTHORIZATION fixture_meter_c;
DO $test$
DECLARE r record;
BEGIN
  SELECT * INTO r FROM browser_meter.reserve('cccccccc-cccc-4ccc-8ccc-000000000001');
  IF r.code<>'reserved' OR r.may_start IS DISTINCT FROM true
  THEN RAISE EXCEPTION 'TENANT_C_INITIAL_FAILED'; END IF;
  SELECT * INTO r FROM browser_meter.reserve('cccccccc-cccc-4ccc-8ccc-000000000002');
  IF r.code<>'monthly_cap' OR r.may_start IS DISTINCT FROM false
  THEN RAISE EXCEPTION 'MONTHLY_CAP_BYPASS'; END IF;
END $test$;
RESET SESSION AUTHORIZATION;

SET SESSION AUTHORIZATION fixture_meter_verifier;
DO $test$
DECLARE r text;
BEGIN
  SELECT browser_meter.settle(
    '11111111-1111-4111-8111-111111111111',
    'aaaaaaaa-aaaa-4aaa-8aaa-000000000001',25,
    'dddddddd-dddd-4ddd-8ddd-000000000001') INTO r;
  IF r<>'settled' THEN RAISE EXCEPTION 'SETTLEMENT_FAILED'; END IF;
  SELECT browser_meter.settle(
    '11111111-1111-4111-8111-111111111111',
    'aaaaaaaa-aaaa-4aaa-8aaa-000000000001',25,
    'dddddddd-dddd-4ddd-8ddd-000000000001') INTO r;
  IF r<>'already_settled' THEN RAISE EXCEPTION 'SETTLEMENT_REPLAY_FAILED'; END IF;
  SELECT browser_meter.settle(
    '11111111-1111-4111-8111-111111111111',
    'aaaaaaaa-aaaa-4aaa-8aaa-000000000001',26,
    'dddddddd-dddd-4ddd-8ddd-000000000001') INTO r;
  IF r<>'evidence_conflict' THEN RAISE EXCEPTION 'SETTLEMENT_REWRITTEN'; END IF;
  SELECT browser_meter.release_not_started(
    '22222222-2222-4222-8222-222222222222',
    'bbbbbbbb-bbbb-4bbb-8bbb-000000000001',
    'dddddddd-dddd-4ddd-8ddd-000000000002',false) INTO r;
  IF r<>'unverified' THEN RAISE EXCEPTION 'FALSE_RELEASE_ACCEPTED'; END IF;
  SELECT browser_meter.release_not_started(
    '22222222-2222-4222-8222-222222222222',
    'bbbbbbbb-bbbb-4bbb-8bbb-000000000001',
    'dddddddd-dddd-4ddd-8ddd-000000000002',true) INTO r;
  IF r<>'released' THEN RAISE EXCEPTION 'VERIFIED_RELEASE_DENIED'; END IF;
END $test$;
RESET SESSION AUTHORIZATION;

SET SESSION AUTHORIZATION fixture_meter_a;
DO $test$
DECLARE r record;
BEGIN
  SELECT * INTO r FROM browser_meter.reserve('aaaaaaaa-aaaa-4aaa-8aaa-000000000003');
  IF r.code<>'reserved' OR r.may_start IS DISTINCT FROM true
  THEN RAISE EXCEPTION 'REUSABLE_CAP_NOT_GRANTED'; END IF;
  SELECT * INTO r FROM browser_meter.my_balance();
  IF r.spent_cents<>25 OR r.held_cents<>60 OR r.open_jobs<>2
  THEN RAISE EXCEPTION 'ACCOUNTING_INCONSISTENT'; END IF;
END $test$;
RESET SESSION AUTHORIZATION;

SET SESSION AUTHORIZATION fixture_meter_verifier;
DO $test$
DECLARE r text;
BEGIN
  SELECT browser_meter.settle(
    '11111111-1111-4111-8111-111111111111',
    'aaaaaaaa-aaaa-4aaa-8aaa-000000000002',55,
    'dddddddd-dddd-4ddd-8ddd-000000000003') INTO r;
  IF r<>'overage' THEN RAISE EXCEPTION 'OVERAGE_NOT_RECORDED'; END IF;
END $test$;
RESET SESSION AUTHORIZATION;

SET SESSION AUTHORIZATION fixture_meter_a;
DO $test$
DECLARE r record;
BEGIN
  SELECT * INTO r FROM browser_meter.reserve('aaaaaaaa-aaaa-4aaa-8aaa-000000000004');
  IF r.code<>'account_paused' OR r.may_start IS DISTINCT FROM false
  THEN RAISE EXCEPTION 'OVERAGE_DID_NOT_PAUSE'; END IF;
END $test$;
RESET SESSION AUTHORIZATION;

SET SESSION AUTHORIZATION fixture_meter_b;
DO $test$
DECLARE r record;
BEGIN
  SELECT * INTO r FROM browser_meter.reserve('bbbbbbbb-bbbb-4bbb-8bbb-000000000002');
  IF r.code<>'reserved' OR r.may_start IS DISTINCT FROM true
  THEN RAISE EXCEPTION 'TENANT_A_OVERAGE_BLOCKED_TENANT_B'; END IF;
END $test$;
RESET SESSION AUTHORIZATION;
SELECT 'OFFLINE_COST_LEDGER_CASES_PASS' AS result;
