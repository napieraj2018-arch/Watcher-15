"""Offline security regressions for the mobile owner login handoff.

All sessions are synthetic. No Steel API, Meta login, passwords or real
profile data are used. These tests exercise the ACTUAL 51-tool MCP 2.3 guard.
"""
from __future__ import annotations
import json
import re
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from test_owner_parallel_mcp import MultiManager
from session_ownership.multi_capability_guard import MultiCapabilityGuard
from session_ownership.owner_mobile_handoff import (
    COOKIE, SETUP_ORIGIN, SETUP_PATH, _viewer_url
)
from session_ownership.capability_guard import OwnershipError
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent /
                       "session_ownership" / "tests"))
from test_sdk_contract import fake_mcp

PROFILE = "Meta - Synthetic-Operator"
GOOD_URL = "https://app.steel.dev/sessions/synthetic-valid-debug"
FACEBOOK = "https://www.facebook.com/login/"


class FakeMobileManager(MultiManager):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.fake_viewer = GOOD_URL

    async def start(self, profile, mode="read_only", start_url="about:blank",
                    headless=True):
        result = await super().start(profile,mode=mode,start_url=start_url,
                                     headless=headless)
        self._sessions[result["session_id"]].browser = SimpleNamespace(
            _aib_viewer_url=self.fake_viewer,
            remote_id="REDACTED_SYNTHETIC_REMOTE",
        )
        return result


def request(path, method="GET", data=None, cookie="", origin=SETUP_ORIGIN,
            content_type="application/json"):
    headers = []
    if method == "POST":
        headers.extend([(b"origin",origin.encode("ascii")),
                        (b"content-type",content_type.encode("ascii"))])
    if cookie:
        headers.append((b"cookie",cookie.encode("ascii")))
    body = b"" if data is None else json.dumps(data).encode("utf-8")
    if method == "POST":
        headers.append((b"content-length",str(len(body)).encode("ascii")))
    async def receive():
        return {"type":"http.request","body":body,"more_body":False}
    scope = {
        "type":"http","method":method,"path":path,"headers":headers,
        "query_string":b"","scheme":"https",
        "server":("ai-browser-cloud.onrender.com",443),
    }
    return Request(scope, receive)


class MobileHandoffTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.manager = FakeMobileManager()
        self.mcp = fake_mcp(self.manager)
        async def legacy(_request):
            return JSONResponse({"unexpected":"legacy_viewer"})
        self.mcp._custom_starlette_routes.append(
            Route("/setup/legacy",legacy,methods=["POST"]))
        self.guard = MultiCapabilityGuard(
            self.mcp, self.manager, capacity=5, watchdog_enabled=False)
        self.assertEqual(self.guard.install(),51)
        self.handoff = self.guard.mobile_handoff
        self.handoff.clock=lambda:100

    async def begin(self, **kw):
        return await self.handoff.create(
            {"profile":PROFILE,"login_url":FACEBOOK,**kw})

    async def claim(self, setup):
        token=setup["setup_url"].split("#s=",1)[-1]
        return await self.handoff.claim(request(
            SETUP_PATH+"/claim","POST",{"token":token}))

    async def test_owner_setup_has_scoped_short_lived_fragment_not_debug_url(self):
        setup=await self.begin(timeout_seconds=900)
        self.assertEqual(setup["expires_in_seconds"],600)
        self.assertIn("/owner-mobile-login#s=",setup["setup_url"])
        self.assertNotIn("steel.dev",setup["setup_url"])
        self.assertNotIn("REDACTED_SYNTHETIC_REMOTE",str(setup))
        self.assertEqual(len(self.manager._sessions),1)
        self.assertEqual(next(iter(self.manager._sessions.values())).profile,PROFILE)
        self.assertEqual(next(iter(self.manager._sessions.values())).mode,"write")
        self.assertEqual(self.guard.capacity,5)

    async def test_login_link_claim_view_finish_saves_exact_session(self):
        setup=await self.begin()
        home=await self.handoff.home(request(SETUP_PATH))
        self.assertEqual(home.status_code,200)
        self.assertNotIn(b"synthetic-valid-debug",home.body)
        self.assertNotIn(setup["setup_url"].split("#s=")[-1].encode(),home.body)
        self.assertIn(b"location.hash",home.body)
        claim=await self.claim(setup)
        self.assertEqual(claim.status_code,200)
        cookie=claim.headers["set-cookie"].split(";",1)[0]
        self.assertTrue(cookie.startswith(COOKIE+"="))
        self.assertIn("httponly",claim.headers["set-cookie"].lower())
        self.assertIn("samesite=strict",claim.headers["set-cookie"].lower())
        view=await self.handoff.view(request(SETUP_PATH+"/view",cookie=cookie))
        self.assertEqual(view.status_code,200)
        self.assertIn(b"synthetic-valid-debug",view.body)
        self.assertNotIn(setup["setup_url"].split("#s=")[-1].encode(),view.body)
        finish=await self.handoff.finish(request(
            SETUP_PATH+"/finish","POST",{},cookie=cookie))
        self.assertEqual(finish.status_code,200)
        self.assertIn(b"saved_and_closed",finish.body)
        self.assertEqual(self.manager._sessions,{})
        self.assertEqual(self.guard.safe_sessions(),[])
        old_view=await self.handoff.view(request(
            SETUP_PATH+"/view",cookie=cookie))
        self.assertNotIn(b"synthetic-valid-debug",old_view.body)

    async def test_steal_link_after_claim_fails(self):
        setup=await self.begin()
        self.assertEqual((await self.claim(setup)).status_code,200)
        replay=await self.claim(setup)
        self.assertEqual(replay.status_code,410)
        self.assertNotIn(GOOD_URL,replay.body.decode())

    async def test_wrong_origin_and_content_type_cannot_claim(self):
        setup=await self.begin()
        token=setup["setup_url"].split("#s=",1)[1]
        bad=await self.handoff.claim(request(
            SETUP_PATH+"/claim","POST",{"token":token},
            origin="https://attacker.example"))
        self.assertEqual(bad.status_code,403)
        other=await self.handoff.claim(request(
            SETUP_PATH+"/claim","POST",{"token":token},
            content_type="text/plain"))
        self.assertEqual(other.status_code,403)
        good=await self.claim(setup)
        self.assertEqual(good.status_code,200)

    async def test_wrong_cookie_cannot_read_or_finish(self):
        await self.begin()
        fake=COOKIE+"="+("Z"*43)
        view=await self.handoff.view(request(SETUP_PATH+"/view",cookie=fake))
        self.assertNotIn(b"synthetic-valid-debug",view.body)
        reply=await self.handoff.finish(request(
            SETUP_PATH+"/finish","POST",{},cookie=fake))
        self.assertEqual(reply.status_code,410)
        self.assertEqual(len(self.manager._sessions),1)

    async def test_link_expires_without_deleting_or_adopting_session(self):
        setup=await self.begin()
        self.handoff.clock=lambda:1000
        response=await self.claim(setup)
        self.assertEqual(response.status_code,410)
        self.assertEqual(len(self.manager._sessions),1)
        self.assertFalse(self.guard.quarantined)

    async def test_no_redirect_to_fake_facebook_origin(self):
        for raw in ("http://www.facebook.com/login/",
                    "https://www.facebook.com.evil.test/login/",
                    "https://www.facebook.com/login/?redirect=abc",
                    "https://www.instagram.com/accounts/login/",
                    "about:blank"):
            with self.subTest(raw=raw):
                with self.assertRaisesRegex(OwnershipError,"MOBILE_LOGIN_ORIGIN_NOT_ALLOWED"):
                    await self.handoff.create({
                        "profile":PROFILE,"login_url":raw})
        self.assertEqual(self.manager._sessions,{})

    async def test_debug_url_rejected_for_untrusted_domains(self):
        for url in ("https://steel.dev.evil.test/x",
                    "http://app.steel.dev/sessions/xxx",
                    "https://x:secret@app.steel.dev/",
                    "https://app.steel.dev:4444/sessions/x",
                    "javascript:alert(1)"):
            with self.subTest(url=url),self.assertRaisesRegex(
                    OwnershipError,"MOBILE_VIEWER_INVALID"):
                _viewer_url(url)

    async def test_absent_viewer_closes_only_new_session(self):
        self.manager.fake_viewer="https://untrusted.example/sessions/x"
        with self.assertRaisesRegex(OwnershipError,"MOBILE_VIEWER_UNAVAILABLE"):
            await self.begin()
        self.assertEqual(self.manager._sessions,{})
        self.assertEqual(self.guard.safe_sessions(),[])

    async def test_other_owner_session_is_not_stopped(self):
        old=await self.mcp.call_tool("browser_start",{
            "profile":"Meta - Other-Synthetic","start_url":"https://example.com/"})
        self.assertEqual(len(self.manager._sessions),1)
        setup=await self.begin()
        self.assertEqual(len(self.manager._sessions),2)
        claimed=await self.claim(setup)
        cookie=claimed.headers["set-cookie"].split(";",1)[0]
        finish=await self.handoff.finish(request(
            SETUP_PATH+"/finish","POST",{},cookie=cookie))
        self.assertEqual(finish.status_code,200)
        self.assertEqual(len(self.manager._sessions),1)
        remaining=next(iter(self.manager._sessions.values()))
        self.assertEqual(remaining.profile,"Meta - Other-Synthetic")

    async def test_no_second_setup_during_first_active(self):
        await self.begin()
        with self.assertRaisesRegex(OwnershipError,"MOBILE_SETUP_IN_PROGRESS"):
            await self.begin()
        self.assertEqual(len(self.manager._sessions),1)

    async def test_scoped_routes_do_not_reenable_legacy_or_profile_delete(self):
        paths=[r.path for r in self.mcp._custom_starlette_routes]
        self.assertIn(SETUP_PATH,paths)
        self.assertIn("/health/context",paths)
        legacy = next(r for r in self.mcp._custom_starlette_routes
                      if r.path.startswith("/health") is False
                      and r.path != SETUP_PATH
                      and not r.path.startswith(SETUP_PATH+"/"))
        result=await legacy.endpoint(request(legacy.path,"POST",{}))
        self.assertEqual(result.status_code,403)
        with self.assertRaises(Exception):
            await self.mcp.call_tool("profile_delete",{
                "profile":PROFILE,"confirmation":"DELETE"})

    async def test_failed_save_does_not_pretend_complete(self):
        setup=await self.begin()
        reply=await self.claim(setup)
        cookie=reply.headers["set-cookie"].split(";",1)[0]
        self.manager.broken_save=True
        saved=await self.handoff.finish(request(
            SETUP_PATH+"/finish","POST",{},cookie=cookie))
        self.assertEqual(saved.status_code,503)
        self.assertFalse(self.handoff.active.finished)
        self.assertTrue(self.guard.quarantined)

    async def test_session_link_is_not_plain_provider_url(self):
        r=await self.begin()
        self.assertEqual(r["status"],"ready_for_human_login")
        self.assertNotIn("app.steel.dev",json.dumps(r))
        self.assertEqual(r["password_collected_by_chat"],False)
        self.assertEqual(r["browser_session_started"],True)


if __name__=="__main__":
    import unittest
    unittest.main(verbosity=2)
