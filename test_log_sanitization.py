"""Synthetic access-log safety regressions; contains no real bearer secrets."""
import logging
import unittest
import auth_status_v052 as app

MARKER="SYNTHETIC_VALUE_PRIVATE_DO_NOT_EXPOSE"

class LogRedactionTests(unittest.TestCase):
    def check(self, raw, expected):
        result=app.redact_log_text(raw)
        self.assertEqual(result,expected)
        self.assertNotIn(MARKER,result)

    def test_mcp_path_secret(self):
        self.check("POST /mcp/"+MARKER+" HTTP/1.1",
                   "POST /mcp/[redacted] HTTP/1.1")

    def test_mcp_path_with_subpath(self):
        self.check("GET /mcp/"+MARKER+"/stream HTTP/1.1",
                   "GET /mcp/[redacted]/stream HTTP/1.1")

    def test_mobile_setup_token(self):
        self.check("GET /setup/"+MARKER+"/view HTTP/1.1",
                   "GET /setup/[redacted]/view HTTP/1.1")

    def test_profile_setup_token(self):
        self.check("GET /profile-setup/"+MARKER+" HTTP/1.1",
                   "GET /profile-setup/[redacted] HTTP/1.1")

    def test_login_window_token(self):
        self.check("GET /login-window/"+MARKER+" HTTP/1.1",
                   "GET /login-window/[redacted] HTTP/1.1")

    def test_mobile_login_token(self):
        self.check("GET /mobile-login/"+MARKER+" HTTP/1.1",
                   "GET /mobile-login/[redacted] HTTP/1.1")

    def test_oauth_state_query(self):
        self.check("https://fixture.test/callback?state="+MARKER,
                   "https://fixture.test/callback?state=[redacted]")

    def test_oauth_code_query(self):
        self.check("/callback?code="+MARKER+"&x=5",
                   "/callback?code=[redacted]&x=5")

    def test_api_key_query(self):
        self.check("/page?apiKey="+MARKER+"&test=true",
                   "/page?apiKey=[redacted]&test=true")

    def test_session_id_query(self):
        self.check("/page?session_id="+MARKER,
                   "/page?session_id=[redacted]")

    def test_nonce_query(self):
        self.check("/page?nonce="+MARKER,
                   "/page?nonce=[redacted]")

    def test_bearer_header(self):
        self.check("Authorization: Bearer "+MARKER,
                   "Authorization: Bearer [redacted]")

    def test_bearer_preserves_surrounding_text(self):
        self.check("err Bearer "+MARKER+" requested",
                   "err Bearer [redacted] requested")

    def test_case_insensitive_path(self):
        self.check("POST /MCP/"+MARKER+" HTTP/1.1",
                   "POST /MCP/[redacted] HTTP/1.1")

    def test_benign_url_unchanged(self):
        text="GET /health/context HTTP/1.1"
        self.assertEqual(app.redact_log_text(text),text)

    def test_benign_static_asset_unchanged(self):
        text="GET /static/main.css HTTP/1.1"
        self.assertEqual(app.redact_log_text(text),text)

    def test_short_numeric_setup_segment_not_hidden(self):
        text="GET /setup/123 HTTP/1.1"
        self.assertEqual(app.redact_log_text(text),text)

    def test_mcp_query_and_path_both_masked(self):
        raw="/mcp/"+MARKER+"?state="+MARKER
        result=app.redact_log_text(raw)
        self.assertNotIn(MARKER,result)
        self.assertIn("?state=[redacted]",result)

    def test_log_filter_preserves_uvicorn_access_tuple_contract(self):
        args=("127.0.0.1","GET","/setup/"+MARKER+"/view","1.1",200)
        rec=logging.LogRecord("uvicorn.access",logging.INFO,"",1,
                              '%s %s %s %s %s',args,None)
        self.assertTrue(app.AccessSecretFilter().filter(rec))
        self.assertEqual(len(rec.args),5)
        self.assertEqual(rec.args[4],200)
        self.assertNotIn(MARKER,rec.getMessage())

    def test_log_filter_handles_httpx_dict(self):
        rec=logging.LogRecord("httpx",logging.INFO,"",1,
                              "call %(url)s",{"url":"https://fixture.test/?state="+MARKER},None)
        app.AccessSecretFilter().filter(rec)
        self.assertNotIn(MARKER,rec.getMessage())

    def test_false_non_string_unchanged(self):
        self.assertEqual(app.redact_log_text(None),None)

    def test_idempotent(self):
        text="GET /setup/"+MARKER+"/view?code="+MARKER
        once=app.redact_log_text(text)
        twice=app.redact_log_text(once)
        self.assertEqual(once,twice)

if __name__=="__main__":
    unittest.main(verbosity=2)
