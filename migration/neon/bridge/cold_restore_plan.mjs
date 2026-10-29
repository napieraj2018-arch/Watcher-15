/**
 * Private cold snapshot -> restricted Neon STAGING import plan.
 * Importing real owner data requires a NEW owner-signed provider/saved-close
 * freeze, legitimate limited import role and verified backup receipt.
 *
 * Merely producing this plan (even for a genuine backup) does not establish
 * current site authentication, correct native three-store restoration,
 * a new migration epoch, operational read/write readiness, or cutover.
 */
import {validateColdBackup} from './cold_backup.mjs';
import {verifyMigrationFreeze,assertShadowDestination} from './preflight.mjs';
import {normalizeShadowRecord,normalizeEngineBinding,
 normalizeConfigRow,normalizeEventRow} from './row_mapper.mjs';

const EXPECTED_TABLES=[
 'browser_profiles','browser_profile_versions','browser_engine_profiles',
 'browser_task_checkpoints','vault_config','browser_control_leases',
 'browser_account_attempts','browser_profile_events'
];
const deny=code=>{throw Error(code)};
const count=v=>Number.isSafeInteger(v)&&v>=0?v:deny('COLD_RESTORE_COUNT_INVALID');
const sha=v=>typeof v==='string'&&/^[a-f0-9]{64}$/.test(v);
const safeReceipt=r=>r&&typeof r==='object'&&!Array.isArray(r)
  &&typeof r.backup_id==='string'
  &&/^[0-9a-f]{8}-[0-9a-f-]{27,}$/.test(r.backup_id)
  &&typeof r.observed_at_text==='string'
  &&typeof r.private_object_key==='string'
  &&/^2026-[0-9]{2}-[0-9]{2}\/source-vault-v[0-9]+\.jsonl\.gz$/.test(r.private_object_key)
  &&sha(r.object_sha256)&&sha(r.source_rows_sha256)
  &&r.imported_to_tables===false&&r.production_cutover===false
  &&r.compressed_bytes>0&&r.compressed_bytes<67108864;

export function expectedColdReceipt(row){
 if(!safeReceipt(row))deny('COLD_RESTORE_RECEIPT_INVALID');
 const counts={
  browser_profiles:count(row.profile_count),
  browser_profile_versions:count(row.archive_count),
  browser_engine_profiles:count(row.engine_count),
  browser_task_checkpoints:count(row.task_count),
  vault_config:count(row.config_count),
  browser_control_leases:count(row.lease_count??0),
  browser_account_attempts:count(row.account_attempt_count??0),
  browser_profile_events:count(row.event_count)
 };
 if(Object.keys(counts).length!==EXPECTED_TABLES.length||counts.browser_profiles===0)
  deny('COLD_RESTORE_RECEIPT_INVALID');
 return {
  batch_id:row.backup_id,observed_at:row.observed_at_text,
  source_rows_sha256:row.source_rows_sha256,
  sha256:row.object_sha256,compressed_bytes:row.compressed_bytes,
  production_cutover:false,promotion_allowed:false,counts
 };
}

export function planRestrictedColdRestore({compressed,privateReceipt,
 freezeReceipt,freezeKey,stage,role}){
 // Check the NEW signed freeze before any data mutation or plan issuance.
 const proof=verifyMigrationFreeze(freezeReceipt,freezeKey);
 if(!/^[a-z0-9]{8}-[a-z0-9-]{27,}$/.test(proof.batch_id))
  deny('COLD_RESTORE_FREEZE_INVALID');
 if(!role||!/^aib_import_[a-z0-9_]{1,40}$/.test(role))
  deny('COLD_RESTORE_ROLE_NOT_RESTRICTED');
 assertShadowDestination(stage);
 const expected=expectedColdReceipt(privateReceipt);
 if(proof.batch_id!==expected.batch_id)deny('COLD_RESTORE_PROVENANCE_CONFLICT');
 const {records,summary}=validateColdBackup(compressed,expected);
 if(summary.protected_archives!==count(privateReceipt.protected_archive_count))
  deny('COLD_RESTORE_ARCHIVE_COUNT_CONFLICT');
 if(summary.counts.browser_control_leases!==0||summary.counts.browser_account_attempts!==0)
  deny('COLD_RESTORE_ACTIVE_SOURCE_STATE');
 let neutralRolling=0,neutralProtected=0,neutralForensic=0,neutralPre=0;
 for(const r of records){
  if(r.table==='browser_profile_versions'&&r.row.profile_name==='Acceptance-20261023-R158'){
   if(r.row.reason==='update')neutralRolling++;
   else{neutralProtected++;
    if(r.row.reason.startsWith('forensic_r158_'))neutralForensic++;
    if(r.row.reason==='pre_verified_recovery_20261023_160')neutralPre++;
   }
  }
 }
 if(neutralRolling!==20||neutralProtected!==21||neutralForensic!==20||neutralPre!==1)
  deny('COLD_RESTORE_R158_PROVENANCE_INVALID');
 const result={profile:[],archive:[],engine:[],task:[],config:[],event:[]};
 for(const r of records){
  if(r.table==='browser_profiles')result.profile.push(normalizeShadowRecord('profile',r.row));
  else if(r.table==='browser_profile_versions')result.archive.push(normalizeShadowRecord('archive',r.row));
  else if(r.table==='browser_engine_profiles')result.engine.push(normalizeEngineBinding(r.row));
  else if(r.table==='browser_task_checkpoints')result.task.push(normalizeShadowRecord('task',r.row));
  else if(r.table==='vault_config')result.config.push(normalizeConfigRow(r.row));
  else if(r.table==='browser_profile_events')result.event.push(normalizeEventRow(r.row));
 }
 if(result.profile.length!==summary.counts.browser_profiles||
    result.archive.length!==summary.counts.browser_profile_versions||
    result.engine.length!==summary.counts.browser_engine_profiles||
    result.task.length!==summary.counts.browser_task_checkpoints||
    result.config.length!==summary.counts.vault_config||
    result.event.length!==summary.counts.browser_profile_events)
  deny('COLD_RESTORE_MAPPING_INCOMPLETE');
 return {batch_id:proof.batch_id,records:result,
  summary:{
   verified_private_backup:true,provider_signed_freeze:true,
   restricted_role_verified:true,
   counts:Object.fromEntries(Object.entries(result).map(([k,v])=>[k,v.length])),
   neutral_r158_rolling:neutralRolling,neutral_r158_protected:neutralProtected,
   source_snapshot_stale_until_fresh_delta:true,
   restored_to_neon:false,cutover_allowed:false,
   login_verified:false
  }};
}
