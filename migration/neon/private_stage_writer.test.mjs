import {test} from 'node:test';
import {strict as assert} from 'node:assert';
import {normalizeShadowRecord,normalizeEngineBinding,
 normalizeConfigRow,normalizeEventRow} from './bridge/row_mapper.mjs';
import {stageAndVerifyColdRestore} from './bridge/private_stage_writer.mjs';

const stamp='2026-10-29 01:14:48.986868+00';
const name='Acceptance-20261023-R158';
const encrypted='synthetic-test-ciphertext-not-real-account';
const batch='00000000-0000-4000-8000-000000000001';
const source=[
 {table:'browser_profiles',row:{profile_name:name,encrypted_state:encrypted,updated_at:stamp}},
 {table:'browser_engine_profiles',row:{profile_name:name,
  provider_profile_id:'00000000-0000-4000-8000-000000000008',
  updated_at:stamp,hydrated:true}},
 {table:'browser_task_checkpoints',row:{
  task_id:'00000000-0000-4000-8000-000000000009',owner_hash:'b'.repeat(64),
  revision:5,encrypted_state:encrypted,claim_hash:'',
  claim_expires_at:null,resumable:true,queued:false,
  created_at:stamp,updated_at:stamp}},
 {table:'vault_config',row:{config_key:'safe-synthetic',config_value:'not-a-real-key'}},
 {table:'browser_profile_events',row:{id:'9007199254740993',
  profile_name:name,event_type:'save',created_at:stamp}},
];
for(let i=0;i<41;i++)source.push({
 table:'browser_profile_versions',row:{
  id:String(9007199254740994n+BigInt(i)),
  profile_name:name,encrypted_state:encrypted,
  source_updated_at:stamp,archived_at:stamp,
  reason:i<20?'update':i<40?'forensic_r158_synthetic':
    'pre_verified_recovery_20261023_160'
 }
});
function plan(){
 const records={profile:[],archive:[],engine:[],task:[],config:[],event:[]};
 for(const x of source){
  if(x.table==='browser_profiles')records.profile.push(normalizeShadowRecord('profile',x.row));
  else if(x.table==='browser_profile_versions')records.archive.push(normalizeShadowRecord('archive',x.row));
  else if(x.table==='browser_task_checkpoints')records.task.push(normalizeShadowRecord('task',x.row));
  else if(x.table==='browser_engine_profiles')records.engine.push(normalizeEngineBinding(x.row));
  else if(x.table==='vault_config')records.config.push(normalizeConfigRow(x.row));
  else if(x.table==='browser_profile_events')records.event.push(normalizeEventRow(x.row));
 }
 return {batch_id:batch,records};
}
function mockDb({tamper=false,missing=false}={}){
 const arrays={ciphertext:[],engine:[],config:[],event:[]};
 const calls=[];
 return {arrays,calls,unsafe:async function(q,args){
  calls.push({q,args});
  if(q.startsWith('SELECT aib_shadow_put_encrypted')){
   arrays.ciphertext.push({source_kind:args[1],source_key:args[2],encrypted_state:args[3],
    source_updated_at:args[4],source_metadata:JSON.parse(args[6])});
   return [{accepted:true}];
  }
  if(q.startsWith('SELECT aib_shadow_put_engine_binding')){
   arrays.engine.push({profile_name:args[1],provider_profile_id:args[2],
     updated_at:args[3],hydrated:args[4]});
   return [{accepted:true}];
  }
  if(q.startsWith('SELECT aib_shadow_put_config')){
   arrays.config.push({config_key:args[1],config_value:args[2]});
   return [{accepted:true}];
  }
  if(q.startsWith('SELECT aib_shadow_put_event')){
   arrays.event.push({source_id:args[1],profile_name:args[2],
    event_type:args[3],source_created_text:args[4]});
   return [{accepted:true}];
  }
  if(q.startsWith('SELECT source_kind,source_key,encrypted_state')){
   const data=structuredClone(arrays.ciphertext);
   if(tamper)data[0].encrypted_state='changed-ciphertext-but-same-count';
   return data;
  }
  if(q.startsWith('SELECT profile_name,provider_profile_id::text')){
   return arrays.engine;
  }
  if(q.startsWith('SELECT config_key,config_value')){
   return missing?[]:arrays.config;
  }
  if(q.startsWith('SELECT source_id::text')){
   return arrays.event;
  }
  throw Error('UNEXPECTED_SQL_OPERATION');
 }};
}
const expiry=()=>Math.floor(Date.now()/1000)+900;
test('import all eight source kinds and verify exact private replay',async()=>{
 const sql=mockDb();
 const r=await stageAndVerifyColdRestore(sql,plan(),source,{expiresAtSeconds:expiry()});
 assert.equal(r.status,'STAGING_IMPORT_VERIFIED');
 assert.equal(r.row_count,46);
 assert.equal(r.neutral_r158_protected,21);
 assert.equal(r.production_cutover,false);
 assert.equal(r.writer_enabled,false);
 assert.equal(sql.calls.filter(c=>c.q.startsWith('SELECT aib_shadow_put_')).length,46);
 const q=sql.calls.find(c=>c.q.includes('aib_shadow_put_encrypted'));
 assert.equal(q.q.includes(encrypted),false);
 assert.equal(q.q.includes('$4'),true);
});
test('one altered ciphertext fails readback even with equal count',async()=>{
 const sql=mockDb({tamper:true});
 await assert.rejects(()=>stageAndVerifyColdRestore(sql,plan(),source,
  {expiresAtSeconds:expiry()}),/RESTORE_PARITY_INVALID_OR_INCOMPLETE/);
});
test('missing config value prevents claiming complete import',async()=>{
 const sql=mockDb({missing:true});
 await assert.rejects(()=>stageAndVerifyColdRestore(sql,plan(),source,
  {expiresAtSeconds:expiry()}),/RESTORE_PARITY_INVALID_OR_INCOMPLETE/);
});
test('expired migration freeze stops before any write',async()=>{
 const sql=mockDb();
 await assert.rejects(()=>stageAndVerifyColdRestore(sql,plan(),source,
  {expiresAtSeconds:Math.floor(Date.now()/1000)-1}),/RESTORE_FREEZE_EXPIRED/);
 assert.equal(sql.calls.length,0);
});
test('invalid SQL adapter and missing source rows are explicitly refused',async()=>{
 await assert.rejects(()=>stageAndVerifyColdRestore({},plan(),source,
  {expiresAtSeconds:expiry()}),/RESTORE_PRIVATE_STAGE_ARGUMENT_INVALID/);
 await assert.rejects(()=>stageAndVerifyColdRestore(mockDb(),plan(),null,
  {expiresAtSeconds:expiry()}),/RESTORE_PRIVATE_STAGE_ARGUMENT_INVALID/);
});
