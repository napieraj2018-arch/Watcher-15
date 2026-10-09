-- Ephemeral PostgreSQL only. No real browser tasks are touched.
\set ON_ERROR_STOP on

SET SESSION AUTHORIZATION fixture_tenant_a;
DO $tests$
DECLARE code text; current text; count_tasks integer; i integer;
BEGIN
  SELECT status_code,current_state INTO code,current
    FROM browser_product.enqueue_task(
     'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
     'aaaaaaaa-0000-4000-8000-000000000001',
     'aaaaaaaa-6666-4666-8666-666666666666');
  IF code<>'existing' OR current<>'queued'
    THEN RAISE EXCEPTION 'IDEMPOTENCY_RETRY_CREATED_TASK'; END IF;

  SELECT status_code INTO code FROM browser_product.enqueue_task(
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    'aaaaaaaa-0000-4000-8000-000000000099',
    'aaaaaaaa-6666-4666-8666-666666666666');
  IF code<>'idempotency_conflict'
    THEN RAISE EXCEPTION 'CONFLICTING_RETRY_NOT_REJECTED'; END IF;

  SELECT status_code INTO code FROM browser_product.enqueue_task(
    'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
    'aaaaaaaa-0000-4000-8000-000000000099', gen_random_uuid());
  IF code<>'profile_not_available'
    THEN RAISE EXCEPTION 'UNREADY_PROFILE_ACCEPTED'; END IF;

  SELECT count(*) INTO count_tasks FROM browser_product.browser_tasks
   WHERE state IN ('queued','running');
  FOR i IN 1..(10-count_tasks) LOOP
    SELECT status_code INTO code FROM browser_product.enqueue_task(
      'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
      'aaaaaaaa-0000-4000-8000-000000000001',gen_random_uuid());
    IF code<>'created' THEN RAISE EXCEPTION 'QUOTA_EARLY_REJECT'; END IF;
  END LOOP;

  SELECT status_code INTO code FROM browser_product.enqueue_task(
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    'aaaaaaaa-0000-4000-8000-000000000001',gen_random_uuid());
  IF code<>'quota_reached'
    THEN RAISE EXCEPTION 'QUOTA_EXCEEDED'; END IF;
  SELECT count(*) INTO count_tasks FROM browser_product.browser_tasks
   WHERE state IN ('queued','running');
  IF count_tasks<>10 THEN RAISE EXCEPTION 'QUOTA_COUNT_WRONG'; END IF;

  -- Arbitrary custom tenant GUC cannot alter session_user.
  PERFORM set_config('app.tenant_id','22222222-2222-4222-8222-222222222222',true);
  SELECT status_code INTO code FROM browser_product.enqueue_task(
    'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
    'bbbbbbbb-0000-4000-8000-000000000002',gen_random_uuid());
  IF code<>'profile_not_available'
    THEN RAISE EXCEPTION 'CUSTOM_GUC_TENANT_SPOOF'; END IF;
END $tests$;
RESET SESSION AUTHORIZATION;

-- Tenant B is intentionally disabled by the base isolation regression.
SET SESSION AUTHORIZATION fixture_tenant_b;
DO $tests$
DECLARE code text;
BEGIN
  SELECT status_code INTO code FROM browser_product.enqueue_task(
    'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
    'bbbbbbbb-0000-4000-8000-000000000002',gen_random_uuid());
  IF code<>'unauthorized'
    THEN RAISE EXCEPTION 'DISABLED_TENANT_ENQUEUED'; END IF;
END $tests$;
RESET SESSION AUTHORIZATION;
SELECT 'TENANT_QUEUE_QUOTA_SERIAL_PASS' AS proof;
