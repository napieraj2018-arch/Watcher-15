/**
 * Read-only private Neon boot asset gateway. Staging only until owner
 * configures a secret token digest, rechecks provider idle and approves cutover.
 * Exactly two immutable encrypted application packages; NEVER profile state.
 * The Neon branch injects scoped S3 credentials in its Function runtime.
 */
import {createHash,createHmac,timingSafeEqual} from 'node:crypto';

const ASSETS=Object.freeze({
 '/v1/core': Object.freeze({key:'bootstrap/core-v041.aib',
  size:48104,sha256:'9f489586db5043cea0fec3ca2f2b5025092268075f65ea53f86a7e4158a40e12',
  magic:'AIBSRC1'}),
 '/v1/repair': Object.freeze({key:'bootstrap/repair-v042.aib',
  size:12150,sha256:'3460cac9927fa8911659a73f5766524243f952f76adf446f287434becb550764',
  magic:'AIBRPR1'}),
});
const HEADERS={'cache-control':'no-store','x-content-type-options':'nosniff',
 'referrer-policy':'no-referrer'};
const DENY=Object.freeze({error:'BOOT_ASSET_UNAVAILABLE',browser_available:false});
const sha=v=>createHash('sha256').update(v).digest('hex');
const hmac=(key,data)=>createHmac('sha256',key).update(data).digest();
const reply=(body,status)=>new Response(JSON.stringify(body),{
 status,headers:{...HEADERS,'content-type':'application/json'}});
const serviceEndpoint='br-ancient-firefly-baqgm1x0.storage.c-8.eu-central-1.aws.neon.tech';
const base='https://'+serviceEndpoint;
const bucket='aib-runtime-recovery';

function configured(env){
 return env&&typeof env.AIB_ASSET_TOKEN_SHA256==='string'&&
  /^[a-f0-9]{64}$/.test(env.AIB_ASSET_TOKEN_SHA256)&&
  typeof env.AWS_ACCESS_KEY_ID==='string'&&env.AWS_ACCESS_KEY_ID.length>=12&&
  typeof env.AWS_SECRET_ACCESS_KEY==='string'&&env.AWS_SECRET_ACCESS_KEY.length>=16&&
  env.AWS_ENDPOINT_URL_S3?.replace(/\/$/,'')===base&&
  env.AWS_REGION==='eu-central-1';
}
function authorize(value,expected){
 if(typeof value!=='string'||value.length>650||
    !/^Bearer [\x21-\x7e]{32,512}$/.test(value))return false;
 const digest=Buffer.from(sha(value.slice(7)),'hex');
 return timingSafeEqual(digest,Buffer.from(expected,'hex'));
}
function signS3Get(env,key,at){
 const time=at.toISOString().replace(/[-:]|\.\d{3}/g,'');
 const day=time.slice(0,8),region=env.AWS_REGION;
 // Exact immutable key map, never URL parameters or user supplied paths.
 const uri='/'+[bucket,...key.split('/')].map(encodeURIComponent).join('/');
 const canonicalHeaders='host:'+serviceEndpoint+'\n'+
   'x-amz-content-sha256:UNSIGNED-PAYLOAD\nx-amz-date:'+time+'\n';
 const signedHeaders='host;x-amz-content-sha256;x-amz-date';
 const request=['GET',uri,'',canonicalHeaders,signedHeaders,'UNSIGNED-PAYLOAD'].join('\n');
 const scope=day+'/'+region+'/s3/aws4_request';
 const stringToSign=['AWS4-HMAC-SHA256',time,scope,sha(request)].join('\n');
 // Date-scoped key is derived for each request (never persisted).
 const keyDate=hmac(Buffer.from('AWS4'+env.AWS_SECRET_ACCESS_KEY),day);
 const correctKey=hmac(hmac(hmac(keyDate,region),'s3'),'aws4_request');
 const signature=hmac(correctKey,stringToSign).toString('hex');
 return {
  url:base+uri,
  headers:{
   'x-amz-date':time,
   'x-amz-content-sha256':'UNSIGNED-PAYLOAD',
   authorization:'AWS4-HMAC-SHA256 Credential='+env.AWS_ACCESS_KEY_ID+'/'+scope+
    ', SignedHeaders='+signedHeaders+', Signature='+signature
  }
 };
}
async function readAtMost(response,max){
 const reader=response.body?.getReader();
 if(!reader)throw Error('S3_NO_BODY');
 const chunks=[];let total=0;
 try{
  for(;;){
   const {done,value}=await reader.read();if(done)break;
   total+=value.byteLength;
   if(total>max)throw Error('S3_TOO_LARGE');
   chunks.push(Buffer.from(value));
  }
  return Buffer.concat(chunks,total);
 }finally{try{await reader.cancel()}catch{};try{reader.releaseLock()}catch{}}
}
export function createAssetApi({env,fetcher=fetch,clock=()=>new Date(),assets=ASSETS}){
 return {async fetch(request){
  let url;try{url=new URL(request.url)}catch{return reply(DENY,400)}
  if(request.method==='GET'&&url.pathname==='/health')
   return reply({status:'staging',browser_available:false,profiles_available:false},200);
  if(request.method!=='GET'||url.search||url.hash||
    !Object.hasOwn(assets,url.pathname))return reply(DENY,404);
  // Fail shut before requesting the private storage endpoint.
  if(!configured(env))return reply(DENY,503);
  if(!authorize(request.headers.get('authorization'),env.AIB_ASSET_TOKEN_SHA256))
   return reply({error:'unauthorized'},401);
  const asset=assets[url.pathname];if(!asset||asset.size>1000000)return reply(DENY,503);
  try{
   const signed=signS3Get(env,asset.key,clock());
   const r=await fetcher(signed.url,{method:'GET',headers:signed.headers,
     redirect:'error',signal:AbortSignal.timeout(10000)});
   if(r.status!==200)return reply(DENY,503);
   const len=r.headers.get('content-length');
   if(len!==null&&Number(len)>asset.size)return reply(DENY,503);
   const bytes=await readAtMost(r,asset.size);
   if(bytes.length!==asset.size||sha(bytes)!==asset.sha256||
      bytes.subarray(0,7).toString('ascii')!==asset.magic)return reply(DENY,503);
   return new Response(new Uint8Array(bytes),{status:200,headers:{
    ...HEADERS,'content-type':'application/octet-stream','content-length':String(bytes.length)
   }});
  }catch{return reply(DENY,503)}
 }};
}
