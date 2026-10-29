/**
 * Trusted-process verifier of a FULL restored cold-vault snapshot.
 *
 * Compare original decoded JSONL records with a freshly SELECTed, source-shaped
 * destination export. Caller must keep BOTH sets in its private runtime.
 * Never return ciphertext, identifiers, hashes, source names or per-row errors.
 *
 * This is evidence of byte-preserving import, NOT authentication, saved-close,
 * provider reconciliation, source freeze, or cutover permission.
 */
import {createHash,timingSafeEqual} from 'node:crypto';

const FIELDS=Object.freeze({
 browser_profiles:['profile_name','encrypted_state','updated_at'],
 browser_profile_versions:['id','profile_name','encrypted_state',
   'source_updated_at','archived_at','reason'],
 browser_engine_profiles:['profile_name','provider_profile_id','updated_at','hydrated'],
 browser_task_checkpoints:['task_id','owner_hash','encrypted_state','claim_hash',
   'claim_expires_at','resumable','queued','revision','created_at','updated_at'],
 vault_config:['config_key','config_value'],
 browser_control_leases:['slot','claim_id','epoch','expires_at','holder_hash','updated_at'],
 browser_account_attempts:['attempt_id','claim_key','attempt_day','attempt_count',
   'retry_after','suspended','updated_at'],
 browser_profile_events:['id','profile_name','event_type','created_at']
});
const KEY=Object.freeze({
 browser_profiles:'profile_name',browser_profile_versions:'id',
 browser_engine_profiles:'profile_name',browser_task_checkpoints:'task_id',
 vault_config:'config_key',browser_control_leases:'slot',
 browser_account_attempts:'attempt_id',browser_profile_events:'id'
});
const TARGET='Acceptance-20261023-R158';
const own=(v,k)=>Object.prototype.hasOwnProperty.call(v,k);
const deny=()=>{throw Error('RESTORE_PARITY_INVALID_OR_INCOMPLETE')};
const hash=v=>createHash('sha256').update(v).digest();

function indexed(records){
 if(!Array.isArray(records)||records.length>200000)deny();
 const map=new Map(),counts=Object.fromEntries(Object.keys(FIELDS).map(k=>[k,0]));
 const reasons={rolling:0,forensic:0,pre_verified:0,other_protected:0};
 for(const record of records){
  if(!record||typeof record!=='object'||Array.isArray(record)||
      !own(FIELDS,record.table)||!record.row||typeof record.row!=='object'||
      Array.isArray(record.row))deny();
  const {table,row}=record, fields=FIELDS[table],keyField=KEY[table];
  if(Object.keys(row).length!==fields.length||fields.some(f=>!own(row,f)))deny();
  for(const f of fields){
   const v=row[f];
   if(v===undefined||(v!==null&&typeof v==='object')||
      (typeof v==='number'&&!Number.isSafeInteger(v)))deny();
   if(f.endsWith('_at')&&v!==null&&typeof v!=='string')deny();
  }
  const id=row[keyField];
  if(typeof id!=='string'||id.length<1||id.length>250)deny();
  if((table==='browser_profile_versions'||table==='browser_profile_events')&&
     !/^[0-9]+$/.test(id))deny();
  const k=table+'\0'+id;if(map.has(k))deny();
  // Include every original source field, including encrypted bytes,
  // claim state, event metadata and microsecond timestamps.
  const canonical=JSON.stringify([table,fields.map(f=>row[f])]);
  map.set(k,hash(canonical));
  counts[table]++;
  if(table==='browser_profile_versions'&&row.profile_name===TARGET){
   if(row.reason==='update')reasons.rolling++;
   else if(typeof row.reason==='string'&&row.reason.startsWith('forensic_r158_'))
     reasons.forensic++;
   else if(row.reason==='pre_verified_recovery_20261023_160')
     reasons.pre_verified++;
   else reasons.other_protected++;
  }
 }
 return {map,counts,reasons};
}

export function verifyColdRestoreParity(sourceRecords,destinationRecords){
 const source=indexed(sourceRecords),dest=indexed(destinationRecords);
 if(source.map.size===0||source.map.size!==dest.map.size)deny();
 for(const [k,v] of source.map){
  const match=dest.map.get(k);
  if(!match||!timingSafeEqual(v,match))deny();
 }
 const a=source.reasons,b=dest.reasons;
 const r158Protected=a.forensic+a.pre_verified+a.other_protected;
 const r158ClassificationVerified=a.rolling===20&&r158Protected===21&&
   a.forensic===20&&a.pre_verified===1&&a.other_protected===0&&
   JSON.stringify(a)===JSON.stringify(b);
 return {
  exact_source_destination_rows_verified:true,
  row_count:source.map.size,
  table_counts:source.counts,
  neutral_r158_rolling:a.rolling,
  neutral_r158_protected:r158Protected,
  neutral_r158_provenance_verified:r158ClassificationVerified,
  promotion_allowed:false,
  provider_reconciliation_verified:false,
  browser_login_verified:false,
  requires_new_source_freeze:true
 };
}
