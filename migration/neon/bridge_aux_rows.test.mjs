import {test} from 'node:test';
import {strict as assert} from 'node:assert';
import {createHash} from 'node:crypto';
import {normalizeConfigRow,normalizeEventRow} from './bridge/row_mapper.mjs';

const stamp='2026-10-29 01:14:48.986868+00';
const sha=s=>createHash('sha256').update(s,'utf8').digest('hex');
const base={id:'9007199254740993',profile_name:'Neutral-Test',
 event_type:'save',created_at:stamp};

test('config ciphertext-adjacent value hash preserves exact UTF-8 bytes',()=>{
 const r=normalizeConfigRow({config_key:'test-only',config_value:'sample-zażółć'});
 assert.equal(r.sourceKey,'test-only');
 assert.equal(r.sourceSha256,sha('sample-zażółć'));
 assert.equal(r.configValue,'sample-zażółć');
});
test('rejects empty, oversized and non-string private config values',()=>{
 for(const v of ['',4,'X'.repeat(1048577)]){
  assert.throws(()=>normalizeConfigRow({config_key:'k',config_value:v}),/SHADOW_CONFIG_INVALID/);
 }
});
test('event digest binds bigint ID, profile, action and full microseconds',()=>{
 const r=normalizeEventRow(base);
 assert.equal(r.sourceId,'9007199254740993');
 assert.equal(r.sourceCreatedAt,stamp);
 assert.equal(r.sourceSha256,sha([
  '9007199254740993','Neutral-Test','save',stamp
 ].join('\x1f')));
});
test('mutating any event identity component changes the input hash',()=>{
 const original=normalizeEventRow(base).sourceSha256;
 for(const delta of [
  {id:'9007199254740994'},{profile_name:'Other-Test'},
  {event_type:'open'},{created_at:'2026-10-29 01:14:48.986867+00'}
 ]){
  assert.notEqual(normalizeEventRow({...base,...delta}).sourceSha256,original);
 }
});
test('invalid IDs, timestamps, illegal delimiters fail closed',()=>{
 for(const delta of [{id:'1.0'},{id:9007199254740993},
  {id:'0'},{created_at:'2026-10-29'}, {event_type:'save\x1fopen'},
  {profile_name:'a\x1fb'}]){
  assert.throws(()=>normalizeEventRow({...base,...delta}));
 }
});
test('event errors do not expose private event data',()=>{
 try{normalizeEventRow({...base,event_type:'\x1fprivate-secret'});assert.fail('expected refusal')}
 catch(e){assert.equal(e.message,'SHADOW_EVENT_INVALID')}
});
