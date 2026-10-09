"""Deterministic diagnostics tests: fake cookie values, no accounts or network."""
import ast
import copy
import json
import pathlib
import unittest

from test_profile_recovery_051 import ns, remote, state

ROOT = pathlib.Path(__file__).with_name('steel_context_fix.py')
SOURCE = ROOT.read_text(encoding='utf-8')
tree = ast.parse(SOURCE)
tree.body = [node for node in tree.body if isinstance(node, ast.FunctionDef)
             and node.name == 'synthetic_fixture_evidence']
local = {}
exec(compile(tree, str(ROOT), 'exec'), local)
inspect = local['synthetic_fixture_evidence']
ns['synthetic_fixture_evidence'] = inspect


def fixture(cookie="sample-test-only", storage="sample-test-only"):
    return {
        "cookies": [{
            "name": "random-fixture-cookie", "domain": "ai-browser-vault.floot.app",
            "value": cookie, "path": "/"
        }],
        "origins": [{
            "origin": "https://ai-browser-vault.floot.app",
            "localStorage": [{"name": "random-fixture-key", "value": storage}]
        }]
    }


class FixtureStateChecks(unittest.TestCase):
    def test_same_marker_in_native_and_backup(self):
        a = fixture()
        result = inspect(a, a, a)
        self.assertTrue(result["native"]["identical_pair_present"])
        self.assertTrue(result["portable"]["identical_pair_present"])
        self.assertTrue(result["resolved"]["identical_pair_present"])

    def test_mismatch_in_native_but_coherent_portable(self):
        old, new = fixture("stale", "fresh"), fixture("fresh", "fresh")
        result = inspect(old, new, new)
        self.assertFalse(result["native"]["identical_pair_present"])
        self.assertTrue(result["portable"]["identical_pair_present"])
        self.assertTrue(result["resolved"]["identical_pair_present"])

    def test_inconsistent_backup_is_detected_not_automatically_repaired(self):
        a = fixture("test-x", "test-y")
        r = inspect(a, a, a)
        self.assertFalse(r["portable"]["identical_pair_present"])
        self.assertFalse(r["resolved"]["identical_pair_present"])

    def test_cookie_and_storage_in_different_origins_do_not_match(self):
        a = fixture("test", "test")
        a["origins"][0]["origin"] = "https://elsewhere.example.test"
        out = inspect(a, a, a)
        self.assertFalse(out["native"]["identical_pair_present"])
        self.assertEqual(out["native"]["test_local_storage_values"], 0)

    def test_cookie_and_storage_in_other_domain_are_excluded(self):
        a = fixture("test", "test")
        a["cookies"][0]["domain"] = "private.example.test"
        out = inspect(a, a, a)
        self.assertFalse(out["portable"]["identical_pair_present"])
        self.assertEqual(out["native"]["test_cookie_values"], 0)

    def test_url_encoded_cookie_detected_separately(self):
        a = fixture("a%2Bb", "a+b")
        out = inspect(a, a, a)
        self.assertFalse(out["resolved"]["identical_pair_present"])
        self.assertTrue(out["resolved"]["url_decoded_pair_present"])

    def test_cookie_with_parent_dot_domain_allowed(self):
        a = fixture()
        a["cookies"][0]["domain"] = ".ai-browser-vault.floot.app"
        self.assertTrue(inspect(a, a, a)["native"]["identical_pair_present"])

    def test_counts_are_bounded(self):
        a = fixture()
        a["cookies"] = a["cookies"] * 100
        a["origins"][0]["localStorage"] = a["origins"][0]["localStorage"] * 100
        result = inspect(a, a, a)
        self.assertEqual(result["native"]["test_cookie_values"], 30)
        self.assertEqual(result["native"]["test_local_storage_values"], 30)

    def test_cross_pairs_detect_mixed_sources(self):
        native = fixture("stale-cookie", "new-storage")
        portable = fixture("new-storage", "old-storage")
        result = inspect(native, portable, native)
        self.assertTrue(result["portable_cookie_vs_native_storage"])
        self.assertFalse(result["native_cookie_vs_portable_storage"])

    def test_missing_state_graceful(self):
        result = inspect(None, None, None)
        self.assertEqual(result["native"]["test_cookie_values"], 0)
        self.assertFalse(result["resolved"]["identical_pair_present"])

    def test_never_returns_values_domains_or_ids(self):
        secret = "synthetic-private-value-WOULD_BE_BAD_TO_LOG"
        a = fixture(secret, secret)
        a["cookies"][0]["name"] = "ANOTHER_PRIVATE_KEY"
        output = json.dumps(inspect(a, a, a))
        self.assertNotIn(secret, output)
        self.assertNotIn("ANOTHER_PRIVATE_KEY", output)
        self.assertNotIn("ai-browser-vault.floot.app", output)

    def test_never_mutates_input(self):
        a = fixture()
        before = copy.deepcopy(a)
        inspect(a, a, a)
        self.assertEqual(a, before)

    def test_multiple_values_one_coherent_pair(self):
        a = fixture("good", "good")
        a["cookies"].append({"domain":"ai-browser-vault.floot.app","name":"other","value":"BAD"})
        a["origins"][0]["localStorage"].append({"name":"another","value":"not-paired"})
        r=inspect(a,a,a)
        self.assertTrue(r["resolved"]["identical_pair_present"])
        self.assertEqual(r["resolved"]["test_cookie_values"],2)


class IntegrationChecks(unittest.IsolatedAsyncioTestCase):
    async def test_technical_profile_has_only_evidence(self):
        current = fixture("native-wrong", "native-right")
        backup = fixture("portable-right", "portable-right")
        r,c = remote(current=current)
        binding = r.engine._native_bindings['r']
        binding['profile'] = 'SteelSelfTest'
        await ns['native_context'](r, storage_state=backup)
        self.assertIn('synthetic_fixture_evidence', binding)
        info = binding['synthetic_fixture_evidence']
        self.assertFalse(info['native']['identical_pair_present'])
        self.assertTrue(info['portable']['identical_pair_present'])
        self.assertNotIn("portable-right", json.dumps(info))

    async def test_meta_profile_never_stores_diagnostic_evidence(self):
        r,c = remote(current=fixture("alpha", "beta"))
        binding = r.engine._native_bindings['r']
        binding['profile'] = 'Meta - Maciej - Monitoring'
        await ns['native_context'](r, storage_state=fixture("gamma", "gamma"))
        self.assertNotIn('synthetic_fixture_evidence', binding)

    async def test_google_profile_never_stores_diagnostic_evidence(self):
        r,c = remote(current=fixture("alpha", "beta"))
        binding = r.engine._native_bindings['r']
        binding['profile'] = 'Google - Weterynarz'
        await ns['native_context'](r, storage_state=fixture("gamma", "gamma"))
        self.assertNotIn('synthetic_fixture_evidence', binding)


if __name__ == '__main__':
    unittest.main(verbosity=2)
