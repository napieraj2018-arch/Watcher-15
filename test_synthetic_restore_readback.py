"""SteelSelfTest-only diagnostics: distinguish intended from actual restore.

No live Steel, passwords, network, browser storage values or customer accounts.
"""
import asyncio
import copy
import unittest
from types import SimpleNamespace

from test_profile_recovery_051 import ns, Context, remote
from test_synthetic_fixture_exact import fixture
from steel_context_fix import synthetic_fixture_page_readback


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
