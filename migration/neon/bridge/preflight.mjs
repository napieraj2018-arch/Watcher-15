/**
 * Neutral, internal migration preflight. NOT a public API route.
 * The source must have been frozen by the owner controller after a genuine
 * saved-close/provider inventory receipt; never trust a caller's assertion.
 */
import {createHmac,timingSafeEqual} from 'node:crypto';

const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
export class BridgeSafetyError extends Error {
 constructor(code){super(code);this.name='BridgeSafetyError';this.code=code}
}
const deny=code=>{throw new BridgeSafetyError(code)};
export function verifyMigrationFreeze(receipt,secret,nowSeconds=Math.floor(Date.now()/1000)){
 if(!receipt||typeof receipt!=='object'||Array.isArray(receipt))
  deny('BRIDGE_FROZEN_RECEIPT_REQUIRED');
 const {batch_id,source_frozen,saved_close_verified,provider_idle_verified,
  no_active_lease_verified,checkpoint_closed_verified,issued_at,expires_at,signature}=receipt;
 if(typeof secret!=='string'||secret.length<40||secret.length>256
    ||typeof signature!=='string'||!/^[a-f0-9]{64}$/.test(signature)
    ||typeof batch_id!=='string'||!UUID.test(batch_id)
    ||source_frozen!==true||saved_close_verified!==true
    ||provider_idle_verified!==true||no_active_lease_verified!==true
    ||checkpoint_closed_verified!==true
    ||!Number.isSafeInteger(issued_at)||!Number.isSafeInteger(expires_at)
    ||expires_at<=issued_at||expires_at-issued_at>900
    ||nowSeconds<issued_at-60||nowSeconds>expires_at)
  deny('BRIDGE_FROZEN_RECEIPT_INVALID');
 const parts=[batch_id,source_frozen,saved_close_verified,provider_idle_verified,
   no_active_lease_verified,checkpoint_closed_verified,issued_at,expires_at];
 const data=JSON.stringify(parts);
 const expected=createHmac('sha256',secret).update(data).digest();
 const actual=Buffer.from(signature,'hex');
 if(!timingSafeEqual(expected,actual))
  deny('BRIDGE_FROZEN_RECEIPT_INVALID');
 return {verified:true,batch_id};
}
export function assertShadowDestination(stage){
 if(stage===null||typeof stage!=='object'||Array.isArray(stage)
   ||stage.mode!=='staging_read_only'||stage.write_enabled!==false
   ||stage.profile_count!==0||stage.engine_count!==0||stage.active_leases!==0
   ||stage.inbox_ready!==true)
  deny('BRIDGE_DESTINATION_NOT_FENCED');
 return true;
}
export function sanitizeTransferCount(count){
 if(!Number.isSafeInteger(count)||count<0||count>1000000)
  deny('BRIDGE_COUNT_INVALID');
 return count;
}
