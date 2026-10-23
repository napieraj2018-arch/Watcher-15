import asyncio, copy, hashlib, json, os, types, unittest
from unittest.mock import patch
from durable_tasks import Vault,TaskService,TaskError,canonical

class MemoryVault(Vault):
 def __init__(self):
  with patch.dict(os.environ,{'AI_BROWSER_MASTER_KEY':'synthetic-only-master','AI_BROWSER_MCP_TOKEN':'synthetic-only-owner','AI_BROWSER_PROFILE_STORE_TOKEN':'synthetic-only-store','AI_BROWSER_PROFILE_STORE_URL':'https://ai-browser-vault.floot.app/_api/profile-vault'}): super().__init__()
  self.rows={}
 async def request(self,**b):
  a=b['action'];tid=b.get('task_id')
  if a=='list': return {'tasks':copy.deepcopy(list(self.rows.values()))}
  if a=='create':
   if tid in self.rows: raise TaskError('conflict')
   self.rows[tid]={'taskId':tid,'revision':1,'encryptedState':b['state'],'resumable':True,'queued':False,'claim':b['claim']};return {'revision':1}
  r=self.rows[tid]
  if a=='get': return {'task':copy.deepcopy(r)}
  if a=='claim':
   if r['claim'] or not r['resumable']: raise TaskError('busy')
   r['claim']=b['claim'];return {'task':copy.deepcopy(r)}
  if r['claim']!=b['claim'] or r['revision']!=b['expected_revision']:raise TaskError('conflict')
  if a=='release':
   if not r['resumable']: raise TaskError('unsafe')
   r['claim']='';return {'revision':r['revision']}
  r.update(encryptedState=b['state'],resumable=b['resumable'],queued=b['queued'],revision=r['revision']+1)
  return {'revision':r['revision']}

class Tests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.v=MemoryVault();self.clicks=0;self.guard=types.SimpleNamespace(safe_sessions=lambda:[],leases={},capacity=5,by_profile={})
  async def start(**kw):return {'session_id':'new-local-capability'}
  async def stop(**kw):return {'stopped':True,'full_profile_saved':True}
  async def click(**kw):self.clicks+=1;return {'clicked':True}
  async def snap(**kw):return {'text':'Licznik: '+str(self.clicks)}
  self.reg={k:types.SimpleNamespace(fn=v) for k,v in {'browser_start':start,'browser_stop':stop,'browser_click':click,'browser_snapshot':snap}.items()}
  self.s=TaskService(self.v,self.reg,self.guard)
  r=await self.s.run('create',profile='Acceptance-Synthetic',title='Neutral test',data_json='{"remaining_steps":["one","two"]}')
  self.tid=r['task_id'];self.claim=r['task_claim']
 async def call(self,a,**kw):return await self.s.run(a,task_id=self.tid,task_claim=self.claim,**kw)
 async def test_ciphertext_not_plaintext(self):self.assertNotIn('Neutral test',str(self.v.rows))
 async def test_owner_not_client_selected(self):
  r=await self.call('get');self.assertEqual(r['owner'],self.v.owner);self.assertNotIn('claim_hash',r)
 async def test_wrong_claim(self):
  with self.assertRaises(TaskError):await self.s.run('checkpoint',task_id=self.tid,task_claim='bad')
 async def test_no_adopt_active_task(self):
  await self.call('start')
  with self.assertRaises(TaskError):await self.s.run('resume',task_id=self.tid)
 async def test_restart_claim_from_checkpoint(self):
  await self.call('checkpoint',data_json='{"last_confirmed_step":"one","remaining_steps":["two"]}')
  await self.call('release');s2=TaskService(self.v,self.reg,self.guard)
  r=await s2.run('resume',task_id=self.tid)
  self.assertEqual(r['last_confirmed_step'],'one');self.assertEqual(r['remaining_steps'],['two']);self.assertNotEqual(r['task_claim'],self.claim)
 async def test_new_claim_rejects_old_claim(self):
  await self.call('release');await self.s.run('resume',task_id=self.tid)
  with self.assertRaises(TaskError):await self.call('checkpoint')
 async def test_active_session_requires_saved_stop(self):
  await self.call('start')
  with self.assertRaises(TaskError):await self.call('release')
 async def test_save_stop_then_new_service_resume(self):
  await self.call('start');r=await self.call('stop');self.assertEqual(r['session_state'],'saved_closed')
  await self.call('release');r=await TaskService(self.v,self.reg,self.guard).run('resume',task_id=self.tid);self.assertEqual(r['session_state'],'saved_closed')
 async def test_crash_never_adopts_capability(self):
  await self.call('start');s2=TaskService(self.v,self.reg,self.guard)
  with self.assertRaises(TaskError):await s2.run('stop',task_id=self.tid,task_claim=self.claim)
 async def test_capacity_queue_persisted(self):
  self.guard.leases={str(i):1 for i in range(5)}
  r=await self.call('start');self.assertTrue(r['queued']);self.assertFalse(r['started']);self.assertEqual((await self.call('get'))['session_state'],'none')
 async def test_profile_busy_queue(self):
  self.guard.by_profile={'Acceptance-Synthetic':'other'};r=await self.call('start');self.assertEqual(r['queue_reason'],'profile_busy')
 async def test_quarantine_no_create(self):
  self.guard.safe_sessions=lambda:[{'state':'provider_reconciliation_required'}]
  with self.assertRaises(TaskError):await self.call('start')
 async def test_click_needs_readback_and_never_replays(self):
  await self.call('start');kw={'operation_id':'op-one','browser_tool':'browser_click','data_json':'{"ref":"e1"}'}
  await self.call('browser',**kw);r=await self.call('browser',**kw);self.assertFalse(r['executed']);self.assertTrue(r['verification_required']);self.assertEqual(self.clicks,1)
  r=await self.call('verify',operation_id='op-one',expected_text='Licznik: 1');self.assertTrue(r['verified'])
  r=await self.call('browser',**kw);self.assertFalse(r['executed']);self.assertFalse(r['verification_required']);self.assertEqual(self.clicks,1)
 async def test_different_payload_same_operation_rejected(self):
  await self.call('start');await self.call('browser',operation_id='op-one',browser_tool='browser_click',data_json='{"ref":"e1"}')
  with self.assertRaises(TaskError):await self.call('browser',operation_id='op-one',browser_tool='browser_click',data_json='{"ref":"e2"}')
 async def test_uncertain_operation_blocks_next(self):
  await self.call('start');await self.call('begin',operation_id='mail-one',data_json='{"kind":"synthetic-only"}')
  with self.assertRaises(TaskError):await self.call('browser',operation_id='click-two',browser_tool='browser_click',data_json='{"ref":"e1"}')
 async def test_external_begin_is_once(self):
  args={'operation_id':'mail-one','data_json':'{"kind":"synthetic-only"}'}
  self.assertTrue((await self.call('begin',**args))['execute']);self.assertFalse((await self.call('begin',**args))['execute'])
 async def test_external_confirm_requires_receipt(self):
  await self.call('begin',operation_id='mail-one')
  with self.assertRaises(TaskError):await self.call('confirm',operation_id='mail-one')
 async def test_failed_readback_does_not_clear_pending(self):
  await self.call('start');await self.call('begin',operation_id='op-one');r=await self.call('verify',operation_id='op-one',expected_text='Licznik: 9');self.assertFalse(r['verified'])
  self.assertEqual((await self.call('get'))['operations']['op-one']['status'],'started')
 async def test_foreign_session_injected(self):
  await self.call('start')
  with self.assertRaises(TaskError):await self.call('browser',browser_tool='browser_snapshot',data_json='{"session_id":"foreign"}')
 async def test_stale_cas_cannot_overwrite(self):
  row,d=await self.s.load(self.tid);await self.call('checkpoint',data_json='{"last_confirmed_step":"new"}')
  with self.assertRaises(TaskError):await self.s.save(row,d,self.claim)
 async def test_tampered_ciphertext(self):
  self.v.rows[self.tid]['encryptedState']='x'*50
  with self.assertRaises(TaskError):await self.call('get')
 async def test_wrong_task_aad(self):
  sealed=self.v.rows[self.tid]['encryptedState']
  with self.assertRaises(TaskError):self.v.open('different-task',sealed)
 async def test_profile_input_validation(self):
  with self.assertRaises(TaskError):await self.s.run('create',profile='../foreign',title='test')
 async def test_unexpected_checkpoint_fields(self):
  with self.assertRaises(TaskError):await self.call('checkpoint',data_json='{"claim_hash":"attacker"}')
 async def test_pending_survives_restart(self):
  await self.call('begin',operation_id='op-one');await self.call('release');s2=TaskService(self.v,self.reg,self.guard)
  r=await s2.run('resume',task_id=self.tid);self.assertEqual(r['operations']['op-one']['status'],'started')
 async def test_no_public_claim_in_list(self):
  self.assertNotIn(self.claim,canonical(await self.s.run('list')))
class InstalledContract(unittest.IsolatedAsyncioTestCase):
 async def test_real_sdk_registration_start_stop_resume(self):
  import sys
  from pathlib import Path
  sys.path.insert(0,str(Path(__file__).parent/'session_ownership'/'tests'))
  from test_owner_parallel_mcp import MultiManager
  from test_sdk_contract import fake_mcp
  from multi_capability_guard import MultiCapabilityGuard
  import durable_tasks
  class ReceiptManager(MultiManager):
   async def stop(self,sid):return {**await super().stop(sid),'stopped':True}
  manager=ReceiptManager();mcp=fake_mcp(manager)
  guard=MultiCapabilityGuard(mcp,manager,capacity=5,watchdog_enabled=False);guard.install()
  vault=MemoryVault();ns={'mcp':mcp,'_AIB_OWNER_PARALLEL_GUARD':guard}
  with patch.object(durable_tasks,'Vault',return_value=vault):durable_tasks.install(ns)
  tool=mcp._tool_manager._tools['aib_task'].fn
  r=await tool(action='create',profile='Acceptance-Installed',title='Installed SDK')
  args={'task_id':r['task_id'],'task_claim':r['task_claim']}
  started=await tool(action='start',**args);self.assertEqual(started['session_state'],'active')
  self.assertTrue(started['browser']['session_id'].startswith('aib_'))
  await tool(action='stop',**args);await tool(action='release',**args)
  r2=await tool(action='resume',task_id=r['task_id']);self.assertNotEqual(r['task_claim'],r2['task_claim'])
 async def test_restart_gate_blocks_legacy_start_when_task_uncertain(self):
  import sys
  from pathlib import Path
  sys.path.insert(0,str(Path(__file__).parent/'session_ownership'/'tests'))
  from test_owner_parallel_mcp import MultiManager
  from test_sdk_contract import fake_mcp
  from multi_capability_guard import MultiCapabilityGuard
  import durable_tasks
  vault=MemoryVault()
  async def service():
   manager=MultiManager();mcp=fake_mcp(manager);guard=MultiCapabilityGuard(mcp,manager,capacity=5,watchdog_enabled=False);guard.install()
   ns={'mcp':mcp,'_AIB_OWNER_PARALLEL_GUARD':guard}
   with patch.object(durable_tasks,'Vault',return_value=vault):durable_tasks.install(ns)
   return mcp,ns['_AIB_DURABLE_TASKS']
  mcp,s=await service();r=await s.run('create',profile='Acceptance-Crash',title='Crash fixture');await s.run('start',task_id=r['task_id'],task_claim=r['task_claim'])
  mcp2,s2=await service()
  with self.assertRaises(TaskError):await mcp2._tool_manager._tools['browser_start'].fn(profile='Foreign',mode='read_only')
if __name__=='__main__':unittest.main(verbosity=2)
