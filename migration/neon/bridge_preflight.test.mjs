import {strict as assert} from 'node:assert';
import {createHmac} from 'node:crypto';
import {test} from 'node:test';
import {BridgeSafetyError,verifyMigrationFreeze,
 assertShadowDestination,sanitizeTransferCount} from './bridge/preflight.mjs';

const KEY='NEUTRAL_SYNTHETIC_KEY_DO_NOT_USE_'.repeat(2);
const NOW=1793200000;
const BASE={
 batch_id:'00000000-0000-4000-8000-000000000025',
 source_frozen:true,saved_close_verified:true,provider_idle_verified:true,
 no_active_lease_verified:true,checkpoint_closed_verified:true,
 issued_at:NOW-50,expires_at:NOW+400
};
function signed(obj=BASE){
 const ordered=[obj.batch_id,obj.source_frozen,obj.saved_close_verified,
 obj.provider_idle_verified,obj.no_active_lease_verified,
 obj.checkpoint_closed_verified,obj.issued_at,obj.expires_at];
 const signature=createHmac('sha256',KEY).update(JSON.stringify(ordered)).digest('hex');
 return {...obj,signature};
}
const denied=(f,code)=>assert.throws(f,e=>e instanceof BridgeSafetyError&&e.code===code);
test('proper signed receipt accepted for only its own short time window',()=>{
 const r=verifyMigrationFreeze(signed(),KEY,NOW);
 assert.equal(r.verified,true);
 assert.equal(r.batch_id,BASE.batch_id);
});
test('signed nonce is not enough without all provider/lease/close proofs',()=>{
 for(const key of ['source_frozen','saved_close_verified','provider_idle_verified',
 'no_active_lease_verified','checkpoint_closed_verified']){
  denied(()=>verifyMigrationFreeze(signed({...BASE,[key]:false}),KEY,NOW),
   'BRIDGE_FROZEN_RECEIPT_INVALID');
 }
});
test('unsigned and tampered receipts cannot begin an import',()=>{
 denied(()=>verifyMigrationFreeze({...BASE},KEY,NOW),
  'BRIDGE_FROZEN_RECEIPT_INVALID');
 const receipt=signed();receipt.batch_id='00000000-0000-4000-8000-000000000026';
 denied(()=>verifyMigrationFreeze(receipt,KEY,NOW),'BRIDGE_FROZEN_RECEIPT_INVALID');
 denied(()=>verifyMigrationFreeze(signed(),KEY+'different',NOW),'BRIDGE_FROZEN_RECEIPT_INVALID');
});
test('past expiry or over-long lease is refused',()=>{
 denied(()=>verifyMigrationFreeze(signed(),KEY,NOW+1000),'BRIDGE_FROZEN_RECEIPT_INVALID');
 denied(()=>verifyMigrationFreeze(signed({...BASE,expires_at:NOW+900}),KEY,NOW),
  'BRIDGE_FROZEN_RECEIPT_INVALID');
});
test('destination must still be empty production-writer-fenced stage',()=>{
 const valid={mode:'staging_read_only',write_enabled:false,
  profile_count:0,engine_count:0,active_leases:0,inbox_ready:true};
 assert.equal(assertShadowDestination(valid),true);
 for(const key of Object.keys(valid)){
  const invalid={...valid,[key]:key==='mode'?'neon_primary':key==='inbox_ready'?false:
    key==='write_enabled'?true:1};
  denied(()=>assertShadowDestination(invalid),'BRIDGE_DESTINATION_NOT_FENCED');
 }
});
test('counts are bounded and no receipt data leaks in error codes',()=>{
 assert.equal(sanitizeTransferCount(1216),1216);
 denied(()=>sanitizeTransferCount(-1),'BRIDGE_COUNT_INVALID');
 denied(()=>sanitizeTransferCount(Number.NaN),'BRIDGE_COUNT_INVALID');
 try{verifyMigrationFreeze(signed(),KEY+'WRONG',NOW)}
 catch(e){assert.doesNotMatch(String(e),/NEUTRAL_SYNTHETIC/);}
});
