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
   ||!/^[0-9]{4}-[0-9]{2}-[0-9]{2}[ T][0-9]{2}:[0-9]{2}:[0-9]{2}(?:\\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}(?::?[0-9]{2})?)$/i.test(v))
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
export function shadowSummary(counts){
 if(!counts||typeof counts!=='object')throw Error('SHADOW_COUNTS_INVALID');
 const out={};
 for(const k of ['profile','archive','task']){
  if(!Number.isSafeInteger(counts[k])||counts[k]<0)
   throw Error('SHADOW_COUNTS_INVALID');
  out[k]=counts[k];
 }
 return out;
}
