/**
 * Offline cutover decision gate. Internal-only verified receipts from a
 * trusted runner; NEVER expose this route over public HTTP or accept a
 * caller-supplied "verified" boolean without validating a real HMAC.
 */
import {createHmac,timingSafeEqual} from 'node:crypto';
const COUNT_KEYS=Object.freeze([
 'profiles','engine_bindings','archives','protected_archives','tasks'
]);
const okInt=n=>Number.isSafeInteger(n)&&n>=0;
const validTotals=x=>x!==null&&typeof x==='object'&&!Array.isArray(x)&&
  COUNT_KEYS.every(k=>okInt(x[k]));
function canonical(x){
 if(Array.isArray(x))return '['+x.map(canonical).join(',')+']';
 if(x!==null&&typeof x==='object')return '{'+Object.keys(x).sort()
   .map(k=>JSON.stringify(k)+':'+canonical(x[k])).join(',')+'}';
 return JSON.stringify(x);
}
function secureHex(v){return typeof v==='string'&&/^[a-f0-9]{64}$/.test(v)}
function verifyReceipt(payload,signature,key){
 if(!secureHex(signature)||typeof key!=='string'||key.length<40)return false;
 const actual=createHmac('sha256',key).update(canonical(payload)).digest();
 return timingSafeEqual(actual,Buffer.from(signature,'hex'));
}
export function signSyntheticManifestForTest(payload,key){
 if(process.env.NODE_ENV==='production')throw Error('TEST_SIGNING_DISABLED');
 if(typeof key!=='string'||key.length<40)throw Error('INVALID_TEST_KEY');
 return createHmac('sha256',key).update(canonical(payload)).digest('hex');
}
const fail=(code)=>({cutover_allowed:false,readiness:false,reason:code});
export function evaluateTrustedCutover({payload,signature,key}={}){
 // Signed claim is mandatory. The trusted caller owns key in an
 // environment secret; never store a shared HMAC in code, PR or chat.
 if(!payload||!verifyReceipt(payload,signature,key))
  return fail('MANIFEST_ATTESTATION_MISSING');
 const {source,destination,proof,verification}=payload;
 if(!validTotals(source)||!validTotals(destination))
  return fail('MANIFEST_SCHEMA_INVALID');
 // A project with zero live profiles cannot be treated as a migrated vault.
 if(source.profiles===0||source.archives===0||source.protected_archives===0)
  return fail('SOURCE_MANIFEST_EMPTY');
 if(COUNT_KEYS.some(k=>source[k]!==destination[k]))
  return fail('SOURCE_DESTINATION_COUNT_MISMATCH');
 if(source.protected_archives<21)
  return fail('PROTECTED_ARCHIVE_PROVENANCE_MISSING');
 if(!proof||proof.algorithm!=='sha256'||proof.source_rows_match!==true
    ||proof.versions_match!==true||proof.engine_bindings_match!==true
    ||proof.tasks_match!==true||proof.protected_r158_21_match!==true)
  return fail('ENCRYPTED_IDENTITY_UNVERIFIED');
 if(!verification||verification.source_frozen!==true
    ||verification.no_active_vault_writer!==true
    ||verification.no_unresolved_task_claim!==true
    ||verification.steel_provider_idle!==true
    ||verification.neutral_three_store_coherent!==true
    ||verification.saved_close_new_controller_pass!==true)
  return fail('LIVE_RESTORE_OR_PROVIDER_GATE_UNVERIFIED');
 // Cutover is technically eligible only after a verified source freeze,
 // equal encrypted archives, and original neutral 3-store restore PASS.
 // Browser overall READY additionally requires 5 real auth and iPhone test.
 const ready=verification.five_live_meta_after_reopen===true
   &&verification.real_iphone_roundtrip_pass===true;
 return {cutover_allowed:true,readiness:ready,
    reason:ready?'ACCEPTED':'ACCOUNTS_OR_IPHONE_PENDING'};
}
