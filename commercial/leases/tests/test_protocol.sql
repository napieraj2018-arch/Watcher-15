-- Run exclusively on ephemeral PostgreSQL 16 with a fixture database.
\set ON_ERROR_STOP on
CREATE ROLE fixture_slot_worker LOGIN IN ROLE aib_slot_worker;
CREATE ROLE fixture_slot_verifier LOGIN IN ROLE aib_slot_verifier;

SET SESSION AUTHORIZATION fixture_slot_worker;
DO $test$
DECLARE rec record;
BEGIN
  SELECT * INTO rec FROM browser_slot_guard.claim_slot(
    '11111111-1111-4111-8111-111111111111',
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    'aaaaaaaa-1111-4111-8111-111111111111',300);
  IF rec.granted IS DISTINCT FROM true OR rec.should_start IS DISTINCT FROM true
     OR rec.lease_generation <> 1 THEN RAISE EXCEPTION 'FIRST_CLAIM_FAILED'; END IF;
  SELECT * INTO rec FROM browser_slot_guard.claim_slot(
    '11111111-1111-4111-8111-111111111111',
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    'aaaaaaaa-1111-4111-8111-111111111111',300);
  IF rec.granted IS DISTINCT FROM true OR rec.should_start IS DISTINCT FROM false
     OR rec.status_code <> 'existing' THEN RAISE EXCEPTION 'RETRY_CREATED_EXTRA_SESSION'; END IF;
  SELECT * INTO rec FROM browser_slot_guard.claim_slot(
    '22222222-2222-4222-8222-222222222222',
    'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
    'bbbbbbbb-2222-4222-8222-222222222222',300);
  IF rec.granted IS DISTINCT FROM false OR rec.status_code <> 'busy'
  THEN RAISE EXCEPTION 'CROSS_TENANT_DOUBLE_CLAIM'; END IF;

  IF browser_slot_guard.activate_slot(
    '22222222-2222-4222-8222-222222222222',
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    'aaaaaaaa-1111-4111-8111-111111111111',1)
  THEN RAISE EXCEPTION 'TENANT_B_ACTIVATED_A'; END IF;
  IF browser_slot_guard.activate_slot(
    '11111111-1111-4111-8111-111111111111',
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    'aaaaaaaa-1111-4111-8111-111111111111',2)
  THEN RAISE EXCEPTION 'OLD_GENERATION_ACTIVATED'; END IF;
  IF NOT browser_slot_guard.activate_slot(
    '11111111-1111-4111-8111-111111111111',
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    'aaaaaaaa-1111-4111-8111-111111111111',1)
  THEN RAISE EXCEPTION 'OWNER_ACTIVATE_FAILED'; END IF;

  BEGIN
    PERFORM * FROM browser_slot_guard.slots;
    RAISE EXCEPTION 'RAW_SLOT_TABLE_VISIBLE_TO_WORKER';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
  BEGIN
    PERFORM browser_slot_guard.record_verified_release(
      'aaaaaaaa-1111-4111-8111-111111111111',1,true,true);
    RAISE EXCEPTION 'WORKER_FORGED_RELEASE_RECEIPT';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
  IF browser_slot_guard.finish_slot(
    '11111111-1111-4111-8111-111111111111',
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    'aaaaaaaa-1111-4111-8111-111111111111',1)
  THEN RAISE EXCEPTION 'RELEASED_WITHOUT_RECEIPT'; END IF;
  IF NOT browser_slot_guard.begin_close(
    '11111111-1111-4111-8111-111111111111',
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    'aaaaaaaa-1111-4111-8111-111111111111',1)
  THEN RAISE EXCEPTION 'BEGIN_CLOSE_FAILED'; END IF;
  IF browser_slot_guard.finish_slot(
    '11111111-1111-4111-8111-111111111111',
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    'aaaaaaaa-1111-4111-8111-111111111111',1)
  THEN RAISE EXCEPTION 'CLOSE_WITHOUT_RECEIPT'; END IF;
END $test$;

RESET SESSION AUTHORIZATION;
SET SESSION AUTHORIZATION fixture_slot_verifier;
DO $test$
BEGIN
  IF browser_slot_guard.record_verified_release(
    'aaaaaaaa-1111-4111-8111-111111111111',1,false,true)
  THEN RAISE EXCEPTION 'PARTIAL_RECEIPT_ACCEPTED'; END IF;
  IF NOT browser_slot_guard.record_verified_release(
    'aaaaaaaa-1111-4111-8111-111111111111',1,true,true)
  THEN RAISE EXCEPTION 'COMPLETE_RECEIPT_REJECTED'; END IF;
END $test$;

RESET SESSION AUTHORIZATION;
SET SESSION AUTHORIZATION fixture_slot_worker;
DO $test$
DECLARE rec record;
BEGIN
  IF browser_slot_guard.finish_slot(
    '22222222-2222-4222-8222-222222222222',
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    'aaaaaaaa-1111-4111-8111-111111111111',1)
  THEN RAISE EXCEPTION 'TENANT_B_FINISHED_A'; END IF;
  IF NOT browser_slot_guard.finish_slot(
    '11111111-1111-4111-8111-111111111111',
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    'aaaaaaaa-1111-4111-8111-111111111111',1)
  THEN RAISE EXCEPTION 'OWNER_FINISH_FAILED'; END IF;
  SELECT * INTO rec FROM browser_slot_guard.claim_slot(
    '22222222-2222-4222-8222-222222222222',
    'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
    'bbbbbbbb-2222-4222-8222-222222222222',300);
  IF rec.granted IS DISTINCT FROM true OR rec.should_start IS DISTINCT FROM true
     OR rec.lease_generation<>2 THEN RAISE EXCEPTION 'NEW_EPOCH_NOT_INCREMENTED'; END IF;
  IF browser_slot_guard.extend_slot(
    '11111111-1111-4111-8111-111111111111',
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    'aaaaaaaa-1111-4111-8111-111111111111',1,300)
  THEN RAISE EXCEPTION 'STALE_LEASE_RENEWED'; END IF;
END $test$;

RESET SESSION AUTHORIZATION;
-- Fast-forward is allowed ONLY inside throwaway CI DB, not customer DB.
UPDATE browser_slot_guard.slots SET expires_at=clock_timestamp()-interval '1 second'
 WHERE slot_name='steel-main';
SET SESSION AUTHORIZATION fixture_slot_worker;
DO $test$
DECLARE rec record;
BEGIN
  IF browser_slot_guard.extend_slot(
    '22222222-2222-4222-8222-222222222222',
    'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
    'bbbbbbbb-2222-4222-8222-222222222222',2,300)
  THEN RAISE EXCEPTION 'EXPIRED_OWNER_RENEWED'; END IF;
  SELECT * INTO rec FROM browser_slot_guard.claim_slot(
    '33333333-3333-4333-8333-333333333333',
    'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
    'cccccccc-3333-4333-8333-333333333333',300);
  IF rec.granted IS DISTINCT FROM false OR rec.status_code <> 'quarantined'
  THEN RAISE EXCEPTION 'EXPIRED_SLOT_REUSED'; END IF;
END $test$;

RESET SESSION AUTHORIZATION;
SET SESSION AUTHORIZATION fixture_slot_verifier;
DO $test$
BEGIN
  IF NOT browser_slot_guard.record_verified_release(
    'bbbbbbbb-2222-4222-8222-222222222222',2,true,true)
  THEN RAISE EXCEPTION 'QUARANTINE_VERIFICATION_FAILED'; END IF;
END $test$;
RESET SESSION AUTHORIZATION;
SET SESSION AUTHORIZATION fixture_slot_worker;
DO $test$
DECLARE rec record;
BEGIN
  IF NOT browser_slot_guard.finish_slot(
    '22222222-2222-4222-8222-222222222222',
    'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
    'bbbbbbbb-2222-4222-8222-222222222222',2)
  THEN RAISE EXCEPTION 'VERIFIED_QUARANTINE_DID_NOT_CLEAR'; END IF;
  SELECT * INTO rec FROM browser_slot_guard.claim_slot(
    '33333333-3333-4333-8333-333333333333',
    'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
    'cccccccc-3333-4333-8333-333333333333',300);
  IF rec.granted IS DISTINCT FROM true OR rec.lease_generation<>3
  THEN RAISE EXCEPTION 'THIRD_GENERATION_FAILED'; END IF;
END $test$;
RESET SESSION AUTHORIZATION;
SELECT 'DURABLE_LEASE_LINEAR_CASES_PASS' AS proof;
