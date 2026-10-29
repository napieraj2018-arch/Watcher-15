/**
 * AI Browser shadow-vault API: first-stage authenticated READ ONLY.
 * No real profile mutation, claim, login, provider, session or deletion routes.
 * One authority at a time. Floot remains the production writer.
 */
import {createHash, timingSafeEqual} from 'node:crypto';

const PROFILE=/^[A-Za-z0-9][A-Za-z0-9._ -]{0,63}$/;
const UUID=/^[a-f0-9]{8}-[a-f0-9]{4}-[1-8][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/i;
const DIGEST=/^[a-f0-9]{64}$/;
const HEADERS=Object.freeze({
 'content-type':'application/json; charset=utf-8',
 'cache-control':'no-store',
 'x-content-type-options':'nosniff',
 'referrer-policy':'no-referrer'
});
function answer(body,status=200){return new Response(JSON.stringify(body),{status,headers:HEADERS})}
function auth(request,hash){
 const line=request.headers.get('authorization')||'';
 if(!line.startsWith('Bearer ')||line.length>1024) return null;
 const token=line.slice(7);
 if(!/^[\x21-\x7e]{32,512}$/.test(token))return null;
 const candidate=createHash('sha256').update(token).digest();
 const reference=Buffer.from(hash,'hex');
 return timingSafeEqual(candidate,reference)?createHash('sha256').update(token).digest('hex'):null;
}
async function boundedJson(request,maxBytes){
 if(request.headers.get('content-type')?.split(';',1)[0]?.trim().toLowerCase()!=='application/json')
  return {error:'json_required',status:415};
 const declared=request.headers.get('content-length');
 if(declared!==null&&(!/^\d+$/.test(declared)||Number(declared)>maxBytes))
  return {error:'invalid_content_length',status:413};
 if(!request.body)return {error:'body_required',status:400};
 const reader=request.body.getReader();let total=0;const chunks=[];
 try{
  for(;;){
   const {done,value}=await reader.read();if(done)break;
   total+=value.byteLength;
   if(total>maxBytes){try{await reader.cancel()}catch{}return {error:'too_large',status:413}}
   chunks.push(value);
  }
  if(total===0)return {error:'invalid_json',status:400};
  const bytes=new Uint8Array(total);let o=0;
  for(const ch of chunks){bytes.set(ch,o);o+=ch.byteLength}
  const data=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes));
  return data&&!Array.isArray(data)&&typeof data==='object'?{data}:{error:'invalid_json',status:400};
 }catch{return {error:'invalid_json',status:400}}
 finally{try{reader.releaseLock()}catch{}}
}
const DECLINED=Object.freeze({
 error:'NEON_STAGING_WRITE_DISABLED',browser_available:false,
 write_enabled:false
});
export function createApi({database,tokenSha256}){
 const configured=typeof database==='function'&&typeof tokenSha256==='string'&&DIGEST.test(tokenSha256);
 return {async fetch(request){
  let url;
  try{url=new URL(request.url)}catch{return answer({error:'invalid_request'},400)}
  const path=url.pathname,method=request.method;
  if(path==='/health'&&method==='HEAD')return new Response(null,{status:200,headers:HEADERS});
  if(path==='/health'&&method==='GET')return answer({
   status:'staging_locked',browser_available:false,write_enabled:false,
   profile_restored:false,source:'floot',storage_backend:'neon_staging'});
  if(!configured)return answer({error:'NEON_STAGING_NOT_CONFIGURED',
      browser_available:false,write_enabled:false},503);
  const owner=auth(request,tokenSha256);
  if(!owner)return answer({error:'unauthorized'},401);
  // Never accept a write, even if a future DB guard has been misconfigured.
  if(method!=='GET'&&!(path==='/_api/task-vault'&&method==='POST'))
    return answer(DECLINED,503);
  try{
   if(method==='GET'&&path==='/_api/stage/status'){
    return answer({ok:true,stage:await database('status')});
   }
   if(method==='GET'&&path==='/_api/profile-vault'){
    const name=url.searchParams.get('profile');
    if(!name)return answer({profiles:await database('profile_list')});
    if(!PROFILE.test(name))return answer({error:'invalid_profile'},400);
    const row=await database('profile_get',{name});
    return row?answer({state:row.encryptedState,updatedAt:row.updatedAt}):
      answer({error:'not_found'},404);
   }
   if(method==='GET'&&path==='/_api/engine-profile'){
    const name=url.searchParams.get('profile');
    if(!name||!PROFILE.test(name))return answer({error:'invalid_profile'},400);
    const row=await database('engine_get',{name});
    return answer({profile_id:row?.providerProfileId??null,hydrated:row?.hydrated===true});
   }
   if(method==='POST'&&path==='/_api/task-vault'){
    const parsed=await boundedJson(request,310000);
    if(!parsed.data)return answer({error:parsed.error},parsed.status);
    const body=parsed.data;
    if(body.action==='list'){
      const rows=await database('task_list',{owner});
      return answer({ok:true,tasks:rows});
    }
    if(body.action==='get'){
      if(typeof body.task_id!=='string'||!UUID.test(body.task_id))
       return answer({error:'task_required'},400);
      const row=await database('task_get',{owner,id:body.task_id});
      return row?answer({ok:true,task:row}):answer({error:'not_found'},404);
    }
    return answer(DECLINED,503);
   }
   return answer(DECLINED,503);
  }catch{return answer({error:'NEON_STAGE_DB_UNCONFIRMED',browser_available:false,write_enabled:false},503)}
 }};
}
