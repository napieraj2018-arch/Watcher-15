-- 005: reproducible, metadata-only verified cold-backup receipts in Neon STAGING.
-- Applied 2026-10-29 to the existing owner Neon project. Not a vault importer.
-- This file deliberately excludes backup hashes, account identifiers, signed
-- storage URLs, credentials and all private source/ciphertext values.
BEGIN;
CREATE TABLE aib_cold_backup_receipts (
 backup_id uuid PRIMARY KEY,
 observed_at timestamptz NOT NULL,
 verified_at timestamptz NOT NULL,
 private_object_key text NOT NULL CHECK(private_object_key ~ '^2026-[0-9]{2}-[0-9]{2}/source-vault-v[0-9]+[.]jsonl[.]gz$'),
 object_sha256 text NOT NULL CHECK(object_sha256 ~ '^[a-f0-9]{64}$'),
 source_rows_sha256 text NOT NULL CHECK(source_rows_sha256 ~ '^[a-f0-9]{64}$'),
 compressed_bytes bigint NOT NULL CHECK(compressed_bytes>0 AND compressed_bytes<67108864),
 profile_count integer NOT NULL CHECK(profile_count>0),
 archive_count integer NOT NULL CHECK(archive_count>=0),
 engine_count integer NOT NULL CHECK(engine_count>=0),
 task_count integer NOT NULL CHECK(task_count>=0),
 config_count integer NOT NULL CHECK(config_count>=0),
 event_count integer NOT NULL CHECK(event_count>=0),
 protected_archive_count integer NOT NULL CHECK(protected_archive_count>=0),
 neutral_r158_rolling_count integer NOT NULL CHECK(neutral_r158_rolling_count>=0),
 neutral_r158_protected_count integer NOT NULL CHECK(neutral_r158_protected_count>=0),
 imported_to_tables boolean NOT NULL DEFAULT false CHECK(NOT imported_to_tables),
 production_cutover boolean NOT NULL DEFAULT false CHECK(NOT production_cutover),
 UNIQUE(private_object_key,object_sha256)
);
CREATE TRIGGER aib_cold_backup_receipts_immutable
 BEFORE UPDATE OR DELETE ON aib_cold_backup_receipts
 FOR EACH ROW EXECUTE FUNCTION aib_shadow_deny_mutation();
REVOKE ALL ON aib_cold_backup_receipts FROM PUBLIC;
COMMENT ON TABLE aib_cold_backup_receipts IS
 'Immutable metadata evidence only; never proof of operational restore, login or writer cutover.';
COMMIT;
