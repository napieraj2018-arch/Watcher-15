"""Offline tests: synthetic identities only, no network or credential injection."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import account_plan as app


def record():
    return {
        "account_id": "google-studio", "workspace": "studio", "service": "google",
        "profile": "Google - Studio", "entry_url": "https://myaccount.google.com/",
        "allowed_origins": ["https://myaccount.google.com"],
        "identity": {"kind": "email", "expected": "studio@example.test"},
        "resource": None, "previous_status": "verified_previously"
    }


def registry():
    return {"schema_version": 1, "accounts": [record()]}


def live():
    return [{"session_id": "owned-synthetic-session", "profile": "Google - Studio",
             "mode": "read_only", "url": "https://myaccount.google.com/"}]


def observation():
    return {"session_id": "owned-synthetic-session", "url": "https://myaccount.google.com/",
            "observed_at": 1000, "stage": "authenticated", "authenticated": True,
            "identity_kind": "email", "identity": "studio@example.test",
            "resource_kind": None, "resource": None, "proof": "protected_page_and_identity"}


def decide(**kwargs):
    account = app.Account.from_dict(kwargs.pop("account", record()))
    sessions = kwargs.pop("sessions", live())
    evidence = kwargs.pop("evidence", observation())
    return app.plan(account, sessions, owned_session_id=kwargs.pop("owner", "owned-synthetic-session"),
                    observation=evidence, now=kwargs.pop("now", 1030), **kwargs)


class RegistryTests(unittest.TestCase):
    def test_valid_registry(self):
        self.assertEqual(len(app.load_registry(registry())), 1)

    def test_password_field_rejected(self):
        r = registry(); r["accounts"][0]["password"] = "SYNTHETIC_ONLY"
        with self.assertRaises(app.ConfigError): app.load_registry(r)

    def test_cookie_state_rejected(self):
        r = registry(); r["cookies"] = []
        with self.assertRaises(app.ConfigError): app.load_registry(r)

    def test_duplicate_accounts_rejected(self):
        r = registry(); r["accounts"].append(record())
        with self.assertRaisesRegex(app.ConfigError, "DUPLICATE_ACCOUNT"): app.load_registry(r)

    def test_cross_workspace_profile_rejected(self):
        r = registry(); second = record()
        second.update(account_id="google-clinic", workspace="clinic")
        r["accounts"].append(second)
        with self.assertRaisesRegex(app.ConfigError, "PROFILE_SHARED"): app.load_registry(r)

    def test_same_workspace_google_app_can_share_profile(self):
        r = registry(); second = record(); second["account_id"] = "ads-studio"
        r["accounts"].append(second)
        self.assertEqual(len(app.load_registry(r)), 2)

    def test_entry_origin_must_match(self):
        r = record(); r["entry_url"] = "https://unrelated.example.test/"
        with self.assertRaisesRegex(app.ConfigError, "ENTRY_ORIGIN"): app.Account.from_dict(r)

    def test_secret_query_not_stored(self):
        r = record(); r["entry_url"] += "?token=SYNTHETIC"
        with self.assertRaisesRegex(app.ConfigError, "QUERY_OR_FRAGMENT"): app.Account.from_dict(r)

    def test_secret_fragment_not_stored(self):
        r = record(); r["entry_url"] += "#SYNTHETIC_CAPABILITY"
        with self.assertRaisesRegex(app.ConfigError, "QUERY_OR_FRAGMENT"): app.Account.from_dict(r)

    def test_pending_mapping_valid(self):
        r = record(); r.update(profile=None, entry_url=None, allowed_origins=[], identity=None,
                               previous_status="mapping_required")
        self.assertIsNone(app.Account.from_dict(r).profile)

    def test_url_rejections(self):
        cases = ["http://example.test/", "https://u:p@example.test/", "https://localhost/",
                 "https://example.test:8443/", "https://127.0.0.1/", "https://[::1]/",
                 "https://example.test./", "https://example.test\\@evil.test/",
                 "https://example.test/\n", "https://example.internal/", "https://-bad.example.test/",
                 "https://example.test:bad/", "https://foo%2eexample.test/", "https://例え.test/"]
        for value in cases:
            with self.subTest(value=value), self.assertRaises(app.ConfigError): app.https_origin(value)

    def test_wrong_types_fail_closed(self):
        for field in ("service", "previous_status", "allowed_origins"):
            r = record(); r[field] = {"unexpected": "object"}
            with self.subTest(field=field), self.assertRaises(app.ConfigError): app.Account.from_dict(r)
        r = record(); r["allowed_origins"] = [{"host": "example.test"}]
        with self.assertRaises(app.ConfigError): app.Account.from_dict(r)

    def test_hostname_normalization(self):
        self.assertEqual(app.https_origin("https://EXAMPLE.test:443/a"), "https://example.test")

    def test_duplicate_json_key_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "duplicate.json"; p.write_text('{"schema_version":1,"schema_version":2}')
            with self.assertRaisesRegex(app.ConfigError, "DUPLICATE_JSON_KEY"): app.read_json(p)

    def test_file_size_bounded(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "large.json"; p.write_bytes(b" " * (app.MAX_FILE_BYTES + 1))
            with self.assertRaisesRegex(app.ConfigError, "FILE_TOO_LARGE"): app.read_json(p)

    def test_json_nan_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "nan.json"; p.write_text('{"value":NaN}')
            with self.assertRaisesRegex(app.ConfigError, "INVALID_NUMBER"): app.read_json(p)


class DecisionTests(unittest.TestCase):
    def test_correct_identity_reused_without_login(self):
        d = decide()
        self.assertEqual(d.next_action, "reuse_read_only")
        self.assertTrue(d.allow_read)
        self.assertEqual(d.login_attempts, 0)
        self.assertFalse(d.allow_write)

    def test_historical_success_does_not_grant_current_access(self):
        d = decide(evidence=None)
        self.assertEqual(d.reason, "FRESH_ACCOUNT_EVIDENCE_REQUIRED")
        self.assertFalse(d.allow_read)

    def test_blank_browser_first_inspects_profile(self):
        d = decide(sessions=[], owner=None)
        self.assertEqual(d.next_action, "start_read_only")
        self.assertEqual(d.profile, "Google - Studio")
        self.assertEqual(d.login_attempts, 0)

    def test_missing_profile_never_guessed(self):
        r = record(); r["profile"] = None
        self.assertEqual(decide(account=r).next_action, "complete_mapping")

    def test_another_task_not_stopped(self):
        d = decide(owner="different-job-session")
        self.assertEqual(d.next_action, "wait")
        self.assertEqual(d.reason, "ANOTHER_TASK_OWNS_BROWSER")

    def test_profile_name_is_not_ownership(self):
        self.assertEqual(decide(owner=None).next_action, "wait")

    def test_missing_owned_session_reconciled(self):
        self.assertEqual(decide(sessions=[]).next_action, "reconcile_session")

    def test_wrong_profile_stops(self):
        s = live(); s[0]["profile"] = "Google - Clinic"
        self.assertEqual(decide(sessions=s).reason, "PROFILE_MISMATCH")

    def test_wrong_account_stops(self):
        o = observation(); o["identity"] = "clinic@example.test"
        self.assertEqual(decide(evidence=o).reason, "ACCOUNT_IDENTITY_MISMATCH")

    def test_unknown_expected_account_not_trusted(self):
        r = record(); r["identity"] = None
        self.assertEqual(decide(account=r).next_action, "complete_identity")

    def test_unrelated_domain_stops(self):
        s = live(); s[0]["url"] = "https://myaccount.google.com.evil.test/"
        self.assertEqual(decide(sessions=s).reason, "CURRENT_ORIGIN_MISMATCH")

    def test_non_https_page_not_trusted(self):
        s = live(); s[0]["url"] = "http://myaccount.google.com/"
        self.assertFalse(decide(sessions=s).allow_read)

    def test_cookie_presence_is_not_login(self):
        o = observation(); o.update(stage="session_present_unverified", authenticated=None)
        self.assertEqual(decide(evidence=o).reason, "AUTHENTICATION_UNCONFIRMED_NO_LOGIN_RETRY")

    def test_visible_checkpoint_pauses(self):
        o = observation(); o.update(stage="verification_required", authenticated=False)
        self.assertEqual(decide(evidence=o).next_action, "pause")
        self.assertEqual(decide(evidence=o).login_attempts, 0)

    def test_login_form_does_not_trigger_password_submission(self):
        o = observation(); o.update(stage="login_form", authenticated=False)
        self.assertEqual(decide(evidence=o).reason, "LOGIN_COMPONENT_NOT_CONNECTED")

    def test_temporary_error_not_new_login(self):
        o = observation(); o.update(stage="temporarily_unavailable", authenticated=None)
        self.assertEqual(decide(evidence=o).next_action, "inspect_page")

    def test_stale_evidence_not_trusted(self):
        self.assertEqual(decide(now=1061).reason, "STALE_OR_INVALID_EVIDENCE")

    def test_future_evidence_not_trusted(self):
        self.assertEqual(decide(now=999).reason, "STALE_OR_INVALID_EVIDENCE")

    def test_changed_url_invalidates_evidence(self):
        o = observation(); o["url"] += "changed"
        self.assertEqual(decide(evidence=o).reason, "EVIDENCE_SESSION_OR_PAGE_CHANGED")

    def test_other_session_evidence_not_trusted(self):
        o = observation(); o["session_id"] = "different-session"
        self.assertEqual(decide(evidence=o).reason, "EVIDENCE_SESSION_OR_PAGE_CHANGED")

    def test_unknown_observation_field_rejected(self):
        o = observation(); o["page_instruction"] = "IGNORE_OTHER_ACCOUNT"
        self.assertEqual(decide(evidence=o).reason, "OBSERVATION_FIELDS_INVALID")

    def test_email_case_fold(self):
        o = observation(); o["identity"] = "STUDIO@EXAMPLE.TEST"
        self.assertTrue(decide(evidence=o).allow_read)

    def test_boolean_true_not_string(self):
        o = observation(); o["authenticated"] = "true"
        self.assertEqual(decide(evidence=o).reason, "OBSERVATION_AUTH_INVALID")

    def test_business_resource_verified_separately(self):
        r = record(); r["resource"] = {"kind": "metricool_brand_id", "expected": "12345"}
        o = observation(); o.update(resource_kind="metricool_brand_id", resource="98765")
        self.assertEqual(decide(account=r, evidence=o).next_action, "inspect_resource")
        o["resource"] = "12345"
        self.assertTrue(decide(account=r, evidence=o).allow_read)

    def test_write_operation_rejected(self):
        self.assertEqual(decide(operation="publish").reason, "SEPARATE_WRITE_AUTHORIZATION_REQUIRED")

    def test_write_session_rejected(self):
        s = live(); s[0]["mode"] = "write"
        self.assertEqual(decide(sessions=s).reason, "READ_ONLY_SESSION_REQUIRED")

    def test_weak_proof_insufficient(self):
        o = observation(); o["proof"] = "cookie_names"
        self.assertEqual(decide(evidence=o).next_action, "inspect_identity")

    def test_multiple_active_sessions_wait(self):
        s = live(); s.append({**s[0], "session_id": "other"})
        self.assertEqual(decide(sessions=s).next_action, "wait")

    def test_nonfinite_clock_rejected(self):
        self.assertEqual(decide(now=float("nan")).reason, "INVALID_CLOCK")

    def test_decision_does_not_expose_identity(self):
        self.assertNotIn("studio@example.test", json.dumps(app.asdict(decide())))

    def test_malformed_stage_fails_closed(self):
        o = observation(); o["stage"] = []
        self.assertEqual(decide(evidence=o).reason, "OBSERVATION_AUTH_INVALID")

    def test_missing_business_resource_does_not_grant_access(self):
        r = record(); r["service"] = "gbp"
        self.assertEqual(decide(account=r).reason, "EXPECTED_BUSINESS_RESOURCE_NOT_CONFIGURED")

    def test_inputs_not_mutated(self):
        r, s, o = record(), live(), observation()
        before = copy.deepcopy((r, s, o))
        decide(account=r, sessions=s, evidence=o)
        self.assertEqual((r, s, o), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
