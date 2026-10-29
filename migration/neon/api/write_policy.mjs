/** Owner-only vault mutation contract. PURE VALIDATION ONLY.
 * This module is not imported by the currently deployed staging Function.
 * A real writer requires independently accepted cutover AND DB fencing.
 */
export class VaultMutationError extends Error {
  constructor(code,status=409){super(code);this.name='VaultMutationError';this.code=code;this.status=status}
}
const NAME=/^[A-Za-z0-9][A-Za-z0-9._ -]{0,63}$/;
const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const SHA=/^[0-9a-f]{64}$/;
const MAX_STATE=8000000;
const MAX_TASK=300000;
const MAX_CLAIM=256;
const fail=(code,status)=>{throw new VaultMutationError(code,status)};
const has=(v,k)=>Object.prototype.hasOwnProperty.call(v,k);
const obj=x=>x!==null&&typeof x==='object'&&!Array.isArray(x);
function only(data,allow){
  if(!obj(data))fail('invalid_input',400);
  if(Object.keys(data).some(k=>!allow.includes(k)))fail('unsupported_field',400);
}
function name(v){if(typeof v!=='string'||!NAME.test(v))fail('invalid_profile',400);return v}
function uuid(v){if(typeof v!=='string'||!UUID.test(v))fail('invalid_task_id',400);return v}
function hash(v){if(typeof v!=='string'||!SHA.test(v))fail('invalid_owner',400);return v}
function secret(v,field){
  if(typeof v!=='string'||v.length<32||v.length>MAX_CLAIM||!(/^[\x21-\x7e]+$/).test(v))
    fail(field+'_invalid',400);
  return v;
}
function encrypted(v,limit){
  if(typeof v!=='string'||v.length<20||v.length>limit)fail('state_invalid',400);
  return v;
}
function revision(v){if(!Number.isSafeInteger(v)||v<=0)fail('revision_invalid',400);return v}
function flag(v){if(typeof v!=='boolean')fail('flag_required',400);return v}
function exact(data,allow){
  only(data,allow);
  for(const k of allow)if(!has(data,k))fail('missing_field',400);
}
export function validateVaultMutation(action,body){
  // Unsupported side effects are NEVER inferred from an ambiguous payload.
  if(action==='profile_save'){
    exact(body,['profile','state','expected_sha256']);
    const expected=body.expected_sha256;
    if(expected!==null&&(typeof expected!=='string'||!SHA.test(expected)))
      fail('expected_profile_hash_invalid',400);
    return {profile:name(body.profile),state:encrypted(body.state,MAX_STATE),
      expected_sha256:expected};
  }
  if(action==='engine_bind'){
    only(body,['profile','profile_id','hydrated']);
    if(!has(body,'profile')||!has(body,'profile_id'))fail('missing_field',400);
    return {profile:name(body.profile),profile_id:uuid(body.profile_id),
      hydrated:body.hydrated===undefined?false:flag(body.hydrated)};
  }
  if(action==='task_create'){
    exact(body,['task_id','state','claim']);
    return {task_id:uuid(body.task_id),state:encrypted(body.state,MAX_TASK),
      claim:secret(body.claim,'claim')};
  }
  if(action==='task_claim'){
    exact(body,['task_id','claim']);
    return {task_id:uuid(body.task_id),claim:secret(body.claim,'claim')};
  }
  if(action==='task_checkpoint'){
    only(body,['task_id','claim','expected_revision','state','resumable','queued']);
    for(const k of ['task_id','claim','expected_revision','state','resumable'])
      if(!has(body,k))fail('missing_field',400);
    return {task_id:uuid(body.task_id),claim:secret(body.claim,'claim'),
      expected_revision:revision(body.expected_revision),state:encrypted(body.state,MAX_TASK),
      resumable:flag(body.resumable),queued:body.queued===undefined?false:flag(body.queued)};
  }
  if(action==='task_release'){
    exact(body,['task_id','claim','expected_revision']);
    return {task_id:uuid(body.task_id),claim:secret(body.claim,'claim'),
      expected_revision:revision(body.expected_revision)};
  }
  // Profile deletion and provider session mutation cannot be inferred.
  fail('mutation_not_supported',403);
}
export function rejectUnsafeWriteGate(gate){
  // No trust in request data: caller must obtain gate in the same DB TX.
  if(!obj(gate)||gate.mode!=='neon_primary'||gate.write_enabled!==true
     ||gate.source_frozen!==true||gate.owner_reconciled!==true
     ||gate.source_manifest_verified!==true||gate.destination_manifest_verified!==true
     ||!Number.isSafeInteger(gate.epoch)||gate.epoch<1)
    fail('NEON_CUTOVER_NOT_ACCEPTED',503);
}
export function validateOwnerHash(owner){return hash(owner)}
export function allowedMutationNames(){
  return Object.freeze(['profile_save','engine_bind','task_create',
    'task_claim','task_checkpoint','task_release']);
}
