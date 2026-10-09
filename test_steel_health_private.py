"""Offline public Steel health privacy tests. No credentials or API calls."""
import os
import unittest
from unittest.mock import patch

from steel_runtime import admin_health_authorized, steel_health_payload


class StubEngine:
    authenticated = True

    def __init__(self, quarantined=False, remote_count=0):
        self._quarantined = quarantined
        self.remote = {str(i): object() for i in range(remote_count)}


class TestSteelHealthPrivacy(unittest.TestCase):
    def setUp(self):
        self.private = "synthetic-admin-token-not-a-real-secret-123456789"
        self.env = patch.dict(os.environ, {
            "AI_BROWSER_ADMIN_TOKEN": self.private,
            "STEEL_API_KEY": "synthetic-steel-key-never-send",
        })
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_public_health_does_not_enumerate_private_runtime(self):
        payload = steel_health_payload(StubEngine(remote_count=1))
        self.assertEqual(set(payload), {"status", "runtime", "version"})
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["runtime"], "steel")
        self.assertNotIn("active_remote_sessions", payload)
        self.assertNotIn("key_configured", payload)

    def test_wrong_and_malformed_tokens_do_not_open_diagnostics(self):
        for header in [
            "", "Bearer wrong", "bearer "+self.private,
            "Bearer "+self.private+"x",
            "Bearer "+"a"*600,
            "Bearer é"*48,
        ]:
            with self.subTest(header_size=len(header)):
                self.assertFalse(admin_health_authorized(header))
                self.assertEqual(
                    set(steel_health_payload(StubEngine(), header)),
                    {"status", "runtime", "version"},
                )

    def test_matching_admin_bearer_sees_flags_without_secrets(self):
        self.assertTrue(admin_health_authorized("Bearer "+self.private))
        payload = steel_health_payload(StubEngine(remote_count=1),
                                       "Bearer "+self.private)
        self.assertTrue(payload["key_configured"])
        self.assertTrue(payload["remote_connection_verified"])
        self.assertEqual(payload["active_remote_sessions"], 1)
        self.assertFalse(payload["requires_reconciliation"])
        text = repr(payload)
        self.assertNotIn(self.private, text)
        self.assertNotIn(os.environ["STEEL_API_KEY"], text)

    def test_quarantine_is_visible_as_public_degraded_without_session_metadata(self):
        public = steel_health_payload(StubEngine(quarantined=True,remote_count=1))
        self.assertEqual(public["status"], "degraded")
        self.assertNotIn("active_remote_sessions", public)
        self.assertNotIn("requires_reconciliation", public)
        privileged = steel_health_payload(StubEngine(quarantined=True),
                                          "Bearer "+self.private)
        self.assertTrue(privileged["requires_reconciliation"])

    def test_missing_admin_token_denies_privileged_route_even_with_bearer(self):
        os.environ.pop("AI_BROWSER_ADMIN_TOKEN", None)
        self.assertFalse(admin_health_authorized("Bearer "+self.private))
        result = steel_health_payload(StubEngine(), "Bearer "+self.private)
        self.assertEqual(set(result), {"status", "runtime", "version"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
