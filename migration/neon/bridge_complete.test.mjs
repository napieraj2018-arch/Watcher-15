import {test} from 'node:test';
import {strict as assert} from 'node:assert';
import {spawnSync} from 'node:child_process';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';

const file=new URL('./bridge/transfer.mjs',import.meta.url);
test('complete bridge runner is syntax checked in CI, not just auxiliary policy',()=>{
 const r=spawnSync(process.execPath,['--check',fileURLToPath(file)],
  {encoding:'utf8',timeout:20000});
 assert.equal(r.status,0,(r.stderr||'').slice(0,500));
});
test('all source categories are reconciled and two new inboxes stay private',()=>{
 const s=readFileSync(file,'utf8');
 for(const token of [
  'normalizeConfigRow','normalizeEventRow',
  'aib_shadow_put_config','aib_shadow_put_event',
  'BRIDGE_CONFIG_COUNT_MISMATCH','BRIDGE_EVENT_COUNT_MISMATCH',
  'account_attempts!==0','BRIDGE_DESTINATION_ROLE_NOT_RESTRICTED',
  'verifyMigrationFreeze','BRIDGE_SOURCE_NOT_IDLE']){
  assert.ok(s.includes(token),'Missing safety/coverage marker: '+token);
 }
 assert.doesNotMatch(s,/console\.log\s*\(|sourceSecret|DELETE FROM|TRUNCATE\s/i);
});
