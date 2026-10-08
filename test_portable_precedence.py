"""Offline opt-in priority tests using only synthetic fixture state.

No real browser profiles, tokens, cookies, or accounts are accessed.
"""
import copy
import os
import re
import unittest
from unittest.mock import patch

from test_profile_recovery_051 import ns, state, remote, Failure

# The historical regression harness compiles selected functions only.
ns["PROFILE_RE"] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,63}$")

class PortableRecoveryCoherence(unittest.IsolatedAsyncioTestCase):
    async def test_backup_priority_keeps_cookie_and_local_storage_in_sync(self):
        latest=state("same-new-test-marker")
        native=state("old-marker")
        # Known synthetic failure: cookie stale but localStorage current.
        native["origins"]=copy.deepcopy(latest["origins"])
        r,c=remote(current=native)
        binding=r.engine._native_bindings["r"]
        binding["profile"]="SteelSelfTest"
        with patch.dict(os.environ, {"AI_BROWSER_PORTABLE_PRIORITY_PROFILES":"SteelSelfTest"}):
            await ns["native_context"](r,storage_state=latest)
        self.assertEqual(c.current,latest)
        self.assertTrue(binding["portable_priority_used"])
        self.assertTrue(binding["backup_recovery_applied"])

    async def test_meta_profile_preserves_native_cookie_when_only_fixture_opted_in(self):
        latest=state("portable-old")
        native=state("native-new")
        r,c=remote(current=native)
        binding=r.engine._native_bindings["r"]
        binding["profile"]="Meta - Maciej - Monitoring"
        with patch.dict(os.environ, {"AI_BROWSER_PORTABLE_PRIORITY_PROFILES":"SteelSelfTest"}):
            await ns["native_context"](r,storage_state=latest)
        self.assertEqual(c.current,native)
        self.assertFalse(binding["portable_priority_used"])

    async def test_policy_disabled_preserves_native_by_default(self):
        latest=state("portable-old")
        native=state("native-new")
        r,c=remote(current=native)
        r.engine._native_bindings["r"]["profile"]="SteelSelfTest"
        with patch.dict(os.environ, {"AI_BROWSER_PORTABLE_PRIORITY_PROFILES":""}):
            await ns["native_context"](r,storage_state=latest)
        self.assertEqual(c.current,native)

    async def test_wrong_case_does_not_enable_replacement(self):
        latest=state("portable-old")
        native=state("native-new")
        r,c=remote(current=native)
        r.engine._native_bindings["r"]["profile"]="SteelSelfTest"
        with patch.dict(os.environ, {"AI_BROWSER_PORTABLE_PRIORITY_PROFILES":"steelselftest"}):
            await ns["native_context"](r,storage_state=latest)
        self.assertEqual(c.current,native)

    async def test_invalid_whitelist_is_rejected_before_any_mutation(self):
        r,c=remote(current=state("native"))
        r.engine._native_bindings["r"]["profile"]="SteelSelfTest"
        with patch.dict(os.environ, {"AI_BROWSER_PORTABLE_PRIORITY_PROFILES":"SteelSelfTest,../fake"}):
            with self.assertRaisesRegex(Failure,"PROFILE_RECOVERY_POLICY_INVALID"):
                await ns["native_context"](r,storage_state=state("new"))
        self.assertEqual(c.states,[])
        self.assertEqual(c.current,state("native"))

    async def test_original_backup_and_native_objects_unchanged(self):
        native=state("old")
        backup=state("new")
        before=(copy.deepcopy(native),copy.deepcopy(backup))
        r,c=remote(current=native)
        r.engine._native_bindings["r"]["profile"]="SteelSelfTest"
        with patch.dict(os.environ, {"AI_BROWSER_PORTABLE_PRIORITY_PROFILES":"SteelSelfTest"}):
            await ns["native_context"](r,storage_state=backup)
        self.assertEqual(native,before[0])
        self.assertEqual(backup,before[1])

    async def test_no_portable_snapshot_never_resets_state(self):
        r,c=remote(current=state("existing"))
        r.engine._native_bindings["r"]["profile"]="SteelSelfTest"
        with patch.dict(os.environ, {"AI_BROWSER_PORTABLE_PRIORITY_PROFILES":"SteelSelfTest"}):
            await ns["native_context"](r)
        self.assertEqual(c.states,[])
        self.assertEqual(c.current,state("existing"))

if __name__ == "__main__":
    unittest.main(verbosity=2)
