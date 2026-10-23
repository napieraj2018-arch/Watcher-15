"""Offline security regressions for the mobile owner login handoff.

All sessions are synthetic. No Steel API, Meta login, passwords or real
profile data are used. These tests exercise the ACTUAL 51-tool MCP 2.3 guard.
"""
from __future__ import annotations
import asyncio
import json
import re
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from test_owner_parallel_mcp import MultiManager
from multi_capability_guard import MultiCapabilityGuard
from owner_mobile_handoff import (
    COOKIE, SETUP_ORIGIN, SETUP_PATH, _viewer_url, _login_url, _https_origin
)
from capability_guard import OwnershipError
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
        self.last_headless = None
        self.last_start_url = None

    async def start(self, profile, mode="read_only", start_url="about:blank",
                    headless=True):
        self.last_headless = headless
        self.last_start_url = start_url
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
        self.handoff.wall_clock=lambda:1700000100

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
        # Forces the Steel browser to use its portrait mobile viewport,
        # rather than squeezing a desktop screenshot into a tall iframe.
        self.assertIs(self.manager.last_headless,False)
        self.assertEqual(self.guard.capacity,5)

    async def test_slow_start_caps_invite_to_actual_guard_deadline(self):
        now = [100.0]
        self.guard.clock = self.handoff.clock = lambda: now[0]
        original_start = self.handoff.original_start

        async def slow_start(**args):
            result = await original_start(**args)
            now[0] += 270
            result["remaining_seconds"] = 600
            return result

        self.handoff.original_start = slow_start
        setup = await self.begin(timeout_seconds=900)
        lease = next(iter(self.guard.leases.values()))
        self.assertEqual(setup["expires_in_seconds"], 510)
        self.assertEqual(self.handoff.active.expires_at, 880)
        self.assertEqual(self.handoff.active.expires_at,
                         self.guard.close_deadlines[lease.internal_session_id])
        self.assertEqual(len(self.guard.leases), 1)
        self.assertEqual(self.manager.saved, [])

    async def delayed_viewer_setup(self, *, remaining, delay,
                                  timeout_seconds=900, close_in_lookup=False):
        now = [100.0]
        self.guard.clock = self.handoff.clock = lambda: now[0]
        self.manager.fake_viewer = None
        original_start = self.handoff.original_start

        async def start_without_viewer(**args):
            result = await original_start(**args)
            sid = result["session_id"]

            async def metadata(method, path, timeout):
                self.assertEqual(method, "GET")
                self.assertEqual(path, "/sessions/REDACTED_SYNTHETIC_REMOTE")
                self.assertEqual(timeout, 12)
                now[0] += delay
                if close_in_lookup:
                    await self.guard.watchdog(self.guard.leases[sid])
                return {"debugUrl": GOOD_URL}

            self.manager._sessions[sid].browser.engine = SimpleNamespace(request=metadata)
            result["remaining_seconds"] = remaining
            return result

        self.handoff.original_start = start_without_viewer
        return await self.begin(timeout_seconds=timeout_seconds)

    async def test_viewer_metadata_time_is_deducted_before_invite(self):
        setup = await self.delayed_viewer_setup(remaining=450, delay=80)
        lease = next(iter(self.guard.leases.values()))
        self.assertEqual(setup["expires_in_seconds"], 280)
        self.assertEqual(self.handoff.active.expires_at, 460)
        self.assertEqual(self.guard.close_deadlines[lease.internal_session_id], 460)
        self.assertEqual(len(self.guard.leases), 1)

    async def test_short_requested_invite_is_not_extended_to_larger_budget(self):
        setup = await self.delayed_viewer_setup(
            remaining=450, delay=80, timeout_seconds=120)
        self.assertEqual(setup["expires_in_seconds"], 120)
        self.assertEqual(self.handoff.active.expires_at, 300)

    async def test_short_actual_budget_can_further_reduce_valid_requested_ttl(self):
        setup = await self.delayed_viewer_setup(
            remaining=200, delay=30, timeout_seconds=120)
        self.assertEqual(setup["expires_in_seconds"], 80)
        self.assertEqual(self.handoff.active.expires_at, 210)

    async def test_exhausted_metadata_budget_saves_only_its_session_and_creates_no_invite(self):
        other = await self.guard.start(self.handoff.original_start, {
            "profile": "Meta - Other-Synthetic", "start_url": "https://example.com/"})
        other_lease = self.guard.authorize(other["session_id"])
        other_record = self.manager._sessions[other_lease.internal_session_id]
        with self.assertRaisesRegex(OwnershipError, "MOBILE_SETUP_BUDGET_EXHAUSTED"):
            await self.delayed_viewer_setup(remaining=100, delay=11)
        self.assertIsNone(self.handoff.active)
        self.assertEqual(self.manager.saved, ["INTERNAL_SYNTHETIC_SESSION_2"])
        self.assertEqual(set(self.guard.leases), {other_lease.internal_session_id})
        self.assertIs(self.manager._sessions[other_lease.internal_session_id], other_record)
        self.assertFalse(self.guard.quarantined)
        self.assertNotIn(PROFILE, self.guard.by_profile)

    async def test_exhausted_metadata_budget_failed_save_keeps_quarantine(self):
        self.manager.broken_save = True
        with self.assertRaisesRegex(OwnershipError, "MOBILE_SAVE_UNCONFIRMED"):
            await self.delayed_viewer_setup(remaining=100, delay=11)
        self.assertIsNone(self.handoff.active)
        self.assertTrue(self.guard.quarantined)
        self.assertEqual(len(self.guard.leases), 1)
        self.assertEqual([x["state"] for x in self.guard.safe_sessions()],
                         ["missing_session_quarantined"])

    async def test_watchdog_close_during_metadata_does_not_create_stale_invite(self):
        with self.assertRaisesRegex(OwnershipError, "MOBILE_SETUP_SESSION_EXPIRED"):
            await self.delayed_viewer_setup(
                remaining=100, delay=11, close_in_lookup=True)
        self.assertIsNone(self.handoff.active)
        self.assertEqual(self.manager.saved, ["INTERNAL_SYNTHETIC_SESSION_1"])
        self.assertEqual(self.guard.leases, {})
        self.assertEqual(self.guard.safe_sessions(), [])
        self.assertFalse(self.guard.quarantined)

    async def test_owner_cancellation_stops_only_bound_setup(self):
        previous=await self.mcp.call_tool("browser_start",{
            "profile":"Meta - Other-Synthetic",
            "start_url":"https://example.com/"})
        setup=await self.begin()
        self.assertEqual(len(self.manager._sessions),2)
        receipt=await self.handoff.cancel({"setup_id":setup["setup_id"]})
        self.assertTrue(receipt["cancelled"])
        self.assertTrue(receipt["profile_saved"])
        self.assertTrue(receipt["full_profile_saved"])
        self.assertEqual(receipt["status"],"saved_and_closed")
        self.assertFalse(receipt["auth_verified"])
        self.assertEqual(len(self.manager._sessions),1)
        self.assertEqual(next(iter(self.manager._sessions.values())).profile,
                         "Meta - Other-Synthetic")
        self.assertTrue(self.handoff.active.finished)

    async def test_cancellation_without_setup_id_denied(self):
        setup=await self.begin()
        with self.assertRaisesRegex(OwnershipError,"MOBILE_SETUP_ID_NOT_OWNED"):
            await self.handoff.cancel({"setup_id":"X"*43})
        self.assertEqual(len(self.manager._sessions),1)
        self.assertFalse(self.handoff.active.finished)

    async def test_login_link_claim_view_finish_saves_exact_session(self):
        setup=await self.begin()
        home=await self.handoff.home(request(SETUP_PATH))
        self.assertEqual(home.status_code,200)
        self.assertNotIn(b"synthetic-valid-debug",home.body)
        self.assertNotIn(setup["setup_url"].split("#s=")[-1].encode(),home.body)
        self.assertIn(b"location.hash",home.body)
        self.assertIn(b'location.replace("/owner-mobile-login/touch")',home.body)
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
        self.assertIn(b'id="fullscreen"',view.body)
        self.assertIn(b'Sterowanie dotykowe',view.body)
        self.assertIn(b'href="/owner-mobile-login/touch"',view.body)
        self.assertIn(b'Alternatywa: podgl',view.body)
        self.assertNotIn(b"<iframe",view.body)
        self.assertNotIn(b"height:70vh",view.body)
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

    async def test_reopening_claimed_link_resumes_only_same_cookie_session(self):
        setup=await self.begin()
        first=await self.claim(setup)
        self.assertEqual(first.status_code,200)
        cookie=first.headers["set-cookie"].split(";",1)[0]
        home=await self.handoff.home(request(SETUP_PATH,cookie=cookie))
        self.assertEqual(home.status_code,303)
        self.assertEqual(home.headers["location"],SETUP_PATH+"/touch")
        self.assertEqual(len(self.manager._sessions),1)
        self.assertNotIn(GOOD_URL,str(home.headers))
        # No cookie: same one-use invitation cannot be claimed again.
        anonymous=await self.handoff.home(request(SETUP_PATH))
        self.assertEqual(anonymous.status_code,200)
        self.assertIn(b"location.hash",anonymous.body)
        replay=await self.claim(setup)
        self.assertEqual(replay.status_code,410)
        self.assertEqual(len(self.manager._sessions),1)

    async def test_expired_claim_cookie_cannot_resume_or_reveal_player(self):
        setup=await self.begin()
        first=await self.claim(setup)
        cookie=first.headers["set-cookie"].split(";",1)[0]
        self.handoff.clock=lambda:100 + setup["expires_in_seconds"] + 91
        expired=await self.handoff.home(request(SETUP_PATH,cookie=cookie))
        self.assertEqual(expired.status_code,200)
        self.assertNotIn(GOOD_URL,expired.body.decode())
        expired_view=await self.handoff.view(request(SETUP_PATH+"/view",cookie=cookie))
        self.assertNotIn(GOOD_URL,expired_view.body.decode())

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

    async def test_safe_facebook_deep_links_normalize_to_login(self):
        # Work often supplies a home page or account settings URL rather
        # than one of the two literal URLs accepted before this fix.
        for raw in (
            "https://www.facebook.com",
            "https://www.facebook.com/",
            "https://facebook.com/",
            "https://business.facebook.com/settings/?tab=profile_access",
            "https://www.facebook.com/settings/?tab=profile_access",
            "https://www.facebook.com/login",
            "https://www.facebook.com/login/?next=https%3A%2F%2Fevil.test",
            "https://www.facebook.com/login.php?next=malicious",
            "https://www.facebook.com/groups/1886172518407420/",
        ):
            with self.subTest(raw=raw):
                self.assertEqual(_login_url(raw), FACEBOOK)
        self.assertEqual(_login_url("https://m.facebook.com/login/?next=unsafe"),
                         "https://m.facebook.com/")
        setup = await self.handoff.create({
            "profile": PROFILE,
            "login_url": "https://www.facebook.com/settings/?tab=profile_access",
        })
        self.assertEqual(setup["status"], "ready_for_human_login")
        self.assertEqual(self.manager.last_start_url, FACEBOOK)
        self.assertEqual(len(self.manager._sessions), 1)

    async def test_no_redirect_to_fake_facebook_origin(self):
        for raw in ("http://www.facebook.com/login/",
                    "https://www.facebook.com.evil.test/login/",
                    "https://fakefacebook.com/login/",
                    "https://facebook.com.evil.test/login/",
                    "https://www.facebook.com:444/login/",
                    "https://somebody:password@www.facebook.com/login/",
                    "https://www.facebook.com./login/",
                    "https://www.facebook.com/\\nignored",
                    "https://www.facebook.com/login/ ",
                    "https://login.openai.com/",
                    "https://custom.canva.com/login/",
                    "https://customer.metricool.com/login/",
                    "about:blank"):
            with self.subTest(raw=raw):
                with self.assertRaisesRegex(OwnershipError,"MOBILE_LOGIN_ORIGIN_NOT_ALLOWED"):
                    await self.handoff.create({
                        "profile":PROFILE,"login_url":raw})
        self.assertEqual(self.manager._sessions,{})

    async def test_service_login_deep_links_use_fixed_official_destinations(self):
        cases = {
            "https://chatgpt.com/g/g-example/project?tab=sources":
                "https://chatgpt.com/auth/login",
            "https://chat.openai.com/?next=https://evil.test/":
                "https://chatgpt.com/auth/login",
            "https://auth.openai.com/log-in?state=discarded":
                "https://chatgpt.com/auth/login",
            "https://auth0.openai.com/authorize?redirect_uri=https://evil.test/":
                "https://chatgpt.com/auth/login",
            "https://app.metricool.com/planner?next=https://evil.test/":
                "https://app.metricool.com/login",
            "https://www.metricool.com/": "https://app.metricool.com/login",
            "https://www.canva.com/design/synthetic/edit?redirect=unsafe":
                "https://www.canva.com/login/",
            "https://canva.com/pl_pl/login/": "https://www.canva.com/login/",
            "https://accounts.google.com/ServiceLogin?continue=https://evil.test/":
                "https://accounts.google.com/ServiceLogin",
            "https://mail.google.com/mail/u/0/#inbox":
                "https://accounts.google.com/ServiceLogin",
            "https://www.instagram.com/synthetic/":
                "https://www.instagram.com/accounts/login/",
            "https://architekt.radom.pl/poradnik/wp-admin/admin.php?page=wpcode":
                "https://architekt.radom.pl/poradnik/wp-login.php",
            "https://weterynarz.radom.pl/wp-admin/?redirect_to=https://evil.test/":
                "https://weterynarz.radom.pl/wp-login.php",
        }
        for supplied, expected in cases.items():
            with self.subTest(supplied=supplied):
                self.assertEqual(_login_url(supplied), expected)

    async def test_service_scope_is_bound_to_handoff_and_ui_names_service(self):
        cases = (
            ("ChatGPT", "https://chatgpt.com/g/synthetic", "https://chatgpt.com/auth/login"),
            ("Metricool", "https://app.metricool.com/planner", "https://app.metricool.com/login"),
            ("Canva", "https://www.canva.com/design/synthetic", "https://www.canva.com/login/"),
            ("Google", "https://accounts.google.com/", "https://accounts.google.com/ServiceLogin"),
            ("Instagram", "https://www.instagram.com/", "https://www.instagram.com/accounts/login/"),
            ("WordPress — Architekt", "https://architekt.radom.pl/poradnik/wp-admin/",
             "https://architekt.radom.pl/poradnik/wp-login.php"),
            ("WordPress — Napieraj i Synowie", "https://weterynarz.radom.pl/wp-admin/",
             "https://weterynarz.radom.pl/wp-login.php"),
        )
        for service, supplied, expected in cases:
            with self.subTest(service=service):
                setup = await self.begin(login_url=supplied)
                self.assertEqual(self.manager.last_start_url, expected)
                self.assertEqual(setup["service"], service)
                self.assertEqual(setup["login_origin"], _https_origin(expected))
                record = self.handoff.active
                self.assertEqual(record.service_name, service)
                self.assertIn(_https_origin(expected), record.allowed_origins)
                self.assertIsInstance(record.allowed_origins, frozenset)
                self.assertNotIn("https://evil.test", record.allowed_origins)
                claimed = await self.claim(setup)
                cookie = claimed.headers["set-cookie"].split(";", 1)[0]
                view = await self.handoff.view(request(SETUP_PATH+"/view",cookie=cookie))
                self.assertIn(("Logowanie — " + service).encode(), view.body)
                self.assertNotIn(b"Logowanie Facebook", view.body)
                receipt = await self.handoff.cancel({"setup_id":setup["setup_id"]})
                self.assertTrue(receipt["profile_saved"])

    async def test_untrusted_service_lookalikes_and_client_scope_are_rejected(self):
        for supplied in (
            "https://chatgpt.com.evil.test/", "https://evil-chatgpt.com/",
            "https://auth.openai.com.evil.test/", "https://chatgpt.com./",
            "https://chatgpt.com:444/", "https://evil@chatgpt.com/",
            "https://app.metricool.com.evil.test/", "http://app.metricool.com/",
            "https://www.canva.com/\\evil.test", "https://accounts.google.com/ ",
            "https://accounts.google.com.evil.test/", "https://accounts.google.com@evil.test/",
            "https://127.0.0.1/", "file:///etc/passwd", "javascript:alert(1)",
            "https://architekt.radom.pl.evil.test/wp-login.php",
            "https://other.architekt.radom.pl/wp-login.php", "https://radom.pl/wp-login.php",
        ):
            with self.subTest(supplied=supplied):
                with self.assertRaisesRegex(OwnershipError, "MOBILE_LOGIN_ORIGIN_NOT_ALLOWED"):
                    await self.begin(login_url=supplied)
        with self.assertRaisesRegex(OwnershipError, "MOBILE_SETUP_PARAMETERS_INVALID"):
            await self.begin(login_url="https://chatgpt.com/",
                             allowed_origins=["https://evil.test"])
        self.assertEqual(self.manager.counter, 0)

    async def test_steel_player_url_enables_real_input_without_leaking_token(self):
        # The live Steel player accepts video and can still be read-only
        # unless both the provider session and viewer request allow input.
        base = ("https://api.steel.dev/v1/sessions/"
                "b87f2eeb-7dcb-4cb0-aa34-d7aeb5e4eaee/player")
        self.assertEqual(_viewer_url(base), base
                         + "?interactive=true&showControls=true")
        self.assertEqual(
            _viewer_url(base + "?interactive=false&showControls=false"),
            base + "?interactive=true&showControls=true")
        self.manager.fake_viewer = base + "?interactive=false"
        setup = await self.begin()
        self.assertNotIn(base, str(setup))
        claimed = await self.claim(setup)
        cookie = claimed.headers["set-cookie"].split(";", 1)[0]
        view = await self.handoff.view(
            request(SETUP_PATH + "/view", cookie=cookie))
        self.assertEqual(view.status_code, 200)
        self.assertIn(b"interactive=true", view.body)
        self.assertIn(b"showControls=true", view.body)
        self.assertNotIn(b"interactive=false", view.body)
        without_cookie = await self.handoff.view(
            request(SETUP_PATH + "/view"))
        self.assertNotIn(base.encode(), without_cookie.body)
        saved = await self.handoff.finish(
            request(SETUP_PATH + "/finish", "POST", {}, cookie=cookie))
        self.assertEqual(saved.status_code, 200)

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

    async def test_watchdog_saved_stop_retires_only_expired_handoff(self):
        first = await self.begin()
        old_record = self.handoff.active
        old_handle = old_record.handle
        # Emulate the real guard watchdog completing a verified saved-stop
        # without pressing the mobile page's Finish button.
        receipt = await self.guard.action(
            "browser_stop", self.handoff.original_stop,
            {"session_id": old_handle})
        self.assertTrue(receipt["profile_saved"])
        self.assertTrue(receipt["full_profile_saved"])
        self.assertEqual(self.guard.safe_sessions(), [])
        self.assertFalse(old_record.finished)
        second = await self.begin()
        self.assertNotEqual(second["setup_id"], first["setup_id"])
        self.assertTrue(old_record.finished)
        self.assertEqual(old_record.viewer_url, "")
        self.assertIsNone(old_record.cookie_digest)
        self.assertEqual(len(self.manager._sessions), 1)
        # Previously consumed links cannot adopt the newly created browser.
        replay = await self.claim(first)
        self.assertEqual(replay.status_code, 410)

    async def test_retired_setup_does_not_close_other_owned_profiles(self):
        first = await self.begin()
        other = await self.mcp.call_tool("browser_start", {
            "profile": "Meta - Other-Synthetic",
            "start_url": "https://example.com/"})
        self.assertEqual(len(self.manager._sessions), 2)
        receipt = await self.guard.action(
            "browser_stop", self.handoff.original_stop,
            {"session_id": self.handoff.active.handle})
        self.assertTrue(receipt["full_profile_saved"])
        next_setup = await self.begin()
        self.assertEqual(len(self.manager._sessions), 2)
        profiles = sorted(s.profile for s in self.manager._sessions.values())
        self.assertEqual(profiles, ["Meta - Other-Synthetic", PROFILE])
        self.assertNotEqual(first["setup_id"], next_setup["setup_id"])

    async def test_uncertain_saved_stop_does_not_retire_stale_handoff(self):
        await self.begin()
        self.manager.broken_save = True
        receipt = await self.guard.action(
            "browser_stop", self.handoff.original_stop,
            {"session_id": self.handoff.active.handle})
        self.assertFalse(receipt["full_profile_saved"])
        self.assertTrue(self.guard.quarantined)
        with self.assertRaisesRegex(OwnershipError, "MOBILE_SETUP_IN_PROGRESS"):
            await self.begin()
        self.assertFalse(self.handoff.active.finished)
        self.assertEqual(self.manager.counter, 1)

    async def test_active_lease_does_not_retire_just_because_time_passed(self):
        first = await self.begin()
        # 1000 elapsed handoff seconds is NOT evidence of profile save,
        # provider release, or expiration of the owner guard's lease.
        self.handoff.clock = lambda: 1000
        with self.assertRaisesRegex(OwnershipError, "MOBILE_SETUP_IN_PROGRESS"):
            await self.begin()
        self.assertFalse(self.handoff.active.finished)
        self.assertEqual(len(self.manager._sessions), 1)

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

    async def claimed_setup(self, **kwargs):
        setup = await self.begin(**kwargs)
        reply = await self.claim(setup)
        return setup, reply.headers["set-cookie"].split(";", 1)[0]

    async def read_status(self, cookie):
        reply = await self.handoff.status(request(SETUP_PATH + "/status", cookie=cookie))
        self.assertEqual(reply.status_code, 200)
        return json.loads(reply.body)

    async def test_lost_finish_response_can_be_read_and_repeated_without_second_stop(self):
        setup, cookie = await self.claimed_setup()
        first = await self.handoff.finish(request(SETUP_PATH + "/finish", "POST", {}, cookie=cookie))
        self.assertEqual(first.status_code, 200)
        receipt = json.loads(first.body)
        self.assertTrue(receipt["profile_saved"])
        self.assertTrue(receipt["full_profile_saved"])
        self.assertEqual(receipt["save_confirmed_at"], 1700000100)
        self.assertFalse(receipt["auth_verified"])
        self.assertNotIn("set-cookie", first.headers)
        self.assertIsNone(self.handoff._cookie_record(request(SETUP_PATH, cookie=cookie)))
        self.assertEqual(await self.read_status(cookie), receipt)
        repeated = await self.handoff.finish(request(SETUP_PATH + "/finish", "POST", {}, cookie=cookie))
        self.assertEqual(json.loads(repeated.body), receipt)
        self.assertEqual(self.manager.saved, ["INTERNAL_SYNTHETIC_SESSION_1"])
        home = await self.handoff.home(request(SETUP_PATH, cookie=cookie))
        self.assertIn("Profil zapisany".encode(), home.body)
        self.assertNotIn(GOOD_URL.encode(), home.body)
        self.assertEqual((await self.claim(setup)).status_code, 410)

    async def test_cancel_has_saved_semantics_and_is_idempotent(self):
        setup, cookie = await self.claimed_setup()
        first = await self.handoff.cancel({"setup_id": setup["setup_id"]})
        second = await self.handoff.cancel({"setup_id": setup["setup_id"]})
        self.assertEqual(first, second)
        self.assertEqual(first["completion_source"], "cancelled")
        self.assertTrue(first["full_profile_saved"])
        self.assertEqual(len(self.manager.saved), 1)
        self.assertEqual((await self.read_status(cookie))["status"], "saved_and_closed")

    async def test_cancelled_http_finish_keeps_confirmed_receipt_for_phone_return(self):
        _, cookie = await self.claimed_setup()
        entered, release = asyncio.Event(), asyncio.Event()
        original = self.handoff.original_stop

        async def delayed_stop(**kwargs):
            entered.set()
            await release.wait()
            return await original(**kwargs)

        self.handoff.original_stop = delayed_stop
        task = asyncio.create_task(self.handoff.finish(request(
            SETUP_PATH + "/finish", "POST", {}, cookie=cookie)))
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        await asyncio.sleep(0)
        release.set()
        with self.assertRaises(asyncio.CancelledError):
            await task
        status = await self.read_status(cookie)
        self.assertEqual(status["status"], "saved_and_closed")
        self.assertTrue(status["full_profile_saved"])
        self.assertFalse(self.guard.quarantined)
        repeated = await self.handoff.finish(request(SETUP_PATH + "/finish", "POST", {}, cookie=cookie))
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(len(self.manager.saved), 1)

    async def test_status_does_not_claim_save_before_full_receipt_after_record_removal(self):
        _, cookie = await self.claimed_setup()
        entered, release = asyncio.Event(), asyncio.Event()
        original = self.handoff.original_stop

        async def delayed_receipt(**kwargs):
            receipt = await original(**kwargs)
            entered.set()
            await release.wait()
            return receipt

        self.handoff.original_stop = delayed_receipt
        task = asyncio.create_task(self.handoff.finish(request(
            SETUP_PATH + "/finish", "POST", {}, cookie=cookie)))
        await asyncio.wait_for(entered.wait(), 1)
        self.assertEqual(self.manager._sessions, {})
        try:
            pending = await self.read_status(cookie)
            self.assertEqual(pending["status"], "saving")
            self.assertFalse(pending["profile_saved"])
            self.assertFalse(pending["full_profile_saved"])
            self.assertIsNone(pending["save_confirmed_at"])
            self.assertEqual(len(self.guard.leases), 1)
            home = await self.handoff.home(request(SETUP_PATH, cookie=cookie))
            self.assertEqual(home.status_code, 200)
            self.assertNotIn(GOOD_URL.encode(), home.body)
            self.assertNotIn(b'id="touch"', home.body)
        finally:
            release.set()
            await task
        self.assertTrue((await self.read_status(cookie))["full_profile_saved"])

    async def test_receipt_flags_without_released_lease_never_report_finished(self):
        _, cookie = await self.claimed_setup()

        async def incomplete_close(**kwargs):
            return {"profile_saved": True, "full_profile_saved": True}

        self.handoff.original_stop = incomplete_close
        reply = await self.handoff.finish(request(SETUP_PATH + "/finish", "POST", {}, cookie=cookie))
        self.assertEqual(reply.status_code, 503)
        self.assertFalse(self.handoff.active.finished)
        self.assertTrue(self.guard.quarantined)
        self.assertEqual(len(self.guard.leases), 1)
        status = await self.read_status(cookie)
        self.assertEqual(status["status"], "save_unconfirmed")
        self.assertFalse(status["full_profile_saved"])

    async def test_failed_save_readback_never_retries_close_or_clears_quarantine(self):
        _, cookie = await self.claimed_setup()
        self.manager.broken_save = True
        for _ in range(2):
            reply = await self.handoff.finish(request(SETUP_PATH + "/finish", "POST", {}, cookie=cookie))
            self.assertEqual(reply.status_code, 503)
        self.assertEqual(len(self.manager.saved), 1)
        self.assertTrue(self.guard.quarantined)
        self.assertEqual((await self.read_status(cookie))["status"], "save_unconfirmed")
        self.assertFalse(self.handoff.active.finished)

    async def test_watchdog_result_survives_control_expiry_without_changing_deadline(self):
        now = [100.0]
        self.guard.clock = self.handoff.clock = lambda: now[0]
        setup, cookie = await self.claimed_setup()
        lease = self.handoff.active.lease
        deadline = self.guard.close_deadlines[lease.internal_session_id]
        self.assertEqual(deadline, 880)
        self.assertEqual((await self.read_status(cookie))["remaining_seconds"], 690)
        now[0] = 800
        expired = await self.read_status(cookie)
        self.assertEqual(expired["status"], "expired")
        self.assertFalse(expired["profile_saved"])
        self.assertEqual(expired["auto_save_close_in_seconds"], 80)
        self.assertEqual(self.guard.close_deadlines[lease.internal_session_id], deadline)
        self.assertEqual(self.manager.saved, [])
        self.assertIsNone(self.handoff._cookie_record(request(SETUP_PATH, cookie=cookie)))
        now[0] = 880
        await self.guard.watchdog(lease)
        saved = await self.read_status(cookie)
        self.assertEqual(saved["status"], "saved_and_closed")
        self.assertEqual(saved["completion_source"], "owner_guard")
        self.assertTrue(saved["full_profile_saved"])
        repeated = await self.handoff.finish(request(SETUP_PATH + "/finish", "POST", {}, cookie=cookie))
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(len(self.manager.saved), 1)

    async def test_elapsed_time_alone_and_missing_manager_record_are_not_receipts(self):
        now = [100.0]
        self.guard.clock = self.handoff.clock = lambda: now[0]
        _, cookie = await self.claimed_setup()
        lease = self.handoff.active.lease
        self.manager._sessions.pop(lease.internal_session_id)
        now[0] = 900
        status = await self.read_status(cookie)
        self.assertEqual(status["status"], "save_unconfirmed")
        self.assertFalse(status["full_profile_saved"])
        self.assertIsNone(status["save_confirmed_at"])
        self.assertFalse(self.handoff.active.finished)
        self.assertEqual(len(self.guard.leases), 1)
        self.assertTrue(self.guard.quarantined)

    async def test_finish_racing_watchdog_reports_one_verified_close(self):
        now = [100.0]
        self.guard.clock = self.handoff.clock = lambda: now[0]
        _, cookie = await self.claimed_setup()
        entered, release = asyncio.Event(), asyncio.Event()
        original_stop = self.manager.stop
        calls = []

        async def delayed_stop(sid):
            calls.append(sid)
            receipt = await original_stop(sid)
            entered.set()
            await release.wait()
            return receipt

        self.manager.stop = delayed_stop
        now[0] = 880
        watchdog = asyncio.create_task(self.guard.watchdog(self.handoff.active.lease))
        await asyncio.wait_for(entered.wait(), 1)
        finish = asyncio.create_task(self.handoff.finish(request(
            SETUP_PATH + "/finish", "POST", {}, cookie=cookie)))
        await asyncio.sleep(0)
        self.assertTrue(self.handoff.active.saving)
        release.set()
        await watchdog
        reply = await finish
        self.assertEqual(reply.status_code, 200)
        self.assertTrue(json.loads(reply.body)["full_profile_saved"])
        self.assertEqual(calls, ["INTERNAL_SYNTHETIC_SESSION_1"])
        self.assertFalse(self.guard.quarantined)

    async def test_result_cookie_cannot_access_new_session_or_outlive_readback_window(self):
        _, cookie = await self.claimed_setup()
        await self.handoff.finish(request(SETUP_PATH + "/finish", "POST", {}, cookie=cookie))
        other = await self.guard.start(self.handoff.original_start, {
            "profile": PROFILE, "start_url": "https://example.com/"})
        lease = self.guard.authorize(other["session_id"])
        self.assertIsNone(self.handoff._cookie_record(request(SETUP_PATH, cookie=cookie)))
        self.assertEqual((await self.read_status(cookie))["status"], "saved_and_closed")
        await self.handoff.finish(request(SETUP_PATH + "/finish", "POST", {}, cookie=cookie))
        self.assertIn(lease.internal_session_id, self.manager._sessions)
        self.assertEqual(len(self.manager.saved), 1)
        self.handoff.clock = lambda: self.handoff.active.receipt_expires_at + 1
        denied = await self.handoff.status(request(SETUP_PATH + "/status", cookie=cookie))
        self.assertEqual(denied.status_code, 410)
        wrong = await self.handoff.status(request(SETUP_PATH + "/status", cookie=COOKIE + "=" + "Z" * 43))
        self.assertEqual(wrong.status_code, 410)
        self.assertIn(lease.internal_session_id, self.manager._sessions)

    async def test_status_exposes_only_safe_backup_and_live_authentication_evidence(self):
        _, cookie = await self.claimed_setup(login_url="https://myaccount.google.com/")
        backup = {"ok": True, "saved_at": 1700000000}

        async def metadata(sid):
            self.manager._session(sid)
            return {"url": "https://myaccount.google.com/?private=DO_NOT_RETURN",
                    "portable_backup": backup,
                    "authentication": {"stage": "authenticated", "authenticated": True,
                                       "private_identity": "DO_NOT_RETURN"},
                    "secret": "DO_NOT_RETURN"}

        self.manager.status = metadata
        active = await self.read_status(cookie)
        self.assertEqual(active["last_successful_backup_at"], 1700000000)
        self.assertTrue(active["portable_backup_ok"])
        self.assertFalse(active["profile_saved"])
        self.assertFalse(active["full_profile_saved"])
        self.assertTrue(active["auth_verified"])
        self.assertNotIn("DO_NOT_RETURN", json.dumps(active))
        backup.update({"ok": False, "saved_at": 1700000050})
        failed_backup = await self.read_status(cookie)
        self.assertEqual(failed_backup["last_successful_backup_at"], 1700000000)
        self.assertFalse(failed_backup["portable_backup_ok"])
        receipt = await self.handoff.finish(request(SETUP_PATH + "/finish", "POST", {}, cookie=cookie))
        saved = json.loads(receipt.body)
        self.assertTrue(saved["full_profile_saved"])
        self.assertFalse(saved["auth_verified"])
        self.assertEqual(saved["authentication_stage"], "unverified")

    async def test_sso_account_status_does_not_confirm_destination_login(self):
        _, cookie = await self.claimed_setup(login_url="https://chatgpt.com/")

        async def google_identity(sid):
            return {"url": "https://accounts.google.com/",
                    "authentication": {"stage": "authenticated", "authenticated": True}}

        self.manager.status = google_identity
        status = await self.read_status(cookie)
        self.assertFalse(status["auth_verified"])
        self.assertEqual(status["authentication_stage"], "unverified")

    async def test_own_confirmed_close_does_not_clear_another_session_quarantine(self):
        _, cookie = await self.claimed_setup()
        self.guard.quarantined = True
        reply = await self.handoff.finish(request(SETUP_PATH + "/finish", "POST", {}, cookie=cookie))
        self.assertEqual(reply.status_code, 200)
        self.assertTrue(json.loads(reply.body)["full_profile_saved"])
        self.assertTrue(self.guard.quarantined)


if __name__=="__main__":
    import unittest
    unittest.main(verbosity=2)
