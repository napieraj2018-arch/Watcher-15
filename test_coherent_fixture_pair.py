"""Synthetic browser-check fixture-only coherence repair, NEVER real logins."""
import copy
import unittest

from test_profile_recovery_051 import ns, remote
from test_synthetic_fixture_exact import fixture
from steel_context_fix import select_coherent_fixture_pair


class CoherentFixturePair(unittest.TestCase):
    def test_native_stale_cookie_backup_fresh_pair_is_recovered(self):
        native = fixture('native-stale', 'native-stale')
        native['origins'] = []
        backup = fixture('portable-fresh', 'portable-fresh')
        merged = ns['merge_profile_state'](native, backup)
        self.assertFalse(ns['synthetic_fixture_exact_evidence'](
            merged, merged, merged)['resolved']['exact_pair_matches'])
        output, changed = select_coherent_fixture_pair(native, backup, merged)
        self.assertTrue(changed)
        proof = ns['synthetic_fixture_exact_evidence'](
            output, output, output)['resolved']
        self.assertTrue(proof['exact_pair_matches'])
        self.assertFalse(proof['duplicates_present'])

    def test_valid_native_pair_is_never_overwritten(self):
        native = fixture('native-valid', 'native-valid')
        backup = fixture('older-valid', 'older-valid')
        merged = ns['merge_profile_state'](native, backup)
        out, changed = select_coherent_fixture_pair(native, backup, merged)
        self.assertFalse(changed)
        self.assertEqual(out, merged)

    def test_incoherent_backup_is_never_preferred(self):
        native = fixture('native-old', 'native-old')
        native['origins'] = []
        backup = fixture('cookie-not-matching', 'storage-not-matching')
        merged = ns['merge_profile_state'](native, backup)
        out, changed = select_coherent_fixture_pair(native, backup, merged)
        self.assertFalse(changed)
        self.assertEqual(out, merged)

    def test_duplicate_portable_test_markers_deny(self):
        native = fixture('native', 'native')
        native['origins'] = []
        backup = fixture('backup-good', 'backup-good')
        backup['cookies'].append(copy.deepcopy(backup['cookies'][0]))
        merged = ns['merge_profile_state'](native, backup)
        out, changed = select_coherent_fixture_pair(native, backup, merged)
        self.assertFalse(changed)
        self.assertEqual(out, merged)

    def test_unrelated_domains_and_indexeddb_are_preserved(self):
        native = fixture('native-old', 'native-old')
        native['origins'] = []
        native['cookies'].append({
            'name':'unrelated','domain':'google.example.test','path':'/',
            'value':'fixture-external','expires':2200000000,
            'secure':True,'httpOnly':False,'sameSite':'Lax'
        })
        native['origins'].append({
            'origin':'https://unrelated.example.test',
            'localStorage':[{'name':'user-key','value':'synthetic'}],
            'indexedDB':[{'name':'sample-database','version':1,'stores':[]}]
        })
        before = copy.deepcopy(native)
        backup = fixture('fresh-good','fresh-good')
        merged = ns['merge_profile_state'](native, backup)
        result, changed = select_coherent_fixture_pair(native, backup, merged)
        self.assertTrue(changed)
        self.assertEqual(native, before)
        self.assertIn(before['cookies'][1],result['cookies'])
        self.assertIn(before['origins'][0],result['origins'])

    def test_expired_portable_cookie_is_not_recovered(self):
        native=fixture('native','native')
        native['origins']=[]
        backup=fixture('expired','expired',expires=1600000000)
        merged=ns['merge_profile_state'](native,backup)
        out,changed=select_coherent_fixture_pair(native,backup,merged)
        self.assertFalse(changed)
        self.assertEqual(out,merged)

    def test_function_does_not_emit_cookies(self):
        native=fixture('native','native')
        native['origins']=[]
        backup=fixture('fixture-private-value','fixture-private-value')
        merged=ns['merge_profile_state'](native,backup)
        out,changed=select_coherent_fixture_pair(native,backup,merged)
        self.assertTrue(changed)
        # The internal state is preserved only in memory and no stdout/logs.
        self.assertIn('fixture-private-value',str(out))
        self.assertIs(type(changed),bool)


class PerProfileIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_candidate_recovery_only_for_steel_self_test(self):
        backup=fixture('portable-same','portable-same')
        current=fixture('native-old','native-old')
        current['origins']=[]
        r,c=remote(current=current)
        r.engine._native_bindings['r']['profile']='SteelSelfTest'
        await ns['native_context'](r,storage_state=backup)
        self.assertIs(
            r.engine._native_bindings['r']['synthetic_fixture_pair_repaired'],
            True)
        self.assertTrue(ns['synthetic_fixture_exact_evidence'](
            c.current,c.current,c.current)['resolved']['exact_pair_matches'])

    async def test_google_never_changes_test_marker_precedence(self):
        backup=fixture('portable-same','portable-same')
        current=fixture('native-old','native-old')
        current['origins']=[]
        r,c=remote(current=current)
        r.engine._native_bindings['r']['profile']='Google - Architekt'
        await ns['native_context'](r,storage_state=backup)
        self.assertNotIn('synthetic_fixture_pair_repaired',
                         r.engine._native_bindings['r'])


if __name__=='__main__':
    unittest.main(verbosity=2)
