import {test} from 'node:test';
import {strict as assert} from 'node:assert';
import {createHash} from 'node:crypto';
import {createAssetApi} from './assets/core.mjs';
const sha=v=>createHash('sha256').update(v).digest('hex');
const token='NeutralTestToken'.repeat(4);
const env={
 AIB_ASSET_TOKEN_SHA256:sha(token),
 AWS_ACCESS_KEY_ID:'test_neon_scoped_id_123456',
 AWS_SECRET_ACCESS_KEY:'secret-do-not-use-in-production-neon-fixture-123',
 AWS_ENDPOINT_URL_S3:'https://br-ancient-firefly-baqgm1x0.storage.c-8.eu-central-1.aws.neon.tech',
 AWS_REGION:'eu-central-1'
};
const base='https://assets.neon.test';
const req=(path,method='GET',headers={authorization:'Bearer '+token})=>
 new Request(base+path,{method,headers});
const body=Buffer.concat([Buffer.from('AIBSRC1'),Buffer.alloc(5,99)]);
const asset={'/v1/core':{key:'bootstrap/core-v041.aib',size:body.length,
 sha256:sha(body),magic:'AIBSRC1'}};
test('public health leaks no account identifiers or credentials',async()=>{
 const api=createAssetApi({env:{}});
 const r=await api.fetch(req('/health'));
 assert.equal(r.status,200);
 const s=await r.text();
 assert.doesNotMatch(s,/secret|AWS|profile_name|floot/i);
});
test('missing configured digest fails closed without any S3 request',async()=>{
 let calls=0;
 const api=createAssetApi({env:{...env,AIB_ASSET_TOKEN_SHA256:''},
  fetcher:async()=>{calls++;throw Error('MUST_NOT_FETCH')}});
 const r=await api.fetch(req('/v1/core'));
 assert.equal(r.status,503);assert.equal(calls,0);
});
test('anonymous and wrong token rejected before storage access',async()=>{
 let calls=0;
 const api=createAssetApi({env,fetcher:async()=>{calls++;throw Error('MUST_NOT_FETCH')}});
 assert.equal((await api.fetch(req('/v1/core','GET',{}))).status,401);
 assert.equal((await api.fetch(req('/v1/core','GET',{authorization:'Bearer '+'X'.repeat(40)}))).status,401);
 assert.equal(calls,0);
});
test('mutations, unknown paths and query strings refused',async()=>{
 let calls=0;
 const api=createAssetApi({env,fetcher:async()=>{calls++;throw Error('MUST_NOT_FETCH')}});
 for(const r of [req('/v1/core','POST'),req('/v1/missing'),req('/v1/core?key=evil')])
  assert.equal((await api.fetch(r)).status,404);
 assert.equal(calls,0);
});
test('exact immutable synthetic bytes are returned with signed private S3 request',async()=>{
 const calls=[];
 const api=createAssetApi({env,clock:()=>new Date('2026-10-29T09:00:00.000Z'),assets:asset,
  fetcher:async(u,opts)=>{
   calls.push({u,method:opts.method,headers:opts.headers});
   return new Response(new Uint8Array(body),{status:200});
  }});
 const r=await api.fetch(req('/v1/core'));
 assert.equal(r.status,200);
 assert.deepEqual(Buffer.from(await r.arrayBuffer()),body);
 assert.equal(calls.length,1);
 assert.equal(calls[0].method,'GET');
 assert.equal(new URL(calls[0].u).pathname,'/aib-runtime-recovery/bootstrap/core-v041.aib');
 assert.equal(calls[0].headers.authorization.startsWith('AWS4-HMAC-SHA256 Credential='),true);
 assert.ok(!calls[0].u.includes('floot'));
});
test('mutated storage bytes and oversized responses are rejected',async()=>{
 const b=Buffer.from(body);b[b.length-1]^=1;
 const invalid=createAssetApi({env,assets:asset,fetcher:async()=>new Response(b,{status:200})});
 assert.equal((await invalid.fetch(req('/v1/core'))).status,503);
 const large=createAssetApi({env,assets:asset,
  fetcher:async()=>new Response(Buffer.concat([body,Buffer.from('X')]),{status:200})});
 assert.equal((await large.fetch(req('/v1/core'))).status,503);
});
test('unexpected endpoint environment cannot exfiltrate S3 signatures',async()=>{
 let calls=0;
 const api=createAssetApi({env:{...env,AWS_ENDPOINT_URL_S3:'https://example.org'},
  fetcher:async()=>{calls++;throw Error('NOPE')}});
 assert.equal((await api.fetch(req('/v1/core'))).status,503);
 assert.equal(calls,0);
});
