"""No provider calls or real profiles; exact disposable canary admission only."""
import ast
import copy
import re
from pathlib import Path
import unittest

tree = ast.parse(Path(__file__).with_name('steel_context_fix.py').read_text())
tree.body = [n for n in tree.body if isinstance(n, ast.FunctionDef)
             and n.name in {'native_context_trial_payload', 'portable_cookies_for_provider'}]
class Failure(RuntimeError):
    pass
ns = {'copy': copy, 'ReliabilityError': Failure,
      'PROFILE_RE': re.compile(r'^[A-Za-z0-9][A-Za-z0-9._ -]{0,63}$')}
exec(compile(tree, '<trial-test>', 'exec'), ns)
policy = ns['native_context_trial_payload']
cookies = ns['portable_cookies_for_provider']

class Trial(unittest.TestCase):
    def setUp(self):
        self.payload = {'profileId': 'test-id', 'persistProfile': True,
                        'solveCaptcha': False, 'sessionId': 'test-session'}
        self.binding = {'hydrated': True, 'profile_id': 'test-id'}
        self.state = {'cookies': [{'name': 'neutral', 'value': 'test-only',
                                  'domain': 'example.test', 'path': '/'}],
                      'origins': [{'origin': 'https://example.test',
                                   'localStorage': [{'name': 'counter', 'value': '1'}]}]}

    def test_exact_hydrated_canary_only(self):
        before = copy.deepcopy(self.payload)
        for profile in ('Acceptance-20261023-Rollback', 'Acceptance-20261023-R158'):
            with self.subTest(profile=profile):
                value = policy(self.payload, profile, self.binding, self.state)
                self.assertEqual(value, {**before, 'sessionContext': {'cookies': self.state['cookies']}})
        self.assertEqual(self.payload, before)

    def test_real_profiles_never_receive_experimental_context_override(self):
        for profile in ['WordPress - Napieraj i Synowie', 'Google - Weterynarz',
                        'Meta - Anita', 'Acceptance-20261023-R158-other',
                        'Acceptance-20261023-Rollback-other']:
            self.assertEqual(policy(self.payload, profile, self.binding), self.payload)

    def test_special_fixture_and_invalid_names_unchanged(self):
        for profile in ['SteelSelfTest', '../profile', '', None]:
            self.assertEqual(policy(self.payload, profile, self.binding), self.payload)

    def test_new_or_unverified_canary_is_unchanged(self):
        # R158 must not inherit the experimental provider override when
        # a native profile has not been independently verified as hydrated.
        for profile in ('Acceptance-20261023-Rollback', 'Acceptance-20261023-R158'):
            for binding in [{}, {'hydrated': False, 'profile_id': 'test-id'},
                            {'hydrated': True}, {'hydrated': 1, 'profile_id': 'test-id'}]:
                with self.subTest(profile=profile, binding=binding):
                    self.assertEqual(policy(self.payload, profile, binding), self.payload)

    def test_explicit_context_is_never_silently_discarded(self):
        for profile in ('Acceptance-20261023-Rollback', 'Acceptance-20261023-R158'):
            with self.subTest(profile=profile):
                with self.assertRaisesRegex(Failure, 'NATIVE_PROFILE_CONTEXT_CONFLICT'):
                    policy({**self.payload, 'sessionContext': {'cookies': []}},
                           profile, self.binding)

    def test_snapshot_required_before_canary_create(self):
        for profile in ('Acceptance-20261023-Rollback', 'Acceptance-20261023-R158'):
            with self.subTest(profile=profile):
                with self.assertRaisesRegex(Failure, 'PROFILE_COOKIE_SNAPSHOT_REQUIRED'):
                    policy(self.payload, profile, self.binding)

    def test_partitioned_cookie_preserves_cross_site_flag(self):
        for flag in [True, False]:
            state = copy.deepcopy(self.state)
            state['cookies'][0].update(partitionKey='https://top.test', _crHasCrossSiteAncestor=flag)
            out = cookies(state)
            self.assertEqual(out[0]['partitionKey'], {'topLevelSite': 'https://top.test', 'hasCrossSiteAncestor': flag})
            self.assertNotIn('_crHasCrossSiteAncestor', out[0])
            self.assertEqual(state['cookies'][0]['_crHasCrossSiteAncestor'], flag)

    def test_partitioned_cookie_uses_playwright_default(self):
        state = copy.deepcopy(self.state)
        state['cookies'][0]['partitionKey'] = 'https://top.test'
        self.assertTrue(cookies(state)[0]['partitionKey']['hasCrossSiteAncestor'])

    def test_unknown_cookie_fields_are_never_silently_discarded(self):
        state = copy.deepcopy(self.state)
        state['cookies'][0]['unsupported'] = 'test-only'
        with self.assertRaisesRegex(Failure, 'PROFILE_COOKIE_FORMAT_UNSUPPORTED'):
            cookies(state)

if __name__ == '__main__':
    unittest.main()
