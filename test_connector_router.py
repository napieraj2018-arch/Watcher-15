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

    def test_wordpress_brand_binds_exact_site_but_requires_live_permissions(self):
        anita=plan_operation("wordpress","wordpress_publish","anita")
        vet=plan_operation("wordpress","wordpress_publish","weterynarz")
        self.assertEqual(anita["expected_site_url"],"https://architekt.radom.pl/poradnik")
        self.assertEqual(vet["expected_site_url"],"https://weterynarz.radom.pl")
        self.assertEqual(anita["action"],"discover_abilities")
        self.assertTrue(anita["requires_live_connector_probe"])
        self.assertNotEqual(anita["expected_site_url"],vet["expected_site_url"])
        self.assertNotIn("password",str(anita).lower())

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
            brand="anita" if service in {"instagram","facebook","google_business","wordpress"} else ""
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


if __name__=="__main__":
    unittest.main(verbosity=2)
