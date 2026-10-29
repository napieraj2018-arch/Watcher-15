import asyncio, copy, hashlib, json, os, types, unittest
import httpx
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from unittest.mock import patch
from durable_tasks import Vault,TaskService,TaskError,canonical,vault_retry_after_seconds

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
  async def stop(**kw):return {'stopped':True,'full_profile_saved':True,'profile_saved':True}
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
 async def test_invalid_start_mode_does_not_change_checkpoint(self):
  for args in ['{"mode":{}}','{"mode":"admin"}','{"headless":"false"}','{"profile":"other"}']:
   with self.assertRaisesRegex(TaskError,'TASK_START_ARGUMENTS_INVALID'):await self.call('start',data_json=args)
  self.assertEqual((await self.call('get'))['session_state'],'none')
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
 async def test_verified_opt_in_handoff_after_explicit_stop(self):
  await self.call('checkpoint',data_json='{"handoff_after_saved_close":true}')
  await self.call('start')
  result=await self.call('stop')
  self.assertEqual(result['session_state'],'saved_closed')
  self.assertTrue(result['claim_released'])
  self.assertEqual(self.v.rows[self.tid]['claim'],'')
  s2=TaskService(self.v,self.reg,self.guard)
  reopened=await s2.run('resume',task_id=self.tid)
  self.assertNotEqual(reopened['task_claim'],self.claim)
  self.assertTrue(reopened['handoff_after_saved_close'])
  self.assertEqual(reopened['session_state'],'saved_closed')
  with self.assertRaises(TaskError):
   await self.s.run('checkpoint',task_id=self.tid,task_claim=self.claim,
                    data_json='{"status":"stale"}')
 async def test_default_keeps_existing_explicit_release_protocol(self):
  await self.call('start')
  result=await self.call('stop')
  self.assertFalse(result['handoff_requested'])
  self.assertFalse(result['claim_released'])
  self.assertNotEqual(self.v.rows[self.tid]['claim'],'')
  await self.call('release')
  reopened=await TaskService(self.v,self.reg,self.guard).run('resume',task_id=self.tid)
  self.assertEqual(reopened['session_state'],'saved_closed')
 async def test_handoff_requires_strict_boolean_and_verified_profile_saved(self):
  with self.assertRaisesRegex(TaskError,'TASK_HANDOFF_FLAG_INVALID'):
   await self.call('checkpoint',data_json='{"handoff_after_saved_close":"true"}')
  await self.call('checkpoint',data_json='{"handoff_after_saved_close":true}')
  await self.call('start')
  async def partial(**kw):
   return {'stopped':True,'full_profile_saved':True,'profile_saved':False}
  self.reg['browser_stop'].fn=partial
  with self.assertRaisesRegex(TaskError,'TASK_FULL_SAVE_UNCONFIRMED'):
   await self.call('stop')
  self.assertFalse(self.v.rows[self.tid]['resumable'])
  self.assertNotEqual(self.v.rows[self.tid]['claim'],'')
 async def test_handoff_release_failure_does_not_undo_confirmed_saved_close(self):
  await self.call('checkpoint',data_json='{"handoff_after_saved_close":true}')
  await self.call('start')
  original=self.v.request
  async def deny_release(**kwargs):
   if kwargs['action']=='release': raise TaskError('TASK_VAULT_RATE_LIMITED')
   return await original(**kwargs)
  with patch.object(self.v,'request',side_effect=deny_release):
   result=await self.call('stop')
  self.assertTrue(result['handoff_requested'])
  self.assertFalse(result['claim_released'])
  self.assertEqual(result['session_state'],'saved_closed')
  self.assertEqual(self.v.rows[self.tid]['resumable'],True)
  self.assertNotEqual(self.v.rows[self.tid]['claim'],'')
class Vault429Tests(unittest.IsolatedAsyncioTestCase):
 def test_retry_after_is_bounded_and_never_uses_invalid_dates(self):
  self.assertEqual(vault_retry_after_seconds(None),900)
  self.assertEqual(vault_retry_after_seconds('-2'),900)
  self.assertEqual(vault_retry_after_seconds('1200'),1200)
  self.assertEqual(vault_retry_after_seconds('99999999'),86400)
  clock=datetime(2026,10,29,tzinfo=timezone.utc)
  self.assertEqual(vault_retry_after_seconds(format_datetime(clock+timedelta(minutes=20)),now=clock),1200)
  self.assertEqual(vault_retry_after_seconds('not a date'),900)
 async def test_429_opens_shared_circuit_and_refuses_parallel_retries(self):
  calls=[]
  def handler(req):
   calls.append(req)
   if len(calls)==1:
    return httpx.Response(429,headers={'Retry-After':'1200'},json={'error':'private-do-not-log'})
   return httpx.Response(200,json={'ok':True})
  transport=httpx.MockTransport(handler)
  original_client=httpx.AsyncClient
  def mock_client(*args,**kwargs):
   return original_client(*args,transport=transport,**kwargs)
  with patch.dict(os.environ,{'AI_BROWSER_MASTER_KEY':'synthetic-only-master',
          'AI_BROWSER_MCP_TOKEN':'synthetic-only-owner',
          'AI_BROWSER_PROFILE_STORE_TOKEN':'synthetic-only-store',
          'AI_BROWSER_PROFILE_STORE_URL':'https://ai-browser-vault.floot.app/_api/profile-vault'}):
   vault=Vault()
  with patch('durable_tasks.httpx.AsyncClient',side_effect=mock_client):
   results=await asyncio.gather(vault.request(action='list'),vault.request(action='list'),
                                return_exceptions=True)
   self.assertEqual(len(calls),1)
   self.assertTrue(all(isinstance(v,TaskError) and 'TASK_VAULT_RATE_LIMITED' in str(v) for v in results))
   with self.assertRaisesRegex(TaskError,'TASK_VAULT_RATE_LIMITED'):
    await vault.request(action='list')
   self.assertEqual(len(calls),1)
   vault._rate_limit_until=0
   self.assertEqual((await vault.request(action='list'))['ok'],True)
   self.assertEqual(len(calls),2)


class InstalledContract(unittest.IsolatedAsyncioTestCase):
 async def installed(self):
  import sys
  from pathlib import Path
  sys.path.insert(0,str(Path(__file__).parent/'session_ownership'/'tests'))
  from test_owner_parallel_mcp import MultiManager
  from test_sdk_contract import fake_mcp
  from multi_capability_guard import MultiCapabilityGuard
  import durable_tasks
  manager=MultiManager();mcp=fake_mcp(manager)
  guard=MultiCapabilityGuard(mcp,manager,capacity=5,watchdog_enabled=False);guard.install()
  vault=MemoryVault();ns={'mcp':mcp,'_AIB_OWNER_PARALLEL_GUARD':guard}
  with patch.object(durable_tasks,'Vault',return_value=vault):durable_tasks.install(ns)
  service=ns['_AIB_DURABLE_TASKS']
  task=await service.run('create',profile='Synthetic-Race',title='Admission race')
  return manager,mcp,guard,vault,service,{'task_id':task['task_id'],'task_claim':task['task_claim']}
 async def test_admission_race_does_not_create_false_durable_recovery(self):
  manager,mcp,guard,vault,service,args=await self.installed()
  original=mcp._tool_manager._tools['browser_start'].fn
  other=[]
  async def raced(**kw):
   checkpoint_token=service.start_checkpoint.set(None)
   task_token=service.starting_task.set(None)
   try:other.append(await original(profile='Synthetic-Race',mode='read_only'))
   finally:
    service.start_checkpoint.reset(checkpoint_token);service.starting_task.reset(task_token)
   return await original(**kw)
  mcp._tool_manager._tools['browser_start'].fn=raced
  with self.assertRaisesRegex(Exception,'PARALLEL_PROFILE_BUSY'):await service.run('start',**args)
  state=await service.run('get',task_id=args['task_id'])
  self.assertEqual(state['session_state'],'none');self.assertTrue(vault.rows[args['task_id']]['resumable'])
  self.assertEqual(manager.counter,1);self.assertFalse(guard.quarantined)
  await service.run('release',**args)
  await mcp._tool_manager._tools['browser_stop'].fn(session_id=other[0]['session_id'])
 async def test_durable_intent_is_saved_before_provider_create(self):
  manager,mcp,guard,vault,service,args=await self.installed()
  previous=manager.start
  async def observed(*a,**kw):
   _,state=await service.load(args['task_id'])
   self.assertEqual(state['session_state'],'starting');self.assertFalse(vault.rows[args['task_id']]['resumable'])
   return await previous(*a,**kw)
  manager.start=observed
  r=await service.run('start',data_json='{"mode":"read_only","headless":true}',**args)
  self.assertEqual(r['browser']['mode'],'read_only')
 async def test_unknown_provider_start_keeps_recovery_block(self):
  manager,mcp,guard,vault,service,args=await self.installed()
  async def unknown(*a,**kw):raise RuntimeError('UNCERTAIN_PROVIDER')
  manager.start=unknown
  with self.assertRaisesRegex(RuntimeError,'UNCERTAIN_PROVIDER'):await service.run('start',**args)
  self.assertEqual((await service.run('get',task_id=args['task_id']))['session_state'],'starting')
  self.assertFalse(vault.rows[args['task_id']]['resumable'])
 async def test_expected_task_refusal_uses_sdk_public_error_type(self):
  from mcp.server.mcpserver import MCPServer
  from mcp.server.mcpserver.exceptions import ToolError
  from durable_tasks import validate_checkpoint
  self.assertTrue(issubclass(TaskError,ToolError))
  server=MCPServer('task-error-contract')
  @server.tool()
  async def neutral_checkpoint(data_json:str)->dict:
   validate_checkpoint(json.loads(data_json));return {'ok':True}
  with self.assertRaisesRegex(ToolError,'TASK_CHECKPOINT_FIELDS_INVALID'):
   await server._tool_manager._tools['neutral_checkpoint'].run({'data_json':'{"unsupported":"neutral"}'},context=None)
  self.assertEqual(await server._tool_manager._tools['neutral_checkpoint'].run({'data_json':'{"remaining_steps":[]}'},context=None),{'ok':True})
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
 async def test_watchdog_saved_close_records_checkpoint_without_capability_adoption(self):
  import sys
  from pathlib import Path
  sys.path.insert(0,str(Path(__file__).parent/'session_ownership'/'tests'))
  from test_owner_parallel_mcp import MultiManager
  from test_sdk_contract import fake_mcp
  from multi_capability_guard import MultiCapabilityGuard
  import durable_tasks
  class ReceiptManager(MultiManager):
   async def stop(self,sid):return {**await super().stop(sid),'stopped':True}
  manager=ReceiptManager();mcp=fake_mcp(manager);guard=MultiCapabilityGuard(mcp,manager,capacity=5,watchdog_enabled=False);guard.install()
  vault=MemoryVault();ns={'mcp':mcp,'_AIB_OWNER_PARALLEL_GUARD':guard}
  with patch.object(durable_tasks,'Vault',return_value=vault):durable_tasks.install(ns)
  service=ns['_AIB_DURABLE_TASKS'];r=await service.run('create',profile='Acceptance-Watchdog',title='Watchdog fixture')
  args={'task_id':r['task_id'],'task_claim':r['task_claim']};started=await service.run('start',**args)
  lease=guard.authorize(started['browser']['session_id']);token=guard.actor_session.set(lease.internal_session_id)
  # Hold task.lock while stop finishes: the finalizer must not await it here.
  async with service.lock(r['task_id']):
   await asyncio.wait_for(manager.stop(lease.internal_session_id),1)
   guard._complete(lease)
  guard.actor_session.reset(token)
  await asyncio.gather(*service.finalizers)
  self.assertEqual((await service.run('get',task_id=r['task_id']))['session_state'],'saved_closed')
  await service.run('release',**args)
 async def test_watchdog_saved_close_auto_releases_opted_in_task(self):
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
  service=ns['_AIB_DURABLE_TASKS']
  created=await service.run('create',profile='Acceptance-Handoff',title='Watchdog handoff',
                            data_json='{"handoff_after_saved_close":true}')
  args={'task_id':created['task_id'],'task_claim':created['task_claim']}
  started=await service.run('start',**args)
  lease=guard.authorize(started['browser']['session_id'])
  token=guard.actor_session.set(lease.internal_session_id)
  async with service.lock(created['task_id']):
   await asyncio.wait_for(manager.stop(lease.internal_session_id),1)
   guard._complete(lease)
  guard.actor_session.reset(token)
  await asyncio.gather(*service.finalizers)
  self.assertEqual((await service.run('get',task_id=created['task_id']))['session_state'],'saved_closed')
  self.assertEqual(vault.rows[created['task_id']]['claim'],'')
  resumed=await TaskService(vault,service.registry,guard).run('resume',task_id=created['task_id'])
  self.assertNotEqual(resumed['task_claim'],created['task_claim'])
  self.assertTrue(resumed['handoff_after_saved_close'])
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
