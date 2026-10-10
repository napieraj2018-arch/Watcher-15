"""SteelSelfTest-only diagnostics: distinguish intended from actual restore.

No live Steel, passwords, network, browser storage values or customer accounts.
"""
import asyncio
import copy
import os
import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from test_profile_recovery_051 import ns, Context, remote
from test_synthetic_fixture_exact import fixture
from steel_context_fix import (
    ReliabilityError, guard_synthetic_fixture_save,
    synthetic_fixture_browser_verified, synthetic_fixture_page_readback,
    install as install_context_fix,
)


class UnappliedContext(Context):
    async def set_storage_state(self, value):
        # Simulate Playwright accepting the API call while silently retaining
        # the old state. The previous diagnostic falsely claimed merged PASS.
        self.states.append(copy.deepcopy(value))


class SyntheticReadback(unittest.IsolatedAsyncioTestCase):
    async def test_true_readback_after_successful_restore(self):
        wanted = fixture("test-only-match","test-only-match")
        r, c = remote(current={"cookies": [], "origins": []})
        r.engine._native_bindings["r"]["profile"] = "SteelSelfTest"
        await ns["native_context"](r,storage_state=wanted)
        result=r.engine._native_bindings["r"]["synthetic_fixture_evidence"]
        self.assertTrue(result["post_apply_readback_available"])
        self.assertTrue(result["exact_marker"]["proposed"]["exact_pair_matches"])
        self.assertTrue(result["exact_marker"]["resolved"]["exact_pair_matches"])
        self.assertEqual(len(c.states),1)

    async def test_noop_state_apply_cannot_claim_merged_success(self):
        wanted = fixture("test-only-match","test-only-match")
        r,c=remote(current={"cookies": [], "origins": []})
        fake=UnappliedContext(c.current)
        r.browser.contexts=[fake]
        r.engine._native_bindings["r"]["profile"]="SteelSelfTest"
        await ns["native_context"](r,storage_state=wanted)
        data=r.engine._native_bindings["r"]["synthetic_fixture_evidence"]
        self.assertTrue(data["exact_marker"]["proposed"]["exact_pair_matches"])
        self.assertFalse(data["exact_marker"]["resolved"]["exact_pair_matches"])
        self.assertEqual(data["resolved"]["test_cookie_values"],0)
        self.assertEqual(data["resolved"]["test_local_storage_values"],0)

    async def test_readback_failure_is_not_reported_as_verified(self):
        class BrokenReadback(Context):
            calls=0
            async def storage_state(self,**kwargs):
                self.calls+=1
                if self.calls>1: raise RuntimeError("fixture error must not leak")
                return await super().storage_state(**kwargs)
        r,c=remote(current={"cookies": [], "origins": []})
        broken=BrokenReadback(c.current)
        r.browser.contexts=[broken]
        r.engine._native_bindings["r"]["profile"]="SteelSelfTest"
        await ns["native_context"](r,storage_state=fixture())
        d=r.engine._native_bindings["r"]["synthetic_fixture_evidence"]
        self.assertFalse(d["post_apply_readback_available"])
        self.assertFalse(d["exact_marker"]["resolved"]["exact_pair_matches"])
        self.assertNotIn("fixture error",str(d))

    async def test_other_profiles_do_not_receive_test_diagnostics(self):
        r,_=remote(current={"cookies": [], "origins": []})
        r.engine._native_bindings["r"]["profile"]="Google - Architekt"
        await ns["native_context"](r,storage_state=fixture())
        self.assertNotIn("synthetic_fixture_evidence",r.engine._native_bindings["r"])

    async def test_fixture_page_observation_reveals_only_booleans(self):
        class Page:
            url="https://ai-browser-vault.floot.app/browser-check"
            async def evaluate(self,js):
                assert "localStorage.getItem" in js and "document.cookie" in js
                return {"cookie_present":True,"storage_present":True,
                        "pair_matches":False}
        report=await synthetic_fixture_page_readback(Page())
        self.assertEqual(report,{
            "status":"observed","cookie_present":True,
            "storage_present":True,"pair_matches":False})
        self.assertNotIn("test-only-match",str(report))

    async def test_never_probe_non_fixture_site(self):
        class Page:
            url="https://www.facebook.com/"
            async def evaluate(self,js):
                raise AssertionError("must never evaluate private page storage")
        self.assertEqual(await synthetic_fixture_page_readback(Page()),
                         {"status":"not_fixture_page"})

    async def test_malformed_browser_response_fails_closed(self):
        class Page:
            url="https://ai-browser-vault.floot.app/browser-check"
            async def evaluate(self,js):
                return {"cookie_present":"sensitive", "storage_present":True,
                        "pair_matches":True,"cookie_value":"SHOULD_NEVER_ECHO"}
        self.assertEqual(await synthetic_fixture_page_readback(Page()),
                         {"status":"readback_invalid"})


class SyntheticSaveGuard(unittest.IsolatedAsyncioTestCase):
    class Page:
        url = "https://ai-browser-vault.floot.app/browser-check"
        def __init__(self, valid=True):
            self.valid = valid
        async def evaluate(self, js):
            return {"cookie_present": True, "storage_present": True,
                    "pair_matches": self.valid}

    async def test_matching_live_dom_allows_synthetic_save_after_recovery(self):
        session = SimpleNamespace(profile="SteelSelfTest", page=self.Page())
        await guard_synthetic_fixture_save(session, {
            "backup_recovery_applied": True,
            "synthetic_fixture_evidence": {
                "exact_marker": {"resolved": {"exact_pair_matches": False}}
            }
        })
        self.assertTrue(synthetic_fixture_browser_verified({
            "status": "observed", "cookie_present": True,
            "storage_present": True, "pair_matches": True,
        }))

    async def test_mismatch_blocks_synthetic_profile_save(self):
        session = SimpleNamespace(profile="SteelSelfTest", page=self.Page(False))
        with self.assertRaisesRegex(
                ReliabilityError, "^SYNTHETIC_FIXTURE_SAVE_NOT_VERIFIED$"):
            await guard_synthetic_fixture_save(session, {})

    async def test_unknown_page_after_recovery_blocks_synthetic_save(self):
        class NotFixture:
            url = "about:blank"
            async def evaluate(self, js):
                raise AssertionError("not a fixture, must not be evaluated")
        session = SimpleNamespace(profile="SteelSelfTest", page=NotFixture())
        with self.assertRaisesRegex(
                ReliabilityError, "^SYNTHETIC_FIXTURE_SAVE_NOT_VERIFIED$"):
            await guard_synthetic_fixture_save(session, {
                "backup_recovery_applied": True
            })

    async def test_incoherent_chromium_snapshot_needs_real_page_proof(self):
        session = SimpleNamespace(profile="SteelSelfTest",
                                  page=SimpleNamespace(url="about:blank"))
        with self.assertRaisesRegex(ReliabilityError,
                                    "SYNTHETIC_FIXTURE_SAVE_NOT_VERIFIED"):
            await guard_synthetic_fixture_save(session, {
                "synthetic_fixture_evidence": {
                    "exact_marker": {
                        "resolved": {"exact_pair_matches": False}
                    }
                }
            })

    async def test_closed_page_metadata_fails_safe_not_leaky(self):
        class ClosedPage:
            @property
            def url(self):
                raise RuntimeError("secret provider URL / closed page")
        session = SimpleNamespace(profile="SteelSelfTest", page=ClosedPage())
        self.assertEqual(await synthetic_fixture_page_readback(session.page),
                         {"status": "readback_unavailable"})
        with self.assertRaisesRegex(ReliabilityError,
                                    "^SYNTHETIC_FIXTURE_SAVE_NOT_VERIFIED$"):
            await guard_synthetic_fixture_save(
                session, {"backup_recovery_applied": True})

    async def test_other_profiles_are_never_inspected_or_blocked(self):
        class PrivatePage:
            @property
            def url(self):
                raise AssertionError("must not inspect any live account")
        for profile in ("Meta - Anita", "Google - Architekt",
                        "Meta - Maciej - Monitoring"):
            with self.subTest(profile=profile):
                await guard_synthetic_fixture_save(
                    SimpleNamespace(profile=profile, page=PrivatePage()),
                    {"backup_recovery_applied": True})

    async def test_no_recovery_no_fixture_can_stop_without_false_claims(self):
        session = SimpleNamespace(profile="SteelSelfTest",
                                  page=SimpleNamespace(url="about:blank"))
        await guard_synthetic_fixture_save(session, {})
        self.assertFalse(synthetic_fixture_browser_verified({
            "status": "not_fixture_page"
        }))


class WiredSaveGuard(unittest.IsolatedAsyncioTestCase):
    """Exercise the installed manager wrappers, not only a pure helper."""

    class Mcp:
        def tool(self):
            return lambda fn: fn
        def custom_route(self, *args, **kwargs):
            return lambda fn: fn

    async def _make_manager(self, good):
        calls = {"flush": 0, "stop": 0}
        async def original_flush(sid, *args, **kwargs):
            calls["flush"] += 1
            return {"saved": True}
        async def original_stop(sid, *args, **kwargs):
            calls["stop"] += 1
            manager._sessions.pop(sid, None)
            return {"profile_saved": True, "full_profile_saved": True}
        async def original_start(*args, **kwargs):
            raise AssertionError("do not create a provider session")
        async def original_status(sid):
            return {"session_id": sid}

        engine = SimpleNamespace(_native_bindings={}, request=original_status)
        manager = SimpleNamespace(
            _steel_engine=engine, _sessions={},
            start=original_start, stop=original_stop,
            status=original_status, flush_profile=original_flush)
        manager._session = lambda sid: manager._sessions[sid]
        class RuntimeRemoteBrowser:
            new_context = None
        runtime = types.SimpleNamespace(
            RemoteBrowser=RuntimeRemoteBrowser, VERSION="test")
        with patch.dict(sys.modules, {"steel_runtime": runtime}), patch.dict(
            os.environ, {
                "AI_BROWSER_ENGINE": "steel",
                "AI_BROWSER_PROFILE_STORE_URL":
                    "https://fixture.invalid/profile-vault"
            }):
            install_context_fix({
                "manager": manager, "mcp": self.Mcp(),
                "_SETUP_HTML": "technical fixture only"})
        page = SyntheticSaveGuard.Page(good)
        manager._sessions["sid"] = SimpleNamespace(
            profile="SteelSelfTest", page=page,
            browser=SimpleNamespace(remote_id="remote"))
        engine._native_bindings["remote"] = {
            "profile": "SteelSelfTest", "backup_recovery_applied": True}
        return manager, calls

    async def test_bad_fixture_blocks_both_flush_and_saved_stop(self):
        manager, calls = await self._make_manager(False)
        with self.assertRaisesRegex(ReliabilityError,
                                    "SYNTHETIC_FIXTURE_SAVE_NOT_VERIFIED"):
            await manager.flush_profile("sid")
        with self.assertRaisesRegex(ReliabilityError,
                                    "SYNTHETIC_FIXTURE_SAVE_NOT_VERIFIED"):
            await manager.stop("sid")
        self.assertEqual(calls, {"flush": 0, "stop": 0})
        self.assertIn("sid", manager._sessions)

    async def test_verified_fixture_allows_both_wrapped_operations(self):
        manager, calls = await self._make_manager(True)
        saved = await manager.flush_profile("sid")
        self.assertEqual(saved["saved"], True)
        stopped = await manager.stop("sid")
        self.assertTrue(stopped["profile_saved"])
        self.assertEqual(calls, {"flush": 1, "stop": 1})


if __name__ == "__main__":
    unittest.main(verbosity=2)
