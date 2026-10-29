import {test} from 'node:test';
import {strict as assert} from 'node:assert';
import {spawnSync} from 'node:child_process';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';

const script=new URL('./bridge/steel_inventory_cli.mjs',import.meta.url);
test('owner-only Steel CLI syntax valid on both CI Node runtimes',()=>{
 const p=spawnSync(process.execPath,['--check',fileURLToPath(script)],{
  encoding:'utf8',timeout:12000});
 assert.equal(p.status,0,(p.stderr||'').slice(0,500));
});
test('no API key means fixed refusal and no attempt to reach Steel',()=>{
 const env={...process.env};delete env.STEEL_API_KEY;
 const p=spawnSync(process.execPath,[fileURLToPath(script)],{
  encoding:'utf8',timeout:12000,env});
 assert.equal(p.status,1);
 assert.equal(p.stdout,'');
 assert.equal(p.stderr,'STEEL_INVENTORY_AUTH_UNAVAILABLE\n');
});
test('owner CLI only reads the account-scoped Steel provider GET API',()=>{
 const s=readFileSync(script,'utf8');
 assert.match(s,/STEEL_API_KEY/);
 assert.match(s,/createSteelReadonlyClient/);
 assert.doesNotMatch(s,/createSession|releaseAll|startSession|\/profiles\/\$\{|fetch\('http:\/\//i);
 assert.doesNotMatch(s,/console\.log\(/);
});
