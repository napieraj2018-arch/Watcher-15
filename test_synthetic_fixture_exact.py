"""Exact synthetic cookie/Path/localStorage diagnostics; no user accounts or secrets."""
from __future__ import annotations
import copy
import json
import unittest

from test_profile_recovery_051 import ns, remote

inspect = ns["synthetic_fixture_exact_evidence"]
EXPIRES = 2200000000

def fixture(cookie="test-only-matching", storage="test-only-matching", *,
            path="/browser-check", name="aibrowser_test_cookie",
            key="aibrowser_public_test_marker", domain="ai-browser-vault.floot.app",
            secure=True, http_only=False, expires=EXPIRES):
    return {
        "cookies": [{"name":name,"domain":domain,"path":path,
                     "value":cookie,"expires":expires,
                     "httpOnly":http_only,"secure":secure,"sameSite":"Strict"}],
        "origins": [{"origin":"https://ai-browser-vault.floot.app",
                     "localStorage":[{"name":key,"value":storage}]}]
    }

class ExactEvidence(unittest.TestCase):
    def assertMatch(self, state, expected=True):
        d=inspect(state,state,state,now_seconds=1900000000)
        self.assertEqual(d["resolved"]["exact_pair_matches"],expected)
        self.assertEqual(d["source"],"exact_synthetic_marker_v2")
        return d

    def test_matching_specific_cookie_and_key(self):
        d=self.assertMatch(fixture())
        self.assertEqual(d["resolved"]["cookie_with_exact_name_count"],1)
        self.assertEqual(d["resolved"]["cookie_with_exact_path_count"],1)
        self.assertEqual(d["resolved"]["cookie_readable_count"],1)
        self.assertEqual(d["resolved"]["storage_exact_key_count"],1)

    def test_different_marker_value_rejected(self):
        self.assertMatch(fixture("old","new"),False)

    def test_wrong_name_not_counted(self):
        d=self.assertMatch(fixture(name="other_cookie"),False)
        self.assertEqual(d["resolved"]["cookie_with_exact_name_count"],0)
        self.assertTrue(d["resolved"]["valid_page_cookie_missing"])

    def test_wrong_storage_key_not_counted(self):
        d=self.assertMatch(fixture(key="other_storage"),False)
        self.assertEqual(d["resolved"]["storage_exact_key_count"],0)

    def test_cookie_wrong_path_not_page_cookie(self):
        d=self.assertMatch(fixture(path="/"),False)
        self.assertEqual(d["resolved"]["cookie_with_exact_name_count"],1)
        self.assertEqual(d["resolved"]["cookie_with_exact_path_count"],0)

    def test_parent_dot_domain_is_valid(self):
        self.assertMatch(fixture(domain=".ai-browser-vault.floot.app"))

    def test_cookie_from_unrelated_subdomain_ignored(self):
        d=self.assertMatch(fixture(domain="evil.ai-browser-vault.floot.app"),False)
        self.assertEqual(d["resolved"]["cookie_with_exact_name_count"],0)

    def test_http_only_cookie_not_visible_to_page(self):
        d=self.assertMatch(fixture(http_only=True),False)
        self.assertEqual(d["resolved"]["cookie_readable_count"],0)

    def test_nonsecure_test_cookie_not_accepted_as_valid(self):
        d=self.assertMatch(fixture(secure=False),False)
        self.assertTrue(d["resolved"]["valid_page_cookie_missing"])

    def test_expired_test_cookie_not_restored_as_valid(self):
        self.assertMatch(fixture(expires=1850000000),False)

    def test_session_cookie_with_negative_expiry_allowed(self):
        self.assertMatch(fixture(expires=-1))

    def test_future_expiry_allowed(self):
        self.assertMatch(fixture(expires=EXPIRES))

    def test_url_encoded_cookie_reported_separately(self):
        d=self.assertMatch(fixture("test%2Bmarker","test+marker"),False)
        self.assertTrue(d["resolved"]["url_decoded_pair_matches"])

    def test_distinct_cookie_name_with_same_value_is_ignored(self):
        d=self.assertMatch(fixture(name="unrelated_but_matches_storage"),False)
        self.assertFalse(d["resolved"]["exact_pair_matches"])

    def test_distinct_storage_key_with_same_value_is_ignored(self):
        d=self.assertMatch(fixture(key="unrelated_but_matches_cookie"),False)
        self.assertFalse(d["resolved"]["exact_pair_matches"])

    def test_other_cookie_matching_other_storage_cannot_mask_exact_mismatch(self):
        state=fixture("stale","fresh")
        state["cookies"].append({"name":"other","domain":"ai-browser-vault.floot.app",
                                 "path":"/","value":"matching_unrelated"})
        state["origins"][0]["localStorage"].append(
            {"name":"other","value":"matching_unrelated"})
        d=self.assertMatch(state,False)
        self.assertEqual(d["resolved"]["cookie_with_exact_name_count"],1)
        self.assertEqual(d["resolved"]["storage_exact_key_count"],1)

    def test_duplicate_exact_cookies_fail_closed(self):
        state=fixture()
        state["cookies"].append(copy.deepcopy(state["cookies"][0]))
        d=self.assertMatch(state,False)
        self.assertTrue(d["resolved"]["duplicates_present"])

    def test_duplicate_exact_storage_keys_fail_closed(self):
        state=fixture()
        state["origins"][0]["localStorage"].append(
            {"name":"aibrowser_public_test_marker","value":"test-only-matching"})
        d=self.assertMatch(state,False)
        self.assertTrue(d["resolved"]["duplicates_present"])

    def test_native_cookie_matches_portable_storage(self):
        native=fixture("new","old")
        backup=fixture("old","new")
        result=inspect(native,backup,native,now_seconds=1900000000)
        self.assertTrue(result["native_cookie_matches_portable_storage"])
        self.assertTrue(result["portable_cookie_matches_native_storage"])
        self.assertFalse(result["native"]["exact_pair_matches"])

    def test_native_cookie_equals_portable_cookie_even_if_storage_not(self):
        native=fixture("same-cookie","old")
        backup=fixture("same-cookie","new")
        r=inspect(native,backup,native,now_seconds=1900000000)
        self.assertTrue(r["cookie_same_between_native_and_portable"])
        self.assertFalse(r["storage_same_between_native_and_portable"])

    def test_returns_boolean_and_count_only_not_secrets(self):
        unique="TEST_SECRET_VALUE_DO_NOT_ECHO_a9s8d7"
        s=fixture(unique,unique)
        text=json.dumps(inspect(s,s,s,now_seconds=1900000000))
        for private in (unique,"aibrowser_test_cookie","aibrowser_public_test_marker",
                        "ai-browser-vault.floot.app", "2200000000"):
            self.assertNotIn(private,text)

    def test_does_not_mutate_profile_snapshots(self):
        s=fixture("native","portable")
        original=copy.deepcopy(s)
        inspect(s,s,s,now_seconds=1900000000)
        self.assertEqual(s,original)

    def test_bad_state_shapes_do_not_crash_or_confirm(self):
        weird=[None,{},{"cookies":{},"origins":"a"},[],
               {"cookies":[None,{}],"origins":[None,{"localStorage":{}}]}]
        for state in weird:
            with self.subTest(state=str(type(state))):
                out=inspect(state,state,state,now_seconds=1900000000)
                self.assertFalse(out["resolved"]["exact_pair_matches"])

    def test_invalid_nan_clock_rejected(self):
        for bad in (float("nan"),float("inf"),float("-inf")):
            with self.subTest(value=bad),self.assertRaises(ValueError):
                inspect(None,None,None,now_seconds=bad)

    def test_unrelated_profile_cookies_do_not_influence_result(self):
        s=fixture()
        s["cookies"].append({"name":"session_key","domain":"facebook.com",
                             "path":"/","value":"private_session_token"})
        out=inspect(s,s,s,now_seconds=1900000000)
        self.assertEqual(out["resolved"]["cookie_readable_count"],1)
        self.assertNotIn("facebook",json.dumps(out))

    def test_diagnostic_never_transmitted_to_meta_profile_binding(self):
        r,c=remote(current=fixture("old","new"))
        binding=r.engine._native_bindings["r"]
        binding["profile"]="Meta - Maciej - Monitoring"
        self.assertNotIn("synthetic_fixture_evidence",binding)

class ScopedIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_only_synthetic_profile_reports_exact_marker(self):
        r,c=remote(current=fixture("old","new"))
        binding=r.engine._native_bindings["r"]
        binding["profile"]="SteelSelfTest"
        await ns["native_context"](r,storage_state=fixture("new","new"))
        evidence=binding["synthetic_fixture_evidence"]["exact_marker"]
        self.assertFalse(evidence["native"]["exact_pair_matches"])
        self.assertTrue(evidence["portable"]["exact_pair_matches"])

    async def test_google_profile_never_reports_exact_marker(self):
        r,c=remote(current=fixture("old","new"))
        r.engine._native_bindings["r"]["profile"]="Google - Architekt"
        await ns["native_context"](r,storage_state=fixture("new","new"))
        self.assertNotIn("synthetic_fixture_evidence",r.engine._native_bindings["r"])

    async def test_meta_profile_never_reports_exact_marker(self):
        r,c=remote(current=fixture("old","new"))
        r.engine._native_bindings["r"]["profile"]="Meta - Maciej - Monitoring"
        await ns["native_context"](r,storage_state=fixture("new","new"))
        self.assertNotIn("synthetic_fixture_evidence",r.engine._native_bindings["r"])

if __name__=="__main__":
    unittest.main(verbosity=2)
