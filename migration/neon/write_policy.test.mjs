import {strict as assert} from 'node:assert';
import {test} from 'node:test';
import {validateVaultMutation,rejectUnsafeWriteGate,VaultMutationError,
  validateOwnerHash,allowedMutationNames} from './api/write_policy.mjs';

const UID='00000000-0000-4000-8000-000000000011';
const CLAIM='Q'.repeat(48);
const STATE='ciphertext_only_synthetic_marker_2026';
const validGate={mode:'neon_primary',write_enabled:true,source_frozen:true,
  owner_reconciled:true,source_manifest_verified:true,
  destination_manifest_verified:true,epoch:2};
function denied(fn,code){
 assert.throws(fn,e=>e instanceof VaultMutationError&&e.code===code);
}
test('writer rejects all stage, missing and half-accepted migrations',()=>{
 for(const key of Object.keys(validGate)){
  const altered={...validGate};
  altered[key]=key==='mode'?'staging_read_only':key==='epoch'?0:false;
  denied(()=>rejectUnsafeWriteGate(altered),'NEON_CUTOVER_NOT_ACCEPTED');
 }
 denied(()=>rejectUnsafeWriteGate(null),'NEON_CUTOVER_NOT_ACCEPTED');
 assert.doesNotThrow(()=>rejectUnsafeWriteGate(validGate));
});
test('owner identity must be the authenticated 64-char digest',()=>{
 denied(()=>validateOwnerHash('Meta - Maciej'),'invalid_owner');
 denied(()=>validateOwnerHash('a'.repeat(63)),'invalid_owner');
 assert.equal(validateOwnerHash('a'.repeat(64)),'a'.repeat(64));
});
test('only exact operations are available; nothing deletes profiles',()=>{
 assert.deepEqual(allowedMutationNames(),['profile_save','engine_bind','task_create',
   'task_claim','task_checkpoint','task_release']);
 for(const name of ['profile_delete','provider_recovery_attest','lease_steal',
   'restore_archive','override_source','mfa_bypass','run_login']){
  denied(()=>validateVaultMutation(name,{}),'mutation_not_supported');
 }
});
test('profile save validates exact name and encrypted-only bounded input',()=>{
 assert.deepEqual(validateVaultMutation('profile_save',{profile:'Neutral-test',state:STATE}),
  {profile:'Neutral-test',state:STATE});
 for(const profile of ['', '../another', 'Meta/Login', '\nTest',
  'long'.repeat(50)]){
  denied(()=>validateVaultMutation('profile_save',{profile,state:STATE}),'invalid_profile');
 }
 denied(()=>validateVaultMutation('profile_save',{profile:'Neutral',state:'x'}),'state_invalid');
 denied(()=>validateVaultMutation('profile_save',{
  profile:'Neutral',state:'x'.repeat(8000001)}),'state_invalid');
 denied(()=>validateVaultMutation('profile_save',{
  profile:'Neutral',state:STATE,unknown:'WRITE'}),'unsupported_field');
});
test('engine binds are explicit UUID and cannot set arbitrary fields',()=>{
 assert.equal(validateVaultMutation('engine_bind',{
  profile:'Neutral',profile_id:UID}).hydrated,false);
 denied(()=>validateVaultMutation('engine_bind',{
  profile:'Neutral',profile_id:'fake'}),'invalid_task_id');
 denied(()=>validateVaultMutation('engine_bind',{
  profile:'Neutral',profile_id:UID,hydrated:'yes'}),'flag_required');
});
test('task creation, claim, CAS and release validate precise requirements',()=>{
 assert.equal(validateVaultMutation('task_create',{
  task_id:UID,state:STATE,claim:CLAIM}).task_id,UID);
 assert.equal(validateVaultMutation('task_claim',{
  task_id:UID,claim:CLAIM}).claim,CLAIM);
 assert.equal(validateVaultMutation('task_checkpoint',{
  task_id:UID,claim:CLAIM,expected_revision:5,state:STATE,resumable:true}).queued,false);
 assert.equal(validateVaultMutation('task_release',{
  task_id:UID,claim:CLAIM,expected_revision:2}).expected_revision,2);
 denied(()=>validateVaultMutation('task_claim',{task_id:UID,claim:'weak'}),
   'claim_invalid');
 denied(()=>validateVaultMutation('task_checkpoint',{
  task_id:UID,claim:CLAIM,expected_revision:0,state:STATE,resumable:true}),
  'revision_invalid');
 denied(()=>validateVaultMutation('task_checkpoint',{
  task_id:UID,claim:CLAIM,expected_revision:1,state:STATE,resumable:'true'}),
  'flag_required');
 denied(()=>validateVaultMutation('task_release',{
  task_id:UID,claim:CLAIM,expected_revision:1,force:true}),
  'unsupported_field');
});
