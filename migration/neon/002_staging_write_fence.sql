-- Exact isolated Neon staging only: cannot mutate any live-shaped vault table.
-- Never run against Floot production. No security definer, no tokens or cookies.
BEGIN;
CREATE FUNCTION aib_shadow_deny_mutation() RETURNS trigger
  LANGUAGE plpgsql SECURITY INVOKER AS $body$
BEGIN
  RAISE EXCEPTION 'AIB_SHADOW_READ_ONLY' USING ERRCODE='42501';
END;
$body$;
CREATE TRIGGER aib_deny_profile_writes
 BEFORE INSERT OR UPDATE OR DELETE ON browser_profiles
 FOR EACH ROW EXECUTE FUNCTION aib_shadow_deny_mutation();
CREATE TRIGGER aib_deny_archive_writes
 BEFORE INSERT OR UPDATE OR DELETE ON browser_profile_versions
 FOR EACH ROW EXECUTE FUNCTION aib_shadow_deny_mutation();
CREATE TRIGGER aib_deny_engine_writes
 BEFORE INSERT OR UPDATE OR DELETE ON browser_engine_profiles
 FOR EACH ROW EXECUTE FUNCTION aib_shadow_deny_mutation();
CREATE TRIGGER aib_deny_task_writes
 BEFORE INSERT OR UPDATE OR DELETE ON browser_task_checkpoints
 FOR EACH ROW EXECUTE FUNCTION aib_shadow_deny_mutation();
CREATE TRIGGER aib_deny_lease_writes
 BEFORE INSERT OR UPDATE OR DELETE ON browser_control_leases
 FOR EACH ROW EXECUTE FUNCTION aib_shadow_deny_mutation();
CREATE TRIGGER aib_deny_events_writes
 BEFORE INSERT OR UPDATE OR DELETE ON browser_profile_events
 FOR EACH ROW EXECUTE FUNCTION aib_shadow_deny_mutation();
CREATE TRIGGER aib_deny_attempt_writes
 BEFORE INSERT OR UPDATE OR DELETE ON browser_account_attempts
 FOR EACH ROW EXECUTE FUNCTION aib_shadow_deny_mutation();
CREATE TRIGGER aib_deny_config_writes
 BEFORE INSERT OR UPDATE OR DELETE ON vault_config
 FOR EACH ROW EXECUTE FUNCTION aib_shadow_deny_mutation();
CREATE TRIGGER aib_deny_migration_guard_updates
 BEFORE UPDATE OR DELETE ON vault_migration_guard
 FOR EACH ROW EXECUTE FUNCTION aib_shadow_deny_mutation();
COMMIT;
