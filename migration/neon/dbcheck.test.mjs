import {strict as assert} from 'node:assert';
import {test} from 'node:test';
import {readFileSync} from 'node:fs';
test('stage DB probe only returns safety status and never accesses ciphertext',()=>{
 const s=readFileSync(new URL('./diagnostics/dbcheck.mjs',import.meta.url),'utf8');
 assert.ok(s.includes('vault_migration_guard'));
 assert.ok(s.includes('SELECT mode,write_enabled'));
 assert.ok(s.includes('staging_read_only'));
 assert.ok(s.includes('browser_available:false'));
 assert.ok(s.includes('write_enabled:false'));
 assert.ok(s.includes('lastAt<60000'));
 assert.doesNotMatch(s,/SELECT encrypted_state|INSERT INTO|UPDATE browser_profiles|DELETE FROM browser_profiles/);
 assert.doesNotMatch(s,/JSON.stringify\(rows\)|process.env.AI_BROWSER_MASTER_KEY|process.env.STEEL_API_KEY/);
});