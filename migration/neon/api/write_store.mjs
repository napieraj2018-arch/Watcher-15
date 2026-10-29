/**
 * SQL writer engine for a separately reviewed Neon cutover.
 * NOT imported by current stage Function. ZERO writes until ALL guard receipts.
 * All private records remain inside the trusted runtime and parameterized SQL.
 */
import {createHash,timingSafeEqual} from 'node:crypto';
import {VaultMutationError,validateVaultMutation,
  rejectUnsafeWriteGate,validateOwnerHash} from './write_policy.mjs';

const err=(code,status=409)=>new VaultMutationError(code,status);
const sha=value=>createHash('sha256').update(value).digest('hex');
const valid64=v=>typeof v==='string'&&/^[a-f0-9]{64}$/.test(v);

/**
 * sql: instance of postgres.js, supplied by trusted runtime, never from caller.
 * proof: random cutover secret from server-only environment, not HTTP request.
 * A plan/code change alone cannot unlock the stage without verified manifests.
 */
export function createWriterStore(sql,{proof}={}){
 if(!sql||typeof sql.begin!=='function')
   throw err('DATABASE_TRANSACTION_REQUIRED',503);
 const proofEnabled=typeof proof==='string'&&proof.length>=40&&proof.length<=256;
 async function guard(tx){
  if(!proofEnabled)throw err('NEON_CUTOVER_NOT_ACCEPTED',503);
  const rows=await tx`SELECT mode,write_enabled FROM vault_migration_guard
                           WHERE only_row=true FOR UPDATE`;
  if(rows.length!==1)throw err('NEON_CUTOVER_NOT_ACCEPTED',503);
  const receipt=await tx`SELECT config_value FROM vault_config
        WHERE config_key='neon_cutover_acceptance_v1' FOR UPDATE`;
  if(receipt.length!==1)throw err('NEON_CUTOVER_NOT_ACCEPTED',503);
  let cfg;try{cfg=JSON.parse(receipt[0].config_value)}catch{
   throw err('NEON_CUTOVER_NOT_ACCEPTED',503);
  }
  rejectUnsafeWriteGate({...cfg,mode:rows[0].mode,write_enabled:rows[0].write_enabled});
  if(!valid64(cfg.proof_sha256))throw err('NEON_CUTOVER_NOT_ACCEPTED',503);
  const expected=Buffer.from(cfg.proof_sha256,'hex');
  const actual=createHash('sha256').update(proof).digest();
  if(!timingSafeEqual(expected,actual))throw err('NEON_CUTOVER_NOT_ACCEPTED',503);
  return cfg.epoch;
 }
 return async function mutate(operation,payload,owner){
  const p=validateVaultMutation(operation,payload);
  const ownerHash=validateOwnerHash(owner);
  return sql.begin(async tx=>{
   await guard(tx);
   if(operation==='profile_save'){
    // Lost-state prevention: caller must supply SHA256 of the CURRENT encrypted
    // version it read, or null only when creating a new profile.
    // A duplicate of an already-saved ciphertext is harmless and does not
    // create another rolling archive or change updated_at.
    const old=await tx`SELECT encrypted_state FROM browser_profiles
      WHERE profile_name=${p.profile} FOR UPDATE`;
    if(old.length===1&&old[0].encrypted_state===p.state)
      return {ok:true,unchanged:true,profile:p.profile,sha256:sha(p.state)};
    if(old.length===1&&
       p.expected_sha256!==sha(old[0].encrypted_state))
      throw err('profile_revision_conflict');
    if(old.length===0&&p.expected_sha256!==null)
      throw err('profile_revision_conflict');
    let rows;
    if(old.length===0){
      rows=await tx`INSERT INTO browser_profiles(profile_name,encrypted_state)
        VALUES(${p.profile},${p.state})
        ON CONFLICT(profile_name) DO NOTHING RETURNING profile_name`;
    }else{
      rows=await tx`UPDATE browser_profiles
        SET encrypted_state=${p.state},updated_at=now()
        WHERE profile_name=${p.profile}
          AND encrypted_state IS DISTINCT FROM ${p.state}
        RETURNING profile_name`;
    }
    if(rows.length!==1)throw err('profile_revision_conflict');
    return {ok:true,unchanged:false,profile:p.profile,sha256:sha(p.state)};
   }
   if(operation==='engine_bind'){
    await tx`INSERT INTO browser_engine_profiles(profile_name,provider_profile_id)
       VALUES(${p.profile},${p.profile_id}::uuid)
       ON CONFLICT(profile_name) DO NOTHING`;
    const rows=await tx`SELECT provider_profile_id
       FROM browser_engine_profiles WHERE profile_name=${p.profile} FOR UPDATE`;
    if(rows.length!==1||String(rows[0].provider_profile_id)!==p.profile_id)
      throw err('profile_binding_conflict');
    if(p.hydrated){
      await tx`UPDATE browser_engine_profiles
         SET hydrated=true,updated_at=now()
         WHERE profile_name=${p.profile} AND provider_profile_id=${p.profile_id}::uuid
           AND hydrated=false`;
    }
    return {ok:true};
   }
   if(operation==='task_create'){
    const rows=await tx`INSERT INTO browser_task_checkpoints
      (task_id,owner_hash,encrypted_state,claim_hash,claim_expires_at,resumable)
      VALUES(${p.task_id}::uuid,${ownerHash},${p.state},
           ${sha(p.claim)},now()+interval '15 minutes',true)
      ON CONFLICT(task_id) DO NOTHING RETURNING revision`;
    if(rows.length!==1)throw err('task_exists');
    return {ok:true,revision:rows[0].revision};
   }
   if(operation==='task_claim'){
    const rows=await tx`UPDATE browser_task_checkpoints
       SET claim_hash=${sha(p.claim)},claim_expires_at=now()+interval '15 minutes',
           updated_at=now()
       WHERE task_id=${p.task_id}::uuid AND owner_hash=${ownerHash}
         AND resumable=true
         AND (claim_hash='' OR claim_expires_at<now())
       RETURNING task_id AS "taskId",revision,encrypted_state AS "encryptedState",
         resumable,queued`;
    if(rows.length!==1)throw err('task_busy_or_recovery_required');
    return {ok:true,task:rows[0]};
   }
   if(operation==='task_checkpoint'){
    // A state marked interrupted (resumable=false) cannot be silently made
    // resumable by a stale/compromised task writer. A distinct verified
    // provider saved-close attestation is required to lift that condition.
    const rows=await tx`UPDATE browser_task_checkpoints SET
      encrypted_state=${p.state},resumable=${p.resumable},
      queued=${p.queued},revision=revision+1,updated_at=now(),
      claim_expires_at=now()+interval '15 minutes'
      WHERE task_id=${p.task_id}::uuid AND owner_hash=${ownerHash}
       AND claim_hash=${sha(p.claim)} AND claim_expires_at>now()
       AND revision=${p.expected_revision}
       AND (resumable=true OR ${p.resumable}=false)
      RETURNING revision`;
    if(rows.length!==1)throw err('revision_or_claim_conflict');
    return {ok:true,revision:rows[0].revision};
   }
   if(operation==='task_release'){
    const rows=await tx`UPDATE browser_task_checkpoints
      SET claim_hash='',claim_expires_at=null,updated_at=now()
      WHERE task_id=${p.task_id}::uuid AND owner_hash=${ownerHash}
       AND revision=${p.expected_revision}
       AND claim_hash=${sha(p.claim)} AND claim_expires_at>now()
       AND resumable=true RETURNING revision`;
    if(rows.length!==1)throw err('conflict_or_unsafe_release');
    return {ok:true,revision:rows[0].revision};
   }
   throw err('mutation_not_supported',403);
  });
 };
}
