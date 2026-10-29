import {test} from 'node:test';
import {strict as assert} from 'node:assert';
import {validateRecoveryInspection} from './api/recovery_protocol.mjs';
const ID='00000000-0000-4000-8000-000000000011';
const OWNER='00000000-0000-4000-8000-000000000012';
const BASE={ok:true,pending:false,configured:true,verified:true,gate_id:ID};
const validPending={ok:true,pending:true,gate:{
 version:1,gate_id:ID,session_id:ID,profile_id:OWNER,profile_name:'Neutral-Test',
 pending:true},local:{safe:false,profile_count:68}};
test('only verified and configured imported clear receipt is accepted',()=>{
 assert.deepEqual(validateRecoveryInspection(BASE),{
  ok:true,pending:false,verified:true,gate_id:ID
 });
});
test('no imported config cannot masquerade as a cleared provider gate',()=>{
 for(const bad of [
  {ok:true,pending:false,configured:false,verified:true,gate_id:ID},
  {ok:true,pending:false,configured:true,verified:false,gate_id:ID},
  {ok:true,pending:false,configured:true,verified:true,gate_id:'invalid'},
  {ok:true,pending:false},{ok:true,pending:0},{ok:false,pending:false},
  null,{},[],{pending:false}
 ]){
  assert.throws(()=>validateRecoveryInspection(bad),/RECOVERY_READBACK_UNVERIFIED/);
 }
});
test('pending recovery is preserved without inventing success',()=>{
 assert.deepEqual(validateRecoveryInspection(validPending),validPending);
 const safe={...validPending,local:{safe:true,control_leases:0}};
 const v=validateRecoveryInspection(safe);
 assert.equal(v.pending,true);assert.equal(v.local.safe,true);
});
test('invalid provider plan is denied before presenting a false saved-close receipt',()=>{
 for(const change of [
  {version:2},{session_id:'bad'},{profile_id:'bad'},
  {pending:false},{profile_name:'x'.repeat(65)},
  {gate_id:'not-a-uuid'}
 ]){
  const invalid={...validPending,gate:{...validPending.gate,...change}};
  assert.throws(()=>validateRecoveryInspection(invalid),/RECOVERY_READBACK_UNVERIFIED/);
 }
});
test('recovery inspection does not mutate or return arbitrary sensitive fields',()=>{
 const v=validateRecoveryInspection({...BASE,secret:'DO_NOT_LEAK'});
 assert.equal(v.secret,undefined);
 assert.equal(Object.keys(v).length,4);
});
