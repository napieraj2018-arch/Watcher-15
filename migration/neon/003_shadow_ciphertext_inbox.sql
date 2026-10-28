-- Neon-only immutable ciphertext transfer inbox, NOT a production vault writer.
-- Requires pgcrypto for byte-exact SHA256; always preserve source ciphertext.
BEGIN;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE TABLE aib_shadow_ciphertext_inbox(
 batch_id uuid NOT NULL,
 source_kind text NOT NULL CHECK(source_kind IN ('profile','archive','task')),
 source_key text NOT NULL CHECK(length(source_key) BETWEEN 1 AND 150),
 encrypted_state text NOT NULL CHECK(octet_length(encrypted_state) BETWEEN 20 AND 8000000),
 source_updated_at timestamptz NOT NULL,
 source_sha256 text NOT NULL CHECK(source_sha256 ~ '^[a-f0-9]{64}$'),
 source_metadata jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(
    jsonb_typeof(source_metadata)='object' AND octet_length(source_metadata::text)<=4096),
 received_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(batch_id,source_kind,source_key)
);
CREATE FUNCTION aib_shadow_put_encrypted(
 p_batch uuid,p_kind text,p_key text,p_state text,p_timestamp timestamptz,
 p_sha text,p_metadata jsonb DEFAULT '{}'::jsonb
) RETURNS boolean LANGUAGE plpgsql SECURITY INVOKER AS $body$
DECLARE current_row aib_shadow_ciphertext_inbox%ROWTYPE; inserted boolean;
BEGIN
 IF (SELECT mode FROM vault_migration_guard WHERE only_row) IS DISTINCT FROM 'staging_read_only'
    OR (SELECT write_enabled FROM vault_migration_guard WHERE only_row) IS DISTINCT FROM false THEN
   RAISE EXCEPTION 'AIB_SHADOW_MODE_UNCONFIRMED' USING ERRCODE='42501';
 END IF;
 IF p_batch IS NULL OR p_kind NOT IN ('profile','archive','task')
   OR p_key IS NULL OR length(p_key) NOT BETWEEN 1 AND 150
   OR p_state IS NULL OR octet_length(p_state) NOT BETWEEN 20 AND 8000000
   OR p_timestamp IS NULL OR p_sha IS NULL OR p_sha !~ '^[a-f0-9]{64}$'
   OR p_metadata IS NULL OR jsonb_typeof(p_metadata) IS DISTINCT FROM 'object'
   OR octet_length(p_metadata::text)>4096 THEN
   RAISE EXCEPTION 'AIB_SHADOW_INPUT_INVALID' USING ERRCODE='22023';
 END IF;
 IF encode(digest(convert_to(p_state,'UTF8'),'sha256'),'hex')<>p_sha THEN
   RAISE EXCEPTION 'AIB_SHADOW_SHA256_MISMATCH' USING ERRCODE='22023';
 END IF;
 INSERT INTO aib_shadow_ciphertext_inbox(batch_id,source_kind,source_key,encrypted_state,
  source_updated_at,source_sha256,source_metadata)
 VALUES(p_batch,p_kind,p_key,p_state,p_timestamp,p_sha,p_metadata)
 ON CONFLICT DO NOTHING RETURNING true INTO inserted;
 IF inserted THEN RETURN true; END IF;
 SELECT * INTO current_row FROM aib_shadow_ciphertext_inbox
  WHERE batch_id=p_batch AND source_kind=p_kind AND source_key=p_key;
 IF NOT FOUND OR current_row.source_sha256<>p_sha
  OR current_row.encrypted_state<>p_state
  OR current_row.source_updated_at<>p_timestamp
  OR current_row.source_metadata<>p_metadata THEN
   RAISE EXCEPTION 'AIB_SHADOW_IMPORT_CONFLICT' USING ERRCODE='23505';
 END IF;
 RETURN false;
END;
$body$;
CREATE TRIGGER aib_shadow_ciphertext_immutable
 BEFORE UPDATE OR DELETE ON aib_shadow_ciphertext_inbox
 FOR EACH ROW EXECUTE FUNCTION aib_shadow_deny_mutation();
COMMENT ON TABLE aib_shadow_ciphertext_inbox IS
 'STAGING ONLY. Encrypted historical snapshots. Immutable; never a second active profile writer.';
COMMIT;
