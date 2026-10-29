import {test} from 'node:test';
import {strict as assert} from 'node:assert';
import {RESTRICTED_ROLE_SQL,assertRestrictedImporterEvidence,
 checkRestrictedImporter} from './bridge/import_role_gate.mjs';

const allowed=()=>{
 const role={role_name:'aib_import_owner_private',timezone:'GMT',datestyle:'ISO, MDY',
  unprivileged_login:true,not_owner_member:true,no_schema_creation:true,
  guard_read:true,receipt_read:true,receipt_no_write:true};
 for(let i=0;i<9;i++)role['live_denied_'+i]=true;
 for(let i=0;i<4;i++){
  role['stage_read_'+i]=true;
  role['stage_insert_'+i]=true;
  role['stage_no_mutation_'+i]=true;
  role['fn_exec_'+i]=true;
 }
 return role;
};
const deny=e=>assert.throws(()=>assertRestrictedImporterEvidence(e),
 /RESTORE_IMPORT_ROLE_LEAST_PRIVILEGE_NOT_VERIFIED/);

test('correct synthetic least-privilege role is the only acceptable grant matrix',()=>{
 const ok=assertRestrictedImporterEvidence(allowed());
 assert.equal(ok.verified,true);
 assert.equal(ok.production_writer_unchanged,true);
});
test('owner and other unapproved role names are denied',()=>{
 for(const name of ['neondb_owner','postgres','aib_import_invalid-','aib_import_']){
  const e=allowed();e.role_name=name;deny(e);
 }
});
test('role with any elevated grant or membership is rejected',()=>{
 for(const key of ['unprivileged_login','not_owner_member','no_schema_creation',
  'guard_read','receipt_read','receipt_no_write']){
  const e=allowed();e[key]=false;deny(e);
 }
});
test('any live table write privilege blocks the importer',()=>{
 for(let i=0;i<9;i++){const e=allowed();e['live_denied_'+i]=false;deny(e)}
});
test('four staging tables require read/insert but cannot mutate or truncate',()=>{
 for(let i=0;i<4;i++){
  for(const key of ['stage_read_','stage_insert_','stage_no_mutation_','fn_exec_']){
   const e=allowed();e[key+i]=false;deny(e);
  }
 }
});
test('timezone mismatch and missing boolean evidence fail closed',()=>{
 for(const value of ['UTC','Europe/Warsaw','GMT+1']){
  const e=allowed();e.timezone=value;deny(e);
 }
 const x=allowed();delete x.stage_insert_0;deny(x);
});
test('role privilege query reads only metadata and no account state',()=>{
 assert.match(RESTRICTED_ROLE_SQL,/pg_roles/);
 assert.match(RESTRICTED_ROLE_SQL,/has_table_privilege/);
 assert.match(RESTRICTED_ROLE_SQL,/has_function_privilege/);
 assert.doesNotMatch(RESTRICTED_ROLE_SQL,/CREATE\s+ROLE|GRANT\s|INSERT\s+INTO|UPDATE\s+browser|DELETE\s+FROM|encrypted_state/i);
});
test('query uses a single read-only SELECT and verifies the returned role',async()=>{
 let calls=0;
 const sql={unsafe:async query=>{calls++;assert.equal(query,RESTRICTED_ROLE_SQL);return [allowed()]}};
 const p=await checkRestrictedImporter(sql);
 assert.equal(calls,1);assert.equal(p.verified,true);
});
test('empty and privileged role query responses cannot pass',async()=>{
 await assert.rejects(()=>checkRestrictedImporter({unsafe:async()=>[]}),
  /RESTORE_IMPORT_ROLE_LEAST_PRIVILEGE_NOT_VERIFIED/);
 const owner={...allowed(),role_name:'neondb_owner'};
 await assert.rejects(()=>checkRestrictedImporter({unsafe:async()=>[owner]}),
  /RESTORE_IMPORT_ROLE_LEAST_PRIVILEGE_NOT_VERIFIED/);
});
