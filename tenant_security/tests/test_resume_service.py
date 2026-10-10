"""Task ticket encryption and fail-closed BFF/worker unit regressions.

Everything synthetic. No browser provider, real accounts or network requests.
The actual cross-process PostgreSQL 16 proof runs separately in this CI.
"""
from __future__ import annotations
from dataclasses import dataclass
from uuid import UUID, uuid4
import unittest

from tenant_security.bff.gate import Principal
from tenant_security.recovery.tickets import (
    TaskResumeTickets, ResumeTicketError,
)
from tenant_security.recovery.service import (
    ReattachmentService, RecoveryRejected, NoProviderProbe,
)

A=UUID("11111111-1111-4111-8111-111111111111")
B=UUID("22222222-2222-4222-8222-222222222222")
USER_A=UUID("aaaaaaaa-eeee-4eee-8eee-000000000001")
USER_B=UUID("bbbbbbbb-eeee-4eee-8eee-000000000002")
SAME_TENANT_OTHER=UUID("aaaaaaaa-eeee-4eee-8eee-000000000003")
TASK=UUID("aaaaaaaa-ffff-4fff-8fff-000000000001")
OTHER_TASK=UUID("aaaaaaaa-ffff-4fff-8fff-000000000002")
KEY=b"synthetic-local-test-key-notreal!" # 32 bytes
assert len(KEY)==32
SESSION="a"*64
CSRF="c"*64

class Clock:
    def __init__(self): self.t=1791620000
    def __call__(self): return self.t


class ProviderFake:
    def __init__(self): self.active=True; self.checks=0; self.on_verify=None
    def verify_active(self,tenant,principal,task,slot,gen):
        self.checks+=1
        if self.on_verify:
            self.on_verify()
        return self.active and tenant==A and principal==USER_A and task==TASK and slot==1 and gen==4


class RepoFake:
    def __init__(self):
        self.epoch=0
        self.request=None
        self.active=True
        self.cancelled=False
        self.calls=[]
        self.fail=False
        self.db_fails=False
    def list_own(self,sid,csrf):
        if self.db_fails: raise RuntimeError("PRIVATE_DATABASE_STACKTRACE")
        if sid!=SESSION or csrf!=CSRF: return []
        return [(TASK,"running",self.cancelled,self.epoch)]
    def reattach(self,sid,csrf,task,attempt):
        if self.db_fails: raise RuntimeError("PRIVATE_DATABASE_STACKTRACE")
        self.calls.append(("reattach",task))
        if sid!=SESSION or csrf!=CSRF: return ("not_authorized",None,None,None)
        if task!=TASK or self.cancelled: return ("not_available",None,None,None)
        if not self.active: return ("provider_recheck_required",None,None,None)
        if attempt==self.request:
            return ("already_attached",1,4,self.epoch)
        self.epoch+=1
        self.request=attempt
        return ("reattach_epoch_issued",1,4,self.epoch)
    def can_execute(self,tenant,task,slot,generation,epoch):
        if self.db_fails: raise RuntimeError("PRIVATE_DATABASE_STACKTRACE")
        self.calls.append(("can_execute",epoch))
        return (self.active and not self.cancelled
                and tenant==A and task==TASK and slot==1
                and generation==4 and epoch==self.epoch and epoch>0)
    def cancel(self,sid,csrf,task):
        self.calls.append(("cancel",task))
        if sid!=SESSION or csrf!=CSRF: return "not_authorized"
        if task!=TASK: return "not_available"
        if self.cancelled: return "already_requested"
        self.cancelled=True
        self.epoch+=1
        return "cancel_requested"


class Tickets(unittest.TestCase):
    def setUp(self):
        self.clock=Clock()
        self.issuer=TaskResumeTickets(KEY,clock=self.clock)

    def issue(self):
        return self.issuer.issue(tenant_id=A,principal_id=USER_A,
            task_id=TASK,slot_no=1,generation=4,attachment_epoch=2,ttl=30)

    def test_encrypted_roundtrip_and_no_plaintext_identifiers(self):
        value=self.issue()
        self.assertTrue(value.startswith("aibr_"))
        self.assertNotIn(str(TASK),value)
        self.assertNotIn(str(USER_A),value)
        claims=self.issuer.verify(value,tenant_id=A,principal_id=USER_A,task_id=TASK)
        self.assertEqual((claims.slot_no,claims.generation,claims.attachment_epoch),(1,4,2))
        self.assertNotIn("aaaaaaaa",repr(claims))

    def test_tampering_wrong_keys_and_bindings_are_rejected(self):
        value=self.issue()
        for tenant,principal,task in ((B,USER_A,TASK),(A,USER_B,TASK),
                                      (A,USER_A,OTHER_TASK)):
            with self.assertRaisesRegex(ResumeTicketError,"TICKET_INVALID"):
                self.issuer.verify(value,tenant_id=tenant,principal_id=principal,task_id=task)
        flipped=value[:-1]+("A" if value[-1]!="A" else "B")
        with self.assertRaisesRegex(ResumeTicketError,"TICKET_INVALID"):
            self.issuer.verify(flipped,tenant_id=A,principal_id=USER_A,task_id=TASK)
        wrong=TaskResumeTickets(b"different-synthetic-key-not-real!",clock=self.clock)
        with self.assertRaisesRegex(ResumeTicketError,"TICKET_INVALID"):
            wrong.verify(value,tenant_id=A,principal_id=USER_A,task_id=TASK)

    def test_expired_ticket_never_accepted(self):
        value=self.issue()
        self.clock.t+=30
        with self.assertRaisesRegex(ResumeTicketError,"TICKET_EXPIRED"):
            self.issuer.verify(value,tenant_id=A,principal_id=USER_A,task_id=TASK)

    def test_keys_and_claims_reject_invalid_types(self):
        for key in (None,b"",b"too short","a"*32,True):
            with self.assertRaisesRegex(ResumeTicketError,"KEY_INVALID"):
                TaskResumeTickets(key)
        for ttl in (0,46,"30",True,-1):
            with self.assertRaisesRegex(ResumeTicketError,"CLAIMS_INVALID"):
                self.issuer.issue(tenant_id=A,principal_id=USER_A,task_id=TASK,
                    slot_no=1,generation=4,attachment_epoch=2,ttl=ttl)


class ResumeFlowTests(unittest.TestCase):
    def setUp(self):
        self.clock=Clock()
        self.repo=RepoFake()
        self.probe=ProviderFake()
        self.tickets=TaskResumeTickets(KEY,clock=self.clock)
        self.service=ReattachmentService(self.repo,self.probe,self.tickets)
        self.owner=Principal(A,USER_A,"operator",CSRF)
        self.wrong=Principal(B,USER_B,"operator",CSRF)
        self.other=Principal(A,SAME_TENANT_OTHER,"operator",CSRF)

    def resume(self,**kwargs):
        return self.service.resume(principal=kwargs.get("principal",self.owner),
            session_digest=kwargs.get("session_digest",SESSION),
            csrf_digest=kwargs.get("csrf_digest",CSRF),
            task_id=kwargs.get("task_id",TASK),
            attempt_id=kwargs.get("attempt_id",uuid4()))

    def test_owner_can_resume_and_ticket_is_short_lived(self):
        result=self.resume()
        self.assertEqual(result.attachment_epoch,1)
        self.assertEqual(result.expires_in_seconds,30)
        self.assertNotIn(result.ticket,repr(result))
        claims=self.service.authorize_ticket(result.ticket,principal=self.owner,task_id=TASK)
        self.assertEqual(claims.attachment_epoch,1)
        self.assertGreaterEqual(self.probe.checks,2)

    def test_same_attempt_idempotent_new_attempt_revokes_old_ticket(self):
        attempt=uuid4()
        first=self.resume(attempt_id=attempt)
        second=self.resume(attempt_id=attempt)
        self.assertEqual(first.attachment_epoch,second.attachment_epoch)
        third=self.resume()
        self.assertEqual(third.attachment_epoch,first.attachment_epoch+1)
        with self.assertRaisesRegex(RecoveryRejected,"LEASE_CHANGED"):
            self.service.authorize_ticket(first.ticket,principal=self.owner,task_id=TASK)
        self.service.authorize_ticket(third.ticket,principal=self.owner,task_id=TASK)

    def test_forged_or_different_principal_cannot_exchange_ticket(self):
        result=self.resume()
        for actor in (self.wrong,self.other):
            with self.assertRaisesRegex(RecoveryRejected,"TICKET_REJECTED"):
                self.service.authorize_ticket(result.ticket,principal=actor,task_id=TASK)

    def test_failed_provider_readback_denies_ticket(self):
        self.probe.active=False
        with self.assertRaisesRegex(RecoveryRejected,"PROVIDER_RECHECK_REQUIRED"):
            self.resume()
        self.assertEqual(self.probe.checks,1)

    def test_concurrent_reattach_epoch_change_during_provider_readback(self):
        def rotate():
            self.repo.epoch+=1
        self.probe.on_verify=rotate
        with self.assertRaisesRegex(RecoveryRejected,"LEASE_CHANGED"):
            self.resume()
        self.assertEqual(self.repo.epoch,2)

    def test_sql_negative_attestation_must_deny_ticket(self):
        self.repo.active=False
        with self.assertRaisesRegex(RecoveryRejected,"PROVIDER_RECHECK_REQUIRED"):
            self.resume()
        self.assertEqual(self.probe.checks,0)

    def test_no_provider_adapter_always_fails_closed(self):
        self.service=ReattachmentService(self.repo,NoProviderProbe(),self.tickets)
        with self.assertRaisesRegex(RecoveryRejected,"PROVIDER_RECHECK_REQUIRED"):
            self.resume()

    def test_cancel_own_only_marks_intent_and_revokes_ticket(self):
        token=self.resume().ticket
        self.assertEqual(self.service.cancel_task(principal=self.owner,
            session_digest=SESSION,csrf_digest=CSRF,task_id=TASK),
            "stop_requested_provider_not_released")
        self.assertTrue(self.repo.cancelled)
        with self.assertRaisesRegex(RecoveryRejected,"LEASE_CHANGED"):
            self.service.authorize_ticket(token,principal=self.owner,task_id=TASK)
        with self.assertRaisesRegex(RecoveryRejected,"TASK_NOT_FOUND"):
            self.resume()

    def test_list_only_confirmed_own_tasks_without_private_provider_ids(self):
        tasks=self.service.list_tasks(principal=self.owner,
            session_digest=SESSION,csrf_digest=CSRF)
        self.assertEqual(len(tasks),1)
        self.assertEqual(tasks[0]["task_id"],str(TASK))
        self.assertNotIn("provider",str(tasks))
        self.assertNotIn("session_id",str(tasks))

    def test_database_failure_never_returns_exception_text(self):
        self.repo.db_fails=True
        with self.assertRaisesRegex(RecoveryRejected,"BACKEND_UNAVAILABLE") as out:
            self.resume()
        self.assertNotIn("PRIVATE_DATABASE_STACKTRACE",str(out.exception))

    def test_viewer_role_cannot_resume(self):
        viewer=Principal(A,USER_A,"viewer",CSRF)
        with self.assertRaisesRegex(RecoveryRejected,"NOT_AUTHORIZED"):
            self.resume(principal=viewer)


if __name__=="__main__":
    unittest.main(verbosity=2)
