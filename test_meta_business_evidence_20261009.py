"""Meta Business auth evidence: synthetic DOM fixtures, no real account changes."""
import unittest
import json
from test_auth_status_052 import app, session

CLINIC = ("Edytuj zdjęcie w tle\nPrzychodnia TESTOWA\n"
          "Edytuj stronę na Facebooku | Edytuj profil na Instagramie\n"
          "Obserwatorzy na Facebooku\n100\n"
          "Obserwujący na Instagramie\n50\n"
          "Utwórz post\nUtwórz reklamę\n")
ANITA = ("Anita TESTOWA\nEdytuj stronę na Facebooku\n"
         "Obserwatorzy na Facebooku\n980\nObserwujący na Instagramie\n487\n"
         "Utwórz post\n")
ENGLISH = ("Edit Facebook Page\nFacebook followers\n15\n"
           "Instagram followers\n6\nCreate post\n")
BUSINESS = "https://business.facebook.com/latest/home?asset_id=138554046242234"
ANITA_URL = "https://business.facebook.com/latest/home?asset_id=1630317700539552"
LOGIN = "https://business.facebook.com/business/loginpage/?next=%2Flatest%2Fhome"

class BusinessDashboardTests(unittest.IsolatedAsyncioTestCase):
    async def test_clinic_dashboard_visible_does_not_falsely_report_logout(self):
        ans = await app.inspect_session(session(url=BUSINESS,body=CLINIC,cookies=[]))
        self.assertIsNone(ans["authenticated"])
        self.assertEqual(ans["stage"], "session_present_unverified")
        self.assertEqual(ans["provider"], "meta_business")
        self.assertEqual(ans["next_action"], "verify_business_identity_without_login")

    async def test_anita_dashboard_same_evidence(self):
        ans = await app.inspect_session(session(url=ANITA_URL,body=ANITA,cookies=[]))
        self.assertEqual(ans["evidence"], "protected_dashboard_visible")
        self.assertIsNone(ans["authenticated"])

    async def test_business_login_redirect_still_requires_sign_in(self):
        ans = await app.inspect_session(session(url=LOGIN,body=CLINIC,cookies=[]))
        self.assertEqual(ans["stage"], "not_authenticated")
        self.assertIs(ans["authenticated"], False)
        self.assertEqual(ans["next_action"], "account_switch_or_explicit_login_required")

    async def test_missing_page_controls_is_unknown_not_logged_out(self):
        ans = await app.inspect_session(session(url=BUSINESS,body="Create post",cookies=[]))
        self.assertEqual(ans["stage"], "unverified")
        self.assertIsNone(ans["authenticated"])

    async def test_login_form_wins_over_forged_dashboard_copy(self):
        ans = await app.inspect_session(session(url=BUSINESS,body=CLINIC,password=True))
        self.assertEqual(ans["stage"], "login_form")
        self.assertIs(ans["authenticated"], False)

    async def test_challenge_wins_over_dashboard(self):
        ans = await app.inspect_session(session(url=BUSINESS,body=CLINIC,challenge=True))
        self.assertEqual(ans["stage"], "verification_required")

    async def test_page_changes_mid_inspection(self):
        s = session(url=BUSINESS,body=CLINIC)
        s.page.items["body"].change = lambda: setattr(s.page,"url",LOGIN)
        ans=await app.inspect_session(s)
        self.assertIsNone(ans["authenticated"])
        self.assertEqual(ans["reason"], "page_changed_during_check")

    async def test_mobile_facebook_without_cookie_is_unknown(self):
        ans=await app.inspect_session(session(url="https://m.facebook.com/",body="Feed posts",cookies=[]))
        self.assertIsNone(ans["authenticated"])
        self.assertEqual(ans["next_action"], "verify_protected_page_without_login")

    async def test_cross_host_lookalike_never_verifies(self):
        ans=await app.inspect_session(session(url="https://business.facebook.com.evil.test/latest/home?asset_id=138554046242234",body=CLINIC))
        self.assertIsNone(ans["authenticated"])
        self.assertNotEqual(ans.get("evidence"),"protected_dashboard_visible")

    async def test_no_account_id_cannot_classify_dashboard(self):
        ans=await app.inspect_session(session(url="https://business.facebook.com/latest/home",body=CLINIC))
        self.assertEqual(ans["stage"], "unverified")

    async def test_duplicate_ids_invalid(self):
        url=BUSINESS+"&asset_id=1630317700539552"
        self.assertFalse(app.business_dashboard_visible(url,CLINIC))

    async def test_english_dashboard_supported(self):
        self.assertTrue(app.business_dashboard_visible(BUSINESS,ENGLISH))

    async def test_incomplete_english_dashboard_not_verified(self):
        self.assertFalse(app.business_dashboard_visible(BUSINESS,"Create post\nFacebook followers"))

    async def test_http_not_accepted(self):
        self.assertFalse(app.business_dashboard_visible(BUSINESS.replace("https","http"),CLINIC))

    async def test_expired_redirect_not_silently_logged_in(self):
        ans=await app.inspect_session(session(url=LOGIN,body="Meta for Business sign in"))
        self.assertIs(ans["authenticated"],False)

    async def test_machine_result_never_returns_page_text_or_page_identity(self):
        body=CLINIC+"\nSYNTHETIC_PRIVATE_TOKEN_DO_NOT_ECHO"
        ans=await app.inspect_session(session(url=BUSINESS,body=body))
        self.assertNotIn("SYNTHETIC_PRIVATE_TOKEN",json.dumps(ans))
        self.assertNotIn("Przychodnia TESTOWA",json.dumps(ans))
        self.assertNotIn("138554046242234",json.dumps(ans))

if __name__=="__main__":
    unittest.main(verbosity=2)
