"""Context diagnostics must remain private in production Steel runtime."""
import os
import unittest
from unittest.mock import patch

import steel_runtime as runtime
from steel_context_fix import context_health_payload


class FakeEngine:
    def __init__(self, quarantined=False):
        self._quarantined = quarantined


class ContextHealthPrivacy(unittest.TestCase):
    def setUp(self):
        self.admin = "synthetic-admin-token-not-real-999999999999"
        self.patch = patch.dict(os.environ, {
            "AI_BROWSER_ADMIN_TOKEN": self.admin,
            "AI_BROWSER_CREDENTIALS_JSON": "synthetic-config-present-never-real",
            "STEEL_API_KEY": "synthetic-provider-key",
        })
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def test_public_context_does_not_disclose_provider_metadata(self):
        payload = context_health_payload(runtime, FakeEngine())
        self.assertEqual(set(payload), {"status","runtime","version"})
        self.assertEqual(payload["status"], "ok")
        for item in ("credentials_configured","native_profiles","context_mode",
                     "controller_memory","local_chrome_processes"):
            self.assertNotIn(item, payload)

    def test_bad_bearers_never_unlock_context(self):
        for header in ("Bearer wrong","bearer "+self.admin,
                       "Bearer "+self.admin+"x","Bearer "+"x"*2000,
                       "Bearer ż"*70):
            with self.subTest(n=len(header)):
                self.assertEqual(set(context_health_payload(
                    runtime,FakeEngine(),header)),
                    {"status","runtime","version"})

    def test_owner_gets_safe_flags_without_credential_values(self):
        result = context_health_payload(runtime,FakeEngine(),
                                        "Bearer "+self.admin)
        self.assertTrue(result["credentials_configured"])
        self.assertTrue(result["native_profiles"])
        self.assertEqual(result["context_mode"],"provider_native")
        self.assertNotIn(self.admin,str(result))
        self.assertNotIn("synthetic-config-present-never-real",str(result))
        self.assertNotIn("synthetic-provider-key",str(result))

    def test_quarantined_state_degrades_public_liveness(self):
        public=context_health_payload(runtime,FakeEngine(quarantined=True))
        self.assertEqual(public["status"],"degraded")
        self.assertEqual(set(public), {"status","runtime","version"})

    def test_no_admin_env_denies_privileged_metadata(self):
        os.environ.pop("AI_BROWSER_ADMIN_TOKEN",None)
        self.assertEqual(set(context_health_payload(
            runtime,FakeEngine(),"Bearer "+self.admin)),
            {"status","runtime","version"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
