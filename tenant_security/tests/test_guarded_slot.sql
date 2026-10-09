-- Tenant BFF → SQL queue → durable fenced slot: throwaway PostgreSQL only.
\set ON_ERROR_STOP on
CREATE ROLE fixture_guarded_a LOGIN IN ROLE aib_slot_tenant_worker;
CREATE ROLE fixture_guarded_b LOGIN IN ROLE aib_slot_tenant_worker;

INSERT INTO browser_product.login_tenant_bindings(db_role,tenant_id)
VALUES ('fixture_guarded_a','11111111-1111-4111-8111-111111111111'),
       ('fixture_guarded_b','22222222-2222-4222-8222-222222222222');

-- Clear only the fresh CI fixture, NEVER a live customer database.
DELETE FROM browser_product.browser_tasks;
UPDATE browser_product.profiles SET status='ready'
 WHERE profile_id IN (
  'aaaaaaaa-0000-4000-8000-000000000001',
  'bbbbbbbb-0000-4000-8000-000000000002'
 );
UPDATE browser_slot_guard.slots SET state='free',
 tenant_id=NULL,task_id=NULL,lease_id=NULL,expires_at=NULL
 WHERE slot_name='steel-main';

INSERT INTO browser_product.browser_tasks(tenant_id,workspace_id,task_id,profile_id)
VALUES
('11111111-1111-4111-8111-111111111111',
 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
 'aaaaaaaa-3333-4333-8333-333333333333',
 'aaaaaaaa-0000-4000-8000-000000000001'),
('22222222-2222-4222-8222-222222222222',
 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
 'bbbbbbbb-3333-4333-8333-333333333333',
 'bbbbbbbb-0000-4000-8000-000000000002'),
('11111111-1111-4111-8111-111111111111',
 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
 'aaaaaaaa-4444-4444-8444-444444444444',
 'aaaaaaaa-0000-4000-8000-000000000001');

-- Revoke the original broad grant, including roles inherited by old workers.
SET SESSION AUTHORIZATION fixture_slot_worker;
DO $test$
BEGIN
  BEGIN
    PERFORM browser_slot_guard.claim_slot(
      '11111111-1111-4111-8111-111111111111',
      'aaaaaaaa-3333-4333-8333-333333333333',
      'aaaaaaaa-9999-4999-8999-999999999999',300);
    RAISE EXCEPTION 'UNSCOPED_SLOT_CLAIM_REMAINS_PUBLIC';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
END $test$;
RESET SESSION AUTHORIZATION;

SET SESSION AUTHORIZATION fixture_guarded_a;
DO $test$
DECLARE rec record; code text; state text;
BEGIN
  IF browser_product.authenticated_tenant()
     IS DISTINCT FROM '11111111-1111-4111-8111-111111111111'::uuid
  THEN RAISE EXCEPTION 'MISSING_DB_ROLE_TENANT_IDENTITY'; END IF;

  SELECT * INTO rec FROM browser_product.claim_guarded_slot(
    'bbbbbbbb-3333-4333-8333-333333333333',
    'aaaaaaaa-9999-4999-8999-999999999999',300);
  IF rec.status_code<>'task_not_available' OR rec.granted
  THEN RAISE EXCEPTION 'CLAIMED_OTHER_TENANT_JOB'; END IF;

  SELECT * INTO rec FROM browser_product.claim_guarded_slot(
    'aaaaaaaa-5555-4555-8555-555555555555',
    'aaaaaaaa-9999-4999-8999-999999999999',300);
  IF rec.status_code<>'task_not_available'
  THEN RAISE EXCEPTION 'CLAIMED_NONEXISTENT_JOB'; END IF;

  SELECT * INTO rec FROM browser_product.claim_guarded_slot(
    'aaaaaaaa-3333-4333-8333-333333333333',
    'aaaaaaaa-9999-4999-8999-999999999999',300);
  IF rec.status_code<>'new' OR rec.granted IS DISTINCT FROM true
     OR rec.should_start IS DISTINCT FROM true
     OR rec.lease_generation IS NULL
  THEN RAISE EXCEPTION 'REAL_QUEUED_JOB_CANNOT_CLAIM'; END IF;
  -- Test-only reference, NEVER an authorization source for server code.
  PERFORM set_config('test.fixture_slot_generation',
                     rec.lease_generation::text,false);

  SELECT * INTO rec FROM browser_product.claim_guarded_slot(
    'aaaaaaaa-3333-4333-8333-333333333333',
    'aaaaaaaa-9999-4999-8999-999999999999',300);
  IF rec.status_code<>'existing' OR rec.should_start IS DISTINCT FROM false
  THEN RAISE EXCEPTION 'IDEMPOTENCY_STARTED_TWO_STEEL_SESSIONS'; END IF;

  IF browser_product.activate_guarded_slot(
    'aaaaaaaa-3333-4333-8333-333333333333',
    'aaaaaaaa-9999-4999-8999-999999999999',-1)
  THEN RAISE EXCEPTION 'FORGED_EPOCH_ACTIVATED'; END IF;

  IF NOT browser_product.activate_guarded_slot(
    'aaaaaaaa-3333-4333-8333-333333333333',
    'aaaaaaaa-9999-4999-8999-999999999999',rec.lease_generation)
  THEN RAISE EXCEPTION 'TENANT_CANNOT_ACTIVATE_REAL_JOB'; END IF;

  -- The worker has NO direct SELECT on task rows; an independent
  -- privileged test assertion checks 'running' after this block.

  SELECT * INTO rec FROM browser_product.claim_guarded_slot(
    'aaaaaaaa-3333-4333-8333-333333333333',
    'aaaaaaaa-9999-4999-8999-999999999999',300);
  IF rec.status_code<>'task_not_available'
  THEN RAISE EXCEPTION 'RUNNING_JOB_RESTARTED_STEEL'; END IF;

  IF NOT browser_product.extend_guarded_slot(
    'aaaaaaaa-3333-4333-8333-333333333333',
    'aaaaaaaa-9999-4999-8999-999999999999',
    current_setting('test.fixture_slot_generation')::bigint,300)
  THEN RAISE EXCEPTION 'TENANT_CANNOT_EXTEND_OWN_ACTIVE_LEASE'; END IF;

  IF NOT browser_product.begin_close_guarded_slot(
    'aaaaaaaa-3333-4333-8333-333333333333',
    'aaaaaaaa-9999-4999-8999-999999999999',
    current_setting('test.fixture_slot_generation')::bigint)
  THEN RAISE EXCEPTION 'BEGIN_CLOSE_FAILED'; END IF;

  IF browser_product.finish_guarded_slot(
    'aaaaaaaa-3333-4333-8333-333333333333',
    'aaaaaaaa-9999-4999-8999-999999999999',
    current_setting('test.fixture_slot_generation')::bigint)
  THEN RAISE EXCEPTION 'RELEASE_WITHOUT_PROVIDER_AND_VAULT_RECEIPT'; END IF;
END $test$;
RESET SESSION AUTHORIZATION;
DO $test$
DECLARE task_status text;
BEGIN
  SELECT state INTO task_status FROM browser_product.browser_tasks
   WHERE tenant_id='11111111-1111-4111-8111-111111111111'
     AND task_id='aaaaaaaa-3333-4333-8333-333333333333';
  IF task_status<>'running'
  THEN RAISE EXCEPTION 'TASK_NOT_ATOMICALLY_RUNNING'; END IF;
END $test$;

SET SESSION AUTHORIZATION fixture_guarded_b;
DO $test$
DECLARE rec record;
BEGIN
  SELECT * INTO rec FROM browser_product.claim_guarded_slot(
    'bbbbbbbb-3333-4333-8333-333333333333',
    'bbbbbbbb-9999-4999-8999-999999999999',300);
  IF rec.status_code<>'busy' OR rec.granted IS DISTINCT FROM false
  THEN RAISE EXCEPTION 'TWO_TENANTS_OWNED_ONE_STEEL_SLOT'; END IF;
  IF browser_product.finish_guarded_slot(
    'aaaaaaaa-3333-4333-8333-333333333333',
    'aaaaaaaa-9999-4999-8999-999999999999',
    current_setting('test.fixture_slot_generation')::bigint)
  THEN RAISE EXCEPTION 'TENANT_B_FINISHED_TENANT_A'; END IF;
END $test$;
RESET SESSION AUTHORIZATION;

SET SESSION AUTHORIZATION fixture_slot_verifier;
DO $test$
DECLARE gen bigint;
BEGIN
  -- This is a CI-only fake receipt. Real verifier must independently confirm
  -- remote provider closure and encrypted vault persistence.
  SELECT current_setting('test.fixture_slot_generation')::bigint INTO gen;
  IF NOT browser_slot_guard.record_verified_release(
    'aaaaaaaa-9999-4999-8999-999999999999',gen,true,true)
  THEN RAISE EXCEPTION 'SYNTHETIC_RECEIPT_REJECTED'; END IF;
END $test$;
RESET SESSION AUTHORIZATION;

SET SESSION AUTHORIZATION fixture_guarded_a;
DO $test$
DECLARE gen bigint; task_status text;
BEGIN
  SELECT current_setting('test.fixture_slot_generation')::bigint INTO gen;
  IF NOT browser_product.finish_guarded_slot(
    'aaaaaaaa-3333-4333-8333-333333333333',
    'aaaaaaaa-9999-4999-8999-999999999999',gen)
  THEN RAISE EXCEPTION 'VERIFIED_SLOT_DID_NOT_CLOSE'; END IF;
  -- The database task state is checked by the independent admin fixture,
  -- since even a tenant broker role cannot select task rows directly.

  IF browser_product.extend_guarded_slot(
    'aaaaaaaa-3333-4333-8333-333333333333',
    'aaaaaaaa-9999-4999-8999-999999999999',gen,300)
  THEN RAISE EXCEPTION 'STALE_LEASE_EXTENDED_AFTER_RELEASE'; END IF;
END $test$;
RESET SESSION AUTHORIZATION;
DO $test$
DECLARE task_status text;
BEGIN
  SELECT state INTO task_status FROM browser_product.browser_tasks
   WHERE tenant_id='11111111-1111-4111-8111-111111111111'
     AND task_id='aaaaaaaa-3333-4333-8333-333333333333';
  IF task_status<>'paused'
  THEN RAISE EXCEPTION 'PROVIDER_RELEASE_FALSELY_MARKED_TASK_DONE'; END IF;
END $test$;

-- Another tenant receives a later generation only after verified release.
SET SESSION AUTHORIZATION fixture_guarded_b;
DO $test$
DECLARE rec record;
BEGIN
  SELECT * INTO rec FROM browser_product.claim_guarded_slot(
    'bbbbbbbb-3333-4333-8333-333333333333',
    'bbbbbbbb-9999-4999-8999-999999999999',300);
  IF rec.status_code<>'new' OR rec.granted IS DISTINCT FROM true
  THEN RAISE EXCEPTION 'SECOND_TENANT_STARVED_AFTER_VERIFIED_RELEASE'; END IF;
  PERFORM set_config('test.fixture_slot_generation',
                     rec.lease_generation::text,false);
END $test$;
RESET SESSION AUTHORIZATION;

-- Test forced expiry in this throwaway database only.
UPDATE browser_slot_guard.slots SET expires_at=clock_timestamp()-interval '1 second'
 WHERE slot_name='steel-main';
SET SESSION AUTHORIZATION fixture_guarded_a;
DO $test$
DECLARE rec record;
BEGIN
  SELECT * INTO rec FROM browser_product.claim_guarded_slot(
    'aaaaaaaa-4444-4444-8444-444444444444',
    'aaaaaaaa-8888-4888-8888-888888888888',300);
  IF rec.status_code<>'quarantined' OR rec.granted IS DISTINCT FROM false
  THEN RAISE EXCEPTION 'EXPIRED_UNVERIFIED_SLOT_REUSED'; END IF;
END $test$;
RESET SESSION AUTHORIZATION;

UPDATE browser_product.login_tenant_bindings SET enabled=false
 WHERE db_role='fixture_guarded_b';
SET SESSION AUTHORIZATION fixture_guarded_b;
DO $test$
DECLARE rec record;
BEGIN
  SELECT * INTO rec FROM browser_product.claim_guarded_slot(
    'bbbbbbbb-3333-4333-8333-333333333333',
    'bbbbbbbb-9999-4999-8999-999999999999',300);
  IF rec.status_code<>'unauthorized' OR rec.granted IS DISTINCT FROM false
  THEN RAISE EXCEPTION 'REVOKED_TENANT_CAN_CLAIM'; END IF;
  IF browser_product.extend_guarded_slot(
    'bbbbbbbb-3333-4333-8333-333333333333',
    'bbbbbbbb-9999-4999-8999-999999999999',
    current_setting('test.fixture_slot_generation')::bigint,300)
  THEN RAISE EXCEPTION 'REVOKED_TENANT_CAN_EXTEND'; END IF;
END $test$;
RESET SESSION AUTHORIZATION;

SELECT 'GUARDED_TENANT_DURABLE_SLOT_PASS' AS proof;
