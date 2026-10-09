-- Synthetic isolation tests in an EPHEMERAL PostgreSQL CI database only.
-- Fixed fake UUIDs/role names. Do not use against user profiles.
\set ON_ERROR_STOP on

CREATE ROLE fixture_tenant_a LOGIN IN ROLE browser_product_client;
CREATE ROLE fixture_tenant_b LOGIN IN ROLE browser_product_client;

INSERT INTO browser_product.tenants(tenant_id)
VALUES
 ('11111111-1111-4111-8111-111111111111'),
 ('22222222-2222-4222-8222-222222222222');

INSERT INTO browser_product.login_tenant_bindings(db_role,tenant_id)
VALUES
 ('fixture_tenant_a','11111111-1111-4111-8111-111111111111'),
 ('fixture_tenant_b','22222222-2222-4222-8222-222222222222');

INSERT INTO browser_product.workspaces(tenant_id,workspace_id,display_name)
VALUES
 ('11111111-1111-4111-8111-111111111111','aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa','Clinic A'),
 ('22222222-2222-4222-8222-222222222222','bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb','Clinic B');

INSERT INTO browser_product.profiles(tenant_id,workspace_id,profile_id,display_name,status,provider_profile_ref)
VALUES
 ('11111111-1111-4111-8111-111111111111','aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
  'aaaaaaaa-0000-4000-8000-000000000001','TEST-ONLY A','ready',
  'aaaaaaaa-1111-4111-8111-111111111111'),
 ('22222222-2222-4222-8222-222222222222','bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
  'bbbbbbbb-0000-4000-8000-000000000002','TEST-ONLY B','ready',
  'bbbbbbbb-2222-4222-8222-222222222222');

INSERT INTO browser_product.browser_tasks(tenant_id,workspace_id,profile_id,task_id,state)
VALUES
 ('11111111-1111-4111-8111-111111111111','aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
  'aaaaaaaa-0000-4000-8000-000000000001','aaaaaaaa-3333-4333-8333-333333333333','queued'),
 ('22222222-2222-4222-8222-222222222222','bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
  'bbbbbbbb-0000-4000-8000-000000000002','bbbbbbbb-4444-4444-8444-444444444444','queued');

SET SESSION AUTHORIZATION fixture_tenant_a;

DO $test$
DECLARE got int; touched int; identity uuid; queue_code text; task_state text;
BEGIN
  SELECT browser_product.authenticated_tenant() INTO identity;
  IF identity IS DISTINCT FROM '11111111-1111-4111-8111-111111111111'::uuid
  THEN RAISE EXCEPTION 'A_BOUND_IDENTITY_NOT_VERIFIED'; END IF;

  SELECT count(*) INTO got FROM browser_product.workspaces;
  IF got<>1 THEN RAISE EXCEPTION 'A_WORKSPACE_LEAK'; END IF;
  SELECT count(*) INTO got FROM browser_product.profiles;
  IF got<>1 THEN RAISE EXCEPTION 'A_PROFILE_LEAK'; END IF;
  SELECT count(*) INTO got FROM browser_product.browser_tasks;
  IF got<>1 THEN RAISE EXCEPTION 'A_TASK_LEAK'; END IF;

  -- An attacker can manipulate custom GUCs via SQL injection, so RLS identity
  -- must never trust app.tenant_id or a frontend-supplied tenant identifier.
  PERFORM set_config('app.tenant_id',
     '22222222-2222-4222-8222-222222222222',true);
  IF browser_product.authenticated_tenant() IS DISTINCT FROM identity
  THEN RAISE EXCEPTION 'SPOOFABLE_TENANT_GUC'; END IF;

  UPDATE browser_product.profiles SET display_name='ATTACK'
   WHERE tenant_id='22222222-2222-4222-8222-222222222222';
  GET DIAGNOSTICS touched=ROW_COUNT;
  IF touched<>0 THEN RAISE EXCEPTION 'A_MODIFIED_B_PROFILE'; END IF;

  BEGIN
    INSERT INTO browser_product.workspaces(tenant_id,workspace_id,display_name)
    VALUES('22222222-2222-4222-8222-222222222222',
           'cccccccc-0000-4000-8000-000000000000','MALICIOUS');
    RAISE EXCEPTION 'A_INSERTED_B_WORKSPACE';
  EXCEPTION WHEN insufficient_privilege THEN
    NULL;
  END;

  BEGIN
    PERFORM provider_profile_ref
    FROM browser_product.profiles LIMIT 1;
    RAISE EXCEPTION 'A_READ_STEEL_PROVIDER_SECRET';
  EXCEPTION WHEN insufficient_privilege THEN
    NULL;
  END;

  BEGIN
    DELETE FROM browser_product.profiles
     WHERE tenant_id='11111111-1111-4111-8111-111111111111';
    RAISE EXCEPTION 'A_DELETED_RAW_PROFILE_WITHOUT_PROVIDER_WIPE';
  EXCEPTION WHEN insufficient_privilege THEN
    NULL;
  END;

  IF has_table_privilege(session_user,'browser_product.login_tenant_bindings','SELECT')
  THEN RAISE EXCEPTION 'A_COULD_READ_ROLE_BINDINGS'; END IF;
  -- Task states are server-authoritative. The client cannot inject
  -- running/done at INSERT nor alter an existing task state after enqueue.
  IF has_column_privilege(session_user,'browser_product.browser_tasks','state','INSERT')
     OR has_column_privilege(session_user,'browser_product.browser_tasks','state','UPDATE')
  THEN RAISE EXCEPTION 'A_CLIENT_HAS_LIFECYCLE_PRIVILEGES'; END IF;

  BEGIN
    UPDATE browser_product.browser_tasks SET state='done'
     WHERE tenant_id='11111111-1111-4111-8111-111111111111';
    RAISE EXCEPTION 'A_SPOOFED_TASK_DONE';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
  BEGIN
    INSERT INTO browser_product.browser_tasks(
      tenant_id,workspace_id,task_id,profile_id,state)
    VALUES('11111111-1111-4111-8111-111111111111',
      'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
      'aaaaaaaa-5555-4555-8555-555555555555',
      'aaaaaaaa-0000-4000-8000-000000000001','running');
    RAISE EXCEPTION 'A_CREATED_FALSE_RUNNING_TASK';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
  -- Direct table INSERT is forbidden even for a client's own profile.
  BEGIN
    INSERT INTO browser_product.browser_tasks(
      tenant_id,workspace_id,task_id,profile_id)
    VALUES('11111111-1111-4111-8111-111111111111',
      'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
      'aaaaaaaa-7777-4777-8777-777777777777',
      'aaaaaaaa-0000-4000-8000-000000000001');
    RAISE EXCEPTION 'CLIENT_BYPASSED_QUEUE_QUOTA';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
  -- Only a verified DB login can call the quota-enforcing enqueue function.
  SELECT status_code,current_state INTO queue_code,task_state
    FROM browser_product.enqueue_task(
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    'aaaaaaaa-0000-4000-8000-000000000001',
    'aaaaaaaa-6666-4666-8666-666666666666');
  IF queue_code<>'created' OR task_state<>'queued'
  THEN RAISE EXCEPTION 'OWN_TASK_NOT_QUEUED'; END IF;

  -- The tenant may only create its own workspace/profile.
  INSERT INTO browser_product.workspaces(tenant_id,workspace_id,display_name)
  VALUES('11111111-1111-4111-8111-111111111111',
         'cccccccc-cccc-4ccc-8ccc-cccccccccccc','Owned A Extra');
  INSERT INTO browser_product.profiles(tenant_id,workspace_id,profile_id,display_name)
  VALUES('11111111-1111-4111-8111-111111111111',
         'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
         'aaaaaaaa-0000-4000-8000-000000000099','Own profile');
  SELECT count(*) INTO got FROM browser_product.profiles;
  IF got<>2 THEN RAISE EXCEPTION 'A_COULD_NOT_CREATE_OWN_PROFILE'; END IF;

  SELECT status_code INTO queue_code FROM browser_product.enqueue_task(
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    'bbbbbbbb-0000-4000-8000-000000000002',
    'aaaaaaaa-5555-4555-8555-555555555555');
  IF queue_code<>'profile_not_available'
  THEN RAISE EXCEPTION 'CROSS_TENANT_PROFILE_BOUND_TO_TASK'; END IF;
END
$test$;

RESET SESSION AUTHORIZATION;
SET SESSION AUTHORIZATION fixture_tenant_b;

DO $test$
DECLARE got int; identity uuid;
BEGIN
  SELECT browser_product.authenticated_tenant() INTO identity;
  IF identity IS DISTINCT FROM '22222222-2222-4222-8222-222222222222'::uuid
  THEN RAISE EXCEPTION 'B_BOUND_IDENTITY_NOT_VERIFIED'; END IF;
  SELECT count(*) INTO got FROM browser_product.profiles;
  IF got<>1 THEN RAISE EXCEPTION 'B_PROFILE_LEAK'; END IF;
  SELECT count(*) INTO got FROM browser_product.browser_tasks;
  IF got<>1 THEN RAISE EXCEPTION 'B_TASK_LEAK'; END IF;
  SELECT count(*) INTO got FROM browser_product.workspaces;
  IF got<>1 THEN RAISE EXCEPTION 'B_WORKSPACE_LEAK'; END IF;
END
$test$;

RESET SESSION AUTHORIZATION;

UPDATE browser_product.login_tenant_bindings SET enabled=false
 WHERE db_role='fixture_tenant_b';
SET SESSION AUTHORIZATION fixture_tenant_b;

DO $test$
DECLARE got int;
BEGIN
  IF browser_product.authenticated_tenant() IS NOT NULL
  THEN RAISE EXCEPTION 'DISABLED_TENANT_STILL_AUTHENTICATED'; END IF;
  SELECT count(*) INTO got FROM browser_product.profiles;
  IF got<>0 THEN RAISE EXCEPTION 'DISABLED_TENANT_CAN_READ_PROFILES'; END IF;
END
$test$;

RESET SESSION AUTHORIZATION;
SELECT 'TENANT_RLS_ISOLATION_TESTS_PASS' AS test_status;
