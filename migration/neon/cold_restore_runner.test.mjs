import {test} from 'node:test';
import {strict as assert} from 'node:assert';
import {spawnSync} from 'node:child_process';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';

const file=new URL('./bridge/cold_restore_run.mjs',import.meta.url);
test('private restricted restore runner must pass Node syntax check',()=>{
 const p=spawnSync(process.execPath,['--check',fileURLToPath(file)],{
  encoding:'utf8',timeout:15000});
 assert.equal(p.status,0,(p.stderr||'').slice(0,500));
});
test('runner requires separately provided limited credentials and signed freeze',()=>{
 const s=readFileSync(file,'utf8');
 for(const token of [
  'AIB_COLD_RESTORE_MODE','NEON_IMPORT_DATABASE_URL',
  'AIB_MIGRATION_RECEIPT_JSON','AIB_MIGRATION_HMAC_KEY',
  'AIB_COLD_BACKUP_GET_URL','verifyMigrationFreeze',
  'getStage','assertShadowDestination','RESTORE_RESTRICTED_DB_ROLE_REQUIRED',
  'planRestrictedColdRestore','stageAndVerifyColdRestore'
 ])assert.ok(s.includes(token),'Missing required gate: '+token);
 assert.doesNotMatch(s,/CREATE\s+ROLE|DROP\s+TABLE|ALTER\s+ROLE|UPDATE\s+vault_migration_guard|setInterval|fetch\('http:\/\//i);
});
test('runner never logs private data or auto-promotes the writer',()=>{
 const s=readFileSync(file,'utf8');
 assert.doesNotMatch(s,/console\.log\s*\(|throw\s+rawError|print\s*\(\s*bytes\s*\)/);
 assert.ok(s.includes('RESTORE_NOT_COMPLETED_SAFE_STOP'));
 assert.ok(s.includes('production_cutover'));
 assert.ok(s.includes('AIB_COLD_RESTORE_MODE'));
});
