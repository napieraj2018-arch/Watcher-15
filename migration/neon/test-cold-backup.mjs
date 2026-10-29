import {test} from 'node:test';import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';import {gzipSync} from 'node:zlib';
import {validateColdBackup} from './bridge/cold_backup.mjs';
const hash=x=>createHash('sha256').update(x).digest('hex');
const stamp='2026-10-29 01:14:48.986868+00';
const empty={browser_profiles:0,browser_profile_versions:0,browser_engine_profiles:0,
 browser_task_checkpoints:0,vault_config:0,browser_control_leases:0,
 browser_account_attempts:0,browser_profile_events:0};
const row={table:'browser_profiles',row:{profile_name:'synthetic',encrypted_state:'not-a-real-secret-ciphertext-fixture',updated_at:stamp}};
function fixture(records=[row],headerChanges={}){
 const header={format:'aib-cold-backup-v1',batch_id:'00000000-0000-4000-8000-000000000001',
 source:'floot',observed_at:stamp,snapshot:'repeatable_read',promotion_allowed:false,production_cutover:false,...headerChanges};
 const counts={...empty};for(const x of records)counts[x.table]=(counts[x.table]||0)+1;
 const middle=records.map(x=>JSON.stringify(x)+'\n').join('');const source_rows_sha256=hash(middle);
 const footer={footer:true,counts,source_rows_sha256};const bytes=gzipSync(JSON.stringify(header)+'\n'+middle+JSON.stringify(footer)+'\n');
 return {bytes,receipt:{batch_id:header.batch_id,observed_at:stamp,counts,source_rows_sha256,
  sha256:hash(bytes),compressed_bytes:bytes.length,production_cutover:false,promotion_allowed:false}};
}
test('accepts unchanged complete snapshot, but never permits promotion',()=>{const f=fixture();const r=validateColdBackup(f.bytes,f.receipt);assert.equal(r.summary.verified,true);assert.equal(r.summary.promotion_allowed,false);assert.equal(r.records[0].row.updated_at,stamp);});
test('rejects corrupted compressed bytes',()=>{const f=fixture();f.bytes[15]^=1;assert.throws(()=>validateColdBackup(f.bytes,f.receipt),/BYTES_MISMATCH/);});
test('rejects mismatched external hash',()=>{const f=fixture();f.receipt.sha256='0'.repeat(64);assert.throws(()=>validateColdBackup(f.bytes,f.receipt),/BYTES_MISMATCH/);});
test('rejects altered externally pinned row manifest',()=>{const f=fixture();f.receipt.source_rows_sha256='0'.repeat(64);assert.throws(()=>validateColdBackup(f.bytes,f.receipt),/ROWS_MISMATCH/);});
test('rejects duplicate identifiers',()=>{const f=fixture([row,row]);assert.throws(()=>validateColdBackup(f.bytes,f.receipt),/DUPLICATE_ROW/);});
test('rejects promoted header',()=>{const f=fixture([row],{promotion_allowed:true});assert.throws(()=>validateColdBackup(f.bytes,f.receipt),/PROVENANCE_INVALID/);});
test('rejects receipt claiming production cutover',()=>{const f=fixture();f.receipt.production_cutover=true;assert.throws(()=>validateColdBackup(f.bytes,f.receipt),/PROVENANCE_INVALID/);});
test('rejects unknown snapshot version',()=>{const f=fixture([row],{format:'other'});assert.throws(()=>validateColdBackup(f.bytes,f.receipt),/PROVENANCE_INVALID/);});
test('rejects count mismatch',()=>{const f=fixture();f.receipt.counts={...f.receipt.counts,browser_profiles:2};assert.throws(()=>validateColdBackup(f.bytes,f.receipt),/COUNTS_MISMATCH/);});
test('rejects unsafe timestamp precision conversion',()=>{const f=fixture([{table:'browser_profiles',row:{...row.row,updated_at:123}}]);assert.throws(()=>validateColdBackup(f.bytes,f.receipt),/TIMESTAMP_PRECISION/);});
test('rejects unsupported tables',()=>{const f=fixture([{table:'untrusted',row:{id:'1'}}]);assert.throws(()=>validateColdBackup(f.bytes,f.receipt),/ROW_INVALID/);});
test('preserves forensic archive and exact original timestamp',()=>{const r={table:'browser_profile_versions',row:{id:'9007199254740993',profile_name:'synthetic',encrypted_state:row.row.encrypted_state,source_updated_at:stamp,archived_at:stamp,reason:'forensic_r158_synthetic'}};const f=fixture([r]);const out=validateColdBackup(f.bytes,f.receipt);assert.equal(out.records[0].row.id,'9007199254740993');assert.equal(out.summary.forensic_r158_archives,1);assert.equal(out.summary.protected_archives,1);});
