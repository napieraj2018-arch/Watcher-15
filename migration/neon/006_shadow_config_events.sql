-- 006: complete private source-recovery staging with CONFIG + EVENTS.
-- Run on the EMPTY Neon STAGING branch only, never against original Floot.
-- No source values, credentials or ciphertext are embedded in this file.
-- This does not enable a production writer or grant an import role.
BEGIN;
CREATE TABLE aib_shadow_config_values (
 batch_id uuid NOT NULL,
 config_key text NOT NULL CHECK(length(config_key) BETWEEN 1 AND 150),
 config_value text NOT NULL CHECK(octet_length(config_value) BETWEEN 1 AND 1048576),
 source_sha256 text NOT NULL CHECK(source_sha256 ~ '^[a-f0-9]{64}$'),
 received_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(batch_id,config_key)
);
CREATE FUNCTION aib_shadow_put_config(p_batch uuid,p_key text,p_value text,p_sha text)
 RETURNS boolean LANGUAGE plpgsql SECURITY INVOKER AS $body$
 DECLARE inserted boolean; old_row aib_shadow_config_values%ROWTYPE;
 BEGIN
  IF (SELECT mode FROM vault_migration_guard WHERE only_row)
     IS DISTINCT FROM 'staging_read_only'
    OR (SELECT write_enabled FROM vault_migration_guard WHERE only_row)
     IS DISTINCT FROM false THEN
   RAISE EXCEPTION 'AIB_SHADOW_MODE_UNCONFIRMED' USING ERRCODE='42501';
  END IF;
  IF p_batch IS NULL OR p_key IS NULL OR length(p_key) NOT BETWEEN 1 AND 150
    OR p_value IS NULL OR octet_length(p_value) NOT BETWEEN 1 AND 1048576
    OR p_sha IS NULL OR p_sha !~ '^[a-f0-9]{64}$'
    OR encode(digest(convert_to(p_value,'UTF8'),'sha256'),'hex')<>p_sha THEN
    RAISE EXCEPTION 'AIB_SHADOW_CONFIG_INVALID' USING ERRCODE='22023';
  END IF;
  INSERT INTO aib_shadow_config_values(batch_id,config_key,config_value,source_sha256)
    VALUES(p_batch,p_key,p_value,p_sha)
    ON CONFLICT DO NOTHING RETURNING true INTO inserted;
  IF inserted THEN RETURN true; END IF;
  SELECT * INTO old_row FROM aib_shadow_config_values WHERE batch_id=p_batch AND config_key=p_key;
  IF NOT FOUND OR old_row.config_value<>p_value OR old_row.source_sha256<>p_sha THEN
   RAISE EXCEPTION 'AIB_SHADOW_CONFIG_CONFLICT' USING ERRCODE='23505';
  END IF;
  RETURN false;
 END; $body$;
CREATE TRIGGER aib_shadow_config_immutable BEFORE UPDATE OR DELETE ON aib_shadow_config_values FOR EACH ROW EXECUTE FUNCTION aib_shadow_deny_mutation();
CREATE TABLE aib_shadow_profile_events (
 batch_id uuid NOT NULL,
 source_id bigint NOT NULL CHECK(source_id>0),
 profile_name text NOT NULL CHECK(length(profile_name) BETWEEN 1 AND 150),
 event_type text NOT NULL CHECK(length(event_type) BETWEEN 1 AND 150),
 source_created_text text NOT NULL CHECK(length(source_created_text) BETWEEN 20 AND 60),
 source_created_at timestamptz NOT NULL,
 source_sha256 text NOT NULL CHECK(source_sha256 ~ '^[a-f0-9]{64}$'),
 received_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(batch_id,source_id)
);
CREATE FUNCTION aib_shadow_put_event(p_batch uuid,p_id bigint,p_profile text,p_type text,p_created_text text,p_sha text)
 RETURNS boolean LANGUAGE plpgsql SECURITY INVOKER AS $body$
 DECLARE inserted boolean; old_row aib_shadow_profile_events%ROWTYPE;
 BEGIN
  IF (SELECT mode FROM vault_migration_guard WHERE only_row)
     IS DISTINCT FROM 'staging_read_only'
    OR (SELECT write_enabled FROM vault_migration_guard WHERE only_row)
     IS DISTINCT FROM false THEN
   RAISE EXCEPTION 'AIB_SHADOW_MODE_UNCONFIRMED' USING ERRCODE='42501';
  END IF;
  IF p_batch IS NULL OR p_id IS NULL OR p_id<=0 OR p_profile IS NULL
    OR length(p_profile) NOT BETWEEN 1 AND 150
    OR p_type IS NULL OR length(p_type) NOT BETWEEN 1 AND 150
    OR p_created_text IS NULL OR length(p_created_text) NOT BETWEEN 20 AND 60
    OR p_sha IS NULL OR p_sha !~ '^[a-f0-9]{64}$'
    OR encode(digest(convert_to(
         p_id::text||chr(31)||p_profile||chr(31)||p_type||chr(31)||p_created_text,
         'UTF8'),'sha256'),'hex')<>p_sha THEN
    RAISE EXCEPTION 'AIB_SHADOW_EVENT_INVALID' USING ERRCODE='22023';
  END IF;
  INSERT INTO aib_shadow_profile_events(batch_id,source_id,profile_name,event_type,
    source_created_text,source_created_at,source_sha256)
  VALUES(p_batch,p_id,p_profile,p_type,p_created_text,p_created_text::timestamptz,p_sha)
  ON CONFLICT DO NOTHING RETURNING true INTO inserted;
  IF inserted THEN RETURN true; END IF;
  SELECT * INTO old_row FROM aib_shadow_profile_events
    WHERE batch_id=p_batch AND source_id=p_id;
  IF NOT FOUND OR old_row.profile_name<>p_profile OR old_row.event_type<>p_type
    OR old_row.source_created_text<>p_created_text OR old_row.source_sha256<>p_sha THEN
    RAISE EXCEPTION 'AIB_SHADOW_EVENT_CONFLICT' USING ERRCODE='23505';
  END IF;
  RETURN false;
 END; $body$;
CREATE TRIGGER aib_shadow_event_immutable BEFORE UPDATE OR DELETE ON aib_shadow_profile_events FOR EACH ROW EXECUTE FUNCTION aib_shadow_deny_mutation();
REVOKE ALL ON aib_shadow_config_values,aib_shadow_profile_events FROM PUBLIC;
REVOKE ALL ON FUNCTION aib_shadow_put_config(uuid,text,text,text) FROM PUBLIC;
REVOKE ALL ON FUNCTION aib_shadow_put_event(uuid,bigint,text,text,text,text) FROM PUBLIC;
COMMENT ON TABLE aib_shadow_profile_events IS 'Staging-only immutable original event sequence; never an active browser writer';
COMMENT ON TABLE aib_shadow_config_values IS 'Staging-only private exact config values; restricted importer role required';
COMMIT;
