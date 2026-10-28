import {strict as assert} from 'node:assert';
import {test} from 'node:test';
import {createHash} from 'node:crypto';
import {createWriterStore} from './api/write_store.mjs';
import {VaultMutationError} from './api/write_policy.mjs';

const PROFILE='Acceptance-Neutral';
const STATE='encrypted-only-synthetic-text-123456789';
const ID='00000000-0000-4000-8000-000000000007';
const OWNER='b'.repeat(64),CLAIM='T'.repeat(48),PROOF='Z'.repeat(48);
const sha=v=>createHash('sha256').update(v).digest('hex');
const ACCEPTED={
 epoch:2,source_frozen:true,owner_reconciled:true,
 source_manifest_verified:true,destination_manifest_verified:true,
 proof_sha256:sha(PROOF)
};
const recv=[];
function fakeDb(mode='staging_read_only',proof=PROOF,config=ACCEPTED){
 const calls=[];
 const tx=(strings,...args)=>{
  const query=strings.join('?');
  calls.push({query,args});
  if(query.includes('SELECT mode,write_enabled'))
   return Promise.resolve([{mode,write_enabled:mode==='neon_primary'}]);
  if(query.includes('SELECT config_value'))
   return Promise.resolve([{config_value:JSON.stringify(config)}]);
  if(query.includes('INSERT INTO browser_profiles'))
   return Promise.resolve([{profile_name:PROFILE}]);
  if(query.includes('UPDATE browser_task_checkpoints'))
   return Promise.resolve([]);
  return Promise.resolve([]);
 };
 const sql={begin:async(fn)=>fn(tx)};
 return {write:createWriterStore(sql,{proof}),calls};
}
async function denied(work,code){
 await assert.rejects(work,e=>e instanceof VaultMutationError&&e.code===code);
}
test('no proof => cannot create even if future DB metadata claims cutover',async()=>{
 const calls=[];
 const sql={begin:async(fn)=>fn((strings,...args)=>{
  calls.push(strings.join('?'));return Promise.resolve([])})};
 const write=createWriterStore(sql,{});
 await denied(()=>write('profile_save',{profile:PROFILE,state:STATE},OWNER),
   'NEON_CUTOVER_NOT_ACCEPTED');
 assert.equal(calls.length,0);
});
test('staging guard blocks every mutation before any SQL write',async()=>{
 const {write,calls}=fakeDb();
 await denied(()=>write('profile_save',{profile:PROFILE,state:STATE},OWNER),
   'NEON_CUTOVER_NOT_ACCEPTED');
 assert.equal(calls.filter(x=>/INSERT INTO|UPDATE\s+browser_|DELETE FROM/.test(x.query)).length,0);
});
test('wrong secret denies even with cutover flags present',async()=>{
 const {write,calls}=fakeDb('neon_primary',PROOF,{...ACCEPTED,proof_sha256:sha('OTHER')});
 await denied(()=>write('profile_save',{profile:PROFILE,state:STATE},OWNER),
   'NEON_CUTOVER_NOT_ACCEPTED');
 assert.equal(calls.filter(x=>x.query.includes('INSERT INTO')).length,0);
});
test('missing manifest verifies reject before a provider-side mutation',async()=>{
 for(const key of ['source_manifest_verified','destination_manifest_verified',
   'source_frozen','owner_reconciled']){
  const {write,calls}=fakeDb('neon_primary',PROOF,{...ACCEPTED,[key]:false});
  await denied(()=>write('profile_save',{profile:PROFILE,state:STATE},OWNER),
   'NEON_CUTOVER_NOT_ACCEPTED');
  assert.equal(calls.filter(x=>x.query.includes('INSERT INTO')).length,0);
 }
});
test('accepted synthetic profile save uses parameterized SQL only',async()=>{
 const {write,calls}=fakeDb('neon_primary');
 const r=await write('profile_save',{profile:PROFILE,state:STATE},OWNER);
 assert.equal(r.ok,true);
 assert.equal(r.unchanged,false);
 const row=calls.find(x=>x.query.includes('INSERT INTO browser_profiles'));
 assert.deepEqual(row.args,[PROFILE,STATE]);
 assert.ok(row.query.includes('IS DISTINCT FROM EXCLUDED.encrypted_state'));
 assert.ok(!row.query.includes(STATE));
});
test('task claim busy never returns a false success',async()=>{
 const {write}=fakeDb('neon_primary');
 await denied(()=>write('task_claim',{task_id:ID,claim:CLAIM},OWNER),
   'task_busy_or_recovery_required');
});
test('task release requires revision and resumable=true in SQL',async()=>{
 const {write,calls}=fakeDb('neon_primary');
 await denied(()=>write('task_release',{task_id:ID,claim:CLAIM,expected_revision:5},OWNER),
   'conflict_or_unsafe_release');
 const q=calls.find(x=>x.query.includes('UPDATE browser_task_checkpoints'));
 assert.ok(q.query.includes('AND resumable=true'));
 assert.ok(q.query.includes('AND revision='));
 assert.ok(q.query.includes('claim_expires_at>now()'));
 assert.ok(!q.query.includes(CLAIM));
});
test('interrupted durable task cannot silently resume on a stale write',async()=>{
 const {write,calls}=fakeDb('neon_primary');
 await denied(()=>write('task_checkpoint',{
  task_id:ID,claim:CLAIM,expected_revision:9,state:STATE,
  resumable:true},OWNER),'revision_or_claim_conflict');
 const row=calls.find(x=>x.query.includes('UPDATE browser_task_checkpoints'));
 assert.ok(row.query.includes('(resumable=true OR ?=false)'));
});
test('unsupported provider release and account deletion can never run',async()=>{
 const {write,calls}=fakeDb('neon_primary');
 await denied(()=>write('provider_release',{session_id:ID},OWNER),'mutation_not_supported');
 await denied(()=>write('profile_delete',{profile:PROFILE},OWNER),'mutation_not_supported');
 assert.equal(calls.length,0);
});
test('no private proof is sent to database in plaintext',async()=>{
 const {write,calls}=fakeDb('neon_primary');
 await write('profile_save',{profile:PROFILE,state:STATE},OWNER);
 const joined=JSON.stringify(calls);
 assert.ok(!joined.includes(PROOF));
 assert.ok(!joined.includes(CLAIM));
});
