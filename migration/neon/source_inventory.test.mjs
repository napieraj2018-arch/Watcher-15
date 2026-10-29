import {strict as assert} from 'node:assert';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';

test('source inventory is exclusively counts and immutable, not a shadow vault',()=>{
 const sql=readFileSync(new URL('./004_source_inventory.sql',import.meta.url),'utf8');
 assert.match(sql,/CREATE TABLE IF NOT EXISTS aib_shadow_source_inventory/);
 assert.match(sql,/CHECK\(NOT shadow_writer_enabled\)/);
 assert.match(sql,/BEFORE UPDATE OR DELETE ON aib_shadow_source_inventory/);
 assert.match(sql,/EXECUTE FUNCTION aib_shadow_deny_mutation\(\)/);
 assert.doesNotMatch(sql,/encrypted_state|api_key|bearer_token|private_key|password|cookie_value/);
 assert.doesNotMatch(sql,/\bTRUNCATE\b|\bDROP TABLE\b|\bDELETE FROM\b/);
});
