import {test} from 'node:test';
import {strict as assert} from 'node:assert';
import {createSteelReadonlyClient} from './bridge/steel_inventory_readonly.mjs';

const TOKEN='NEUTRAL_KEY_FOR_TEST_ONLY_'.repeat(3);
const PROJECT='verified-steel-project-12345';
const ID=n=>'00000000-0000-4000-8000-'+String(n).padStart(12,'0');
const sess=(n,status='released')=>({id:ID(n),status,projectId:PROJECT});
const json=(body,status=200)=>new Response(JSON.stringify(body),{status,headers:{'content-type':'application/json'}});
const u=url=>new URL(url);
const bad=(fn,code)=>assert.rejects(fn,e=>e?.message===code);

function mock({pages=[Array.from({length:40},(_,i)=>sess(i+1)),[]],
 live=[],laterLive=[],status=200,broken=false}={}){
 const calls=[];
 let liveCalls=0,historyCalls=0;
 const request=async (url,opts)=>{
  calls.push({url,opts});
  const p=u(url);
  if(p.searchParams.has('status')){
   liveCalls++;
   const sessions=liveCalls===1?live:laterLive;
   return json({sessions,nextCursor:null,totalCount:sessions.length});
  }
  if(status!==200)return json({error:'private-response-MUST-NOT-LOG'},status);
  const next=pages[historyCalls++];
  if(broken)return json({not_sessions:true});
  if(next===undefined)return json({sessions:[],nextCursor:null});
  const nextCursor=historyCalls<pages.length&&next.length?next.at(-1).id:null;
  return json({sessions:next,nextCursor});
 };
 return {calls,create:()=>createSteelReadonlyClient({
  apiKey:TOKEN,projectId:PROJECT,request,now:()=>new Date('2026-10-29T11:39:00.000Z')
 })};
}
test('two live checks bracket all history and return aggregate only',async()=>{
 const m=mock(),r=await m.create().inspect();
 assert.equal(r.status,'STEEL_READONLY_HISTORY_IDLE');
 assert.equal(r.total,40);
 assert.equal(r.released,40);
 assert.equal(r.failed,0);
 assert.equal(r.live_sessions,0);
 assert.equal(r.saved_close_verified,false);
 assert.equal(r.source_frozen,false);
 assert.equal(r.production_cutover_allowed,false);
 assert.equal(r.observed_at,'2026-10-29T11:39:00.000Z');
 assert.equal(m.calls.length,4);
 assert.ok(m.calls.every(x=>x.opts.method==='GET'));
 assert.ok(m.calls.every(x=>x.opts.headers['steel-api-key']===TOKEN));
 assert.ok(m.calls.filter(x=>u(x.url).searchParams.has('status'))
  .every(x=>!u(x.url).searchParams.has('projectId')));
 assert.ok(m.calls.filter(x=>!u(x.url).searchParams.has('status'))
  .every(x=>u(x.url).searchParams.get('projectId')===PROJECT));
 const text=JSON.stringify(r);
 assert.doesNotMatch(text,/00000000-|NEUTRAL_KEY|cookie|token/i);
});
test('pagination completes only after a separate empty terminal page',async()=>{
 const first=Array.from({length:100},(_,i)=>sess(i+1));
 const second=Array.from({length:30},(_,i)=>sess(i+101));
 const m=mock({pages:[first,second,[]]});
 const r=await m.create().inspect();
 assert.equal(r.total,130);
 assert.equal(r.pages,3);
 assert.equal(m.calls.length,5);
 assert.equal(u(m.calls[2].url).searchParams.get('cursorId'),ID(100));
 assert.equal(u(m.calls[3].url).searchParams.get('cursorId'),ID(130));
});
test('live session at beginning denies before any history read',async()=>{
 const m=mock({live:[sess(1000,'live')]});
 await bad(()=>m.create().inspect(),'STEEL_INVENTORY_LIVE_OR_AMBIGUOUS');
 assert.equal(m.calls.length,1);
});
test('race: live session after history rejects and does not issue a freeze',async()=>{
 const m=mock({laterLive:[sess(2000,'live')]});
 await bad(()=>m.create().inspect(),'STEEL_INVENTORY_LIVE_OR_AMBIGUOUS');
});
test('active, unexpected or transient statuses in history deny',async()=>{
 for(const status of ['live','starting','completed','releasing','unknown',null]){
  const m=mock({pages:[[sess(2,status)],[]]});
  await bad(()=>m.create().inspect(),'STEEL_INVENTORY_ACTIVE_OR_UNKNOWN_SESSION');
 }
});
test('duplicate ID on a later page is refused even if state changes',async()=>{
 const m=mock({pages:[[sess(1)], [sess(1,'failed')],[]]});
 await bad(()=>m.create().inspect(),'STEEL_INVENTORY_DUPLICATE_SESSION');
});
test('provider pagination cycle is denied',async()=>{
 const m=mock({pages:[[sess(1)],[sess(1)]]});
 await bad(()=>m.create().inspect(),'STEEL_INVENTORY_DUPLICATE_SESSION');
});
test('failed released sessions counted but not promoted to saved-close',async()=>{
 const m=mock({pages:[[sess(1,'failed'),sess(2)],[]]});
 const r=await m.create().inspect();
 assert.equal(r.failed,1);assert.equal(r.released,1);
 assert.equal(r.saved_close_verified,false);
});
test('rate limit, authentication denial and unexpected HTTP are fixed-code errors',async()=>{
 for(const [status,expected] of [
  [429,'STEEL_INVENTORY_RATE_LIMITED'],
  [401,'STEEL_INVENTORY_ACCESS_DENIED'],
  [403,'STEEL_INVENTORY_ACCESS_DENIED'],
  [502,'STEEL_INVENTORY_HTTP_UNCONFIRMED']
 ]){
  const m=mock();
  const r=async()=>json({secret:'NEVER_ECHO_PASSWORD'},status);
  await bad(()=>createSteelReadonlyClient({apiKey:TOKEN,projectId:PROJECT,request:r}).inspect(),expected);
 }
});
test('malformed JSON envelope never gives a false idle result',async()=>{
 const m=mock({broken:true});
 await bad(()=>m.create().inspect(),'STEEL_INVENTORY_INVALID_RESPONSE');
});
test('wrong pagination cursor format is rejected',async()=>{
 const m=mock();
 const request=async(url)=>{
  if(u(url).searchParams.has('status'))return json({sessions:[],nextCursor:null,totalCount:0});
  return json({sessions:[sess(1)],nextCursor:'not-a-uuid'});
 };
 await bad(()=>createSteelReadonlyClient({apiKey:TOKEN,projectId:PROJECT,request}).inspect(),
  'STEEL_INVENTORY_CURSOR_INVALID');
});
test('bad response byte declarations block unbounded reads',async()=>{
 const req=async()=>new Response('x',{status:200,headers:{'content-length':'5000000'}});
 await bad(()=>createSteelReadonlyClient({apiKey:TOKEN,request:req}).inspect(),
  'STEEL_INVENTORY_RESPONSE_TOO_LARGE');
});
test('no real secret, no network or POST accepted without valid key',()=>{
 for(const token of ['', 'short', 'X\nA'.repeat(15)]){
  assert.throws(()=>createSteelReadonlyClient({apiKey:token}),
    /STEEL_INVENTORY_AUTH_UNAVAILABLE/);
 }
});
test('failed HTTP transports are redacted and not retried',async()=>{
 let calls=0;
 const request=async()=>{calls++;throw Error('PROVIDER_SECRET_SHOULD_NOT_LEAK')};
 await bad(()=>createSteelReadonlyClient({apiKey:TOKEN,request}).inspect(),
  'STEEL_INVENTORY_HTTP_UNCONFIRMED');
 assert.equal(calls,1);
});

test('project must be explicit, not inferred from organization or UI label',()=>{
 assert.throws(()=>createSteelReadonlyClient({apiKey:TOKEN,request:async()=>{}}),
  /STEEL_INVENTORY_PROJECT_UNVERIFIED/);
 assert.throws(()=>createSteelReadonlyClient({apiKey:TOKEN,projectId:'',request:async()=>{}}),
  /STEEL_INVENTORY_PROJECT_UNVERIFIED/);
});
test('provider returning a different project is rejected before returning idle',async()=>{
 const m=mock({pages:[[{...sess(1),projectId:'other-project'}]]});
 await bad(()=>m.create().inspect(),'STEEL_INVENTORY_WRONG_PROJECT');
});
test('no nextCursor metadata is uncertain, not a complete history',async()=>{
 const request=async(url)=>u(url).searchParams.has('status')
  ?json({sessions:[],nextCursor:null,totalCount:0})
  :json({sessions:[sess(1)]});
 await bad(()=>createSteelReadonlyClient({apiKey:TOKEN,projectId:PROJECT,request}).inspect(),
  'STEEL_INVENTORY_INVALID_RESPONSE');
});
test('provider null nextCursor ends history without guessing extra pages',async()=>{
 const m=mock({pages:[[sess(1),sess(2)]]});
 const r=await m.create().inspect();
 assert.equal(r.total,2);
 assert.equal(r.pages,1);
 assert.equal(m.calls.length,3);
});
test('project history count mismatch is an error, not complete inventory',async()=>{
 const request=async(url)=>{
  if(u(url).searchParams.has('status'))return json({sessions:[],nextCursor:null,totalCount:0});
  return json({sessions:[sess(1)],nextCursor:null,totalCount:2});
 };
 await bad(()=>createSteelReadonlyClient({apiKey:TOKEN,projectId:PROJECT,request}).inspect(),
  'STEEL_INVENTORY_PAGINATION_CONFLICT');
});
test('filtered live totalCount nonzero denies even if first page looks empty',async()=>{
 const request=async()=>json({sessions:[],nextCursor:null,totalCount:1});
 await bad(()=>createSteelReadonlyClient({apiKey:TOKEN,projectId:PROJECT,request}).inspect(),
  'STEEL_INVENTORY_LIVE_OR_AMBIGUOUS');
});
test('empty project history with a forward cursor is ambiguous',async()=>{
 const request=async(url)=>{
  if(u(url).searchParams.has('status'))return json({sessions:[],nextCursor:null,totalCount:0});
  return json({sessions:[],nextCursor:ID(1)});
 };
 await bad(()=>createSteelReadonlyClient({apiKey:TOKEN,projectId:PROJECT,request}).inspect(),
  'STEEL_INVENTORY_PAGINATION_CONFLICT');
});
