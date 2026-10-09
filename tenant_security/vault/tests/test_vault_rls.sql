-- Synthetic, ephemeral PostgreSQL 16 ONLY. No real browser profile data.
\set ON_ERROR_STOP on

CREATE ROLE fixture_vault_a LOGIN IN ROLE browser_vault_worker;
CREATE ROLE fixture_vault_b LOGIN IN ROLE browser_vault_worker;

INSERT INTO browser_product.login_tenant_bindings(db_role,tenant_id,enabled)
VALUES ('fixture_vault_a','11111111-1111-4111-8111-111111111111',true),
       ('fixture_vault_b','22222222-2222-4222-8222-222222222222',true);

SET SESSION AUTHORIZATION fixture_vault_a;
DO $verify$
DECLARE code text; revision bigint; seen integer;
BEGIN
  IF browser_product.authenticated_tenant()
     IS DISTINCT FROM '11111111-1111-4111-8111-111111111111'::uuid
  THEN RAISE EXCEPTION 'WRONG_VAULT_A_TENANT'; END IF;

  SELECT status_code,stored_revision INTO code,revision
  FROM browser_product.append_encrypted_profile(
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    'aaaaaaaa-0000-4000-8000-000000000001',
    0, 'test-key-a', decode(repeat('aa',12),'hex'),
    decode(repeat('cc',40),'hex'));
  IF code<>'created' OR revision<>1
  THEN RAISE EXCEPTION 'VAULT_A_INSERT_FAILED'; END IF;

  SELECT count(*) INTO seen FROM browser_product.profile_versions_secure;
  IF seen<>1 THEN RAISE EXCEPTION 'VAULT_A_OWN_READ_FAILED'; END IF;

  SELECT status_code INTO code FROM browser_product.append_encrypted_profile(
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    'aaaaaaaa-0000-4000-8000-000000000001',
    0,'test-key-a',decode(repeat('ab',12),'hex'),decode(repeat('cd',40),'hex'));
  IF code<>'revision_conflict'
  THEN RAISE EXCEPTION 'DUPLICATE_REVISION_NOT_REJECTED'; END IF;

  SELECT status_code INTO code FROM browser_product.append_encrypted_profile(
    'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
    'bbbbbbbb-0000-4000-8000-000000000002',
    0,'test-key-a',decode(repeat('ad',12),'hex'),decode(repeat('ce',40),'hex'));
  IF code<>'profile_not_available'
  THEN RAISE EXCEPTION 'CROSS_TENANT_PROFILE_WRITE_ACCEPTED'; END IF;

  SELECT status_code INTO code FROM browser_product.append_encrypted_profile(
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    'aaaaaaaa-0000-4000-8000-000000000001',
    1,'invalid key with spaces',decode(repeat('ad',12),'hex'),decode(repeat('ce',40),'hex'));
  IF code<>'invalid_request' THEN RAISE EXCEPTION 'INVALID_KEY_ID_ACCEPTED'; END IF;

  BEGIN
    INSERT INTO browser_product.profile_versions_secure(
      tenant_id,workspace_id,profile_id,revision,key_id,nonce,encrypted_state
    ) VALUES (
      '11111111-1111-4111-8111-111111111111',
      'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
      'aaaaaaaa-0000-4000-8000-000000000001',
      2, 'test-key-a',
      decode(repeat('ae',12),'hex'),decode(repeat('cd',40),'hex'));
    RAISE EXCEPTION 'VAULT_WRITER_BYPASSED_APPEND_GUARD';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;

  BEGIN
    UPDATE browser_product.profile_versions_secure
       SET encrypted_state=decode(repeat('ef',40),'hex');
    RAISE EXCEPTION 'VAULT_WRITER_OVERWROTE_IMMUTABLE_HISTORY';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;

  BEGIN
    DELETE FROM browser_product.profile_versions_secure;
    RAISE EXCEPTION 'VAULT_WRITER_DELETED_HISTORY_WITHOUT_ERASURE';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
END $verify$;
RESET SESSION AUTHORIZATION;

SET SESSION AUTHORIZATION fixture_vault_b;
DO $verify$
DECLARE code text; revision bigint; seen integer;
BEGIN
  SELECT count(*) INTO seen FROM browser_product.profile_versions_secure;
  IF seen<>0 THEN RAISE EXCEPTION 'B_CAN_READ_A_ENCRYPTED_HISTORY'; END IF;
  SELECT status_code,stored_revision INTO code,revision
  FROM browser_product.append_encrypted_profile(
    'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
    'bbbbbbbb-0000-4000-8000-000000000002',
    0,'test-key-b',decode(repeat('bb',12),'hex'),decode(repeat('dd',40),'hex'));
  IF code<>'created' OR revision<>1
  THEN RAISE EXCEPTION 'VAULT_B_INSERT_FAILED'; END IF;
  SELECT count(*) INTO seen FROM browser_product.profile_versions_secure;
  IF seen<>1 THEN RAISE EXCEPTION 'VAULT_B_RLS_FAILED'; END IF;
END $verify$;
RESET SESSION AUTHORIZATION;

-- Metadata BFF's tenant DB login cannot read ciphertext or bypass vault role.
SET SESSION AUTHORIZATION fixture_tenant_a;
DO $verify$
BEGIN
  BEGIN
    PERFORM encrypted_state FROM browser_product.profile_versions_secure LIMIT 1;
    RAISE EXCEPTION 'BFF_CLIENT_READ_RAW_PROFILE_BLOB';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
  BEGIN
    PERFORM browser_product.append_encrypted_profile(
       'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
       'aaaaaaaa-0000-4000-8000-000000000001', 1,
       'test-key-a',decode(repeat('ab',12),'hex'),decode(repeat('bc',40),'hex'));
    RAISE EXCEPTION 'BFF_CLIENT_CALLED_VAULT_WRITER';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
END $verify$;
RESET SESSION AUTHORIZATION;

UPDATE browser_product.login_tenant_bindings SET enabled=false
 WHERE db_role='fixture_vault_b';
SET SESSION AUTHORIZATION fixture_vault_b;
DO $verify$
DECLARE code text; seen integer;
BEGIN
  SELECT count(*) INTO seen FROM browser_product.profile_versions_secure;
  IF seen<>0 THEN RAISE EXCEPTION 'DISABLED_VAULT_ROLE_CAN_READ'; END IF;
  SELECT status_code INTO code FROM browser_product.append_encrypted_profile(
    'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
    'bbbbbbbb-0000-4000-8000-000000000002',
    1,'test-key-b',decode(repeat('bc',12),'hex'),decode(repeat('de',40),'hex'));
  IF code<>'unauthorized'
  THEN RAISE EXCEPTION 'DISABLED_VAULT_ROLE_CAN_APPEND'; END IF;
END $verify$;
RESET SESSION AUTHORIZATION;
UPDATE browser_product.login_tenant_bindings SET enabled=true
 WHERE db_role='fixture_vault_b';

SELECT 'TENANT_ENCRYPTED_PROFILE_RLS_PASS' AS proof;
