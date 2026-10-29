/**
 * PRIVATE ONE-SHOT SHADOW COPY. NEVER run as an HTTP request or CI job.
 * Requires server-only source + RESTRICTED destination DB roles and a
 * short-lived independently issued saved-close/provider-idle HMAC proof.
 * No plaintext decryption; no credentials, ciphertext or hashes in logs.
 */
import postgres from 'postgres';
import {verifyMigrationFreeze,assertShadowDestination} from './preflight.mjs';
import {normalizeShadowRecord,normalizeEngineBinding,normalizeConfigRow,normalizeEventRow,shadowSummary} from './row_mapper.mjs';

const mode=process.env.AIB_BRIDGE_MODE||'dry-run';
const validUrl=v=>typeof v==='string'&&/^postgres(?:ql)?:\/\//.test(v);
async function main(){
 if(!['dry-run','copy'].includes(mode))throw Error('BRIDGE_MODE_INVALID');
 const sourceURL=process.env.FLOOT_SOURCE_DATABASE_URL;
 const destinationURL=process.env.NEON_IMPORT_DATABASE_URL;
 if(!validUrl(sourceURL))throw Error('BRIDGE_SOURCE_CREDENTIAL_UNAVAILABLE');
 if(mode==='copy'&&!validUrl(destinationURL))
  throw Error('BRIDGE_DESTINATION_CREDENTIAL_UNAVAILABLE');
 let freeze=null;
 if(mode==='copy'){
  let receipt;
  try{receipt=JSON.parse(process.env.AIB_MIGRATION_RECEIPT_JSON||'')}
  catch{throw Error('BRIDGE_FROZEN_RECEIPT_REQUIRED')}
  freeze=verifyMigrationFreeze(receipt,process.env.AIB_MIGRATION_HMAC_KEY);
 }
 const source=postgres(sourceURL,{max:1,connect_timeout:8,ssl:'require',
   idle_timeout:10,prepare:false});
 const destination=mode==='copy'?postgres(destinationURL,{
   max:1,connect_timeout:8,ssl:'require',idle_timeout:10,prepare:false}):null;
 const tally={profile:0,archive:0,engine:0,task:0,config:0,event:0};
 try{
  if(destination){
   const [stage]=await destination`SELECT
     (SELECT mode FROM vault_migration_guard WHERE only_row) AS mode,
     (SELECT write_enabled FROM vault_migration_guard WHERE only_row) AS write_enabled,
     (SELECT count(*)::int FROM browser_profiles) AS profile_count,
     (SELECT count(*)::int FROM browser_engine_profiles) AS engine_count,
     (SELECT count(*)::int FROM browser_control_leases) AS active_leases,
     (to_regclass('public.aib_shadow_ciphertext_inbox') IS NOT NULL
       AND to_regprocedure('aib_shadow_put_encrypted(uuid,text,text,text,timestamptz,text,jsonb)')
         IS NOT NULL AND to_regclass('public.aib_shadow_engine_bindings') IS NOT NULL
         AND to_regprocedure('aib_shadow_put_engine_binding(uuid,text,uuid,timestamptz,boolean)')
         IS NOT NULL AND to_regclass('public.aib_shadow_config_values') IS NOT NULL
         AND to_regprocedure('aib_shadow_put_config(uuid,text,text,text)') IS NOT NULL
         AND to_regclass('public.aib_shadow_profile_events') IS NOT NULL
         AND to_regprocedure('aib_shadow_put_event(uuid,bigint,text,text,text,text)') IS NOT NULL)
         AS inbox_ready,
     current_user AS db_role`;
   assertShadowDestination(stage);
   if(!/^aib_import_[a-z0-9_]{1,40}$/.test(stage.db_role))
    throw Error('BRIDGE_DESTINATION_ROLE_NOT_RESTRICTED');
  }
  await source.begin(async tx=>{
   await tx`SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY`;
   const [safety]=await tx`SELECT
      (SELECT count(*)::int FROM browser_control_leases) AS leases,
      (SELECT count(*)::int FROM browser_task_checkpoints
        WHERE NOT resumable) AS unresolved,
      (SELECT count(*)::int FROM browser_account_attempts) AS account_attempts`;
   if(!safety||safety.leases!==0||safety.unresolved!==0||safety.account_attempts!==0)
    throw Error('BRIDGE_SOURCE_NOT_IDLE');
   // All timestamptz fields are selected as text: Date destroys microseconds.
   async function append(kind,row){
    const v=normalizeShadowRecord(kind,row);
    tally[kind]++;
    if(!destination)return;
    const meta=JSON.stringify(v.metadata);
    await destination`SELECT aib_shadow_put_encrypted(
      ${freeze.batch_id}::uuid,${kind},${v.sourceKey},${v.encryptedState},
      ${v.sourceUpdatedAt}::timestamptz,${v.sourceSha256},
      ${meta}::jsonb)`;
   }
   let lastName='';
   for(;;){
    const rows=await tx`SELECT profile_name,encrypted_state,updated_at::text AS updated_at
       FROM browser_profiles WHERE profile_name>${lastName}
       ORDER BY profile_name LIMIT 50`;
    if(rows.length===0)break;
    for(const row of rows)await append('profile',row);
    lastName=rows[rows.length-1].profile_name;
   }
   let lastId='0';
   for(;;){
    const rows=await tx`SELECT id,profile_name,encrypted_state,source_updated_at::text AS source_updated_at,
       archived_at::text AS archived_at,reason FROM browser_profile_versions
       WHERE id>${lastId}::bigint ORDER BY id LIMIT 50`;
    if(rows.length===0)break;
    for(const row of rows)await append('archive',row);
    lastId=String(rows[rows.length-1].id);
   }
   // All 67 Steel UUID bindings are private identity mapping, not login
   // credentials. Preserve them in a separate immutable shadow table.
   async function appendEngine(row){
    const v=normalizeEngineBinding(row);
    tally.engine++;
    if(!destination)return;
    await destination`SELECT aib_shadow_put_engine_binding(
      ${freeze.batch_id}::uuid,${v.sourceKey},
      ${v.providerProfileId}::uuid,
      ${v.sourceUpdatedAt}::timestamptz,${v.hydrated})`;
   }
   let lastEngine='';
   for(;;){
    const rows=await tx`SELECT profile_name,provider_profile_id::text AS provider_profile_id,
       updated_at::text AS updated_at,hydrated
       FROM browser_engine_profiles WHERE profile_name>${lastEngine}
       ORDER BY profile_name LIMIT 50`;
    if(rows.length===0)break;
    for(const row of rows)await appendEngine(row);
    lastEngine=rows[rows.length-1].profile_name;
   }
   let lastTask='';
   for(;;){
    const rows=await tx`SELECT task_id,owner_hash,revision,encrypted_state,
       claim_hash,claim_expires_at::text AS claim_expires_at,resumable,queued,
       created_at::text AS created_at,updated_at::text AS updated_at
       FROM browser_task_checkpoints WHERE task_id::text>${lastTask}
       ORDER BY task_id LIMIT 50`;
    if(rows.length===0)break;
    for(const row of rows)await append('task',row);
    lastTask=String(rows[rows.length-1].task_id);
   }
   // Preserve the EXACT private configuration, including owner token digests.
   // These values never enter stdout, ChatGPT, GitHub or provider-visible logs.
   let lastConfig='';
   for(;;){
    const rows=await tx`SELECT config_key,config_value FROM vault_config
      WHERE config_key>${lastConfig} ORDER BY config_key LIMIT 50`;
    if(!rows.length)break;
    for(const row of rows){
     const v=normalizeConfigRow(row);tally.config++;
     if(destination)await destination`SELECT aib_shadow_put_config(
       ${freeze.batch_id}::uuid,${v.sourceKey},${v.configValue},${v.sourceSha256})`;
    }
    lastConfig=rows[rows.length-1].config_key;
   }
   // Preserve the full immutable owner event audit sequence and source time.
   let lastEvent='0';
   for(;;){
    const rows=await tx`SELECT id::text AS id,profile_name,event_type,
       created_at::text AS created_at FROM browser_profile_events
       WHERE id>${lastEvent}::bigint ORDER BY id LIMIT 100`;
    if(!rows.length)break;
    for(const row of rows){
     const v=normalizeEventRow(row);tally.event++;
     if(destination)await destination`SELECT aib_shadow_put_event(
       ${freeze.batch_id}::uuid,${v.sourceId}::bigint,
       ${v.profileName},${v.eventType},${v.sourceCreatedAt},${v.sourceSha256})`;
    }
    lastEvent=String(rows[rows.length-1].id);
   }
   const [expected]=await tx`SELECT
      (SELECT count(*)::int FROM browser_profiles) AS profile,
      (SELECT count(*)::int FROM browser_profile_versions) AS archive,
      (SELECT count(*)::int FROM browser_engine_profiles) AS engine,
      (SELECT count(*)::int FROM browser_task_checkpoints) AS task,
      (SELECT count(*)::int FROM vault_config) AS config,
      (SELECT count(*)::int FROM browser_profile_events) AS event`;
   for(const k of Object.keys(tally))
    if(tally[k]!==expected[k])throw Error('BRIDGE_SNAPSHOT_COUNT_MISMATCH');
  });
  if(destination){
   const counts=await destination`SELECT source_kind AS kind,count(*)::int AS n
      FROM aib_shadow_ciphertext_inbox WHERE batch_id=${freeze.batch_id}::uuid
      GROUP BY source_kind`;
   for(const kind of ['profile','archive','task']){
    const n=counts.find(x=>x.kind===kind)?.n||0;
    if(n!==tally[kind])throw Error('BRIDGE_DESTINATION_COUNT_MISMATCH');
   }
   const [bindings]=await destination`SELECT count(*)::int AS n
     FROM aib_shadow_engine_bindings WHERE batch_id=${freeze.batch_id}::uuid`;
   if(bindings.n!==tally.engine)throw Error('BRIDGE_BINDING_COUNT_MISMATCH');
   const [config]=await destination`SELECT count(*)::int AS n
      FROM aib_shadow_config_values WHERE batch_id=${freeze.batch_id}::uuid`;
   if(config.n!==tally.config)throw Error('BRIDGE_CONFIG_COUNT_MISMATCH');
   const [events]=await destination`SELECT count(*)::int AS n
      FROM aib_shadow_profile_events WHERE batch_id=${freeze.batch_id}::uuid`;
   if(events.n!==tally.event)throw Error('BRIDGE_EVENT_COUNT_MISMATCH');
  }
  // This completion is NOT the source/destination full manifest acceptance.
  // All Steel binding rows are staged; source config, complete byte-by-byte
  // binding verification and provider replay still require separate acceptance.
  process.stdout.write(JSON.stringify({mode,
    snapshot_completed:true,shadow_only:true,production_cutover:false,
    rows:{...shadowSummary(tally),config:tally.config,event:tally.event},
    pending_full_ciphertext_manifest_readback:true})+'\n');
 }finally{
  await source.end({timeout:3});
  if(destination)await destination.end({timeout:3});
 }
}
try{await main()}catch{
 // Never emit DB URI, private exception, row values, cookie, hash or stack.
 process.stderr.write('BRIDGE_NOT_COMPLETED_SAFE_STOP\n');
 process.exitCode=1;
}
