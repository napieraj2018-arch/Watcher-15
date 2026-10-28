"""Fail-closed recovery tests with an exact private incident, no real account."""
import copy,json,unittest
import httpx
from provider_recovery_gate import RecoveryGate,RecoveryGateError,RecoveryRateLimited,run_boot_gate,VAULT,STEEL,retry_after_seconds
from unittest.mock import patch
import io
from datetime import datetime,timezone
from contextlib import redirect_stdout
S='00000000-0000-4000-8000-000000000001'
P='00000000-0000-4000-8000-000000000002'
G='00000000-0000-4000-8000-000000000003'
PLAN={'version':1,'gate_id':G,'session_id':S,'profile_id':P,
      'window_start':'2026-10-23T18:46:00Z','window_end':'2026-10-23T18:47:30Z'}
class Fixture:
 def __init__(self):
  self.calls=[];self.plan=copy.deepcopy(PLAN);self.pending=True;self.safe=True
  self.session={'id':S,'profileId':P,'status':'released','persistProfile':True,'createdAt':'2026-10-23T18:46:39Z'}
  self.profile={'id':P,'status':'READY'};self.rows=[{'id':S,'status':'released'}]
  self.new_live=[];self.repeat=False;self.http=200;self.vault_http=200;self.ack=True;self.change=False
 def transport(self,r):
  self.calls.append((r.method,str(r.url)))
  if str(r.url)==VAULT:
   if self.vault_http!=200:
    return httpx.Response(self.vault_http,headers={'Retry-After':'3600'},
                          json={'private':'DO_NOT_PRINT'})
   self.last_body=json.loads(r.content)
   if self.last_body['action']=='attest':
    return httpx.Response(200,json={'ok':self.ack,'verified':self.ack,'pending':False,'gate_id':G})
   count=sum(1 for m,u in self.calls if u==VAULT)
   return httpx.Response(200,json={'ok':True,'pending':self.pending,
    'gate':self.plan,'local':{'safe':self.safe and not (self.change and count>1),'profile_count':38}})
  if r.method!='GET': raise AssertionError('No provider mutation allowed')
  if self.http!=200:return httpx.Response(self.http,json={'private':'DO_NOT_PRINT'})
  if r.url.path.endswith('/sessions/'+S):return httpx.Response(200,json=self.session)
  if '/profiles/' in r.url.path:return httpx.Response(200,json=self.profile)
  if r.url.params.get('status')=='live':return httpx.Response(200,json={'sessions':self.new_live})
  return httpx.Response(200,json={'sessions':self.rows if self.repeat or not r.url.params.get('cursorId') else []})
 def run(self):
  with httpx.Client(transport=httpx.MockTransport(self.transport)) as c:
   return RecoveryGate(c,'synthetic-store','synthetic-steel').run()
class Tests(unittest.TestCase):
 def setUp(self):self.f=Fixture()
 def denied(self,code):
  with self.assertRaisesRegex(RecoveryGateError,code) as e:self.f.run()
  self.assertNotIn('DO_NOT_PRINT',str(e.exception))
  self.assertFalse(any(m!='GET' and u.startswith(STEEL) for m,u in self.f.calls))
  self.assertFalse(getattr(self.f,'last_body',{}).get('action')=='attest')
 def test_exact_released_complete_inventory_and_preserved_backup_pass(self):
  r=self.f.run();self.assertEqual(r['status'],'verified');self.assertEqual(r['protected_profiles'],38)
  self.assertEqual(self.f.last_body['proof']['inventory_total'],1)
  self.assertEqual(sum(u.endswith('/sessions/'+S) for _,u in self.f.calls),2)
 def test_no_pending_gate_requires_full_fresh_provider_idle_inventory(self):
  self.f.pending=False
  result=self.f.run()
  self.assertEqual(result['status'],'no_pending_gate_provider_idle')
  self.assertIs(result['verified_this_boot'], True)
  self.assertEqual(result['inventory_total'],1)
  self.assertEqual(sum(1 for method,url in self.f.calls
                       if method=='GET' and url.startswith(STEEL)),4)
  self.assertEqual(sum(1 for method,url in self.f.calls
                       if method=='POST' and url==VAULT),2)
  self.assertFalse(any(method!='GET' and url.startswith(STEEL)
                       for method,url in self.f.calls))
  self.assertEqual(self.f.last_body['action'],'inspect')
 def test_no_pending_live_session_is_still_denied(self):
  self.f.pending=False
  self.f.new_live=[{'id':G,'status':'live'}]
  self.denied('PROVIDER_CHANGED')
 def test_no_pending_unknown_session_in_history_is_denied(self):
  self.f.pending=False
  self.f.rows.append({'id':G,'status':'unknown'})
  self.denied('ACTIVE_OR_UNKNOWN')
 def test_no_pending_repeated_history_cursor_denied(self):
  self.f.pending=False;self.f.repeat=True
  self.denied('PAGINATION_CONFLICT')
 def test_no_pending_changed_vault_during_provider_inventory_denied(self):
  self.f.pending=False
  self.f.change=True
  original=self.f.transport
  def changing(request):
   reply=original(request)
   if str(request.url)==VAULT and len([v for v in self.f.calls if v[1]==VAULT])>=2:
    return httpx.Response(200,json={'ok':True,'pending':True})
   return reply
  with httpx.Client(transport=httpx.MockTransport(changing)) as client:
   with self.assertRaisesRegex(RecoveryGateError,'GATE_CHANGED'):
    RecoveryGate(client,'synthetic-store','synthetic-steel').run()
 def test_no_pending_provider_connection_error_denied(self):
  self.f.pending=False
  self.f.http=503
  self.denied('HTTP_503')
 def test_changed_backup_denied(self):self.f.safe=False;self.denied('LOCAL_BACKUP')
 def test_local_state_changes_during_reads_denied(self):self.f.change=True;self.denied('LOCAL_STATE_CHANGED')
 def test_live_exact_session_denied(self):self.f.session['status']='live';self.denied('EXACT_SESSION_NOT_VERIFIED')
 def test_failed_exact_session_is_not_saved_close(self):self.f.session['status']='failed';self.denied('EXACT_SESSION_NOT_VERIFIED')
 def test_wrong_profile_denied(self):self.f.session['profileId']=G;self.denied('EXACT_SESSION_NOT_VERIFIED')
 def test_wrong_session_denied(self):self.f.session['id']=G;self.denied('EXACT_SESSION_NOT_VERIFIED')
 def test_no_persist_profile_denied(self):self.f.session['persistProfile']=False;self.denied('EXACT_SESSION_NOT_VERIFIED')
 def test_wrong_time_denied(self):self.f.session['createdAt']='2026-10-22T18:46:39Z';self.denied('TIME_MISMATCH')
 def test_404_not_reconciliation(self):self.f.http=404;self.denied('HTTP_404')
 def test_403_not_retried(self):self.f.http=403;self.denied('HTTP_403');self.assertEqual(len(self.f.calls),2)
 def test_unready_profile_denied(self):self.f.profile['status']='UPLOADING';self.denied('PROFILE_NOT_READY')
 def test_wrong_ready_profile_denied(self):self.f.profile['id']=G;self.denied('PROFILE_NOT_READY')
 def test_any_live_inventory_session_denied(self):self.f.rows.append({'id':G,'status':'live'});self.denied('ACTIVE_OR_UNKNOWN')
 def test_unknown_inventory_state_denied(self):self.f.rows.append({'id':G,'status':'unknown'});self.denied('ACTIVE_OR_UNKNOWN')
 def test_pagination_duplicate_denied(self):self.f.repeat=True;self.denied('PAGINATION_CONFLICT')
 def test_missing_exact_inventory_denied(self):self.f.rows=[];self.denied('NOT_IN_INVENTORY')
 def test_fresh_live_query_denied(self):self.f.new_live=[{'id':G,'status':'live'}];self.denied('PROVIDER_CHANGED')
 def test_failed_vault_ack_does_not_unlock(self):
  self.f.ack=False
  with self.assertRaisesRegex(RecoveryGateError,'RECEIPT_UNCONFIRMED'):self.f.run()
 def test_invalid_uuid_prevents_provider_request(self):self.f.plan['session_id']='../../other';self.denied('INVALID_BINDING');self.assertEqual(len(self.f.calls),1)
 def test_no_credentials_fails_before_http(self):
  with httpx.Client(transport=httpx.MockTransport(self.f.transport)) as c:
   with self.assertRaisesRegex(RecoveryGateError,'CREDENTIALS'):RecoveryGate(c,'','')
  self.assertEqual(self.f.calls,[])
 def test_vault_429_is_typed_and_honors_retry_after(self):
  self.f.vault_http=429
  with self.assertRaises(RecoveryRateLimited) as caught:self.f.run()
  self.assertEqual(str(caught.exception),'RECOVERY_HTTP_429')
  self.assertEqual(caught.exception.retry_after_seconds,3600)
  self.assertEqual(len(self.f.calls),1)
  self.assertNotIn('DO_NOT_PRINT',str(caught.exception))
 def test_retry_after_delta_date_and_invalid_are_bounded(self):
  now=datetime(2026,10,28,10,0,tzinfo=timezone.utc)
  self.assertEqual(retry_after_seconds('7200'),7200)
  self.assertEqual(retry_after_seconds('Wed, 28 Oct 2026 13:00:00 GMT',now=now),10800)
  self.assertEqual(retry_after_seconds('1'),900)
  self.assertEqual(retry_after_seconds('invalid-SECRET-NEVER-PRINT'),900)
  self.assertEqual(retry_after_seconds('999999999'),604800)
  self.assertEqual(retry_after_seconds('Wed, 28 Oct 2026 09:00:00 GMT',now=now),900)
 def test_boot_gate_429_is_typed_and_never_opens_browser(self):
  with patch.dict('os.environ', {'AI_BROWSER_ENGINE':'steel','AI_BROWSER_PROFILE_STORE_TOKEN':'fixture','STEEL_API_KEY':'fixture'}):
   with patch.object(RecoveryGate,'run',side_effect=RecoveryGateError('RECOVERY_HTTP_429')):
    with redirect_stdout(io.StringIO()):
     with self.assertRaises(RecoveryRateLimited): run_boot_gate()
 def test_boot_gate_non429_still_fails_closed(self):
  with patch.dict('os.environ', {'AI_BROWSER_ENGINE':'steel','AI_BROWSER_PROFILE_STORE_TOKEN':'fixture','STEEL_API_KEY':'fixture'}):
   with patch.object(RecoveryGate,'run',side_effect=RecoveryGateError('RECOVERY_HTTP_403')):
    with redirect_stdout(io.StringIO()):
     with self.assertRaisesRegex(RuntimeError,'AI_BROWSER_RECOVERY_GATE_BLOCKED'): run_boot_gate()
if __name__=='__main__':unittest.main(verbosity=2)
