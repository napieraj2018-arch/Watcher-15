/**
 * OWNER PRIVATE CLI — Neon cold backup staging only.
 *
 * No API listener, no browser actions, no production writer changes.
 * This file is NOT run in CI and must NEVER be called with an administrator
 * DB role or as a substitute for the rejected restricted role provisioning.
 * Credentials and signed URLs come from a dedicated trusted private runtime.
 */
import postgres from 'postgres';
import {verifyMigrationFreeze,assertShadowDestination} from './preflight.mjs';
import {planRestrictedColdRestore,expectedColdReceipt} from './cold_restore_plan.mjs';
import {validateColdBackup} from './cold_backup.mjs';
import {stageAndVerifyBatched} from './private_batch_stage.mjs';

const deny=code=>{throw Error(code)};
const S3_HOST='br-ancient-firefly-baqgm1x0.storage.c-8.eu-central-1.aws.neon.tech';
const S3_BUCKET='aib-vault-recovery';
function boundedSignedUrl(value,key){
 let url;
 try{url=new URL(value)}catch{deny('RESTORE_PRIVATE_URL_INVALID')}
 if(url.protocol!=='https:'||url.hostname!==S3_HOST||
    url.username||url.password||url.port||url.hash||
    url.pathname!=='/'+S3_BUCKET+'/'+key||
    url.searchParams.get('X-Amz-Algorithm')!=='AWS4-HMAC-SHA256'||
    !/^[a-f0-9]{64}$/.test(url.searchParams.get('X-Amz-Signature')||''))
  deny('RESTORE_PRIVATE_URL_INVALID');
 return value;
}
async function downloadPrivate(url,expectedSize){
 const r=await fetch(url,{redirect:'error',signal:AbortSignal.timeout(35000)});
 if(r.status!==200)deny('RESTORE_OBJECT_UNAVAILABLE');
 const size=r.headers.get('content-length');
 if(size!==null&&Number(size)>expectedSize)deny('RESTORE_OBJECT_BYTES_UNCONFIRMED');
 const reader=r.body?.getReader();if(!reader)deny('RESTORE_OBJECT_BYTES_UNCONFIRMED');
 const chunks=[];let n=0;
 try{
  for(;;){
   const {done,value}=await reader.read();if(done)break;
   n+=value.byteLength;
   if(n>expectedSize)deny('RESTORE_OBJECT_BYTES_UNCONFIRMED');
   chunks.push(Buffer.from(value));
  }
 }finally{try{await reader.cancel()}catch{};try{reader.releaseLock()}catch{}}
 if(n!==expectedSize)deny('RESTORE_OBJECT_BYTES_UNCONFIRMED');
 return Buffer.concat(chunks,n);
}
async function getStage(db){
 const [s]=await db.unsafe(
  "SELECT (SELECT mode FROM vault_migration_guard WHERE only_row) AS mode, "+
  "(SELECT write_enabled FROM vault_migration_guard WHERE only_row) AS write_enabled, "+
  "(SELECT count(*)::int FROM browser_profiles) AS profile_count, "+
  "(SELECT count(*)::int FROM browser_engine_profiles) AS engine_count, "+
  "(SELECT count(*)::int FROM browser_control_leases) AS active_leases, "+
  "(to_regclass('public.aib_shadow_ciphertext_inbox') IS NOT NULL AND "+
  "to_regprocedure('aib_shadow_put_encrypted(uuid,text,text,text,timestamptz,text,jsonb)') IS NOT NULL AND "+
  "to_regclass('public.aib_shadow_engine_bindings') IS NOT NULL AND "+
  "to_regprocedure('aib_shadow_put_engine_binding(uuid,text,uuid,timestamptz,boolean)') IS NOT NULL AND "+
  "to_regclass('public.aib_shadow_config_values') IS NOT NULL AND "+
  "to_regprocedure('aib_shadow_put_config(uuid,text,text,text)') IS NOT NULL AND "+
  "to_regclass('public.aib_shadow_profile_events') IS NOT NULL AND "+
  "to_regprocedure('aib_shadow_put_event(uuid,bigint,text,text,text,text)') IS NOT NULL) AS inbox_ready, "+
  "current_user AS db_role");
 assertShadowDestination(s);
 if(!/^aib_import_[a-z0-9_]{1,40}$/.test(s.db_role))
  deny('RESTORE_RESTRICTED_DB_ROLE_REQUIRED');
 return s;
}
async function pinnedReceipt(db,batch){
 const rows=await db.unsafe(
  "SELECT backup_id::text AS backup_id, "+
  "to_char(observed_at AT TIME ZONE 'UTC','YYYY-MM-DD HH24:MI:SS.US')||'+00' AS observed_at_text, "+
  "private_object_key,object_sha256,source_rows_sha256, "+
  "compressed_bytes::int AS compressed_bytes,profile_count,archive_count, "+
  "engine_count,task_count,config_count,event_count,protected_archive_count, "+
  "imported_to_tables,production_cutover "+
  "FROM aib_cold_backup_receipts WHERE backup_id=$1::uuid",[batch]);
 if(rows.length!==1)deny('RESTORE_PRIVATE_RECEIPT_NOT_VERIFIED');
 return rows[0];
}
async function main(){
 if(process.env.AIB_COLD_RESTORE_MODE!=='stage')
  deny('RESTORE_EXPLICIT_STAGE_MODE_REQUIRED');
 const uri=process.env.NEON_IMPORT_DATABASE_URL;
 if(typeof uri!=='string'||!/^postgres(?:ql)?:\/\//.test(uri))
  deny('RESTORE_IMPORT_CREDENTIAL_UNAVAILABLE');
 let receipt;
 try{receipt=JSON.parse(process.env.AIB_MIGRATION_RECEIPT_JSON||'')}
 catch{deny('RESTORE_SIGNED_FREEZE_NOT_PRESENT')}
 const signed=verifyMigrationFreeze(receipt,process.env.AIB_MIGRATION_HMAC_KEY);
 const db=postgres(uri,{max:1,connect_timeout:8,ssl:'require',idle_timeout:8,prepare:false});
 try{
  const stage=await getStage(db),privateReceipt=await pinnedReceipt(db,signed.batch_id);
  const expected=expectedColdReceipt(privateReceipt);
  const link=boundedSignedUrl(process.env.AIB_COLD_BACKUP_GET_URL,
    privateReceipt.private_object_key);
  const bytes=await downloadPrivate(link,expected.compressed_bytes);
  const plan=planRestrictedColdRestore({
   compressed:bytes,privateReceipt,freezeReceipt:receipt,
   freezeKey:process.env.AIB_MIGRATION_HMAC_KEY,stage,role:stage.db_role});
  const source=validateColdBackup(bytes,expected).records;
  // Cold staging is NEVER permission to choose a new primary writer.
  const done=await stageAndVerifyBatched(db,plan,source,
   {expiresAtSeconds:receipt.expires_at});
  process.stdout.write(JSON.stringify(done)+'\n');
 }finally{await db.end({timeout:3})}
}
try{await main()}catch{
 // Never print connection strings, private record values, signed URLs, bearer
 // tokens, provider identifiers, hashes or raw SQL exception messages.
 process.stderr.write('RESTORE_NOT_COMPLETED_SAFE_STOP\n');
 process.exitCode=1;
}
