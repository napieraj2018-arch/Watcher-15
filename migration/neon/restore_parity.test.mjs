import {strict as assert} from 'node:assert';
import {test} from 'node:test';
import {verifyColdRestoreParity} from './bridge/restore_parity.mjs';

const stamp='2026-10-29 01:14:48.986868+00';
const state='private-fixture-ciphertext-not-a-real-secret';
const sample=[
 {table:'browser_profiles',row:{profile_name:'Acceptance-20261023-R158',
  encrypted_state:state,updated_at:stamp}},
 {table:'browser_engine_profiles',row:{profile_name:'Acceptance-20261023-R158',
  provider_profile_id:'00000000-0000-4000-8000-000000000001',
  updated_at:stamp,hydrated:true}},
 {table:'browser_task_checkpoints',row:{task_id:'00000000-0000-4000-8000-000000000007',
  owner_hash:'f'.repeat(64),encrypted_state:state,claim_hash:'',
  claim_expires_at:null,resumable:true,queued:false,revision:5,
  created_at:stamp,updated_at:stamp}},
 {table:'vault_config',row:{config_key:'owner-fixture',config_value:'test-only'}},
 {table:'browser_control_leases',row:{slot:'fixture',claim_id:'00000000-0000-4000-8000-000000000008',
  epoch:'9007199254740993',expires_at:stamp,holder_hash:'a'.repeat(64),updated_at:stamp}},
 {table:'browser_account_attempts',row:{attempt_id:'00000000-0000-4000-8000-000000000009',
  claim_key:'b'.repeat(64),attempt_day:stamp,attempt_count:2,retry_after:stamp,
  suspended:false,updated_at:stamp}},
 {table:'browser_profile_events',row:{id:'9007199254740995',
  profile_name:'Acceptance-20261023-R158',event_type:'test',created_at:stamp}}
];
for(let i=0;i<41;i++){
 sample.push({table:'browser_profile_versions',row:{
  id:String(9007199254740994n+BigInt(i)),
  profile_name:'Acceptance-20261023-R158',encrypted_state:state,
  source_updated_at:stamp,archived_at:stamp,
  reason:i<20?'update':i<40?'forensic_r158_synthetic':
    'pre_verified_recovery_20261023_160'
 }});
}
const clone=()=>structuredClone(sample);
function refuse(expected,observed){
 assert.throws(()=>verifyColdRestoreParity(expected,observed),/RESTORE_PARITY_INVALID_OR_INCOMPLETE/);
}
test('all eight categories and exact 20+21 R158 provenance compare',()=>{
 const result=verifyColdRestoreParity(sample,clone());
 assert.equal(result.exact_source_destination_rows_verified,true);
 assert.equal(result.neutral_r158_provenance_verified,true);
 assert.equal(result.neutral_r158_rolling,20);
 assert.equal(result.neutral_r158_protected,21);
 assert.equal(result.row_count,48);
 assert.equal(result.promotion_allowed,false);
 assert.equal(result.browser_login_verified,false);
});
test('row and field order do not affect byte-exact comparison',()=>{
 const b=clone().reverse();
 b[0].row=Object.fromEntries(Object.entries(b[0].row).reverse());
 assert.equal(verifyColdRestoreParity(sample,b).exact_source_destination_rows_verified,true);
});
test('changing encrypted state is detected even with equal counts',()=>{
 const b=clone();b[0].row.encrypted_state='tampered-but-same-length-fixture';
 refuse(sample,b);
});
test('changing a protected reason is detected',()=>{
 const b=clone();b.at(-1).row.reason='update';refuse(sample,b);
});
test('lost six-digit time precision is rejected',()=>{
 const b=clone();b[0].row.updated_at='2026-10-29 01:14:48.986+00';refuse(sample,b);
});
test('missing or extra record is rejected',()=>{
 refuse(sample,clone().slice(1));
 refuse(sample,[...clone(),clone()[0]]);
});
test('duplicate identity is rejected even if row content differs',()=>{
 const b=clone();b[1].row.profile_name='Acceptance-20261023-R158';
 b[1].table='browser_profiles';b[1].row={...b[0].row};
 refuse(sample,b);
});
test('numeric conversion of bigint archive ID is rejected',()=>{
 const b=clone();b.at(-1).row.id=9007199254740993;
 refuse(sample,b);
});
test('unknown and missing columns fail closed',()=>{
 const b=clone();b[0].row.unsafe='x';refuse(sample,b);
 const c=clone();delete c[0].row.encrypted_state;refuse(sample,c);
});
test('same incomplete R158 history does not get forged provenance PASS',()=>{
 const a=sample.filter((x)=>!(x.table==='browser_profile_versions'&&
  x.row.reason==='pre_verified_recovery_20261023_160'));
 const r=verifyColdRestoreParity(a,structuredClone(a));
 assert.equal(r.exact_source_destination_rows_verified,true);
 assert.equal(r.neutral_r158_provenance_verified,false);
 assert.equal(r.promotion_allowed,false);
});
test('errors disclose neither ciphertext nor technical identity',()=>{
 try{const b=clone();b[0].row.encrypted_state='SECRET_DO_NOT_ECHO';
  verifyColdRestoreParity(sample,b);assert.fail('expected refusal');
 }catch(e){assert.equal(e.message,'RESTORE_PARITY_INVALID_OR_INCOMPLETE');}
});
