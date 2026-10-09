"""External unauthenticated security smoke tests for public AI Browser routes.

Only synthetic invalid inputs are sent. Never use user tokens, credentials,
profile dumps, or secret MCP endpoints in this test.
"""
from __future__ import annotations
import json
import os
import re
import sys
import unittest
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

VAULT = "https://ai-browser-vault.floot.app"
ENGINE = "https://ai-browser-cloud.onrender.com"
TIMEOUT = 20


def request(url: str, *, method="GET", body=None):
    data = None if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8")
    req = Request(url, data=data, method=method)
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "AI-Browser-Unauthorized-CI/1.0")
    try:
        with urlopen(req, timeout=TIMEOUT) as response:
            return response.status, response.read(2048)
    except HTTPError as e:
        return e.code, e.read(2048)


class PublicPerimeterTests(unittest.TestCase):
    def test_profile_vault_get_needs_auth(self):
        code, _ = request(VAULT + "/_api/profile-vault?profile=UnauthorizedSyntheticProbe")
        self.assertIn(code, {401, 403}, f"UNAUTHORIZED_VAULT_READ_STATUS={code}")

    def test_native_registry_get_needs_auth(self):
        code, _ = request(VAULT + "/_api/engine-profile?profile=UnauthorizedSyntheticProbe")
        self.assertIn(code, {401, 403}, f"UNAUTHORIZED_REGISTRY_READ_STATUS={code}")

    def test_profile_vault_post_rejects_before_validation(self):
        # Deliberately schema-invalid, never creates or changes a profile.
        code, _ = request(VAULT + "/_api/profile-vault", method="POST", body={})
        self.assertIn(code, {401, 403}, f"UNAUTHORIZED_VAULT_WRITE_STATUS={code}")

    def test_native_registry_post_rejects_before_validation(self):
        code, _ = request(VAULT + "/_api/engine-profile", method="POST", body={})
        self.assertIn(code, {401, 403}, f"UNAUTHORIZED_REGISTRY_WRITE_STATUS={code}")

    def test_health_reports_no_credentials(self):
        code, text = request(ENGINE + "/health/context")
        self.assertEqual(code, 200, "PUBLIC_HEALTH_NOT_AVAILABLE")
        data = json.loads(text)
        self.assertEqual(data.get("status"), "ok")
        self.assertEqual(data.get("runtime"), "steel")
        serialized = json.dumps(data).lower()
        for forbidden in ("secret", "bearer ", "private_key", "master_key", "access_token", "refresh_token", "cookie", "password_value", "profile_state"):
            self.assertNotIn(forbidden, serialized, "HEALTH_RESPONSE_MUST_NOT_REVEAL_SECRETS")
        self.assertIsInstance(data.get("credentials_configured"), bool)

    def test_liveness_has_no_public_profile_list(self):
        code, text = request(ENGINE + "/health/context")
        data = json.loads(text)
        self.assertNotIn("profiles", data)
        self.assertNotIn("profile_ids", data)
        self.assertNotIn("cookies", data)

    def test_bogus_mcp_session_path_does_not_expose_data(self):
        # A fake path contains no actual connector token.
        code, text = request(ENGINE + "/mcp/UNAUTHORIZED_SYNTHETIC_NON_SECRET")
        self.assertIn(code, {400, 401, 403, 404, 405})
        self.assertNotIn(b"AI_BROWSER_MASTER_KEY", text)
        self.assertNotIn(b"STEEL_API_KEY", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
