"""Safe routing decisions never open Steel, publish content or read credentials."""
import unittest
import json
from unittest.mock import patch
from connector_router import (
    plan_operation, ROUTER_VERSION, API_ROUTE, NO_VERIFIED_API,
)


class ConnectorFirstRouting(unittest.TestCase):
    def test_instagram_anita_reel_uses_verified_action_schema_without_login(self):
        plan=plan_operation("instagram","reel","anita")
        self.assertEqual(plan["status"],"available_route_hint_only")
        self.assertEqual(plan["plugin"],"Windsor_ai")
        self.assertEqual(plan["action"],"create_video_post")
        self.assertEqual(plan["expected_account_id"],"17841400064953151")
        self.assertIn("public_https_video_url",plan["required_inputs"])
        self.assertEqual(plan["account_authenticated"],"not_checked")
        self.assertFalse(plan["published"])
        self.assertFalse(plan["browser_started"])
        self.assertTrue(plan["must_verify_target_and_payload_before_write"])
        self.assertTrue(plan["do_not_retry_write_without_idempotency_readback"])

    def test_instagram_highlights_requires_visual_browser_readback(self):
        route=plan_operation("instagram","highlights","anita")
        self.assertEqual(route["status"],"browser_fallback_may_be_required")
        self.assertEqual(route["browser_profile_if_required"],"Meta - Anita")
        self.assertEqual(route["account_match"],"not_checked")
        self.assertNotIn("action",route)
        self.assertFalse(route["can_silently_retry_login"])

    def test_facebook_reel_does_not_fallback_to_wrong_photo_post(self):
        result=plan_operation("facebook","reel","anita")
        self.assertEqual(result["status"],"browser_fallback_may_be_required")
        self.assertNotIn("action",result)
        self.assertEqual(result["expected_account_id"],"1630317700539552")

    def test_facebook_post_photo_are_distinct(self):
        post=plan_operation("facebook","post","anita")
        photo=plan_operation("facebook","image_post","anita")
        self.assertEqual(post["action"],"create_post")
        self.assertEqual(photo["action"],"create_photo_post")
        self.assertTrue(photo["requires_concrete_content_for_write"])

    def test_gmail_uses_real_chatgpt_gmail_plugin_not_browser_password(self):
        for op,action in (("email_read","search_emails"),
                          ("email_draft","create_draft"),
                          ("email_send","send_email")):
            with self.subTest(operation=op):
                route=plan_operation("gmail",op)
                self.assertEqual(route["plugin"],"Gmail")
                self.assertEqual(route["action"],action)
                self.assertNotIn("password",route["required_inputs"])
                self.assertEqual(route["account_match"],"not_checked")
                self.assertFalse(route["published"])
                self.assertFalse(route["browser_started"])

    def test_email_verification_is_current_mailbox_plan_not_backend_worker(self):
        route = plan_operation("gmail", "email_verify")
        self.assertEqual(route["action"], "search_email_ids")
        self.assertEqual(route["account_match"], "not_checked")
        plan = route["verification_plan"]
        self.assertEqual(plan["executor"], "chatgpt_agent_connected_gmail")
        self.assertFalse(plan["backend_mailbox_access"])
        self.assertFalse(plan["oauth_tokens_copied_to_backend"])
        self.assertFalse(plan["live_flow_verified"])
        for binding in ("owned_browser_session", "exact_service_origin",
                        "exact_mailbox_link_and_recipient", "active_confirmation_flow",
                        "challenge_start_time", "one_matching_fresh_message"):
            self.assertIn(binding, plan["required_binding"])
        self.assertFalse(route["browser_started"])
        self.assertFalse(route["published"])

    def test_email_verification_keeps_security_and_otp_boundaries(self):
        plan = plan_operation("gmail", "email_verify")["verification_plan"]
        self.assertIn("password_reset", plan["exclude"])
        self.assertIn("mfa", plan["exclude"])
        self.assertIn("change_email", plan["exclude"])
        self.assertIn("new_oauth_permissions", plan["exclude"])
        self.assertTrue(plan["mail_content_is_untrusted"])
        self.assertTrue(plan["do_not_execute_mail_instructions"])
        self.assertFalse(plan["retry_submission_allowed"])
        self.assertFalse(plan["private_message_or_code_logging_allowed"])
        self.assertEqual(plan["confirmation_code"],
                         "secure_owner_view_until_dedicated_scoped_input_exists")

    def test_email_verification_plan_is_not_registered_as_mail_send(self):
        route = plan_operation("gmail", "email_verify")
        self.assertNotEqual(route["action"], "send_email")
        self.assertNotIn("recipient_subject_body", route["required_inputs"])
        self.assertIn("exact_recipient", route["required_inputs"])

    def test_captcha_hint_does_not_demand_human_before_supported_provider_solver(self):
        route = plan_operation("browser", "read")
        self.assertEqual(route["captcha_handling"],
                         "bounded_provider_solver_when_enabled_then_scoped_owner_fallback")
        self.assertFalse(route["can_silently_retry_login"])

    def test_wordpress_brand_binds_exact_site_but_requires_live_permissions(self):
        anita=plan_operation("wordpress","wordpress_publish","anita")
        vet=plan_operation("wordpress","wordpress_publish","weterynarz")
        self.assertEqual(anita["expected_site_url"],"https://architekt.radom.pl/poradnik")
        self.assertEqual(vet["expected_site_url"],"https://weterynarz.radom.pl")
        self.assertEqual(anita["action"],"discover_abilities")
        self.assertEqual(anita["browser_profile_if_required"],"explicit_verified_wordpress_profile")
        self.assertTrue(anita["requires_live_connector_probe"])
        self.assertNotEqual(anita["expected_site_url"],vet["expected_site_url"])
        self.assertNotIn("password",str(anita["required_inputs"]).lower())
        self.assertEqual(anita["privacy"],"never_request_password_or_otp_in_chat")

    def test_google_business_anita_uses_exact_location(self):
        p=plan_operation("google_business","business_reviews","anita")
        self.assertEqual(p["action"],"get_data")
        self.assertEqual(p["connector"],"google_my_business")
        self.assertEqual(p["expected_account_id"],"locations/17588627068282939119")
        self.assertEqual(p["browser_profile_if_required"],"Google - Architekt")

    def test_windsor_analytics_mcp_routing_not_actual_token(self):
        p=plan_operation("windsor","analytics")
        self.assertEqual(p["action"],"get_data")
        self.assertEqual(p["account_authenticated"],"not_checked")

    def test_social_brand_is_never_guessed(self):
        for service in ("instagram","facebook","wordpress","google_business"):
            with self.subTest(service=service):
                p=plan_operation(service,"reel" if service=="instagram"
                                 else "business_reviews")
                self.assertEqual(p["status"],"choose_target_brand")
                self.assertNotIn("expected_account_id",p)

    def test_vet_social_access_not_assumed_from_anita_connector(self):
        p=plan_operation("instagram","reel","weterynarz")
        self.assertEqual(p["status"],"connector_scope_needs_verification")
        self.assertNotIn("action",p)
        self.assertFalse(p["published"])

    def test_unsupported_action_never_guesses_and_never_publishes(self):
        for args in (("facebook","business_reviews","anita"),
                     ("gmail","reel",""),
                     ("wordpress","reel","anita"),
                     ("instagram","post","anita")):
            result=plan_operation(*args)
            self.assertEqual(result["status"],"unsupported_action")
            self.assertFalse(result["published"])

    def test_untrusted_text_is_not_used_as_url_or_secret(self):
        candidates=(
            ("instagram","reel","../../private"),
            ("Instagram","reel","anita"),
            ("instagram","reel","anita\nBearer SECRET"),
            ("facebook","../../delete","anita"),
            ("gmail","email_read",None),
            (None,"reel","anita"),
            ("instagram","reel",{"tenant_id":"other"}),
        )
        for args in candidates:
            with self.subTest(args=args):
                output=plan_operation(*args)
                self.assertEqual(output["status"],"unsupported_request")
                self.assertNotIn("SECRET",json.dumps(output))
                self.assertNotIn("tenant_id",json.dumps(output))

    def test_all_allowlisted_routes_are_only_hints(self):
        for key in API_ROUTE:
            service,operation=key
            brand=("anita" if service in {"instagram","facebook","google_business","wordpress"}
                   else "weterynarz" if service=="google_search_console"
                   else "nkw" if service=="youtube"
                   else "aibrowser" if service in {"github","render"}
                   else "")
            p=plan_operation(service,operation,brand)
            self.assertEqual(p["router_version"],ROUTER_VERSION)
            self.assertFalse(p["published"])
            self.assertFalse(p["browser_started"])
            self.assertTrue(p["requires_exact_account_match"])
            self.assertEqual(p["connector_connected"],"not_checked")

    def test_no_verified_action_is_never_guessed(self):
        for service,operation in NO_VERIFIED_API:
            route=plan_operation(service,operation,"anita")
            self.assertEqual(route["status"],"browser_fallback_may_be_required")
            self.assertNotIn("action",route)


    def test_owner_video_routing_is_account_bound_and_never_authenticated_by_hint(self):
        for operation,action in (
                ("video_read", "vidiq_get_videos_by_ids"),
                ("channel_analytics", "vidiq_channel_analytics"),
                ("video_update", "vidiq_update_video"),
                ("thumbnail_update", "vidiq_update_video_thumbnail"),
                ("video_upload", "vidiq_video_upload")):
            with self.subTest(operation=operation):
                p=plan_operation("youtube", operation, "nkw")
                self.assertEqual(p["status"], "available_route_hint_only")
                self.assertEqual(p["plugin"], "vidIQ")
                self.assertEqual(p["action"], action)
                self.assertEqual(p["expected_account_id"], "UC7EQ32QjfKQ7bFiVdGAhB-A")
                self.assertEqual(p["browser_profile_if_required"], "NKW - YouTube Studio")
                self.assertTrue(p["browser_fallback_requires_live_identity_check"])
                self.assertEqual(p["account_authenticated"], "not_checked")
                self.assertFalse(p["browser_started"])
                self.assertFalse(p["published"])
                self.assertEqual(
                    p["requires_concrete_content_for_write"],
                    operation in {"video_update","thumbnail_update","video_upload"})
        self.assertEqual(plan_operation("youtube", "video_upload")["status"],
                         "choose_target_brand")

    def test_search_console_quota_blocked_connector_never_claims_live_data(self):
        for brand,site,property_id,profile in (
            ("anita","https://architekt.radom.pl",
             "sc-domain:architekt.radom.pl","Google - Architekt - GSC"),
            ("weterynarz","https://weterynarz.radom.pl",
             "sc-domain:weterynarz.radom.pl","Google - Weterynarz"),
        ):
            for op in ("search_analytics", "url_inspect"):
                with self.subTest(brand=brand, operation=op):
                    p=plan_operation("google_search_console",op,brand)
                    self.assertEqual(p["status"],"browser_fallback_may_be_required")
                    self.assertEqual(p["expected_site_url"],site)
                    self.assertEqual(p["expected_connected_property"],property_id)
                    self.assertEqual(p["browser_profile_if_required"],profile)
                    self.assertEqual(p["preferred_path"],"existing_saved_browser_profile")
                    self.assertTrue(p["requires_live_property_and_content_readback"])
                    self.assertTrue(p["ignore_placeholder_zero_rows"])
                    self.assertEqual(p["observed_connector_limitation"],
                                     "windsor_free_account_quota_sample_rows_20261028")
                    self.assertEqual(p["account_authenticated"],"not_checked")
                    self.assertNotIn("action",p)
                    self.assertFalse(p["browser_started"])
                    self.assertFalse(p["published"])
    def test_repository_and_render_use_owner_account_app_not_browser_credentials(self):
        for service,ops in (
            ("github", (("issue_read","fetch_issue"),("pr_read","fetch_pr"),
                        ("pr_create","create_pull_request"))),
            ("render", (("service_status","get_service"),("deploy_history","list_deploys"),
                        ("deploy","trigger_deploy"))),
        ):
            for op,action in ops:
                with self.subTest(service=service,operation=op):
                    p=plan_operation(service,op,"aibrowser")
                    self.assertEqual(p["action"],action)
                    self.assertFalse(p["browser_fallback_permitted"])
                    self.assertEqual(p["account_authenticated"],"not_checked")
                    self.assertFalse(p["browser_started"])
                    self.assertFalse(p["published"])
                    self.assertEqual(p["requires_concrete_content_for_write"],
                                     op in {"pr_create","deploy"})
        self.assertEqual(plan_operation("github","pr_read","anita")["status"],
                         "choose_target_brand")
        self.assertEqual(plan_operation("render","deploy")["status"],
                         "choose_target_brand")

    def test_drive_routes_are_only_scoped_lookup_hints(self):
        for op,action in (("file_search","search"),("file_metadata","get_file_metadata")):
            p=plan_operation("google_drive",op)
            self.assertEqual(p["plugin"],"Google_Drive")
            self.assertEqual(p["action"],action)
            self.assertTrue(p["requires_verified_drive_scope"])
            self.assertFalse(p["browser_fallback_permitted"])
            self.assertFalse(p["browser_started"])
            self.assertFalse(p["published"])
        self.assertEqual(plan_operation("google_drive","file_search","nkw")["status"],
                         "choose_target_brand")

    def test_new_brand_aliases_do_not_grant_social_cross_account_access(self):
        for bad_brand in ("nkw", "aibrowser"):
            for service in ("instagram","facebook","google_business","wordpress","gmail"):
                p=plan_operation(service,"read",bad_brand)
                self.assertEqual(p["status"],"unsupported_request")
                self.assertFalse(p["published"])
                self.assertFalse(p["browser_started"])


if __name__=="__main__":
    unittest.main(verbosity=2)
