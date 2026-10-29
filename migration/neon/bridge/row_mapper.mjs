/** Convert an already encrypted legacy row into immutable shadow-inbox input.
 * RUN ONLY INSIDE TRUSTED MIGRATION PROCESS. The caller never prints output.
 * All state remains ciphertext; hashes are for private byte-integrity comparison.
 */
import {createHash} from 'node:crypto';
const key=v=>typeof v==='string'&&v.length>=1&&v.length<=150;
// Preserve PostgreSQL microseconds exactly. The bridge must SELECT
// timestamptz::text at source; parsing into JS Date silently loses 3 digits.
const stamp=v=>{
 if(typeof v!=='string'
   ||!/^[0-9]{4}-[0-9]{2}-[0-9]{2}[ T][0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}(?::?[0-9]{2})?)$/i.test(v))
  throw Error('SHADOW_SOURCE_TIMESTAMP_PRECISION_UNVERIFIED');
 const validate=v.replace(' ','T').replace(/([+-][0-9]{2})$/,'$1:00');
 if(!Number.isFinite(Date.parse(validate)))
  throw Error('SHADOW_SOURCE_TIMESTAMP_INVALID');
 return v; // Raw timezone-aware string, including all six fractional digits.
};
function protect(payload){
 if(typeof payload!=='string'||Buffer.byteLength(payload,'utf8')<20
    ||Buffer.byteLength(payload,'utf8')>8000000)
  throw Error('SHADOW_CIPHERTEXT_INVALID');
 return {encryptedState:payload,
  sourceSha256:createHash('sha256').update(payload,'utf8').digest('hex')};
}
export function normalizeShadowRecord(kind,row){
 if(!row||typeof row!=='object'||Array.isArray(row))
  throw Error('SHADOW_SOURCE_ROW_INVALID');
 let sourceKey,when,metadata;
 if(kind==='profile'){
  sourceKey=row.profile_name;
  when=stamp(row.updated_at);
  metadata={source_updated_at:when};
 }else if(kind==='archive'){
  if(!/^[0-9]+$/.test(String(row.id)))throw Error('SHADOW_SOURCE_ID_INVALID');
  sourceKey=row.profile_name+'#'+String(row.id);
  when=stamp(row.source_updated_at);
  metadata={original_id:String(row.id),profile_name:row.profile_name,
    reason:row.reason,archived_at:stamp(row.archived_at)};
  if(typeof row.reason!=='string'||row.reason.length>150)
   throw Error('SHADOW_SOURCE_REASON_INVALID');
 }else if(kind==='task'){
  sourceKey=row.task_id;
  when=stamp(row.updated_at);
  if(!Number.isSafeInteger(row.revision)||row.revision<1)
   throw Error('SHADOW_TASK_REVISION_INVALID');
  metadata={owner_hash:row.owner_hash,revision:row.revision,
    claim_hash:row.claim_hash,claim_expires_at:row.claim_expires_at?
      stamp(row.claim_expires_at):null,resumable:row.resumable,
    queued:row.queued,created_at:stamp(row.created_at)};
 }else{
  throw Error('SHADOW_KIND_UNSUPPORTED');
 }
 if(!key(sourceKey))throw Error('SHADOW_SOURCE_KEY_INVALID');
 const state=protect(row.encrypted_state);
 if(Buffer.byteLength(JSON.stringify(metadata),'utf8')>4096)
  throw Error('SHADOW_METADATA_TOO_LARGE');
 return {kind,sourceKey,sourceUpdatedAt:when,...state,metadata};
}
// Steel provider binding is private identity metadata, not portable ciphertext.
// It travels ONLY source-DB -> restricted shadow-DB, never via chat/CI/logs.
export function normalizeEngineBinding(row){
 if(!row||typeof row!=='object'||Array.isArray(row)
   ||!key(row.profile_name)
   ||typeof row.provider_profile_id!=='string'
   ||!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(row.provider_profile_id)
   ||typeof row.hydrated!=='boolean')
  throw Error('SHADOW_ENGINE_BINDING_INVALID');
 return {sourceKey:row.profile_name,
  providerProfileId:row.provider_profile_id.toLowerCase(),
  sourceUpdatedAt:stamp(row.updated_at),hydrated:row.hydrated};
}
export function shadowSummary(counts){
 if(!counts||typeof counts!=='object')throw Error('SHADOW_COUNTS_INVALID');
 const out={};
 for(const k of ['profile','archive','engine','task']){
  if(!Number.isSafeInteger(counts[k])||counts[k]<0)
   throw Error('SHADOW_COUNTS_INVALID');
  out[k]=counts[k];
 }
 return out;
}


/** Private vault configuration: preserve EXACT value bytes, never print them. */
export function normalizeConfigRow(row){
 if(!row||typeof row!=='object'||Array.isArray(row)||
   typeof row.config_key!=='string'||row.config_key.length<1||row.config_key.length>150||
   typeof row.config_value!=='string'||
   Buffer.byteLength(row.config_value,'utf8')<1||
   Buffer.byteLength(row.config_value,'utf8')>1048576)
  throw Error('SHADOW_CONFIG_INVALID');
 return {sourceKey:row.config_key,configValue:row.config_value,
  sourceSha256:createHash('sha256').update(row.config_value,'utf8').digest('hex')};
}

/** Private event journal: hash the same byte framing as 006_shadow_config_events.sql. */
export function normalizeEventRow(row){
 if(!row||typeof row!=='object'||Array.isArray(row)||
   typeof row.id!=='string'||!/^[1-9][0-9]{0,18}$/.test(row.id)||
   typeof row.profile_name!=='string'||row.profile_name.length<1||
   row.profile_name.length>150||row.profile_name.includes('\x1f')||
   typeof row.event_type!=='string'||row.event_type.length<1||
   row.event_type.length>150||row.event_type.includes('\x1f'))
  throw Error('SHADOW_EVENT_INVALID');
 const created=stamp(row.created_at);
 if(created.includes('\x1f'))throw Error('SHADOW_EVENT_INVALID');
 const framed=[row.id,row.profile_name,row.event_type,created].join('\x1f');
 return {sourceId:row.id,profileName:row.profile_name,eventType:row.event_type,
  sourceCreatedAt:created,sourceSha256:createHash('sha256')
    .update(framed,'utf8').digest('hex')};
}
