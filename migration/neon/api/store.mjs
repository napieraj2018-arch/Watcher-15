/**
 * Parameterized, read-only Neon PostgreSQL adapter.
 * One production writer remains Floot. This module never makes any writes.
 */
import postgres from 'postgres';
import {createHash} from 'node:crypto';
export function createStore(url){
 if(typeof url!=='string'||!url.startsWith('postgres'))throw Error('DATABASE_URL_REQUIRED');
 const sql=postgres(url,{
  max:2,connect_timeout:6,idle_timeout:20,max_lifetime:120,
  prepare:false,onnotice:()=>{}
 });
 return async function database(op,where={}){
  if(op==='status'){
   const [row]=await sql
    `SELECT
      (SELECT mode FROM vault_migration_guard WHERE only_row) AS mode,
      (SELECT write_enabled FROM vault_migration_guard WHERE only_row) AS write_enabled,
      (SELECT count(*)::int FROM browser_profiles) AS profile_count,
      (SELECT count(*)::int FROM browser_profile_versions) AS archive_count,
      (SELECT count(*)::int FROM browser_task_checkpoints) AS task_count,
      (SELECT count(*)::int FROM browser_control_leases) AS lease_count`;
   if(!row||row.mode!=='staging_read_only'||row.write_enabled!==false)
    throw Error('STAGING_GUARD_UNCONFIRMED');
   return row;
  }
  if(op==='profile_list'){
   const rows=await sql`SELECT profile_name AS name,updated_at AS "updatedAt"
       FROM browser_profiles ORDER BY updated_at DESC LIMIT 200`;
   return rows.map(r=>({name:r.name,updatedAt:new Date(r.updatedAt).toISOString()}));
  }
  if(op==='profile_get'){
   const rows=await sql`SELECT encrypted_state AS "encryptedState",updated_at AS "updatedAt"
       FROM browser_profiles WHERE profile_name=${where.name} LIMIT 1`;
   return rows[0]?{encryptedState:rows[0].encryptedState,
      ciphertextSha256:createHash('sha256').update(rows[0].encryptedState).digest('hex'),
      updatedAt:new Date(rows[0].updatedAt).toISOString()}:null;
  }
  if(op==='engine_get'){
   const rows=await sql`SELECT provider_profile_id AS "providerProfileId",hydrated
       FROM browser_engine_profiles WHERE profile_name=${where.name} LIMIT 1`;
   return rows[0]||null;
  }
  if(op==='task_list'){
   const rows=await sql`SELECT task_id AS "taskId",revision,encrypted_state AS "encryptedState",
      resumable,queued,created_at AS "createdAt",updated_at AS "updatedAt"
      FROM browser_task_checkpoints WHERE owner_hash=${where.owner}
      ORDER BY created_at ASC LIMIT 200`;
   return rows.map(r=>({...r,createdAt:new Date(r.createdAt).toISOString(),
    updatedAt:new Date(r.updatedAt).toISOString()}));
  }
  if(op==='task_get'){
   const rows=await sql`SELECT task_id AS "taskId",revision,encrypted_state AS "encryptedState",
      resumable,queued FROM browser_task_checkpoints
      WHERE task_id=${where.id} AND owner_hash=${where.owner} LIMIT 1`;
   return rows[0]||null;
  }
  throw Error('STAGING_OPERATION_DENIED');
 };
}
