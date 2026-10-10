"""No provider calls: read aliases and failure hints must not force a login."""
import json
import unittest
from copy import deepcopy
from connector_router import plan_operation, plan_access_recovery


class ReadRoutes(unittest.TestCase):
    def test_generic_business_reads_use_existing_api(self):
        for service, connector in (("instagram", "instagram"),
                                   ("facebook", "facebook_organic"),
                                   ("google_business", "google_my_business")):
            with self.subTest(service=service):
                p = plan_operation(service, "read", "anita")
                self.assertEqual(p["action"], "get_data")
                self.assertEqual(p["connector"], connector)
                self.assertEqual(p["account_authenticated"], "not_checked")
                self.assertEqual(p["read_scope"], "business_account_supported_fields_only")
                self.assertFalse(p["published"])
                self.assertFalse(p["browser_started"])

    def test_gmail_generic_read_is_not_reauthentication(self):
        p = plan_operation("gmail", "read")
        self.assertEqual(p["action"], "search_emails")
        self.assertEqual(p["operation"], "email_read")
        self.assertEqual(p["requested_operation"], "read")
        self.assertEqual(p["account_authenticated"], "not_checked")

    def test_wordpress_generic_read_preserves_exact_brand(self):
        a = plan_operation("wordpress", "read", "anita")
        v = plan_operation("wordpress", "read", "weterynarz")
        self.assertEqual(a["action"], "site_info")
        self.assertEqual(a["operation"], "wordpress_read")
        self.assertNotEqual(a["expected_site_url"], v["expected_site_url"])
        self.assertFalse(a["requires_concrete_content_for_write"])

    def test_google_reviews_alias_reuses_existing_route(self):
        p = plan_operation("google_business", "reviews", "anita")
        old = plan_operation("google_business", "business_reviews", "anita")
        for key in ("action", "connector", "expected_account_id", "required_inputs"):
            self.assertEqual(p[key], old[key])

    def test_other_review_aliases_do_not_guess_api(self):
        for s in ("facebook", "instagram", "wordpress"):
            self.assertEqual(plan_operation(s, "reviews", "anita")["status"], "unsupported_action")

    def test_read_does_not_guess_missing_business_brand(self):
        for s in ("facebook", "instagram", "wordpress", "google_business"):
            p = plan_operation(s, "read")
            self.assertEqual(p["status"], "choose_target_brand")
            self.assertNotIn("action", p)

    def test_vet_social_auth_not_inherited_from_anita(self):
        for s in ("facebook", "instagram", "google_business"):
            p = plan_operation(s, "read", "weterynarz")
            self.assertEqual(p["status"], "connector_scope_needs_verification")
            self.assertNotIn("action", p)

    def test_browser_unknown_is_not_logged_out(self):
        p = plan_operation("browser", "read")
        self.assertEqual(p["status"], "browser_state_verification_required")
        self.assertEqual(p["account_authenticated"], "not_checked")
        self.assertFalse(p["can_silently_retry_login"])

    def test_highlights_still_not_claimed_as_business_metadata(self):
        p = plan_operation("instagram", "highlights", "anita")
        self.assertEqual(p["status"], "browser_fallback_may_be_required")
        self.assertNotIn("action", p)
        self.assertNotIn("read_scope", p)

    def test_specific_write_safety_not_weakened_by_generic_reads(self):
        p = plan_operation("instagram", "reel", "anita")
        self.assertEqual(p["action"], "create_video_post")
        self.assertTrue(p["must_verify_target_and_payload_before_write"])
        self.assertTrue(p["do_not_retry_write_without_idempotency_readback"])
        self.assertEqual(p["operation"], "reel")
        self.assertNotIn("read_scope", p)


class RecoveryHints(unittest.TestCase):
    def test_empty_is_not_authentication_failure(self):
        p = plan_access_recovery("empty_result")
        self.assertEqual(p["next_step"], "check_query_scope_and_data_freshness")
        self.assertFalse(p["reauthorization_may_be_needed"])
        self.assertEqual(p["authentication"], "unknown")

    def test_transport_and_permission_errors_are_not_logout(self):
        for kind in ("transport_error", "permission_denied", "rate_limited", "unknown_error"):
            p = plan_access_recovery(kind)
            self.assertEqual(p["authentication"], "unknown")
            self.assertFalse(p["reauthorization_may_be_needed"])
            self.assertFalse(p["retry_write_allowed"])

    def test_only_explicit_provider_auth_challenge_requests_reauthorization(self):
        p = plan_access_recovery("provider_reauthorization_required")
        self.assertTrue(p["reauthorization_may_be_needed"])
        self.assertEqual(p["next_step"], "confirm_provider_evidence_then_authorize_affected_connection")
        self.assertTrue(p["requires_trusted_provider_evidence"])
        self.assertFalse(p["login_attempted"])

    def test_browser_quarantine_does_not_disable_unrelated_connector_work(self):
        p = plan_access_recovery("browser_quarantined")
        self.assertEqual(p["next_step"], "independent_provider_reconciliation_no_browser_restart")
        self.assertTrue(p["independent_connector_tasks_may_continue"])
        self.assertFalse(p["clear_quarantine_allowed"])
        self.assertFalse(p["retry_write_allowed"])

    def test_uncertain_write_requires_receipt_not_resubmission(self):
        p = plan_access_recovery("write_outcome_unknown")
        self.assertEqual(p["next_step"], "verify_receipt_or_existing_object_before_any_retry")
        self.assertFalse(p["retry_write_allowed"])

    def test_human_verification_only_blocks_affected_step(self):
        p = plan_access_recovery("human_verification_required")
        self.assertEqual(p["next_step"], "pause_affected_step_for_human_verification")
        self.assertTrue(p["independent_connector_tasks_may_continue"])
        self.assertFalse(p["login_attempted"])

    def test_untrusted_input_never_returned(self):
        for value in (None, 1, {}, [], "private-access-token", "PERMISSION_DENIED"):
            p = plan_access_recovery(value)
            self.assertEqual(p["status"], "unsupported_observation")
            self.assertNotIn("private-access-token", json.dumps(p))

    def test_return_mutation_never_changes_future_plan(self):
        p = plan_access_recovery("empty_result")
        expected = deepcopy(p)
        p["next_step"] = "bad"
        self.assertEqual(plan_access_recovery("empty_result"), expected)

    def test_routing_includes_available_recovery_without_claiming_execution(self):
        p = plan_operation("gmail", "read")
        self.assertIn("browser_quarantined", p["access_recovery"])
        for hint in p["access_recovery"].values():
            self.assertFalse(hint["login_attempted"])
            self.assertFalse(hint["retry_write_allowed"])
            self.assertFalse(hint["clear_quarantine_allowed"])
            self.assertEqual(hint["status"], "advisory_only")


if __name__ == "__main__":
    unittest.main(verbosity=2)
