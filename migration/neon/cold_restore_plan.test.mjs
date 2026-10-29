import {test} from 'node:test';
import {strict as assert} from 'node:assert';
import {createHash,createHmac} from 'node:crypto';
import {gzipSync} from 'node:zlib';
import {planRestrictedColdRestore,expectedColdReceipt} from './bridge/cold_restore_plan.mjs';

const stamp='2026-10-29 01:14:48.986868+00';
const bid='00000000-0000-4000-8000-000000000001';
const secret='TEST_NEUTRAL_FREEZE_SIGNING_NOT_FOR_PRODUCTION_123456';
const name='Acceptance-20261023-R158';
const state='never-a-real-profile-ciphertext-synthetic-fixture';
const sha=x=>createHash('sha256').update(x).digest('hex');
const stage={mode:'staging_read_only',write_enabled:false,profile_count:0,
 engine_count:0,active_leases:0,inbox_ready:true};

function make(){
 const rows=[
 {table:'browser_profiles',row:{profile_name:name,encrypted_state:state,updated_at:stamp}},
 {table:'browser_engine_profiles',row:{profile_name:name,
   provider_profile_id:'00000000-0000-4000-8000-000000000021',
   updated_at:stamp,hydrated:true}},
 {table:'browser_task_checkpoints',row:{task_id:'00000000-0000-4000-8000-000000000023',
   owner_hash:'c'.repeat(64),revision:1,encrypted_state:state,claim_hash:'',
   claim_expires_at:null,resumable:true,queued:false,created_at:stamp,updated_at:stamp}},
 {table:'vault_config',row:{config_key:'synthetic',config_value:'not-a-token'}},
 {table:'browser_profile_events',row:{id:'42',profile_name:name,event_type:'save',
   created_at:stamp}}
 ];
 for(let i=0;i<41;i++){
  rows.push({table:'browser_profile_versions',row:{id:String(100+i),
   profile_name:name,encrypted_state:state,source_updated_at:stamp,
   archived_at:stamp,reason:i<20?'update':
     i<40?'forensic_r158_'+i:'pre_verified_recovery_20261023_160'}});
 }
 const counts=Object.fromEntries([
 'browser_profiles','browser_profile_versions','browser_engine_profiles',
 'browser_task_checkpoints','vault_config','browser_control_leases',
 'browser_account_attempts','browser_profile_events'].map(t=>[t,rows.filter(x=>x.table===t).length]));
 const middle=rows.map(r=>JSON.stringify(r)+'\n').join('');
 const rowSha=sha(middle);
 const head={format:'aib-cold-backup-v1',batch_id:bid,
 source:'floot',observed_at:stamp,snapshot:'repeatable_read',
 promotion_allowed:false,production_cutover:false};
 const zipped=gzipSync(JSON.stringify(head)+'\n'+middle+
 JSON.stringify({footer:true,counts,source_rows_sha256:rowSha})+'\n');
 const r={backup_id:bid,observed_at_text:stamp,private_object_key:'2026-10-29/source-vault-v1.jsonl.gz',
 object_sha256:sha(zipped),source_rows_sha256:rowSha,compressed_bytes:zipped.length,
 profile_count:counts.browser_profiles,archive_count:counts.browser_profile_versions,
 engine_count:counts.browser_engine_profiles,task_count:counts.browser_task_checkpoints,
 config_count:counts.vault_config,event_count:counts.browser_profile_events,
 protected_archive_count:21,imported_to_tables:false,production_cutover:false};
 const now=Math.floor(Date.now()/1000),freeze={
 batch_id:bid,source_frozen:true,saved_close_verified:true,
 provider_idle_verified:true,no_active_lease_verified:true,
 checkpoint_closed_verified:true,issued_at:now-20,expires_at:now+300};
 const values=[freeze.batch_id,freeze.source_frozen,freeze.saved_close_verified,
 freeze.provider_idle_verified,freeze.no_active_lease_verified,
 freeze.checkpoint_closed_verified,freeze.issued_at,freeze.expires_at];
 freeze.signature=createHmac('sha256',secret).update(JSON.stringify(values)).digest('hex');
 return {compressed:zipped,privateReceipt:r,freezeReceipt:freeze,
  freezeKey:secret,role:'aib_import_test_limited',stage};
}
const valid=()=>make();
test('positive synthetic fully signed plan maps all source categories',()=>{
 const p=planRestrictedColdRestore(valid());
 assert.equal(p.records.profile.length,1);
 assert.equal(p.records.archive.length,41);
 assert.equal(p.records.engine.length,1);
 assert.equal(p.records.task.length,1);
 assert.equal(p.records.config.length,1);
 assert.equal(p.records.event.length,1);
 assert.equal(p.summary.neutral_r158_protected,21);
 assert.equal(p.summary.restored_to_neon,false);
 assert.equal(p.summary.cutover_allowed,false);
 assert.equal(p.summary.source_snapshot_stale_until_fresh_delta,true);
});
test('missing signed proof refused without preparing data',()=>{
 const x=valid();delete x.freezeReceipt.signature;
 assert.throws(()=>planRestrictedColdRestore(x),/BRIDGE_FROZEN_RECEIPT_INVALID/);
});
test('unauthorized owner role fails before any data mutation',()=>{
 const x=valid();x.role='neondb_owner';
 assert.throws(()=>planRestrictedColdRestore(x),/COLD_RESTORE_ROLE_NOT_RESTRICTED/);
});
test('stage must remain protected, not neon_primary or with active leases',()=>{
 for(const delta of [{mode:'neon_primary'},{write_enabled:true},{active_leases:1}]){
  const x=valid();x.stage={...x.stage,...delta};
  assert.throws(()=>planRestrictedColdRestore(x),/BRIDGE_DESTINATION_NOT_FENCED/);
 }
});
test('signed batch mismatch fails without SQL import',()=>{
 const x=valid();x.privateReceipt.backup_id='00000000-0000-4000-8000-000000000009';
 assert.throws(()=>planRestrictedColdRestore(x),/COLD_RESTORE_PROVENANCE_CONFLICT/);
});
test('backup object digest must exactly match immutable receipt',()=>{
 const x=valid();x.privateReceipt.object_sha256='0'.repeat(64);
 assert.throws(()=>planRestrictedColdRestore(x),/COLD_BACKUP_BYTES_MISMATCH/);
});
test('missing configuration count or invalid receipt refused',()=>{
 const x=valid();x.privateReceipt.config_count=-1;
 assert.throws(()=>planRestrictedColdRestore(x),/COLD_RESTORE_COUNT_INVALID/);
 const y=valid();y.privateReceipt.imported_to_tables=true;
 assert.throws(()=>expectedColdReceipt(y.privateReceipt),/COLD_RESTORE_RECEIPT_INVALID/);
});
test('incorrect protected archive count fails the gate',()=>{
 const x=valid();x.privateReceipt.protected_archive_count=20;
 assert.throws(()=>planRestrictedColdRestore(x),/COLD_RESTORE_ARCHIVE_COUNT_CONFLICT/);
});
test('original R158 20/21 provenance cannot be faked by totals alone',()=>{
 const x=valid();
 // The original rolling/protected reason is bound to full row hash.
 const altered=Buffer.from(x.compressed);altered[50]^=1;
 assert.throws(()=>planRestrictedColdRestore({...x,compressed:altered}));
});
test('always fails when one current active source lease is recorded',()=>{
 const x=valid();x.privateReceipt.lease_count=1;
 assert.throws(()=>planRestrictedColdRestore(x),/COLD_BACKUP_COUNTS_MISMATCH/);
});
test('invalid path or false production receipt is rejected',()=>{
 for(const delta of [
 {private_object_key:'https://evil.example/backup.gz'},
 {production_cutover:true}
 ]){const x=valid();Object.assign(x.privateReceipt,delta);
  assert.throws(()=>planRestrictedColdRestore(x),/COLD_RESTORE_RECEIPT_INVALID/);}
});
