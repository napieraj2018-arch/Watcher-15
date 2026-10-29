import {test} from 'node:test';
import {strict as assert} from 'node:assert';
import {normalizeShadowRecord,normalizeEngineBinding,normalizeConfigRow,
 normalizeEventRow} from './bridge/row_mapper.mjs';
import {boundedPrivateBatches,stageAndVerifyBatched} from './bridge/private_batch_stage.mjs';

const when='2026-10-29 01:14:48.986868+00';
const name='Acceptance-20261023-R158';
const ciphertext='fake-test-encrypted-profile-!'.repeat(3);
const batch='00000000-0000-4000-8000-000000000001';
function sourceRows(eventCount=120){
 const out=[
  {table:'browser_profiles',row:{profile_name:name,
   encrypted_state:ciphertext,updated_at:when}},
  {table:'browser_engine_profiles',row:{profile_name:name,
   provider_profile_id:'00000000-0000-4000-8000-000000000008',
   updated_at:when,hydrated:true}},
  {table:'browser_task_checkpoints',row:{
   task_id:'00000000-0000-4000-8000-000000000009',
   owner_hash:'b'.repeat(64),revision:5,
   encrypted_state:ciphertext,claim_hash:'',claim_expires_at:null,
   resumable:true,queued:false,created_at:when,updated_at:when}},
  {table:'vault_config',row:{config_key:'fake-config',config_value:'no-real-secret'}}
 ];
 for(let i=0;i<41;i++)out.push({table:'browser_profile_versions',row:{
  id:String(100+i),profile_name:name,encrypted_state:ciphertext,
  source_updated_at:when,archived_at:when,
  reason:i<20?'update':i<40?'forensic_r158_test':'pre_verified_recovery_20261023_160'
 }});
 for(let i=1;i<=eventCount;i++)out.push({table:'browser_profile_events',row:{
  id:String(i),profile_name:name,event_type:'save',created_at:when
 }});
 return out;
}
function plan(source){
 const p={profile:[],archive:[],task:[],engine:[],config:[],event:[]};
 for(const {table,row} of source){
  if(table==='browser_profiles')p.profile.push(normalizeShadowRecord('profile',row));
  if(table==='browser_profile_versions')p.archive.push(normalizeShadowRecord('archive',row));
  if(table==='browser_task_checkpoints')p.task.push(normalizeShadowRecord('task',row));
  if(table==='browser_engine_profiles')p.engine.push(normalizeEngineBinding(row));
  if(table==='vault_config')p.config.push(normalizeConfigRow(row));
  if(table==='browser_profile_events')p.event.push(normalizeEventRow(row));
 }
 return {batch_id:batch,records:p};
}
const expiry=()=>Math.floor(Date.now()/1000)+600;
function mock({tamper=false,dropConfig=false,missingAccept=false}={}){
 const history=[],stage={ciphertext:[],engine:[],config:[],event:[]};
 return {history,stage,async unsafe(sql,args){
  history.push({sql,args});
  if(sql.includes('count(accepted)')){
   const items=JSON.parse(args[0]);
   if(sql.includes('aib_shadow_put_encrypted')){
    for(const x of items)stage.ciphertext.push({
     source_kind:x.kind,source_key:x.source_key,encrypted_state:x.encrypted_state,
     source_updated_at:x.source_updated_at,source_metadata:x.source_metadata});
   }else if(sql.includes('aib_shadow_put_engine_binding')){
    for(const x of items)stage.engine.push({
     profile_name:x.source_key,provider_profile_id:x.provider_profile_id,
     updated_at:x.source_updated_at,hydrated:x.hydrated});
   }else if(sql.includes('aib_shadow_put_config')){
    for(const x of items)stage.config.push({
     config_key:x.source_key,config_value:x.config_value});
   }else if(sql.includes('aib_shadow_put_event')){
    for(const x of items)stage.event.push({
     source_id:x.source_id,profile_name:x.profile_name,
     event_type:x.event_type,source_created_text:x.source_created_at});
   }else throw Error('INVALID_PRIVATE_QUERY');
   return [{n:missingAccept?items.length-1:items.length}];
  }
  if(sql.includes('FROM aib_shadow_ciphertext_inbox')){
   const copy=structuredClone(stage.ciphertext);
   if(tamper)copy[0].encrypted_state='tampered-byte-copy';
   return copy;
  }
  if(sql.includes('FROM aib_shadow_engine_bindings'))return stage.engine;
  if(sql.includes('FROM aib_shadow_config_values'))return dropConfig?[]:stage.config;
  if(sql.includes('FROM aib_shadow_profile_events'))return stage.event;
  throw Error('UNEXPECTED_DB_QUERY');
 }};
}
test('bounded chunks enforce max record count',()=>{
 const items=Array.from({length:125},(_,i)=>({id:i}));
 const batches=[...boundedPrivateBatches(items)];
 assert.equal(batches.length,3);
 assert.deepEqual(batches.map(x=>x.count),[48,48,29]);
 assert.equal(batches.flatMap(x=>JSON.parse(x.json)).length,125);
});
test('verified real-source-sized ciphertext is accepted in 2MB payload cap',()=>{
 const state='X'.repeat(1342052);
 const parts=[...boundedPrivateBatches([{state},{state}])];
 assert.equal(parts.length,2);
 assert.equal(JSON.parse(parts[0].json)[0].state.length,1342052);
});
test('oversized individual ciphertext stops before any SQL operation',async()=>{
 assert.throws(()=>[...boundedPrivateBatches([{state:'X'.repeat(2500000)}])],
  /RESTORE_BATCH_ITEM_TOO_LARGE/);
 const db=mock();
 const s=sourceRows(5),p=plan(s);
 p.records.profile[0].encryptedState='Z'.repeat(3000000);
 await assert.rejects(()=>stageAndVerifyBatched(db,p,s,{expiresAtSeconds:expiry()}),
  /RESTORE_BATCH_ITEM_TOO_LARGE/);
 assert.equal(db.history.length,0);
});
test('correct chunked full restore exact readback across all categories',async()=>{
 const s=sourceRows(),p=plan(s),db=mock();
 const r=await stageAndVerifyBatched(db,p,s,{expiresAtSeconds:expiry()});
 assert.equal(r.status,'PRIVATE_STAGING_IMPORTED_VERIFIED');
 assert.equal(r.exact_rows,s.length);
 assert.equal(r.neutral_r158_protected,21);
 assert.equal(r.production_cutover,false);
 assert.equal(r.writer_enabled,false);
 assert.ok(r.batches<r.exact_rows/3);
 const writes=db.history.filter(x=>x.sql.includes('count(accepted)'));
 assert.ok(writes.every(x=>x.args[1]===batch));
 assert.ok(writes.every(x=>!x.sql.includes(ciphertext)));
 assert.equal(db.stage.event.length,120);
});
test('tampered ciphertext refuses complete import even with equal counts',async()=>{
 const s=sourceRows(5);
 await assert.rejects(()=>stageAndVerifyBatched(mock({tamper:true}),
  plan(s),s,{expiresAtSeconds:expiry()}),/RESTORE_PARITY_INVALID_OR_INCOMPLETE/);
});
test('lost configuration prevents a false positive',async()=>{
 const s=sourceRows(5);
 await assert.rejects(()=>stageAndVerifyBatched(mock({dropConfig:true}),
  plan(s),s,{expiresAtSeconds:expiry()}),/RESTORE_PARITY_INVALID_OR_INCOMPLETE/);
});
test('missing row acceptance count fails before next batch',async()=>{
 const s=sourceRows(5),db=mock({missingAccept:true});
 await assert.rejects(()=>stageAndVerifyBatched(db,plan(s),s,
  {expiresAtSeconds:expiry()}),/RESTORE_BATCH_INCOMPLETE/);
 assert.equal(db.history.length,1);
});
test('expired signed freeze blocks every SQL request',async()=>{
 const s=sourceRows(5),db=mock();
 await assert.rejects(()=>stageAndVerifyBatched(db,plan(s),s,
  {expiresAtSeconds:Math.floor(Date.now()/1000)-2}),/RESTORE_FREEZE_EXPIRED/);
 assert.equal(db.history.length,0);
});
test('wrong row count and malformed batch API fail closed',async()=>{
 const s=sourceRows(5),db=mock();
 await assert.rejects(()=>stageAndVerifyBatched(db,plan(s),s.slice(1),
  {expiresAtSeconds:expiry()}),/RESTORE_BATCH_SOURCE_MISMATCH/);
 assert.throws(()=>[...boundedPrivateBatches(s,{maxRows:500})],
  /RESTORE_BATCH_LIMIT_INVALID/);
});
