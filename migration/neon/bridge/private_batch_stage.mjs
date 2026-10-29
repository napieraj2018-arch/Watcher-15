/**
 * Fast BOUNDED STAGING-only private upload. Only immutable inbox append
 * functions are called, never live-shaped writer tables. All SQL is fixed,
 * parameters are bound, and a new owner-signed provider/saved-close freeze and
 * a separately authorized restricted DB role remain mandatory in the caller.
 *
 * Every batch is individually idempotent, verified for complete attendance,
 * limited to 48 records and 768 KiB JSON. Partial uploads remain staging only.
 * Final exact ciphertext/readback comparison is compulsory before any use.
 */
import {reassembleShadowRows} from './private_stage_writer.mjs';
import {verifyColdRestoreParity} from './restore_parity.mjs';

const MAX_ROWS=48;
const MAX_JSON_BYTES=768*1024;
const fail=code=>{throw Error(code)};
const QUERIES=Object.freeze({
 ciphertext: [
  'SELECT count(accepted)::int AS n FROM (',
  ' SELECT aib_shadow_put_encrypted($2::uuid,x.kind,x.source_key,',
  ' x.encrypted_state,x.source_updated_at::timestamptz,',
  ' x.source_sha256,x.source_metadata) AS accepted',
  ' FROM jsonb_to_recordset($1::jsonb) AS x(',
  ' kind text,source_key text,encrypted_state text,',
  ' source_updated_at text,source_sha256 text,source_metadata jsonb)',
  ') AS writes'
 ].join(''),
 engine: [
  'SELECT count(accepted)::int AS n FROM (',
  ' SELECT aib_shadow_put_engine_binding($2::uuid,x.source_key,',
  ' x.provider_profile_id::uuid,x.source_updated_at::timestamptz,',
  ' x.hydrated) AS accepted FROM jsonb_to_recordset($1::jsonb) AS x(',
  ' source_key text,provider_profile_id text,source_updated_at text,',
  ' hydrated boolean)) AS writes'
 ].join(''),
 config: [
  'SELECT count(accepted)::int AS n FROM (',
  ' SELECT aib_shadow_put_config($2::uuid,x.source_key,x.config_value,',
  ' x.source_sha256) AS accepted FROM jsonb_to_recordset($1::jsonb) AS x(',
  ' source_key text,config_value text,source_sha256 text)) AS writes'
 ].join(''),
 event: [
  'SELECT count(accepted)::int AS n FROM (',
  ' SELECT aib_shadow_put_event($2::uuid,x.source_id::bigint,',
  ' x.profile_name,x.event_type,x.source_created_at,x.source_sha256)',
  ' AS accepted FROM jsonb_to_recordset($1::jsonb) AS x(',
  ' source_id text,profile_name text,event_type text,',
  ' source_created_at text,source_sha256 text)) AS writes'
 ].join('')
});
const READS=Object.freeze({
 ciphertext:'SELECT source_kind,source_key,encrypted_state,source_updated_at::text AS source_updated_at,source_metadata FROM aib_shadow_ciphertext_inbox WHERE batch_id=$1::uuid',
 engine:'SELECT profile_name,provider_profile_id::text AS provider_profile_id,source_updated_at::text AS updated_at,hydrated FROM aib_shadow_engine_bindings WHERE batch_id=$1::uuid',
 config:'SELECT config_key,config_value FROM aib_shadow_config_values WHERE batch_id=$1::uuid',
 event:'SELECT source_id::text AS source_id,profile_name,event_type,source_created_text FROM aib_shadow_profile_events WHERE batch_id=$1::uuid',
});
const nonneg=n=>Number.isSafeInteger(n)&&n>=0;
function oneBatchJson(records){
 return '['+records.join(',')+']';
}
/** In-memory only. No ciphertext, hashes or identifiers in public results. */
export function* boundedPrivateBatches(items,{maxRows=MAX_ROWS,maxBytes=MAX_JSON_BYTES}={}){
 if(!Array.isArray(items)||!Number.isSafeInteger(maxRows)||maxRows<1||
   maxRows>MAX_ROWS||!Number.isSafeInteger(maxBytes)||maxBytes<100||
   maxBytes>MAX_JSON_BYTES)fail('RESTORE_BATCH_LIMIT_INVALID');
 let texts=[],bytes=2;
 for(const item of items){
  if(!item||typeof item!=='object'||Array.isArray(item))fail('RESTORE_BATCH_ITEM_INVALID');
  const str=JSON.stringify(item);
  const n=Buffer.byteLength(str,'utf8');
  if(n+2>maxBytes)fail('RESTORE_BATCH_ITEM_TOO_LARGE');
  if(texts.length&&(texts.length>=maxRows||bytes+n+1>maxBytes)){
   yield {json:oneBatchJson(texts),count:texts.length};
   texts=[];bytes=2;
  }
  texts.push(str);bytes+=n+(texts.length>1?1:0);
 }
 if(texts.length)yield {json:oneBatchJson(texts),count:texts.length};
}
function rowsOf(plan){
 if(!plan||!plan.records)fail('RESTORE_PLAN_INVALID');
 const p=plan.records,expected=['profile','archive','task','engine','config','event'];
 if(expected.some(k=>!Array.isArray(p[k])))fail('RESTORE_PLAN_INVALID');
 const ciphertext=['profile','archive','task'].flatMap(kind=>p[kind].map(r=>({
  kind,source_key:r.sourceKey,encrypted_state:r.encryptedState,
  source_updated_at:r.sourceUpdatedAt,source_sha256:r.sourceSha256,
  source_metadata:r.metadata
 })));
 const engine=p.engine.map(r=>({source_key:r.sourceKey,
  provider_profile_id:r.providerProfileId,
  source_updated_at:r.sourceUpdatedAt,hydrated:r.hydrated}));
 const config=p.config.map(r=>({source_key:r.sourceKey,
  config_value:r.configValue,source_sha256:r.sourceSha256}));
 const event=p.event.map(r=>({source_id:r.sourceId,
  profile_name:r.profileName,event_type:r.eventType,
  source_created_at:r.sourceCreatedAt,source_sha256:r.sourceSha256}));
 return {ciphertext,engine,config,event};
}
/** Caller must have ALREADY checked the true role, current guard and signed freeze. */
export async function stageAndVerifyBatched(sql,plan,sourceRows,{expiresAtSeconds}={}){
 if(!sql||typeof sql.unsafe!=='function'||!Array.isArray(sourceRows)||
   !plan||typeof plan.batch_id!=='string'||
   !Number.isSafeInteger(expiresAtSeconds))fail('RESTORE_PRIVATE_STAGE_ARGUMENT_INVALID');
 const check=()=>{if(Math.ceil(Date.now()/1000)>=expiresAtSeconds)
   fail('RESTORE_FREEZE_EXPIRED')};
 const batch=plan.batch_id,input=rowsOf(plan);
 const expected=input.ciphertext.length+input.engine.length+
   input.config.length+input.event.length;
 if(expected!==sourceRows.length||expected===0)fail('RESTORE_BATCH_SOURCE_MISMATCH');
 let imported=0,batchCalls=0;
 for(const [kind,items] of Object.entries(input)){
  for(const part of boundedPrivateBatches(items)){
   check();
   const response=await sql.unsafe(QUERIES[kind],[part.json,batch]);
   if(!Array.isArray(response)||response.length!==1||
      !nonneg(response[0].n)||response[0].n!==part.count)
    fail('RESTORE_BATCH_INCOMPLETE');
   batchCalls++;imported+=part.count;
  }
 }
 check();
 const readback={};
 for(const [kind,query] of Object.entries(READS)){
  check();
  readback[kind]=await sql.unsafe(query,[batch]);
 }
 const destination=reassembleShadowRows(readback);
 const result=verifyColdRestoreParity(sourceRows,destination);
 if(result.row_count!==expected||imported!==expected||
   !result.neutral_r158_provenance_verified)
  fail('RESTORE_BATCH_READBACK_INCOMPLETE');
 return {
  status:'PRIVATE_STAGING_IMPORTED_VERIFIED',
  exact_rows:result.row_count,
  counts:result.table_counts,
  neutral_r158_rolling:result.neutral_r158_rolling,
  neutral_r158_protected:result.neutral_r158_protected,
  batches:batchCalls,
  production_cutover:false,writer_enabled:false,account_logins_verified:false
 };
}
