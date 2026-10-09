"""Synthetic tests for auto-opening cards without starting a technical Live view."""
import asyncio
import sys
from pathlib import Path
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from broker import Broker,Principal,Workspace,BrokerError

A=Principal("tenant-A","user-owner","task-111")
A_NEXT=Principal("tenant-A","user-owner","task-222")
B=Principal("tenant-B","user-other","task-333")
C=Principal("tenant-C","user-third","task-444")
URL_A="https://business.facebook.com/latest/home"
URL_B="https://www.facebook.com/"
KEY_A="request-00000000001"
KEY_B="request-00000000002"
KEY_C="request-00000000003"

class BrowserMock:
    def __init__(self):
        self.running=[]
        self.started=[]
        self.opened=[]
        self.stopped=[]
        self.fail_start=False
        self.fail_tab=False
        self.fail_save=False

    async def sessions(self):
        return list(self.running)
    async def start(self,profile,url,mode):
        self.started.append({"profile":profile,"url":url,"mode":mode})
        if self.fail_start:raise RuntimeError("SIMULATED_PROVIDER_DOWN_PRIVATE_INFO")
        if self.running:raise RuntimeError("SIMULATED_BUSY")
        row={"session_id":"internal-browser-id-"+str(len(self.started))}
        self.running=[row]
        return row
    async def new_tab(self,session_id,url):
        self.opened.append((session_id,url))
        if self.fail_tab:raise RuntimeError("SIMULATED_NEW_TAB_FAILURE")
        return {"ok":True}
    async def stop(self,session_id):
        self.stopped.append(session_id)
        if self.fail_save:
            return {"profile_saved":True,"full_profile_saved":False}
        self.running=[]
        return {"profile_saved":True,"full_profile_saved":True}

def workspace(tenant="tenant-A",workspace_id="clinic",profile="Meta - Maciej - Monitoring",
              hosts=frozenset({"business.facebook.com","www.facebook.com"})):
    return Workspace(tenant,workspace_id,profile,hosts)

class BrokerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.t=[1000.0]
        self.browser=BrowserMock()
        self.broker=Broker(self.browser,[
           workspace(),
           workspace("tenant-A","studio","Google - Architekt",frozenset({"myaccount.google.com"})),
           workspace("tenant-B","clinic","Company B - FB",frozenset({"www.facebook.com"})),
           workspace("tenant-C","clinic","Company C - FB",frozenset({"www.facebook.com"})),
        ],clock=lambda:self.t[0],max_queue=20,max_tabs=4)
    async def opena(self,key=KEY_A,url=URL_A,p=A,w="clinic"):
        return await self.broker.open(p,w,url,key)

    async def test_click_card_auto_starts_browser_without_live_button(self):
        r=await self.opena()
        self.assertEqual(r["status"],"ready")
        self.assertTrue(r["tab_id"])
        self.assertEqual(self.browser.started[0]["mode"],"read_only")
        self.assertNotIn("session_id",r)

    async def test_replay_idempotent(self):
        a=await self.opena()
        b=await self.opena()
        self.assertEqual(a,b)
        self.assertEqual(len(self.browser.started),1)

    async def test_wrong_url_replay_rejected(self):
        await self.opena()
        with self.assertRaisesRegex(BrokerError,"IDEMPOTENCY_KEY_CONFLICT"):
            await self.opena(url=URL_B)

    async def test_two_tasks_do_not_share_session(self):
        await self.opena()
        b=await self.opena(key=KEY_B,p=A_NEXT)
        self.assertEqual(b["status"],"queued")
        self.assertEqual(len(self.browser.started),1)

    async def test_different_workspace_same_task_queued(self):
        await self.opena()
        r=await self.opena(key=KEY_B,w="studio",url="https://myaccount.google.com/")
        self.assertEqual(r["status"],"queued")

    async def test_another_tenant_waits_without_stealing(self):
        await self.opena()
        r=await self.opena(key=KEY_B,url=URL_B,p=B)
        self.assertEqual(r["status"],"queued")
        self.assertEqual(r["queue_position"],1)
        self.assertNotIn("profile",r)
        self.assertEqual(len(self.browser.started),1)

    async def test_different_tenants_same_idempotency_key_isolated(self):
        await self.opena(key=KEY_A)
        r=await self.opena(key=KEY_A,url=URL_B,p=B)
        self.assertEqual(r["status"],"queued")
        self.assertEqual(r["queue_position"],1)

    async def test_other_tenant_cannot_get_request_status(self):
        await self.opena()
        with self.assertRaisesRegex(BrokerError,"REQUEST_NOT_FOUND"):
            await self.broker.poll(B,KEY_A)

    async def test_other_tenant_cannot_close(self):
        await self.opena()
        with self.assertRaisesRegex(BrokerError,"TASK_NOT_OWNER"):
            await self.broker.close(B)
        self.assertEqual(len(self.browser.stopped),0)

    async def test_queue_starts_only_after_verified_save(self):
        await self.opena()
        await self.opena(key=KEY_B,url=URL_B,p=B)
        result=await self.broker.close(A)
        self.assertTrue(result["profile_saved"])
        self.assertTrue(result["next_request_pending"])
        next=await self.broker.poll(B,KEY_B)
        self.assertEqual(next["status"],"ready")
        self.assertEqual(len(self.browser.started),2)

    async def test_queue_is_fifo(self):
        await self.opena()
        b=await self.opena(key=KEY_B,url=URL_B,p=B)
        c=await self.opena(key=KEY_C,url=URL_B,p=C)
        self.assertEqual([b["queue_position"],c["queue_position"]],[1,2])
        await self.broker.close(A)
        still=await self.broker.poll(C,KEY_C)
        self.assertEqual(still["status"],"queued")
        ready=await self.broker.poll(B,KEY_B)
        self.assertEqual(ready["status"],"ready")

    async def test_external_session_not_stopped(self):
        self.browser.running=[{"session_id":"unowned"}]
        r=await self.opena()
        self.assertEqual(r["status"],"queued")
        self.assertEqual(self.browser.stopped,[])

    async def test_external_session_then_release_allows_fifo(self):
        self.browser.running=[{"session_id":"unowned"}]
        await self.opena()
        self.browser.running=[]
        self.assertEqual((await self.broker.poll(A,KEY_A))["status"],"ready")

    async def test_same_owner_creates_new_tab_not_new_browser(self):
        a=await self.opena()
        b=await self.opena(key=KEY_B,url=URL_B)
        self.assertEqual(b["status"],"ready")
        self.assertNotEqual(a["tab_id"],b["tab_id"])
        self.assertEqual(len(self.browser.started),1)
        self.assertEqual(len(self.browser.opened),1)

    async def test_tab_limit(self):
        await self.opena()
        for i in range(3):
            await self.opena(key="request-tab-"+str(i)+"--A",url=URL_B)
        with self.assertRaisesRegex(BrokerError,"WORKSPACE_TAB_LIMIT"):
            await self.opena(key="request-tab-999-A",url=URL_B)

    async def test_unverified_save_quarantines(self):
        await self.opena()
        self.browser.fail_save=True
        with self.assertRaisesRegex(BrokerError,"BROWSER_REQUIRES_RECOVERY"):
            await self.broker.close(A)
        with self.assertRaisesRegex(BrokerError,"BROWSER_REQUIRES_RECOVERY"):
            await self.opena(key=KEY_B,url=URL_B,p=B)

    async def test_missing_confirmed_start_no_retry(self):
        self.browser.fail_start=True
        r=await self.opena()
        self.assertEqual(r["status"],"paused")
        self.assertIn("NO_AUTOMATIC_RETRY",r["code"])
        self.assertEqual(len(self.browser.started),1)
        self.assertEqual((await self.opena())["status"],"paused")
        self.assertEqual(len(self.browser.started),1)

    async def test_new_tab_failure_paused_not_resubmitted(self):
        await self.opena()
        self.browser.fail_tab=True
        r=await self.opena(key=KEY_B,url=URL_B)
        self.assertEqual(r["status"],"paused")
        self.assertEqual(len(self.browser.opened),1)
        await self.opena(key=KEY_B,url=URL_B)
        self.assertEqual(len(self.browser.opened),1)

    async def test_cancel_queued(self):
        await self.opena()
        await self.opena(key=KEY_B,url=URL_B,p=B)
        result=await self.broker.cancel(B,KEY_B)
        self.assertEqual(result["status"],"cancelled")
        self.assertEqual(len(self.broker.queue),0)

    async def test_cancel_other_tenant_rejected(self):
        await self.opena()
        await self.opena(key=KEY_B,url=URL_B,p=B)
        with self.assertRaisesRegex(BrokerError,"REQUEST_NOT_FOUND"):
            await self.broker.cancel(A,KEY_B)

    async def test_queue_expires_without_background_polling(self):
        await self.opena()
        await self.opena(key=KEY_B,url=URL_B,p=B)
        self.t[0]+=901
        r=await self.broker.poll(B,KEY_B)
        self.assertEqual(r["status"],"expired")
        self.assertEqual(len(self.broker.queue),0)

    async def test_stale_head_does_not_block_next(self):
        await self.opena()
        await self.opena(key=KEY_B,url=URL_B,p=B)
        self.t[0]+=901
        await self.opena(key=KEY_C,url=URL_B,p=C)
        self.assertEqual(len(self.broker.queue),1)
        self.assertEqual(self.broker.queue[0].principal,C)

    async def test_queue_limit(self):
        self.broker.max_queue=1
        await self.opena()
        await self.opena(key=KEY_B,url=URL_B,p=B)
        with self.assertRaisesRegex(BrokerError,"QUEUE_FULL"):
            await self.opena(key=KEY_C,url=URL_B,p=C)

    async def test_invalid_destination_hosts_rejected(self):
        for url in ["http://business.facebook.com/","https://business.facebook.com.evil.test/",
                    "https://localhost","https://127.0.0.1","file:///etc/passwd",
                    "https://user:pass@business.facebook.com/",
                    "https://business.facebook.com:8443/",
                    "https://business.facebook.com\\@evil.test/"]:
            with self.subTest(url=url),self.assertRaises(BrokerError):
                await self.opena(url=url)

    async def test_wrong_workspace_tenant_rejected(self):
        with self.assertRaisesRegex(BrokerError,"WORKSPACE_NOT_FOUND"):
            await self.opena(p=B,w="studio",url="https://myaccount.google.com/")

    async def test_nontrusted_principal_rejected(self):
        with self.assertRaisesRegex(BrokerError,"TRUSTED_PRINCIPAL_REQUIRED"):
            await self.broker.open("tenant-A","clinic",URL_A,KEY_A)

    async def test_summary_never_exposes_other_tenant_profile(self):
        await self.opena()
        summary=await self.broker.summary(B)
        self.assertTrue(summary["other_task_busy"])
        self.assertNotIn("Meta - Maciej",str(summary))
        self.assertFalse(summary["technical_session_id_disclosed"])

    async def test_concurrent_open_is_single_start(self):
        a,b=await asyncio.gather(self.opena(),self.opena(key=KEY_B,url=URL_B,p=B))
        self.assertEqual({a["status"],b["status"]},{"ready","queued"})
        self.assertEqual(len(self.browser.started),1)

    async def test_profile_identity_cannot_be_shared_across_two_tenants(self):
        with self.assertRaisesRegex(BrokerError,"PROFILE_REUSED_BETWEEN_WORKSPACES"):
            Broker(self.browser,[
              workspace("tenant-A","clinic","Shared - Session"),
              workspace("tenant-B","clinic","Shared - Session")
            ])

    async def test_profile_identity_cannot_be_shared_across_two_workspaces(self):
        with self.assertRaisesRegex(BrokerError,"PROFILE_REUSED_BETWEEN_WORKSPACES"):
            Broker(self.browser,[
              workspace("tenant-A","clinic","Shared - Session"),
              workspace("tenant-A","studio","Shared - Session")
            ])

    async def test_uncertain_provider_start_quarantines_followup_tenants(self):
        self.browser.fail_start=True
        first=await self.opena()
        self.assertEqual(first["status"],"paused")
        self.assertTrue(self.broker.quarantined)
        with self.assertRaisesRegex(BrokerError,"BROWSER_REQUIRES_RECOVERY"):
            await self.opena(key=KEY_B,url=URL_B,p=B)
        self.assertEqual(len(self.browser.started),1)

    async def test_uncertain_start_replay_is_safe_and_does_not_leak_to_others(self):
        self.browser.fail_start=True
        response=await self.opena()
        self.assertEqual(await self.opena(),response)
        with self.assertRaisesRegex(BrokerError,"BROWSER_REQUIRES_RECOVERY"):
            await self.broker.poll(B,KEY_A)

    async def test_uncertain_provider_start_prevents_queued_poll(self):
        await self.opena()
        await self.opena(key=KEY_B,url=URL_B,p=B)
        # Simulate a genuine save failure: no next client can take over.
        self.browser.fail_save=True
        with self.assertRaisesRegex(BrokerError,"BROWSER_REQUIRES_RECOVERY"):
            await self.broker.close(A)
        with self.assertRaisesRegex(BrokerError,"BROWSER_REQUIRES_RECOVERY"):
            await self.broker.poll(B,KEY_B)

    async def test_adapter_start_session_must_exist_in_inventory(self):
        original=self.browser.sessions
        async def no_sessions_after_launch():
            return [] if self.browser.started else await original()
        self.browser.sessions=no_sessions_after_launch
        answer=await self.opena()
        self.assertEqual(answer["status"],"paused")
        self.assertTrue(self.broker.quarantined)
        self.assertEqual(len(self.browser.started),1)

    async def test_adapter_mismatched_session_id_fails_closed(self):
        original=self.browser.sessions
        async def wrong_id():
            if self.browser.started:
                return [{"session_id":"other-user-controller"}]
            return await original()
        self.browser.sessions=wrong_id
        answer=await self.opena()
        self.assertEqual(answer["status"],"paused")
        self.assertTrue(self.broker.quarantined)

    async def test_adapter_wrong_profile_fails_closed(self):
        original=self.browser.sessions
        async def wrong_profile():
            if self.browser.started:
                return [{"session_id":self.browser.running[0]["session_id"],
                         "profile":"other-tenant-profile","mode":"read_only"}]
            return await original()
        self.browser.sessions=wrong_profile
        answer=await self.opena()
        self.assertEqual(answer["status"],"paused")
        self.assertTrue(self.broker.quarantined)

    async def test_adapter_wrong_mode_fails_closed(self):
        original=self.browser.sessions
        async def writable():
            if self.browser.started:
                return [{"session_id":self.browser.running[0]["session_id"],
                         "mode":"write"}]
            return await original()
        self.browser.sessions=writable
        answer=await self.opena()
        self.assertEqual(answer["status"],"paused")
        self.assertTrue(self.broker.quarantined)

    async def test_adapter_extra_session_fails_closed(self):
        original=self.browser.sessions
        async def two_sessions():
            if self.browser.started:
                return [self.browser.running[0],{"session_id":"other-active-task"}]
            return await original()
        self.browser.sessions=two_sessions
        answer=await self.opena()
        self.assertEqual(answer["status"],"paused")
        self.assertTrue(self.broker.quarantined)

    async def test_missing_provider_inventory_quarantines_before_request_recorded(self):
        async def unavailable(): return None
        self.browser.sessions=unavailable
        with self.assertRaisesRegex(BrokerError,"BROWSER_REQUIRES_RECOVERY"):
            await self.opena()
        self.assertTrue(self.broker.quarantined)
        self.assertEqual(self.broker.requests,{})
        self.assertEqual(self.browser.started,[])

    async def test_malformed_provider_inventory_cannot_be_treated_as_empty(self):
        async def malformed(): return [{}]
        self.browser.sessions=malformed
        with self.assertRaisesRegex(BrokerError,"BROWSER_REQUIRES_RECOVERY"):
            await self.opena()
        self.assertTrue(self.broker.quarantined)
        self.assertEqual(self.browser.started,[])

    async def test_raised_provider_inventory_error_is_sanitized(self):
        async def failed(): raise RuntimeError("DO_NOT_EXPOSE_PRIVATE_PROVIDER_KEY")
        self.browser.sessions=failed
        with self.assertRaises(BrokerError) as ctx:
            await self.opena()
        self.assertNotIn("PRIVATE_PROVIDER_KEY",str(ctx.exception))
        self.assertTrue(self.broker.quarantined)

    async def test_poll_with_unknown_inventory_never_starts_queued_job(self):
        self.browser.running=[{"session_id":"someone-else"}]
        await self.opena()
        self.browser.running=[]
        async def failed(): raise RuntimeError("PRIVATE_PROVIDER_ERROR")
        self.browser.sessions=failed
        with self.assertRaisesRegex(BrokerError,"BROWSER_REQUIRES_RECOVERY"):
            await self.broker.poll(A,KEY_A)
        self.assertTrue(self.broker.quarantined)
        self.assertEqual(self.browser.started,[])

    async def test_summary_shows_recovery_without_exposing_provider(self):
        async def failed(): raise RuntimeError("PRIVATE")
        self.browser.sessions=failed
        with self.assertRaises(BrokerError): await self.opena()
        view=await self.broker.summary(A)
        self.assertTrue(view["recovery_required"])
        self.assertFalse(view["technical_session_id_disclosed"])
        self.assertNotIn("PRIVATE",str(view))

    async def test_closed_session_does_not_replay_stale_tab_capability(self):
        first=await self.opena()
        self.assertEqual(first["status"],"ready")
        self.assertIn("tab_id",first)
        await self.broker.close(A)
        old=await self.opena()
        self.assertEqual(old["status"],"closed")
        self.assertNotIn("tab_id",old)
        self.assertEqual(len(self.browser.started),1)
        other=await self.opena(key=KEY_B,url=URL_B)
        self.assertEqual(other["status"],"ready")
        self.assertEqual(len(self.browser.started),2)

    async def test_multi_tab_close_revokes_all_old_handles(self):
        await self.opena()
        await self.opena(key=KEY_B,url=URL_B)
        await self.broker.close(A)
        for key,url in ((KEY_A,URL_A),(KEY_B,URL_B)):
            with self.subTest(key=key):
                result=await self.opena(key=key,url=url)
                self.assertEqual(result["status"],"closed")
                self.assertNotIn("tab_id",result)

    async def test_failed_close_blocks_replaying_ready_session(self):
        await self.opena()
        self.browser.fail_save=True
        with self.assertRaisesRegex(BrokerError,"BROWSER_REQUIRES_RECOVERY"):
            await self.broker.close(A)
        with self.assertRaisesRegex(BrokerError,"BROWSER_REQUIRES_RECOVERY"):
            await self.opena()

    async def test_failed_close_does_not_start_other_work(self):
        await self.opena()
        await self.opena(key=KEY_B,url=URL_B,p=B)
        self.browser.fail_save=True
        with self.assertRaises(BrokerError):
            await self.broker.close(A)
        with self.assertRaises(BrokerError):
            await self.broker.poll(B,KEY_B) if self.broker.active and self.broker.active.quarantine else asyncio.sleep(0)
        self.assertEqual(len(self.browser.started),1)

if __name__=="__main__":
    unittest.main(verbosity=2)
