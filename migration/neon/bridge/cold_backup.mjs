/** Validate a private, immutable cold backup without opening either database.
 * The result is NOT a signed freeze receipt and NEVER authorizes promotion.
 * Callers must not log rows, ciphertext, provider IDs, or per-record hashes.
 */
import {createHash} from 'node:crypto';
import {gunzipSync} from 'node:zlib';
import {normalizeShadowRecord,normalizeEngineBinding} from './row_mapper.mjs';
const MAX_BYTES=64*1024*1024;
const keys={browser_profiles:'profile_name',browser_profile_versions:'id',
 browser_engine_profiles:'profile_name',browser_task_checkpoints:'task_id',
 vault_config:'config_key',browser_control_leases:'slot',
 browser_account_attempts:'attempt_id',browser_profile_events:'id'};
const hash=b=>createHash('sha256').update(b).digest('hex');
const object=v=>v!==null&&typeof v==='object'&&!Array.isArray(v);
const sameCounts=(actual,expected)=>object(expected)&&Object.keys(expected).length===Object.keys(keys).length&&
 Object.keys(keys).every(k=>Number.isSafeInteger(expected[k])&&expected[k]>=0&&actual[k]===expected[k]);
function denied(code){throw Error(code);}
/** All row data stays in the trusted process that called this function. */
export function validateColdBackup(compressed,receipt){
 if(!Buffer.isBuffer(compressed)||compressed.length>MAX_BYTES||!object(receipt))denied('COLD_BACKUP_INPUT_INVALID');
 if(!/^[a-f0-9]{64}$/.test(receipt.sha256||'')||hash(compressed)!==receipt.sha256||compressed.length!==receipt.compressed_bytes)
  denied('COLD_BACKUP_BYTES_MISMATCH');
 let raw,lines,head,footer;
 try{raw=gunzipSync(compressed,{maxOutputLength:MAX_BYTES});
  if(raw.at(-1)!==10)denied('COLD_BACKUP_TRUNCATED');
  lines=raw.toString('utf8').split('\n');lines.pop();
  if(lines.length<2)denied('COLD_BACKUP_TRUNCATED');
  head=JSON.parse(lines[0]);footer=JSON.parse(lines.at(-1));
 }catch{denied('COLD_BACKUP_FORMAT_INVALID');}
 if(!object(head)||head.format!=='aib-cold-backup-v1'||head.source!=='floot'||
   head.snapshot!=='repeatable_read'||head.batch_id!==receipt.batch_id||
   head.observed_at!==receipt.observed_at||head.promotion_allowed!==false||head.production_cutover!==false||
   receipt.promotion_allowed!==false||receipt.production_cutover!==false)
  denied('COLD_BACKUP_PROVENANCE_INVALID');
 if(!object(footer)||footer.footer!==true)denied('COLD_BACKUP_FOOTER_INVALID');
 const counts=Object.fromEntries(Object.keys(keys).map(k=>[k,0]));
 const seen=new Set(),records=[],digest=createHash('sha256');
 let protectedArchives=0,forensicArchives=0;
 for(const line of lines.slice(1,-1)){
  let record;try{record=JSON.parse(line);}catch{denied('COLD_BACKUP_ROW_INVALID');}
  if(!object(record)||!Object.hasOwn(keys,record.table)||!object(record.row))denied('COLD_BACKUP_ROW_INVALID');
  const {table,row}=record,key=row[keys[table]];
  if(typeof key!=='string'||!key.length||key.length>250)denied('COLD_BACKUP_KEY_INVALID');
  const identity=table+'\0'+key;
  if(seen.has(identity))denied('COLD_BACKUP_DUPLICATE_ROW');seen.add(identity);
  if(table==='browser_profiles')normalizeShadowRecord('profile',row);
  if(table==='browser_profile_versions'){
   normalizeShadowRecord('archive',row);
   if(row.reason!=='update')protectedArchives++;
   if(row.reason.startsWith('forensic_r158_'))forensicArchives++;
  }
  if(table==='browser_task_checkpoints')normalizeShadowRecord('task',row);
  if(table==='browser_engine_profiles')normalizeEngineBinding(row);
  counts[table]++;digest.update(line+'\n');records.push(record);
 }
 const rowsHash=digest.digest('hex');
 if(rowsHash!==receipt.source_rows_sha256||rowsHash!==footer.source_rows_sha256)
  denied('COLD_BACKUP_ROWS_MISMATCH');
 if(!sameCounts(counts,receipt.counts)||!sameCounts(counts,footer.counts))denied('COLD_BACKUP_COUNTS_MISMATCH');
 return {records,summary:{verified:true,counts,protected_archives:protectedArchives,
  forensic_r158_archives:forensicArchives,production_cutover:false,promotion_allowed:false,
  requires_fresh_source_freeze:true,requires_provider_reconciliation:true}};
}
