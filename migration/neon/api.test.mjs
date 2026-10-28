import {strict as assert} from 'node:assert';
import {createHash} from 'node:crypto';
import {test} from 'node:test';
import {createApi} from './api/core.mjs';

const TOKEN='x'.repeat(40);
const SHA=createHash('sha256').update(TOKEN).digest('hex');
const BASE='https://stage.example.test';
const calls=[];
async function db(op,args){
 calls.push({op,args});
 if(op==='status')return {mode:'staging_read_only',write_enabled:false,profile_count:0,
     archive_count:0,task_count:0,lease_count:0};
 if(op==='profile_list')return [{name:'Acceptance-Test',updatedAt:'2026-10-28T11:00:00Z'}];
 if(op==='profile_get')return args.name==='Acceptance-Test'?
    {encryptedState:'synthetic-encrypted',updatedAt:'2026-10-28T11:00:00Z'}:null;
 if(op==='engine_get')return {providerProfileId:'00000000-0000-4000-8000-000000000009',
    hydrated:false};
 if(op==='task_list')return [];
 if(op==='task_get')return null;
 throw Error('FAULT_PRIVATE_DO_NOT_ECHO');
}
const api=createApi({database:db,tokenSha256:SHA});
const guest=createApi({database:db,tokenSha256:''});
const req=(path,method='GET',token=TOKEN,body)=>new Request(BASE+path,{
 method,headers:{authorization:'Bearer '+token,...(body===undefined?{}:{'content-type':'application/json'})},
 ...(body===undefined?{}:{body:JSON.stringify(body)})
});
test('health reports neither auth nor profile restored',async()=>{
 for(const a of [api,guest]){
  const r=await a.fetch(new Request(BASE+'/health'));
  const v=await r.json();
  assert.equal(r.status,200);
  assert.equal(v.write_enabled,false);
  assert.equal(v.browser_available,false);
  assert.equal(v.profile_restored,false);
  assert.equal(r.headers.get('cache-control'),'no-store');
  assert.equal(r.headers.get('access-control-allow-origin'),null);
 }
});
test('HEAD health has no payload',async()=>{
 const r=await api.fetch(new Request(BASE+'/health',{method:'HEAD'}));
 assert.equal(r.status,200);
 assert.equal(await r.text(),'');
});
test('missing digest fails closed even for an otherwise valid token',async()=>{
 const r=await guest.fetch(req('/_api/stage/status'));
 assert.equal(r.status,503);
 assert.equal((await r.json()).error,'NEON_STAGING_NOT_CONFIGURED');
});
test('rejects missing and incorrect bearer before any DB operation',async()=>{
 const count=calls.length;
 const a=await api.fetch(new Request(BASE+'/_api/profile-vault'));
 const b=await api.fetch(req('/_api/profile-vault','GET','wrong'.repeat(12)));
 assert.equal(a.status,401);
 assert.equal(b.status,401);
 assert.equal(calls.length,count);
});
test('authenticated stage status exposes counts but no profiles',async()=>{
 const r=await api.fetch(req('/_api/stage/status'));
 const v=await r.json();
 assert.equal(r.status,200);
 assert.equal(v.stage.mode,'staging_read_only');
 assert.equal(v.stage.profile_count,0);
});
test('authenticated existing metadata and exact encrypted fixture are bound',async()=>{
 const list=await api.fetch(req('/_api/profile-vault'));
 assert.equal(list.status,200);
 assert.equal((await list.json()).profiles[0].name,'Acceptance-Test');
 const r=await api.fetch(req('/_api/profile-vault?profile=Acceptance-Test'));
 assert.equal(r.status,200);
 assert.equal((await r.json()).state,'synthetic-encrypted');
});
test('invalid profile and unsupported staging routes refuse',async()=>{
 const x=await api.fetch(req('/_api/profile-vault?profile=../evil'));
 assert.equal(x.status,400);
 assert.equal((await api.fetch(req('/_api/profile-vault?profile=Missing'))).status,404);
 assert.equal((await api.fetch(req('/_api/unknown'))).status,503);
});
test('engine get never reports synthetic authentication',async()=>{
 const r=await api.fetch(req('/_api/engine-profile?profile=Acceptance-Test'));
 const j=await r.json();
 assert.equal(j.hydrated,false);
});
test('durable list/get are read-only and partitioned by owner digest',async()=>{
 const l=await api.fetch(req('/_api/task-vault','POST',TOKEN,{action:'list'}));
 assert.equal(l.status,200);
 assert.deepEqual((await l.json()).tasks,[]);
 const record=calls[calls.length-1];
 assert.equal(record.op,'task_list');
 assert.equal(record.args.owner,SHA);
 const id='00000000-0000-4000-8000-000000000001';
 const g=await api.fetch(req('/_api/task-vault','POST',TOKEN,{action:'get',task_id:id}));
 assert.equal(g.status,404);
 assert.equal((await g.json()).error,'not_found');
});
test('task mutations and profile writes are blocked even with valid bearer',async()=>{
 const start=calls.length;
 for(const route of ['/_api/profile-vault','/_api/engine-profile',
 '/_api/provider-recovery','/mcp','/owner-mobile/login']){
  const r=await api.fetch(req(route,'POST',TOKEN,{action:'save'}));
  assert.equal(r.status,503);
  assert.equal((await r.json()).write_enabled,false);
 }
 for(const action of ['create','claim','save','release','attest','delete']){
  const r=await api.fetch(req('/_api/task-vault','POST',TOKEN,{action}));
  assert.equal(r.status,503);
 }
 assert.equal(calls.length,start);
});
test('database errors are redacted, no exception trace or private text',async()=>{
 const failing=createApi({tokenSha256:SHA,database:async()=>{throw Error('PRIVATE_PASSWORD_DO_NOT_LEAK')}});
 const r=await failing.fetch(req('/_api/stage/status'));
 assert.equal(r.status,503);
 assert.doesNotMatch(await r.text(),/PRIVATE_PASSWORD|Traceback|stack/i);
});
test('request body bounds refuse giant client-controlled data',async()=>{
 const body='X'.repeat(311000);
 const r=await api.fetch(new Request(BASE+'/_api/task-vault',{
  method:'POST',
  headers:{authorization:'Bearer '+TOKEN,'content-type':'application/json'},
  body:JSON.stringify({action:'list',extra:body})
 }));
 assert.equal(r.status,413);
});
test('invalid task ID and invalid body are not hidden successes',async()=>{
 let r=await api.fetch(req('/_api/task-vault','POST',TOKEN,{action:'get',task_id:'a'}));
 assert.equal(r.status,400);
 r=await api.fetch(req('/_api/task-vault','POST',TOKEN,{action:'list'}));
 assert.equal(r.status,200);
});
