/**
 * Owner-private, read-only Steel session inventory preflight.
 *
 * Work/owner may run this in a trusted service with STEEL_API_KEY already
 * securely configured. It performs GET only: NEVER creates, releases,
 * recovers, adopts or renews a Steel session.
 *
 * A clean UI history or an empty "live" list is NOT a full saved-close
 * receipt, source admission freeze, proof of provider profile READY, or
 * authenticated third-party browser account.
 *
 * Do not log session IDs, account data, tokens, provider URLs with secrets,
 * cookies or contents of provider API errors.
 */
const API='https://api.steel.dev/v1';
const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const PAGE_LIMIT=100,MAX_PAGES=100,MAX_RESPONSE_BYTES=2000000;
const deny=code=>{throw Error(code)};
const safeId=v=>typeof v==='string'&&UUID.test(v);
const parsedCursor=v=>{
 if(v===null||v===undefined||v==='')return null;
 if(!safeId(v))deny('STEEL_INVENTORY_CURSOR_INVALID');
 return v.toLowerCase();
};
async function boundedResponse(response){
 const n=response.headers?.get?.('content-length');
 if(n!==null&&n!==undefined&&(!/^[0-9]+$/.test(n)||Number(n)>MAX_RESPONSE_BYTES))
  deny('STEEL_INVENTORY_RESPONSE_TOO_LARGE');
 if(!response.body||typeof response.body.getReader!=='function')
  deny('STEEL_INVENTORY_INVALID_RESPONSE');
 const reader=response.body.getReader(),chunks=[];let bytes=0;
 try{
  for(;;){
   const {done,value}=await reader.read();
   if(done)break;
   bytes+=value.byteLength;
   if(bytes>MAX_RESPONSE_BYTES)deny('STEEL_INVENTORY_RESPONSE_TOO_LARGE');
   chunks.push(value);
  }
  const out=new Uint8Array(bytes);let o=0;
  for(const c of chunks){out.set(c,o);o+=c.length}
  let payload;
  try{payload=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(out))}
  catch{deny('STEEL_INVENTORY_INVALID_JSON')}
  if(!payload||typeof payload!=='object'||Array.isArray(payload))
   deny('STEEL_INVENTORY_INVALID_RESPONSE');
  return payload;
 }finally{try{await reader.cancel()}catch{};try{reader.releaseLock()}catch{}}
}
export function createSteelReadonlyClient({apiKey,request=fetch,now=()=>new Date()}={}){
 if(typeof apiKey!=='string'||apiKey.length<24||apiKey.length>1024||
    /[\r\n]/.test(apiKey)||typeof request!=='function')
  deny('STEEL_INVENTORY_AUTH_UNAVAILABLE');
 async function get(path,params){
  if(path!=='/sessions'||!params||typeof params!=='object')
   deny('STEEL_INVENTORY_ROUTE_DENIED');
  const q=new URLSearchParams();
  q.set('limit',String(PAGE_LIMIT));
  if(params.status!==undefined){
   if(params.status!=='live')deny('STEEL_INVENTORY_STATUS_DENIED');
   q.set('status','live');
  }
  if(params.cursorId!==undefined){
   if(!safeId(params.cursorId))deny('STEEL_INVENTORY_CURSOR_INVALID');
   q.set('cursorId',params.cursorId);
  }
  let result;
  try{
   result=await request(API+path+'?'+q.toString(),{
    method:'GET',redirect:'error',
    headers:{'steel-api-key':apiKey},
    signal:AbortSignal.timeout(12000)
   });
  }catch{deny('STEEL_INVENTORY_HTTP_UNCONFIRMED')}
  if(result.status===429)deny('STEEL_INVENTORY_RATE_LIMITED');
  if(result.status===401||result.status===403)deny('STEEL_INVENTORY_ACCESS_DENIED');
  if(result.status!==200)deny('STEEL_INVENTORY_HTTP_UNCONFIRMED');
  const body=await boundedResponse(result);
  if(!Array.isArray(body.sessions)||body.sessions.length>PAGE_LIMIT)
   deny('STEEL_INVENTORY_INVALID_RESPONSE');
  return body;
 }
 async function emptyLive(){
  const body=await get('/sessions',{status:'live'});
  if(body.sessions.length!==0||body.nextCursor||body.nextCursorId)
   deny('STEEL_INVENTORY_LIVE_OR_AMBIGUOUS');
 }
 async function inspect(){
  // The two independent live checks intentionally bracket the full list.
  await emptyLive();
  const seen=new Set(),statuses={released:0,failed:0};
  let cursor,stopped=false,pages=0;
  for(let index=0;index<MAX_PAGES;index++){
   const params=cursor?{cursorId:cursor}:{};
   const page=await get('/sessions',params);
   pages++;
   if(page.sessions.length===0){
    if(page.nextCursor||page.nextCursorId)
     deny('STEEL_INVENTORY_PAGINATION_CONFLICT');
    stopped=true;break;
   }
   for(const r of page.sessions){
    if(!r||typeof r!=='object'||Array.isArray(r)||!safeId(r.id))
     deny('STEEL_INVENTORY_INVALID_SESSION');
    const id=r.id.toLowerCase();
    if(seen.has(id))deny('STEEL_INVENTORY_DUPLICATE_SESSION');
    seen.add(id);
    if(r.status!=='released'&&r.status!=='failed')
     deny('STEEL_INVENTORY_ACTIVE_OR_UNKNOWN_SESSION');
    statuses[r.status]++;
   }
   const last=page.sessions.at(-1).id.toLowerCase();
   const advertised=parsedCursor(page.nextCursor??page.nextCursorId);
   cursor=advertised||last;
   if(cursor===params.cursorId)deny('STEEL_INVENTORY_PAGINATION_CONFLICT');
   // A truncated or inconsistent page is not a reason to assume complete.
   // Always request the empty terminal page.
  }
  if(!stopped)deny('STEEL_INVENTORY_PAGE_LIMIT');
  await emptyLive();
  const observed=now();
  if(!(observed instanceof Date)||!Number.isFinite(observed.getTime()))
   deny('STEEL_INVENTORY_CLOCK_INVALID');
  return Object.freeze({
   status:'STEEL_READONLY_HISTORY_IDLE',
   observed_at:observed.toISOString(),
   total:seen.size,pages,
   released:statuses.released,failed:statuses.failed,
   live_sessions:0,
   selected_organization_verified:false,
   exact_quarantined_session_reconciled:false,
   saved_close_verified:false,
   source_frozen:false,
   provider_import_freeze_signed:false,
   production_cutover_allowed:false
  });
 }
 return {inspect};
}
