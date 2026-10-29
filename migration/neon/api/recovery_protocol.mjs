/**
 * Compatibility validator for the read-only provider recovery handshake.
 * A real primary Neon API must NOT report pending:false until the original
 * signed cutover receipts and original provider-safe config are independently
 * attested. Attestation writes are NOT available in this candidate.
 */
const UUID=/^[a-f0-9]{8}-[a-f0-9]{4}-[1-8][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/i;
const fail=()=>{throw Error('RECOVERY_READBACK_UNVERIFIED')};
const obj=x=>x!==null&&typeof x==='object'&&!Array.isArray(x);
export function validateRecoveryInspection(value){
 if(!obj(value)||value.ok!==true||typeof value.pending!=='boolean')
  fail();
 if(value.pending===false){
  // Only a separately attested, imported and versioned provider recovery
  // record can be considered clear. Missing legacy config is NOT equivalent.
  if(value.configured!==true||value.verified!==true||
    typeof value.gate_id!=='string'||!UUID.test(value.gate_id))
   fail();
  return {ok:true,pending:false,verified:true,gate_id:value.gate_id};
 }
 const gate=value.gate,local=value.local;
 if(!obj(gate)||!obj(local)||gate.version!==1||
   typeof gate.gate_id!=='string'||!UUID.test(gate.gate_id)||
   typeof gate.session_id!=='string'||!UUID.test(gate.session_id)||
   typeof gate.profile_id!=='string'||!UUID.test(gate.profile_id)||
   typeof gate.profile_name!=='string'||gate.profile_name.length>64||
   typeof gate.pending!=='boolean'||gate.pending!==true||
   typeof local.safe!=='boolean')
  fail();
 // The owner can only inspect a pending plan; this never confirms recovery.
 return {ok:true,pending:true,gate,local};
}
