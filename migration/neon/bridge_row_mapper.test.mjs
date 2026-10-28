import {strict as assert} from 'node:assert';
import {test} from 'node:test';
import {normalizeShadowRecord,shadowSummary} from './bridge/row_mapper.mjs';
const state='SYNTHETIC_ENCRYPTED_ONLY_PAYLOAD_20261028';
const now='2026-10-28T13:00:00.000Z';
const profile={profile_name:'Acceptance-Neutral',updated_at:now,
 encrypted_state:state};
const archive={...profile,id:'4318',source_updated_at:now,
 archived_at:'2026-10-28T13:15:00.000Z',reason:'protected_forensic_4318'};
const task={task_id:'00000000-0000-4000-8000-000000000007',
 owner_hash:'a'.repeat(64),claim_hash:'',claim_expires_at:null,
 encrypted_state:state,revision:159,updated_at:now,created_at:now,
 resumable:true,queued:false};
test('profile archives pass only ciphertext, hashed privately',()=>{
 const x=normalizeShadowRecord('profile',profile);
 assert.equal(x.sourceKey,'Acceptance-Neutral');
 assert.equal(x.sourceUpdatedAt,now);
 assert.equal(x.encryptedState,state);
 assert.match(x.sourceSha256,/^[a-f0-9]{64}$/);
 assert.doesNotMatch(JSON.stringify(shadowSummary({profile:1,archive:0,task:0})),
   /SYNTHETIC_ENCRYPTED/);
});
test('protected archive retains original revision ID, reason and timestamps',()=>{
 const x=normalizeShadowRecord('archive',archive);
 assert.equal(x.sourceKey,'Acceptance-Neutral#4318');
 assert.equal(x.metadata.original_id,'4318');
 assert.equal(x.metadata.reason,archive.reason);
 assert.equal(x.metadata.archived_at,archive.archived_at);
});
test('task metadata preserves original revision without decrypted state',()=>{
 const x=normalizeShadowRecord('task',task);
 assert.equal(x.sourceKey,task.task_id);
 assert.equal(x.metadata.revision,159);
 assert.equal(x.metadata.owner_hash,task.owner_hash);
 assert.equal(x.metadata.resumable,true);
});
test('bad kinds and invalid input fail closed',()=>{
 for(const kind of ['engine','config','cookies','plain_password']){
  assert.throws(()=>normalizeShadowRecord(kind,profile),/SHADOW_KIND_UNSUPPORTED/);
 }
 assert.throws(()=>normalizeShadowRecord('profile',{...profile,encrypted_state:'x'}),
  /SHADOW_CIPHERTEXT_INVALID/);
 assert.throws(()=>normalizeShadowRecord('archive',{...archive,id:'../../secret'}),
  /SHADOW_SOURCE_ID_INVALID/);
 assert.throws(()=>normalizeShadowRecord('task',{...task,revision:0}),
  /SHADOW_TASK_REVISION_INVALID/);
});

test('PostgreSQL source microseconds are never rounded in a profile, archive or task',()=>{
 const raw='2026-10-28 13:00:00.123456+00';
 const profileRow=normalizeShadowRecord('profile',{...profile,updated_at:raw});
 assert.equal(profileRow.sourceUpdatedAt,raw);
 assert.equal(profileRow.metadata.source_updated_at,raw);
 const archiveRow=normalizeShadowRecord('archive',{
  ...archive,source_updated_at:raw,archived_at:raw
 });
 assert.equal(archiveRow.sourceUpdatedAt,raw);
 assert.equal(archiveRow.metadata.archived_at,raw);
 const taskRow=normalizeShadowRecord('task',{
  ...task,updated_at:raw,created_at:raw,claim_expires_at:raw
 });
 assert.equal(taskRow.sourceUpdatedAt,raw);
 assert.equal(taskRow.metadata.created_at,raw);
 assert.equal(taskRow.metadata.claim_expires_at,raw);
});
test('unknown precision must fail closed before any import',()=>{
 assert.throws(()=>normalizeShadowRecord('profile',{
  ...profile,updated_at:new Date(now)
 }),/SHADOW_SOURCE_TIMESTAMP_PRECISION_UNVERIFIED/);
 assert.throws(()=>normalizeShadowRecord('archive',{
  ...archive,archived_at:new Date(now)
 }),/SHADOW_SOURCE_TIMESTAMP_PRECISION_UNVERIFIED/);
 assert.throws(()=>normalizeShadowRecord('task',{
  ...task,claim_expires_at:'2026-10-28T13:00:00.1234567Z'
 }),/SHADOW_SOURCE_TIMESTAMP_PRECISION_UNVERIFIED/);
});
