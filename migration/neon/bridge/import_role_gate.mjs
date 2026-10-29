/**
 * Read-only evidence of a LEGITIMATELY PROVISIONED restricted Neon importer.
 * A role-name prefix alone is insufficient; actual grants and memberships
 * must be checked in the current PostgreSQL connection before any import.
 *
 * This module NEVER creates or grants roles. Refused role-provisioning must
 * be resolved through authorized provider controls, not evaded here.
 */
const LIVE_TABLES=Object.freeze([
 'browser_profiles','browser_profile_versions','browser_engine_profiles',
 'browser_task_checkpoints','browser_control_leases','browser_profile_events',
 'browser_account_attempts','vault_config','vault_migration_guard'
]);
const STAGING_TABLES=Object.freeze([
 'aib_shadow_ciphertext_inbox','aib_shadow_engine_bindings',
 'aib_shadow_config_values','aib_shadow_profile_events'
]);
const FUNCTIONS=Object.freeze([
 'aib_shadow_put_encrypted(uuid,text,text,text,timestamptz,text,jsonb)',
 'aib_shadow_put_engine_binding(uuid,text,uuid,timestamptz,boolean)',
 'aib_shadow_put_config(uuid,text,text,text)',
 'aib_shadow_put_event(uuid,bigint,text,text,text,text)'
]);
const deny=()=>{throw Error('RESTORE_IMPORT_ROLE_LEAST_PRIVILEGE_NOT_VERIFIED')};
/** Exact object names are compile-time allowlisted, not user supplied. */
export const RESTRICTED_ROLE_SQL=[
 'SELECT',
 ' current_user AS role_name,',
 " current_setting('TimeZone') AS timezone,",
 " current_setting('DateStyle') AS datestyle,",
 ' (SELECT NOT (rolsuper OR rolcreaterole OR rolcreatedb OR rolreplication OR rolbypassrls)',
 '  AND rolcanlogin FROM pg_roles WHERE rolname=current_user) AS unprivileged_login,',
 " NOT pg_has_role(current_user,'neondb_owner','MEMBER') AS not_owner_member,",
 " NOT has_schema_privilege(current_user,'public','CREATE') AS no_schema_creation,",
 " has_table_privilege(current_user,'public.vault_migration_guard','SELECT') AS guard_read,",
 " has_table_privilege(current_user,'public.aib_cold_backup_receipts','SELECT') AS receipt_read,",
 " NOT has_table_privilege(current_user,'public.aib_cold_backup_receipts','INSERT,UPDATE,DELETE,TRUNCATE') AS receipt_no_write,",
 ...LIVE_TABLES.map((t,i)=>
  " NOT has_table_privilege(current_user,'public."+t+"','INSERT,UPDATE,DELETE,TRUNCATE') AS live_denied_"+i+","),
 ...STAGING_TABLES.flatMap((t,i)=>[
  " has_table_privilege(current_user,'public."+t+"','SELECT') AS stage_read_"+i+",",
  " has_table_privilege(current_user,'public."+t+"','INSERT') AS stage_insert_"+i+",",
  " NOT has_table_privilege(current_user,'public."+t+"','UPDATE,DELETE,TRUNCATE') AS stage_no_mutation_"+i+","
 ]),
 ...FUNCTIONS.map((f,i)=>
  " has_function_privilege(current_user,'public."+f+"','EXECUTE') AS fn_exec_"+i+(i===FUNCTIONS.length-1?'':',')),
].join('\n');
/** Proof is checked on the same DB connection used for source import. */
export function assertRestrictedImporterEvidence(evidence){
 if(!evidence||typeof evidence!=='object'||Array.isArray(evidence)||
   typeof evidence.role_name!=='string'||
   !/^aib_import_[a-z0-9_]{1,40}$/.test(evidence.role_name)||
   evidence.timezone!=='GMT'||!/^ISO, /.test(evidence.datestyle))
  deny();
 for(const key of ['unprivileged_login','not_owner_member','no_schema_creation',
   'guard_read','receipt_read','receipt_no_write']){
  if(evidence[key]!==true)deny();
 }
 for(let i=0;i<LIVE_TABLES.length;i++){
  if(evidence['live_denied_'+i]!==true)deny();
 }
 for(let i=0;i<STAGING_TABLES.length;i++){
  if(evidence['stage_read_'+i]!==true||
     evidence['stage_insert_'+i]!==true||
     evidence['stage_no_mutation_'+i]!==true||
     evidence['fn_exec_'+i]!==true)
   deny();
 }
 return {verified:true,limited_writer:true,production_writer_unchanged:true};
}
export async function checkRestrictedImporter(sql){
 if(!sql||typeof sql.unsafe!=='function')deny();
 // A SELECT without any private row data: only grants and role attributes.
 const rows=await sql.unsafe(RESTRICTED_ROLE_SQL);
 if(!Array.isArray(rows)||rows.length!==1)deny();
 return assertRestrictedImporterEvidence(rows[0]);
}
