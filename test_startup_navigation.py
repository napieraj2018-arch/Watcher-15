"""Actual owner-guard integration: a bad start URL must not destroy a session."""
import asyncio,json,re,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path[:0]=[str(ROOT/'session_ownership'),str(ROOT/'session_ownership'/'tests')]
from playwright.async_api import Error as PlaywrightError
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.tools.base import Tool
from test_sdk_contract import fake_mcp
from test_owner_parallel_mcp import MultiManager
from multi_capability_guard import MultiCapabilityGuard
import startup_navigation
class Tests(unittest.IsolatedAsyncioTestCase):
 async def setup(self,fail=None):
  manager=MultiManager();server=fake_mcp(manager);calls=[]
  async def navigate(session_id:str,url:str)->dict:
   manager._session(session_id);calls.append(url)
   if fail:raise fail
   return {'ok':True,'session_id':session_id}
  server._tool_manager._tools['browser_navigate']=Tool.from_function(navigate,name='browser_navigate')
  guard=MultiCapabilityGuard(server,manager,capacity=5,watchdog_enabled=False);guard.install()
  ns={'mcp':server,'_AIB_OWNER_PARALLEL_GUARD':guard};startup_navigation.install(ns)
  return server,manager,guard,calls,ns
 async def test_network_failure_retains_exact_owned_session_and_can_saved_close(self):
  server,m,g,calls,_=await self.setup(PlaywrightError('net::ERR_ADDRESS_UNREACHABLE private=SECRET'))
  r=await server._tool_manager._tools['browser_start'].fn(profile='Synthetic-A',mode='read_only',headless=True,start_url='https://example.test/')
  self.assertEqual(len(m._sessions),1);self.assertFalse(g.quarantined)
  self.assertEqual(r['navigation']['status'],'unconfirmed');self.assertNotIn('SECRET',str(r))
  self.assertEqual(calls,['https://example.test/'])
  stop=await server._tool_manager._tools['browser_stop'].fn(session_id=r['session_id'])
  self.assertTrue(stop['full_profile_saved']);self.assertEqual(m._sessions,{})
 async def test_success_is_separate_navigation_not_second_create(self):
  s,m,g,calls,_=await self.setup()
  r=await s._tool_manager._tools['browser_start'].fn(profile='Synthetic-A',start_url='https://example.test/')
  self.assertEqual(r['navigation']['status'],'completed');self.assertEqual(len(m._sessions),1)
  await s._tool_manager._tools['browser_stop'].fn(session_id=r['session_id'])
 async def test_blank_start_does_not_navigate(self):
  s,m,g,calls,_=await self.setup();r=await s._tool_manager._tools['browser_start'].fn(profile='Synthetic-A')
  self.assertEqual(calls,[]);await s._tool_manager._tools['browser_stop'].fn(session_id=r['session_id'])
 async def test_start_returns_current_destination_and_auth_not_blank_receipt(self):
  s,m,g,calls,_=await self.setup()
  status=s._tool_manager._tools['browser_status']
  async def current(session_id):
   g.authorize(session_id)
   return {'session_id':session_id,'url':'https://example.test/login/',
           'title':'Sign in','authentication':{'stage':'login_form','authenticated':False}}
  status.fn=current
  r=await s._tool_manager._tools['browser_start'].fn(profile='Synthetic-A',start_url='https://example.test/')
  self.assertEqual(r['url'],'https://example.test/login/')
  self.assertFalse(r['authentication']['authenticated']);self.assertEqual(len(calls),1)
  await s._tool_manager._tools['browser_stop'].fn(session_id=r['session_id'])
 async def test_readback_failure_keeps_capability_without_repeating_navigation(self):
  s,m,g,calls,_=await self.setup()
  async def broken(**kw):raise RuntimeError('PRIVATE_VALUE')
  s._tool_manager._tools['browser_status'].fn=broken
  r=await s._tool_manager._tools['browser_start'].fn(profile='Synthetic-A',start_url='https://example.test/')
  self.assertEqual(r['authentication']['stage'],'unverified');self.assertIsNone(r['url'])
  self.assertNotIn('PRIVATE_VALUE',str(r));self.assertEqual(len(calls),1)
  await s._tool_manager._tools['browser_stop'].fn(session_id=r['session_id'])
 async def test_invalid_urls_do_not_create(self):
  s,m,g,calls,_=await self.setup()
  for url in ['file:///secret','javascript:alert(1)','https://user:password@example.test/']:
   with self.assertRaises(ToolError):await s._tool_manager._tools['browser_start'].fn(profile='Synthetic-A',start_url=url)
  self.assertEqual(m._sessions,{});self.assertEqual(calls,[])
 async def test_existing_quarantine_still_blocks(self):
  s,m,g,calls,_=await self.setup();g.quarantined=True
  with self.assertRaises(ToolError):await s._tool_manager._tools['browser_start'].fn(profile='Synthetic-A',start_url='https://example.test/')
  self.assertEqual(m._sessions,{});self.assertEqual(calls,[])
 async def test_cancelled_navigation_save_closes_only_its_session(self):
  s,m,g,calls,_=await self.setup(asyncio.CancelledError())
  other=await s._tool_manager._tools['browser_start'].fn(profile='Synthetic-B')
  with self.assertRaises(asyncio.CancelledError):
   await s._tool_manager._tools['browser_start'].fn(profile='Synthetic-A',start_url='https://example.test/')
  self.assertEqual(len(m._sessions),1);self.assertEqual(next(iter(m._sessions.values())).profile,'Synthetic-B')
  await s._tool_manager._tools['browser_stop'].fn(session_id=other['session_id'])
 async def test_double_install_keeps_same_wrapper(self):
  s,m,g,calls,ns=await self.setup();before=s._tool_manager._tools['browser_start'].fn;startup_navigation.install(ns)
  self.assertIs(s._tool_manager._tools['browser_start'].fn,before)
if __name__=='__main__':unittest.main(verbosity=2)
