"""No provider calls or real profiles; exact disposable canary admission only."""
import ast
import copy
from pathlib import Path
import unittest

tree = ast.parse(Path(__file__).with_name('steel_context_fix.py').read_text())
tree.body = [n for n in tree.body if isinstance(n, ast.FunctionDef)
             and n.name == 'native_context_trial_payload']
class Failure(RuntimeError):
    pass
ns = {'copy': copy, 'ReliabilityError': Failure}
exec(compile(tree, '<trial-test>', 'exec'), ns)
policy = ns['native_context_trial_payload']

class Trial(unittest.TestCase):
    def setUp(self):
        self.payload = {'profileId': 'test-id', 'persistProfile': True,
                        'solveCaptcha': False, 'sessionId': 'test-session'}
        self.binding = {'hydrated': True, 'profile_id': 'test-id'}

    def test_exact_hydrated_canary_only(self):
        before = copy.deepcopy(self.payload)
        value = policy(self.payload, 'Acceptance-20261023-Rollback', self.binding)
        self.assertEqual(value, {**before, 'sessionContext': {}})
        self.assertEqual(self.payload, before)

    def test_customer_profiles_and_other_canaries_unchanged(self):
        for profile in ['WordPress - Napieraj i Synowie', 'Google - Weterynarz',
                        'Meta - Anita', 'SteelSelfTest', 'Acceptance-20261023-R158',
                        'Acceptance-20261023-Rollback-other']:
            self.assertEqual(policy(self.payload, profile, self.binding), self.payload)

    def test_new_or_unverified_canary_is_unchanged(self):
        for binding in [{}, {'hydrated': False, 'profile_id': 'test-id'},
                        {'hydrated': True}, {'hydrated': 1, 'profile_id': 'test-id'}]:
            self.assertEqual(policy(self.payload, 'Acceptance-20261023-Rollback', binding), self.payload)

    def test_explicit_context_is_never_silently_discarded(self):
        with self.assertRaisesRegex(Failure, 'NATIVE_CONTEXT_TRIAL_CONFLICT'):
            policy({**self.payload, 'sessionContext': {'cookies': []}},
                   'Acceptance-20261023-Rollback', self.binding)

if __name__ == '__main__':
    unittest.main()
