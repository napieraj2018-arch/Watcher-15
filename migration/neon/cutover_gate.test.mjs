import {strict as assert} from 'node:assert';
import {createHmac} from 'node:crypto';
import {test} from 'node:test';
import {evaluateTrustedCutover} from './api/cutover_gate.mjs';

const SECRET='TEST_Only_Never_Use_In_Production_'.repeat(2);
const source={profiles:4,engine_bindings:4,archives:31,protected_archives:21,tasks:2};
const evidence={
 algorithm:'sha256',source_rows_match:true,versions_match:true,
 engine_bindings_match:true,tasks_match:true,protected_r158_21_match:true
};
const verified={
 source_frozen:true,no_active_vault_writer:true,
 no_unresolved_task_claim:true,steel_provider_idle:true,
 neutral_three_store_coherent:true,saved_close_new_controller_pass:true,
 five_live_meta_after_reopen:false,real_iphone_roundtrip_pass:false
};
const original={source,destination:{...source},proof:evidence,verification:verified};
function canonical(x){
 if(Array.isArray(x))return '['+x.map(canonical).join(',')+']';
 if(x!==null&&typeof x==='object')return '{'+Object.keys(x).sort().map(k=>
  JSON.stringify(k)+':'+canonical(x[k])).join(',')+'}';
 return JSON.stringify(x);
}
function signed(payload=original){
 return {payload,signature:createHmac('sha256',SECRET)
  .update(canonical(payload)).digest('hex'),key:SECRET};
}
function refused(payload,code){
 const r=evaluateTrustedCutover(signed(payload));
 assert.equal(r.cutover_allowed,false);assert.equal(r.readiness,false);
 assert.equal(r.reason,code);
}
test('cannot accept an unsigned or mismatched manifest',()=>{
 assert.equal(evaluateTrustedCutover().reason,'MANIFEST_ATTESTATION_MISSING');
 const t=signed();
 t.payload={...t.payload,source:{...t.payload.source,profiles:100}};
 assert.equal(evaluateTrustedCutover(t).reason,'MANIFEST_ATTESTATION_MISSING');
 const invalid=signed();invalid.key='wrong-secret';
 assert.equal(evaluateTrustedCutover(invalid).reason,'MANIFEST_ATTESTATION_MISSING');
});
test('empty source is never a completed migration even with matching empty targets',()=>{
 refused({...original,source:{...source,profiles:0},
  destination:{...source,profiles:0}},'SOURCE_MANIFEST_EMPTY');
});
test('source and destination counts must agree on every category',()=>{
 for(const key of Object.keys(source)){
  refused({...original,destination:{...source,[key]:source[key]+1}},
    'SOURCE_DESTINATION_COUNT_MISMATCH');
 }
});
test('at least 21 protected R158 forensic snapshots remain required',()=>{
 refused({...original,source:{...source,protected_archives:20},
  destination:{...source,protected_archives:20}},
  'PROTECTED_ARCHIVE_PROVENANCE_MISSING');
});
test('actual encrypted version equality required, not just row counts',()=>{
 for(const key of Object.keys(evidence)){
  const other={...evidence,[key]:key==='algorithm'?'md5':false};
  refused({...original,proof:other},'ENCRYPTED_IDENTITY_UNVERIFIED');
 }
});
test('every source freeze, provider and neutral-state proof is compulsory',()=>{
 for(const key of ['source_frozen','no_active_vault_writer',
  'no_unresolved_task_claim','steel_provider_idle',
  'neutral_three_store_coherent','saved_close_new_controller_pass']){
  refused({...original,verification:{...verified,[key]:false}},
    'LIVE_RESTORE_OR_PROVIDER_GATE_UNVERIFIED');
 }
});
test('cutover can be technically accepted without fabricated five account readiness',()=>{
 const r=evaluateTrustedCutover(signed());
 assert.equal(r.cutover_allowed,true);
 assert.equal(r.readiness,false);
 assert.equal(r.reason,'ACCOUNTS_OR_IPHONE_PENDING');
});
test('READY only after five real Meta reopen and physical iPhone pass',()=>{
 const r=evaluateTrustedCutover(signed({...original,verification:{
  ...verified,five_live_meta_after_reopen:true,real_iphone_roundtrip_pass:true
 }}));
 assert.equal(r.cutover_allowed,true);
 assert.equal(r.readiness,true);
 assert.equal(r.reason,'ACCEPTED');
});
test('invalid counts and missing signatures fail-closed without leaking secrets',()=>{
 refused({...original,source:{...source,profiles:-1}},'MANIFEST_SCHEMA_INVALID');
 const r=evaluateTrustedCutover({payload:original,signature:'0'.repeat(64),key:SECRET});
 assert.equal(r.cutover_allowed,false);
 assert.doesNotMatch(JSON.stringify(r),/TEST_Only/);
});
