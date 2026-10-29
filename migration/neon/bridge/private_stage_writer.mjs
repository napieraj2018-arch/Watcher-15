/**
 * Owner-private Neon STAGING writer and full readback.
 *
 * Uses only fixed SQL statements with positional parameters. Called ONLY
 * after planRestrictedColdRestore verifies signed freeze, minimum-role name,
 * private immutable receipt and exact encrypted snapshot.
 *
 * It neither provisions credentials nor unlocks a production writer.
 */
import {verifyColdRestoreParity} from './restore_parity.mjs';
const fail=code=>{throw Error(code)};
const bound=(sql,q,args)=>sql.unsafe(q,args);
const qCipher='SELECT aib_shadow_put_encrypted($1::uuid,$2,$3,$4,$5::timestamptz,$6,$7::jsonb) AS accepted';
const qEngine='SELECT aib_shadow_put_engine_binding($1::uuid,$2,$3::uuid,$4::timestamptz,$5) AS accepted';
const qConfig='SELECT aib_shadow_put_config($1::uuid,$2,$3,$4) AS accepted';
const qEvent='SELECT aib_shadow_put_event($1::uuid,$2::bigint,$3,$4,$5,$6) AS accepted';
const Q={
 ciphertext:'SELECT source_kind,source_key,encrypted_state,source_updated_at::text AS source_updated_at,source_metadata FROM aib_shadow_ciphertext_inbox WHERE batch_id=$1::uuid',
 engine:'SELECT profile_name,provider_profile_id::text AS provider_profile_id,source_updated_at::text AS updated_at,hydrated FROM aib_shadow_engine_bindings WHERE batch_id=$1::uuid',
 config:'SELECT config_key,config_value FROM aib_shadow_config_values WHERE batch_id=$1::uuid',
 event:'SELECT source_id::text AS source_id,profile_name,event_type,source_created_text FROM aib_shadow_profile_events WHERE batch_id=$1::uuid',
};
export function reassembleShadowRows({ciphertext,engine,config,event}){
 for(const a of [ciphertext,engine,config,event])if(!Array.isArray(a))fail('RESTORE_READBACK_INCOMPLETE');
 const out=[];
 for(const r of ciphertext){
  const m=r.source_metadata;
  if(m===null||typeof m!=='object'||Array.isArray(m))fail('RESTORE_READBACK_METADATA_INVALID');
  if(r.source_kind==='profile')out.push({table:'browser_profiles',row:{
   profile_name:r.source_key,encrypted_state:r.encrypted_state,
   updated_at:m.source_updated_at}});
  else if(r.source_kind==='archive')out.push({table:'browser_profile_versions',row:{
   id:m.original_id,profile_name:m.profile_name,encrypted_state:r.encrypted_state,
   source_updated_at:r.source_updated_at,archived_at:m.archived_at,reason:m.reason}});
  else if(r.source_kind==='task')out.push({table:'browser_task_checkpoints',row:{
   task_id:r.source_key,owner_hash:m.owner_hash,
   revision:m.revision,encrypted_state:r.encrypted_state,claim_hash:m.claim_hash,
   claim_expires_at:m.claim_expires_at,resumable:m.resumable,queued:m.queued,
   created_at:m.created_at,updated_at:r.source_updated_at}});
  else fail('RESTORE_READBACK_KIND_INVALID');
 }
 for(const r of engine)out.push({table:'browser_engine_profiles',row:{
  profile_name:r.profile_name,provider_profile_id:r.provider_profile_id,
  updated_at:r.updated_at,hydrated:r.hydrated}});
 for(const r of config)out.push({table:'vault_config',row:{
  config_key:r.config_key,config_value:r.config_value}});
 for(const r of event)out.push({table:'browser_profile_events',row:{
  id:r.source_id,profile_name:r.profile_name,event_type:r.event_type,
  created_at:r.source_created_text}});
 return out;
}
export async function stageAndVerifyColdRestore(sql,plan,sourceRows,{expiresAtSeconds}){
 if(!sql||typeof sql.unsafe!=='function'||!plan||!plan.records||
   typeof plan.batch_id!=='string'||!Array.isArray(sourceRows)||
   !Number.isSafeInteger(expiresAtSeconds))
  fail('RESTORE_PRIVATE_STAGE_ARGUMENT_INVALID');
 const batch=plan.batch_id;
 const deadline=()=>{if(Date.now()/1000>=expiresAtSeconds)fail('RESTORE_FREEZE_EXPIRED')};
 let calls=0;
 async function run(query,args){
  deadline();
  const rows=await bound(sql,query,args);
  if(!Array.isArray(rows)||rows.length!==1||typeof rows[0].accepted!=='boolean')
   fail('RESTORE_WRITE_RECEIPT_INVALID');
  calls++;
 }
 for(const kind of ['profile','archive','task']){
  for(const r of plan.records[kind]){
   await run(qCipher,[batch,kind,r.sourceKey,r.encryptedState,
    r.sourceUpdatedAt,r.sourceSha256,JSON.stringify(r.metadata)]);
  }
 }
 for(const r of plan.records.engine)await run(qEngine,
  [batch,r.sourceKey,r.providerProfileId,r.sourceUpdatedAt,r.hydrated]);
 for(const r of plan.records.config)await run(qConfig,
  [batch,r.sourceKey,r.configValue,r.sourceSha256]);
 for(const r of plan.records.event)await run(qEvent,
  [batch,r.sourceId,r.profileName,r.eventType,r.sourceCreatedAt,r.sourceSha256]);
 deadline();
 const rows={};
 for(const [kind,query] of Object.entries(Q))rows[kind]=await bound(sql,query,[batch]);
 const destination=reassembleShadowRows(rows);
 const parity=verifyColdRestoreParity(sourceRows,destination);
 if(!parity.exact_source_destination_rows_verified||!parity.neutral_r158_provenance_verified||
   parity.row_count!==calls)
  fail('RESTORE_READBACK_PARITY_FAILURE');
 return {status:'STAGING_IMPORT_VERIFIED',row_count:parity.row_count,
  counts:parity.table_counts,neutral_r158_protected:parity.neutral_r158_protected,
  production_cutover:false,writer_enabled:false,live_logins_verified:false};
}
