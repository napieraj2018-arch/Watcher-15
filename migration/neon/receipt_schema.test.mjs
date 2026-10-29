import {test} from 'node:test';
import {strict as assert} from 'node:assert';
import {readFileSync} from 'node:fs';
const sql=readFileSync(new URL('./005_cold_backup_receipts.sql',import.meta.url),'utf8');
test('private cold backup receipts retain a sealed, non-promotable history',()=>{
 assert.match(sql,/CREATE TABLE aib_cold_backup_receipts/);
 assert.match(sql,/PRIMARY KEY/);
 assert.match(sql,/CHECK\(NOT imported_to_tables\)/);
 assert.match(sql,/CHECK\(NOT production_cutover\)/);
 assert.match(sql,/BEFORE UPDATE OR DELETE/);
 assert.match(sql,/aib_shadow_deny_mutation/);
 assert.match(sql,/REVOKE ALL ON aib_cold_backup_receipts FROM PUBLIC/);
 assert.doesNotMatch(sql,/INSERT INTO|UPDATE\s+vault_migration_guard|DROP\s+TRIGGER|ALTER\s+ROLE/i);
 assert.doesNotMatch(sql,/X-Amz-Signature|Bearer\s|encrypted_state|provider_profile_id/);
});
