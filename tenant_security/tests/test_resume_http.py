"""Real WSGI BFF entrypoint tests. All credentials/clients are synthetic.

The BFF has no live provider implementation; these tests prove only the
request/actor/CSRF/response boundary with a controlled fake provider.
"""
from __future__ import annotations
from hashlib import sha256
from uuid import UUID, uuid4
import unittest

from tenant_security.bff.gate import (
    COOKIE_NAME, Principal, exercise_wsgi,
)
from tenant_security.recovery.http import AuthenticatedTaskRecoveryHTTP
from tenant_security.recovery.service import ReattachmentService
from tenant_security.recovery.tickets import TaskResumeTickets
from tenant_security.tests.test_resume_service import (
    A, USER_A, USER_B, TASK, OTHER_TASK, KEY,
    Clock, RepoFake, ProviderFake, SESSION, CSRF,
)

COOKIE="S"*48
TOKEN_HASH=sha256(COOKIE.encode("ascii")).hexdigest()
CSRF_TOKEN="X"*48
CSRF_HASH=sha256(CSRF_TOKEN.encode("ascii")).hexdigest()
ORIGIN="https://browser.example.test"

class AdapterRepo(RepoFake):
    def _identity(self,sid,csrf):
        return (SESSION if sid==TOKEN_HASH else sid,
                CSRF if csrf==CSRF_HASH else csrf)
    def list_own(self,sid,csrf):
        return super().list_own(*self._identity(sid,csrf))
    def reattach(self,sid,csrf,task,attempt):
        x,y=self._identity(sid,csrf)
        return super().reattach(x,y,task,attempt)
    def cancel(self,sid,csrf,task):
        x,y=self._identity(sid,csrf)
        return super().cancel(x,y,task)


class HTTPBoundary(unittest.TestCase):
    def setUp(self):
        self.clock=Clock()
        self.repo=AdapterRepo()
        self.probe=ProviderFake()
        self.service=ReattachmentService(
            self.repo,self.probe,TaskResumeTickets(KEY,clock=self.clock))
        self.actor=Principal(A,USER_A,"operator",CSRF_HASH)
        self.actor_role="operator"
        self.auth_error=False

        def resolver(digest):
            if self.auth_error:
                raise RuntimeError("SECRET_DB_STACKTRACE")
            if digest==TOKEN_HASH:
                return Principal(A,USER_A,self.actor_role,CSRF_HASH)
            return None
        self.http=AuthenticatedTaskRecoveryHTTP(
            resolver,self.service,allowed_origin=ORIGIN)

    def req(self,method="GET",suffix="",body=None,**kw):
        options={
            "cookie":f"{COOKIE_NAME}={COOKIE}",
            "csrf":CSRF_TOKEN,
            "origin":ORIGIN,
            "body":{} if body is None else body,
            **kw,
        }
        return exercise_wsgi(
            self.http,method=method,path="/api/owner/tasks"+suffix,
            **options)

    def resume(self,**kw):
        return self.req(method="POST",suffix=f"/{TASK}/resume",
                        body={"attempt_id":str(uuid4())},**kw)

    def test_owner_can_list_and_resume_without_seeing_provider_ids(self):
        code,body,head=self.req()
        self.assertEqual(code,200)
        self.assertEqual([i["task_id"] for i in body["tasks"]],[str(TASK)])
        self.assertIn("no-store",head["Cache-Control"])
        code,body,headers=self.resume()
        self.assertEqual(code,200)
        self.assertEqual(body["status"],"ticket_issued_mcp_exchange_required")
        self.assertEqual(body["attachment_epoch"],1)
        self.assertEqual(body["expires_in_seconds"],30)
        self.assertTrue(body["resume_ticket"].startswith("aibr_"))
        self.assertNotIn("STEEL",str(body))
        self.assertNotIn("provider_id",str(body))
        self.assertIn("no-store",headers["Cache-Control"])

    def test_reattach_is_idempotent_but_new_request_rotates_epoch(self):
        nonce=str(uuid4())
        a=self.req(method="POST",suffix=f"/{TASK}/resume",
                   body={"attempt_id":nonce})
        b=self.req(method="POST",suffix=f"/{TASK}/resume",
                   body={"attempt_id":nonce})
        self.assertEqual(a[0],200)
        self.assertEqual(b[0],200)
        self.assertEqual((a[1]["attachment_epoch"],b[1]["attachment_epoch"]),(1,1))
        c=self.resume()
        self.assertEqual(c[1]["attachment_epoch"],2)

    def test_owner_cancel_does_not_claim_remote_close(self):
        before=self.resume()
        code,body,headers=self.req(method="POST",suffix=f"/{TASK}/cancel",
                                   body={})
        self.assertEqual(code,202)
        self.assertEqual(body["status"],"stop_requested_provider_not_released")
        self.assertIs(body["provider_closed"],False)
        self.assertIs(body["profile_saved_verified"],False)
        self.assertTrue(self.repo.cancelled)
        self.assertEqual(self.resume()[0],404)
        self.assertEqual(self.req()[1]["tasks"][0]["cancel_pending"],True)

    def test_tls_cookie_csrf_origin_required(self):
        self.assertEqual(self.req(scheme="http")[0],403)
        self.assertEqual(self.req(cookie=f"{COOKIE_NAME}=WRONG")[0],401)
        self.assertEqual(self.req(csrf="WRONG")[0],403)
        self.assertEqual(self.resume(origin="https://attacker.example")[0],403)
        self.assertEqual(self.resume(scheme="http")[0],403)
        self.assertEqual(self.resume(csrf="WRONG")[0],403)

    def test_actor_role_and_auth_backend_fail_closed(self):
        self.actor_role="viewer"
        self.assertEqual(self.req()[0],403)
        self.assertEqual(self.resume()[0],403)
        self.actor_role="operator"
        self.auth_error=True
        code,body,_=self.resume()
        self.assertEqual((code,body),(503,{"error":"auth_unavailable"}))
        self.assertNotIn("SECRET",str(body))

    def test_duplicate_and_extra_json_fields_are_rejected(self):
        _,nonce=uuid4(),str(uuid4())
        path=f"/{TASK}/resume"
        self.assertEqual(self.req(method="POST",suffix=path,
                    body={"attempt_id":nonce,"tenant_id":str(A)})[0],400)
        self.assertEqual(self.req(method="POST",suffix=path,
                    body=b'{"attempt_id":"abc","attempt_id":"def"}')[0],400)
        self.assertEqual(self.req(method="POST",suffix=path,
                    body={"attempt_id":"../tmp/file"})[0],400)
        self.assertEqual(self.req(method="POST",suffix=path,
                    content_type="text/plain",body={"attempt_id":nonce})[0],415)
        self.assertEqual(self.req(method="POST",suffix=f"/{TASK}/cancel",
                    body={"provider_id":"fake"})[0],400)

    def test_provider_and_database_errors_are_sanitized(self):
        self.probe.active=False
        code,body,_=self.resume()
        self.assertEqual((code,body),(409,{"error":"reconciliation_required"}))
        self.probe.active=True
        self.repo.db_fails=True
        code,body,_=self.resume()
        self.assertEqual((code,body),(503,{"error":"backend_unavailable"}))
        self.assertNotIn("PRIVATE",str(body))

    def test_unknown_task_does_not_expose_information(self):
        code,body,_=self.req(method="POST",
            suffix=f"/{OTHER_TASK}/resume",body={"attempt_id":str(uuid4())})
        self.assertEqual((code,body),(404,{"error":"not_found"}))
        self.assertEqual(self.req(method="GET",suffix="/random")[0],404)
        self.assertEqual(self.req(method="POST",suffix="",body={})[0],404)


if __name__=="__main__":
    unittest.main(verbosity=2)
