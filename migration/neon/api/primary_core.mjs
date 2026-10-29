/**
 * Candidate of the owner-only Neon JSON API that replaces existing Floot
 * routes after a separately verified one-writer migration.
 *
 * NOT DEPLOYED, NOT ENABLED while Neon is staging_read_only.
 * The injected admission check MUST verify database-side active epoch and
 * signed source/provider migration proof on the same trusted server.
 * The injected writer independently fences every transaction.
 */
import {createHash,timingSafeEqual} from 'node:crypto';
import {VaultMutationError} from './write_policy.mjs';
import {validateRecoveryInspection} from './recovery_protocol.mjs';
const PROFILE=/^[A-Za-z0-9][A-Za-z0-9._ -]{0,63}$/;
const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const DIGEST=/^[a-f0-9]{64}$/;
const HEADERS=Object.freeze({
 'content-type':'application/json; charset=utf-8',
 'cache-control':'no-store',
 'x-content-type-options':'nosniff',
 'referrer-policy':'no-referrer'
});
function answer(value,status=200){
 return new Response(JSON.stringify(value),{status,headers:HEADERS});
}
function ownerToken(request,digest){
 const auth=request.headers.get('authorization')||'';
 if(auth.length>650||!/^Bearer [\x21-\x7e]{32,512}$/.test(auth))return null;
 const hash=createHash('sha256').update(auth.slice(7)).digest();
 if(!DIGEST.test(digest)||
   !timingSafeEqual(hash,Buffer.from(digest,'hex')))return null;
 return hash.toString('hex');
}
async function boundedJson(request,maxBytes){
 if((request.headers.get('content-type')||'').split(';')[0].trim().toLowerCase()!=='application/json')
  return {error:'json_required',status:415};
 const header=request.headers.get('content-length');
 if(header!==null&&(!/^[0-9]+$/.test(header)||Number(header)>maxBytes))
  return {error:'body_too_large',status:413};
 if(!request.body)return {error:'body_required',status:400};
 let size=0;const chunks=[];const reader=request.body.getReader();
 try{
  for(;;){const {done,value}=await reader.read();if(done)break;
   size+=value.byteLength;if(size>maxBytes)return {error:'body_too_large',status:413};
   chunks.push(value);
  }
  if(!size)return {error:'invalid_json',status:400};
  const all=new Uint8Array(size);let off=0;
  for(const c of chunks){all.set(c,off);off+=c.byteLength;}
  const data=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(all));
  if(data===null||typeof data!=='object'||Array.isArray(data))
   return {error:'invalid_json',status:400};
  return {data};
 }catch{return {error:'invalid_json',status:400}}
 finally{try{await reader.cancel()}catch{};try{reader.releaseLock()}catch{}}
}
const STATUS=Object.freeze({error:'NEON_CUTOVER_NOT_ACCEPTED',write_enabled:false});
function isUuid(id){return typeof id==='string'&&UUID.test(id)}
function isProfile(id){return typeof id==='string'&&PROFILE.test(id)}
function errorResult(exc){
 if(exc instanceof VaultMutationError &&
   typeof exc.code==='string'&&/^[A-Za-z0-9_]{3,90}$/.test(exc.code) &&
   [400,403,409,503].includes(exc.status))
  return answer({error:exc.code},exc.status);
 return answer({error:'NEON_OPERATION_UNCONFIRMED'},503);
}
async function guarded(admission){
 try{return await admission()===true}catch{return false}
}
/**
 * read(op,params) is a separately fenced Neon primary read client.
 * mutate(operation,payload,ownerHash) is the transactional CAS writer.
 * No browser capability, Steel state or recovery proof comes from HTTP body.
 */
export function createPrimaryApi({read,mutate,admission,tokenSha256}={}){
 const configured=typeof read==='function'&&typeof mutate==='function'&&
  typeof admission==='function'&&typeof tokenSha256==='string'&&
  DIGEST.test(tokenSha256);
 return {async fetch(request){
  let url;
  try{url=new URL(request.url)}catch{return answer({error:'invalid_request'},400)}
  if(request.method==='GET'&&url.pathname==='/health')
   return answer({status:'candidate_only',source:'neon',browser_available:false,
    operational_write_verified:false},200);
  if(!configured)return answer({error:'NEON_PRIMARY_NOT_CONFIGURED'},503);
  const owner=ownerToken(request,tokenSha256);
  if(!owner)return answer({error:'unauthorized'},401);
  // Unsigned migrations or lost admission deliberately disable read AND write.
  if(!(await guarded(admission)))return answer(STATUS,503);
  const method=request.method,path=url.pathname;
  try{
   if(path==='/__owner/primary-status'&&method==='GET'){
    return answer({ok:true,stage:await read('status',{owner})});
   }
   if(path==='/_api/profile-vault'){
    if(method==='GET'){
     const name=url.searchParams.get('profile');
     if(name===null||name==='')return answer({profiles:await read('profile_list',{owner})});
     if(!isProfile(name))return answer({error:'invalid_profile'},400);
     const row=await read('profile_get',{owner,name});
     return row?answer({state:row.encryptedState,updatedAt:row.updatedAt}):
       answer({error:'not_found'},404);
    }
    if(method==='POST'){
     const body=await boundedJson(request,8200000);
     if(!body.data)return answer({error:body.error},body.status);
     if(body.data.action==='delete')return answer({error:'delete_not_supported'},403);
     if(body.data.action!==undefined&&body.data.action!=='save')
      return answer({error:'invalid_action'},400);
     // Never infer expected_sha256 by reading and filling it on behalf of
     // a stale controller; profile state CAS is compulsory.
     const payload={
      profile:body.data.profile,state:body.data.state,
      expected_sha256:body.data.expected_sha256
     };
     const saved=await mutate('profile_save',payload,owner);
     return answer(saved);
    }
   }
   if(path==='/_api/engine-profile'){
    if(method==='GET'){
     const profile=url.searchParams.get('profile');
     if(!isProfile(profile))return answer({error:'invalid_profile'},400);
     const r=await read('engine_get',{owner,name:profile});
     return answer({profile_id:r?.providerProfileId??null,hydrated:r?.hydrated===true});
    }
    if(method==='POST'){
     const body=await boundedJson(request,1024);
     if(!body.data)return answer({error:body.error},body.status);
     const result=await mutate('engine_bind',body.data,owner);
     return answer(result);
    }
   }
   if(path==='/_api/task-vault'&&method==='POST'){
    const body=await boundedJson(request,310000);
    if(!body.data)return answer({error:body.error},body.status);
    const b=body.data;
    if(b.action==='list')
     return answer({ok:true,tasks:await read('task_list',{owner})});
    if(b.action==='get'){
     if(!isUuid(b.task_id))return answer({error:'task_required'},400);
     const t=await read('task_get',{owner,id:b.task_id});
     return t?answer({ok:true,task:t}):answer({error:'not_found'},404);
    }
    if(!isUuid(b.task_id))return answer({error:'task_required'},400);
    const map={create:'task_create',claim:'task_claim',
     save:'task_checkpoint',release:'task_release'};
    const kind=map[b.action];
    if(!kind)return answer({error:'invalid_action'},400);
    const payload={...b};
    delete payload.action;
    // Unsupported extras cannot silently change the verified SQL contract.
    const result=await mutate(kind,payload,owner);
    return answer(result);
   }
   // Recovery INSPECT is read-only and only reflects an imported, externally
   // attested provider gate; pending attest writes remain deliberately blocked.
   if(path==='/_api/provider-recovery'&&method==='POST'){
    const body=await boundedJson(request,4096);
    if(!body.data)return answer({error:body.error},body.status);
    if(body.data.action!=='inspect')return answer(STATUS,503);
    return answer(validateRecoveryInspection(await read('recovery_inspect',{owner})));
   }
   if(path==='/_api/account-attempt')return answer(STATUS,503);
   return answer({error:'not_found'},404);
  }catch(e){return errorResult(e)}
 }};
}
