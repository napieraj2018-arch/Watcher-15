import {test} from 'node:test';
import {strict as assert} from 'node:assert';
import {createHash} from 'node:crypto';
import {createPrimaryApi} from './api/primary_core.mjs';
import {VaultMutationError,validateVaultMutation} from './api/write_policy.mjs';
const TOKEN='S'.repeat(54);
const DIGEST=createHash('sha256').update(TOKEN).digest('hex');
const ID='00000000-0000-4000-8000-000000000004';
const OWNER=DIGEST;
const URL='https://neon-primary-fixture.invalid';
const req=(url,method='GET',body,token=TOKEN)=>{
 const headers={Authorization:'Bearer '+token};
 if(body!==undefined)headers['Content-Type']='application/json';
 return new Request(URL+url,{method,headers,
  ...(body===undefined?{}:{body:JSON.stringify(body)})});
};
function fixture({allowed=true,throwWrite=false}={}){
 const calls=[];
 const read=async (operation,payload)=>{
  calls.push({kind:'read',operation,payload});
  if(operation==='profile_list')return [{name:'Synthetic-Profile',updatedAt:'2026-10-28T09:00:00.000Z'}];
  if(operation==='profile_get')return payload.name==='Synthetic-Profile'?
   {encryptedState:'SYNTHETIC_TEST_ENCRYPTED_V1',updatedAt:'2026-10-28T09:00:00.000Z',
    ciphertextSha256:createHash('sha256').update('SYNTHETIC_TEST_ENCRYPTED_V1').digest('hex')}:null;
  if(operation==='engine_get')return {providerProfileId:ID,hydrated:true};
  if(operation==='task_list')return [];
  if(operation==='task_get')return payload.id===ID?
   {taskId:ID,revision:1,encryptedState:'TEST_TASK_CIPHERTEXT_V1',resumable:true,queued:false}:null;
  if(operation==='status')return {epoch:42,write_enabled:true};
  if(operation==='recovery_inspect')return {ok:true,pending:false,
   configured:true,verified:true,gate_id:'00000000-0000-4000-8000-000000000012'};
  throw Error('READ_PRIVATE_SECRET_MUST_NOT_LEAK');
 };
 const mutate=async (operation,payload,owner)=>{
  calls.push({kind:'mutation',operation,owner,
   shape:Object.keys(payload).sort()});
  if(throwWrite)throw Error('PRIVATE_DATABASE_PASSWORD_MUST_NOT_LEAK');
  validateVaultMutation(operation,payload);
  if(operation==='profile_save')return {ok:true,profile:payload.profile};
  if(operation==='engine_bind')return {ok:true};
  if(operation==='task_claim')return {ok:true,task:{taskId:payload.task_id,revision:1}};
  if(operation==='task_create')return {ok:true,revision:1};
  if(operation==='task_checkpoint')return {ok:true,revision:2};
  if(operation==='task_release')return {ok:true,revision:2};
  throw Error('UNEXPECTED_MUTATION');
 };
 const admission=async()=>{calls.push({kind:'gate'});return allowed};
 return {calls,api:createPrimaryApi({read,mutate,admission,tokenSha256:DIGEST})};
}
test('public health is a candidate, never claims profiles/logins ready',async()=>{
 const {api}=fixture();
 const r=await api.fetch(new Request(URL+'/health'));
 assert.equal(r.status,200);
 const j=await r.json();
 assert.equal(j.browser_available,false);
 assert.equal(j.operational_write_verified,false);
 assert.equal(r.headers.get('cache-control'),'no-store');
 assert.equal(r.headers.has('access-control-allow-origin'),false);
});
test('missing configured secret refuses even valid-looking bearer',async()=>{
 const api=createPrimaryApi({admission:async()=>true,tokenSha256:''});
 const r=await api.fetch(req('/_api/profile-vault'));
 assert.equal(r.status,503);
});
test('unauthorized request never touches the admission gate or database',async()=>{
 const {api,calls}=fixture();
 assert.equal((await api.fetch(new Request(URL+'/_api/profile-vault'))).status,401);
 assert.equal((await api.fetch(req('/_api/profile-vault','GET',undefined,'X'.repeat(54)))).status,401);
 assert.equal(calls.length,0);
});
test('migration admission refusal blocks both read and write',async()=>{
 const {api,calls}=fixture({allowed:false});
 const x=await api.fetch(req('/_api/profile-vault'));
 assert.equal(x.status,503);
 assert.equal((await x.json()).error,'NEON_CUTOVER_NOT_ACCEPTED');
 const y=await api.fetch(req('/_api/profile-vault','POST',
  {profile:'Synthetic-Profile',state:'NOT_REAL_CIPHERTEXT_12345',expected_sha256:null}));
 assert.equal(y.status,503);
 assert.equal(calls.filter(c=>c.kind==='mutation').length,0);
 assert.equal(calls.filter(c=>c.kind==='read').length,0);
});
test('owner profile read returns exact-compatible JSON only after admission',async()=>{
 const {api,calls}=fixture();
 const list=await api.fetch(req('/_api/profile-vault'));
 assert.equal(list.status,200);
 assert.equal((await list.json()).profiles[0].name,'Synthetic-Profile');
 const state=await api.fetch(req('/_api/profile-vault?profile=Synthetic-Profile'));
 assert.equal(state.status,200);
 assert.equal((await state.json()).state,'SYNTHETIC_TEST_ENCRYPTED_V1');
 const again=await api.fetch(req('/_api/profile-vault?profile=Synthetic-Profile'));
 assert.equal((await again.json()).sha256,
  createHash('sha256').update('SYNTHETIC_TEST_ENCRYPTED_V1').digest('hex'));
 assert.ok(calls.some(c=>c.operation==='profile_get'&&c.payload.name==='Synthetic-Profile'));
});
test('unverified profile ciphertext readback never exposes a CAS baseline',async()=>{
 const read=async()=>({encryptedState:'SYNTHETIC_ENCRYPTED_VALUE',
  updatedAt:'2026-10-28T09:00:00.000Z',ciphertextSha256:'a'.repeat(64)});
 const api=createPrimaryApi({read,mutate:async()=>{throw Error('NO_WRITES')},
  admission:async()=>true,tokenSha256:DIGEST});
 const response=await api.fetch(req('/_api/profile-vault?profile=Neutral-Only'));
 assert.equal(response.status,503);
 const data=await response.json();
 assert.equal(data.error,'PROFILE_READBACK_UNVERIFIED');
 assert.equal(data.state,undefined);
});
test('profile write fails closed without explicit expected SHA',async()=>{
 const {api}=fixture();
 const r=await api.fetch(req('/_api/profile-vault','POST',
  {profile:'Synthetic-Profile',state:'ENCRYPTED_TEST_STATE_12345'}));
 assert.equal(r.status,400);
 assert.equal((await r.json()).error,'expected_profile_hash_invalid');
});
test('owner profile write with CAS is correctly mapped, owner hash scoped',async()=>{
 const {api,calls}=fixture();
 const r=await api.fetch(req('/_api/profile-vault','POST',{
  action:'save',profile:'Synthetic-Profile',state:'ENCRYPTED_TEST_STATE_12345',
  expected_sha256:'a'.repeat(64)
 }));
 assert.equal(r.status,200);
 assert.equal((await r.json()).ok,true);
 const w=calls.find(c=>c.kind==='mutation');
 assert.equal(w.operation,'profile_save');
 assert.equal(w.owner,OWNER);
 assert.deepEqual(w.shape.sort(),['expected_sha256','profile','state']);
});
test('profile delete explicitly forbidden without side effects',async()=>{
 const {api,calls}=fixture();
 const r=await api.fetch(req('/_api/profile-vault','POST',
  {action:'delete',profile:'Synthetic-Profile'}));
 assert.equal(r.status,403);
 assert.equal(calls.filter(c=>c.kind==='mutation').length,0);
});
test('engine GET and POST route without provider side effects',async()=>{
 const {api,calls}=fixture();
 const g=await api.fetch(req('/_api/engine-profile?profile=Synthetic-Profile'));
 assert.equal(g.status,200);
 assert.equal((await g.json()).profile_id,ID);
 const w=await api.fetch(req('/_api/engine-profile','POST',
  {profile:'Synthetic-Profile',profile_id:ID,hydrated:true}));
 assert.equal(w.status,200);
 assert.equal(calls.filter(c=>c.operation==='engine_bind').length,1);
});
test('durable task list and get are read-only owner-partitioned',async()=>{
 const {api,calls}=fixture();
 const a=await api.fetch(req('/_api/task-vault','POST',{action:'list'}));
 assert.equal(a.status,200);
 assert.deepEqual((await a.json()).tasks,[]);
 const b=await api.fetch(req('/_api/task-vault','POST',{action:'get',task_id:ID}));
 assert.equal(b.status,200);
 assert.equal((await b.json()).task.taskId,ID);
 const listCall=calls.find(c=>c.operation==='task_list');
 assert.equal(listCall.payload.owner,OWNER);
});
test('claim and checkpoint mutation require real CAS/revision contracts',async()=>{
 const {api,calls}=fixture();
 const claim=await api.fetch(req('/_api/task-vault','POST',
  {action:'claim',task_id:ID,claim:'C'.repeat(48)}));
 assert.equal(claim.status,200);
 const saved=await api.fetch(req('/_api/task-vault','POST',{
  action:'save',task_id:ID,claim:'C'.repeat(48),expected_revision:1,
  state:'SYNTHETIC_ENCRYPTED_CHECKPOINT',resumable:true,queued:false
 }));
 assert.equal(saved.status,200);
 assert.equal((await saved.json()).revision,2);
 assert.equal(calls.filter(c=>c.operation==='task_checkpoint').length,1);
 const outdated=await api.fetch(req('/_api/task-vault','POST',{
  action:'save',task_id:ID,claim:'C'.repeat(48),expected_revision:0,
  state:'SYNTHETIC_ENCRYPTED_CHECKPOINT',resumable:true
 }));
 assert.equal(outdated.status,400);
 assert.equal((await outdated.json()).error,'revision_invalid');
});
test('unsupported recovery/attempt functions never fabricate success',async()=>{
 const {api,calls}=fixture();
 for(const path of ['/_api/provider-recovery','/_api/account-attempt']){
  const r=await api.fetch(req(path,'POST',{action:'complete'}));
  assert.equal(r.status,503);
 }
 assert.equal(calls.filter(c=>c.kind==='mutation').length,0);
});
test('unknown actions, invalid profiles and huge requests fail',async()=>{
 const {api}=fixture();
 assert.equal((await api.fetch(req('/_api/profile-vault?profile=..%2Fevil'))).status,400);
 assert.equal((await api.fetch(req('/_api/task-vault','POST',
  {action:'delete',task_id:ID}))).status,400);
 const big=new Request(URL+'/_api/task-vault',{method:'POST',
  headers:{Authorization:'Bearer '+TOKEN,'Content-Type':'application/json'},
  body:JSON.stringify({action:'list',padding:'X'.repeat(311000)})});
 assert.equal((await api.fetch(big)).status,413);
});
test('provider DB errors redact sensitive strings and return only status',async()=>{
 const {api}=fixture({throwWrite:true});
 const r=await api.fetch(req('/_api/profile-vault','POST',{
  profile:'Synthetic-Profile',state:'ENCRYPTED_TEST_STATE_12345',expected_sha256:null
 }));
 assert.equal(r.status,503);
 assert.doesNotMatch(await r.text(),/PRIVATE_DATABASE_PASSWORD|stack|secret/i);
});
test('invalid JSON content-type rejected before writer is reached',async()=>{
 const {api,calls}=fixture();
 const r=await api.fetch(new Request(URL+'/_api/task-vault',{
  method:'POST',headers:{Authorization:'Bearer '+TOKEN,'Content-Type':'text/plain'},
  body:'{action:list}' }));
 assert.equal(r.status,415);
 assert.equal(calls.filter(c=>c.kind==='mutation').length,0);
});

test('provider recovery inspect is owner only and read-only',async()=>{
 const {api,calls}=fixture();
 const r=await api.fetch(req('/_api/provider-recovery','POST',{action:'inspect'}));
 assert.equal(r.status,200);
 const j=await r.json();
 assert.equal(j.ok,true);
 assert.equal(j.pending,false);
 assert.equal(j.verified,true);
 assert.equal(calls.filter(x=>x.operation==='recovery_inspect').length,1);
 assert.equal(calls.filter(x=>x.kind==='mutation').length,0);
});
test('provider recovery attest requires independently verified implementation',async()=>{
 const {api,calls}=fixture();
 const r=await api.fetch(req('/_api/provider-recovery','POST',
  {action:'attest',gate_id:'00000000-0000-4000-8000-000000000012',proof:{saved:true}}));
 assert.equal(r.status,503);
 assert.equal(calls.filter(x=>x.kind==='mutation').length,0);
});
