-- Synthetic three-session tenant integration. EPHEMERAL PostgreSQL 16 ONLY.
\set ON_ERROR_STOP on

CREATE ROLE fixture_parallel_a LOGIN IN ROLE aib_parallel_worker;
CREATE ROLE fixture_parallel_b LOGIN IN ROLE aib_parallel_worker;
CREATE ROLE fixture_parallel_verify LOGIN IN ROLE aib_parallel_verifier;

INSERT INTO browser_product.login_tenant_bindings(db_role,tenant_id)
VALUES ('fixture_parallel_a','11111111-1111-4111-8111-111111111111'),
       ('fixture_parallel_b','22222222-2222-4222-8222-222222222222');

-- Admin fixture only. None of this runs on a customer DB.
INSERT INTO browser_product.profiles
  (tenant_id,workspace_id,profile_id,display_name,status)
VALUES
 ('11111111-1111-4111-8111-111111111111',
  'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
  'aaaaaaaa-0000-4000-8000-000000000012','Fixture A second','ready'),
 ('22222222-2222-4222-8222-222222222222',
  'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
  'bbbbbbbb-0000-4000-8000-000000000022','Fixture B second','ready');
UPDATE browser_product.profiles SET status='ready'
 WHERE (tenant_id,profile_id) IN (
 ('11111111-1111-4111-8111-111111111111'::uuid,
  'aaaaaaaa-0000-4000-8000-000000000001'::uuid),
 ('22222222-2222-4222-8222-222222222222'::uuid,
  'bbbbbbbb-0000-4000-8000-000000000002'::uuid));

DELETE FROM browser_product.browser_tasks;
INSERT INTO browser_product.browser_tasks
 (tenant_id,workspace_id,profile_id,task_id)
VALUES
 ('11111111-1111-4111-8111-111111111111',
  'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
  'aaaaaaaa-0000-4000-8000-000000000001',
  'aaaaaaaa-1111-4111-8111-000000000001'),
 ('11111111-1111-4111-8111-111111111111',
  'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
  'aaaaaaaa-0000-4000-8000-000000000012',
  'aaaaaaaa-1111-4111-8111-000000000002'),
 ('22222222-2222-4222-8222-222222222222',
  'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
  'bbbbbbbb-0000-4000-8000-000000000002',
  'bbbbbbbb-1111-4111-8111-000000000003'),
 -- Same profile as first A task, deliberately different task
 ('11111111-1111-4111-8111-111111111111',
  'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
  'aaaaaaaa-0000-4000-8000-000000000001',
  'aaaaaaaa-1111-4111-8111-000000000004'),
 ('22222222-2222-4222-8222-222222222222',
  'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
  'bbbbbbbb-0000-4000-8000-000000000022',
  'bbbbbbbb-1111-4111-8111-000000000005'),
 ('11111111-1111-4111-8111-111111111111',
  'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
  'aaaaaaaa-0000-4000-8000-000000000012',
  'aaaaaaaa-1111-4111-8111-000000000006');

SET SESSION AUTHORIZATION fixture_parallel_a;
DO $test$
DECLARE rec record; n record;
BEGIN
  SELECT * INTO rec FROM browser_parallel.claim(
    'aaaaaaaa-1111-4111-8111-000000000001',
    'aaaaaaaa-2222-4222-8222-000000000001',300);
  IF rec.status_code<>'new' OR rec.granted IS DISTINCT FROM true
     OR rec.should_start IS DISTINCT FROM true OR rec.slot_no<>1
     OR rec.lease_generation IS NULL
  THEN RAISE EXCEPTION 'A_FIRST_SESSION_NOT_ASSIGNED'; END IF;

  SELECT * INTO n FROM browser_parallel.claim(
    'aaaaaaaa-1111-4111-8111-000000000004',
    'aaaaaaaa-2222-4222-8222-000000000004',300);
  IF n.status_code<>'profile_busy' OR n.granted IS DISTINCT FROM false
  THEN RAISE EXCEPTION 'SAME_PROFILE_CLAIMED_TWICE'; END IF;

  SELECT * INTO n FROM browser_parallel.claim(
    'aaaaaaaa-1111-4111-8111-000000000001',
    'aaaaaaaa-2222-4222-8222-000000000001',300);
  IF n.status_code<>'existing' OR n.should_start IS DISTINCT FROM false
     OR n.lease_generation<>rec.lease_generation
  THEN RAISE EXCEPTION 'RETRY_AUTHORIZED_DUPLICATE_REMOTE'; END IF;
  SELECT * INTO n FROM browser_parallel.claim(
    'aaaaaaaa-1111-4111-8111-000000000001',
    'aaaaaaaa-2222-4222-8222-000000000099',300);
  IF n.status_code<>'task_busy' THEN RAISE EXCEPTION 'TASK_REBOUND_TO_OTHER_LEASE'; END IF;
  PERFORM set_config('fixture.parallel_a_epoch',rec.lease_generation::text,false);

  IF NOT browser_parallel.activate(
    'aaaaaaaa-1111-4111-8111-000000000001',
    'aaaaaaaa-2222-4222-8222-000000000001',1,rec.lease_generation
  ) THEN RAISE EXCEPTION 'A_FIRST_ACTIVATION_DENIED'; END IF;
  IF browser_parallel.activate(
    'aaaaaaaa-1111-4111-8111-000000000001',
    'aaaaaaaa-2222-4222-8222-000000000001',1,rec.lease_generation
  ) THEN RAISE EXCEPTION 'A_DOUBLE_ACTIVATION'; END IF;

  SELECT * INTO rec FROM browser_parallel.claim(
    'aaaaaaaa-1111-4111-8111-000000000002',
    'aaaaaaaa-2222-4222-8222-000000000002',300);
  IF rec.status_code<>'new' OR rec.slot_no<>2
  THEN RAISE EXCEPTION 'A_SECOND_PROFILE_BLOCKED_BY_FIRST'; END IF;
  PERFORM set_config('fixture.parallel_a2_epoch',rec.lease_generation::text,false);
  IF NOT browser_parallel.activate(
    'aaaaaaaa-1111-4111-8111-000000000002',
    'aaaaaaaa-2222-4222-8222-000000000002',2,rec.lease_generation
  ) THEN RAISE EXCEPTION 'A_SECOND_ACTIVATION_DENIED'; END IF;

  SELECT * INTO n FROM browser_parallel.my_slot_count();
  IF n.active_count<>2 OR n.quarantined_count<>0
  THEN RAISE EXCEPTION 'A_AGGREGATE_NOT_TWO'; END IF;

  BEGIN
    PERFORM * FROM browser_parallel.slots;
    RAISE EXCEPTION 'TENANT_A_CAN_READ_RAW_SLOTS';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
  BEGIN
    PERFORM browser_parallel.record_verified_release(
      1,rec.lease_generation,
      'aaaaaaaa-2222-4222-8222-000000000001',true,true);
    RAISE EXCEPTION 'WORKER_FORGED_VERIFIER_RECEIPT';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
END $test$;
RESET SESSION AUTHORIZATION;

SET SESSION AUTHORIZATION fixture_parallel_b;
DO $test$
DECLARE rec record; other record;
BEGIN
  SELECT * INTO rec FROM browser_parallel.claim(
    'bbbbbbbb-1111-4111-8111-000000000003',
    'bbbbbbbb-2222-4222-8222-000000000003',300);
  IF rec.status_code<>'new' OR rec.slot_no<>3
  THEN RAISE EXCEPTION 'TENANT_B_THIRD_SLOT_UNAVAILABLE'; END IF;
  PERFORM set_config('fixture.parallel_b_epoch',rec.lease_generation::text,false);
  IF NOT browser_parallel.activate(
    'bbbbbbbb-1111-4111-8111-000000000003',
    'bbbbbbbb-2222-4222-8222-000000000003',3,rec.lease_generation
  ) THEN RAISE EXCEPTION 'B_THIRD_ACTIVATION_DENIED'; END IF;
  SELECT * INTO other FROM browser_parallel.claim(
    'bbbbbbbb-1111-4111-8111-000000000005',
    'bbbbbbbb-2222-4222-8222-000000000005',300);
  IF other.status_code<>'capacity_full' OR other.granted IS DISTINCT FROM false
  THEN RAISE EXCEPTION 'FOURTH_STEEL_SESSION_CREATED'; END IF;

  SELECT * INTO other FROM browser_parallel.claim(
    'aaaaaaaa-1111-4111-8111-000000000001',
    'aaaaaaaa-2222-4222-8222-000000000001',300);
  IF other.status_code<>'task_not_available'
  THEN RAISE EXCEPTION 'B_CLAIMED_TENANT_A_TASK'; END IF;

  IF browser_parallel.begin_close(
    'aaaaaaaa-1111-4111-8111-000000000001',
    'aaaaaaaa-2222-4222-8222-000000000001',1,
    current_setting('fixture.parallel_a_epoch')::bigint
  ) THEN RAISE EXCEPTION 'B_CLOSED_TENANT_A_REMOTE'; END IF;
  SELECT * INTO other FROM browser_parallel.my_slot_count();
  IF other.active_count<>1 OR other.quarantined_count<>0
  THEN RAISE EXCEPTION 'B_SEES_A_PRIVATE_SLOT'; END IF;

  IF NOT browser_parallel.begin_close(
    'bbbbbbbb-1111-4111-8111-000000000003',
    'bbbbbbbb-2222-4222-8222-000000000003',3,rec.lease_generation
  ) THEN RAISE EXCEPTION 'B_BEGIN_CLOSE_DENIED'; END IF;
  IF browser_parallel.finish(
    'bbbbbbbb-1111-4111-8111-000000000003',
    'bbbbbbbb-2222-4222-8222-000000000003',3,rec.lease_generation
  ) THEN RAISE EXCEPTION 'SLOT_RELEASE_WITHOUT_VERIFICATION'; END IF;
END $test$;
RESET SESSION AUTHORIZATION;

SET SESSION AUTHORIZATION fixture_parallel_verify;
DO $test$
DECLARE rec boolean;
BEGIN
  SELECT browser_parallel.record_verified_release(
    3,current_setting('fixture.parallel_b_epoch')::bigint,
    'bbbbbbbb-2222-4222-8222-000000000003',false,true) INTO rec;
  IF rec THEN RAISE EXCEPTION 'UNVERIFIED_PROVIDER_CLOSE_ACCEPTED'; END IF;
  SELECT browser_parallel.record_verified_release(
    3,current_setting('fixture.parallel_b_epoch')::bigint,
    'bbbbbbbb-2222-4222-8222-000000000003',true,true) INTO rec;
  IF rec IS DISTINCT FROM true
  THEN RAISE EXCEPTION 'INDEPENDENT_SYNTHETIC_PROOF_REJECTED'; END IF;
END $test$;
RESET SESSION AUTHORIZATION;

SET SESSION AUTHORIZATION fixture_parallel_b;
DO $test$
DECLARE rec record; newg bigint;
BEGIN
  IF NOT browser_parallel.finish(
    'bbbbbbbb-1111-4111-8111-000000000003',
    'bbbbbbbb-2222-4222-8222-000000000003',3,
    current_setting('fixture.parallel_b_epoch')::bigint
  ) THEN RAISE EXCEPTION 'VERIFIED_RELEASE_DID_NOT_FREE_SLOT'; END IF;
  SELECT * INTO rec FROM browser_parallel.claim(
    'bbbbbbbb-1111-4111-8111-000000000005',
    'bbbbbbbb-2222-4222-8222-000000000005',300);
  IF rec.status_code<>'new' OR rec.slot_no<>3
     OR rec.lease_generation <= current_setting('fixture.parallel_b_epoch')::bigint
  THEN RAISE EXCEPTION 'SLOT_NOT_REUSED_WITH_NEW_EPOCH'; END IF;
  IF browser_parallel.activate(
    'bbbbbbbb-1111-4111-8111-000000000005',
    'bbbbbbbb-2222-4222-8222-000000000005',3,
    current_setting('fixture.parallel_b_epoch')::bigint
  ) THEN RAISE EXCEPTION 'STALE_GENERATION_ACTIVATED'; END IF;
  IF NOT browser_parallel.activate(
    'bbbbbbbb-1111-4111-8111-000000000005',
    'bbbbbbbb-2222-4222-8222-000000000005',3,rec.lease_generation
  ) THEN RAISE EXCEPTION 'FRESH_GENERATION_ACTIVATION_FAILED'; END IF;
END $test$;
RESET SESSION AUTHORIZATION;

DO $test$
DECLARE count_running integer;
BEGIN
  SELECT count(*) INTO count_running
  FROM browser_product.browser_tasks WHERE state='running';
  IF count_running<>3 THEN RAISE EXCEPTION 'NOT_THREE_RUNNING_TASKS'; END IF;
END $test$;

-- Only test fixtures can directly manipulate provider TTL in a disposable DB.
UPDATE browser_parallel.slots
  SET expires_at=clock_timestamp()-interval '1 second'
  WHERE slot_no=2;
SET SESSION AUTHORIZATION fixture_parallel_a;
DO $test$
DECLARE rec record; n integer;
BEGIN
  SELECT browser_parallel.quarantine_expired() INTO n;
  IF n<>1 THEN RAISE EXCEPTION 'EXPIRED_LEASE_NOT_QUARANTINED'; END IF;
  SELECT * INTO rec FROM browser_parallel.claim(
    'aaaaaaaa-1111-4111-8111-000000000002',
    'aaaaaaaa-2222-4222-8222-000000000002',300);
  IF rec.status_code<>'quarantined' OR rec.granted IS DISTINCT FROM false
  THEN RAISE EXCEPTION 'EXPIRED_SLOT_RELAUNCHED'; END IF;
  SELECT * INTO rec FROM browser_parallel.claim(
    'aaaaaaaa-1111-4111-8111-000000000006',
    'aaaaaaaa-2222-4222-8222-000000000006',300);
  IF rec.status_code<>'profile_quarantined'
  THEN RAISE EXCEPTION 'QUARANTINED_PROFILE_REUSED'; END IF;
  SELECT * INTO rec FROM browser_parallel.my_slot_count();
  IF rec.active_count<>1 OR rec.quarantined_count<>1
  THEN RAISE EXCEPTION 'A_QUARANTINE_NOT_COUNTED'; END IF;
END $test$;
RESET SESSION AUTHORIZATION;

SELECT 'PARALLEL_THREE_SQL_TENANT_FENCING_PASS' AS proof;
