"""Synthetic challenge evidence only; no email, secrets or provider sessions."""
import asyncio
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import auth_status_v052 as auth
import verification_status as app


class Locator:
    def __init__(self, count=0, text="", change=None, response_present=False):
        self.n, self.text, self.change = count, text, change
        self.response_present = response_present

    async def count(self):
        if self.change:
            self.change()
        return self.n

    async def inner_text(self, **_kwargs):
        if self.change:
            self.change()
        return self.text

    async def evaluate_all(self, script):
        if self.change:
            self.change()
        assert script == app.RESPONSE_PRESENT
        return self.response_present


class Page:
    def __init__(self, *, url="https://fixture.example/login", captcha=False,
                 code=False, body="", legacy=False):
        self.url, self.closed = url, False
        self.items = {
            app.CAPTCHA: Locator(int(captcha)),
            app.ONE_TIME_CODE: Locator(int(code)),
            auth.CHALLENGE: Locator(int(legacy)), "body": Locator(1, body),
        }

    def is_closed(self):
        return self.closed

    def locator(self, selector):
        return self.items.get(selector, Locator())


def session(*, provider=None, **page_args):
    page = Page(**page_args)
    probe = AsyncMock(return_value=provider if provider is not None else {
        "enabled": True, "status": "solving"})
    return SimpleNamespace(page=page, browser=SimpleNamespace(captcha_status=probe),
                           context=SimpleNamespace(), profile="SyntheticFixture")


class VerificationEvidence(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        patcher = patch.object(app, "_now", return_value=100.0)
        self.clock = patcher.start()
        self.addCleanup(patcher.stop)

    async def inspect(self, current, **kwargs):
        return await auth.inspect_session(current, **kwargs)

    async def test_captcha_progress_keeps_existing_password_guard_stage(self):
        current = session(captcha=True)
        evidence = await self.inspect(current)
        self.assertEqual(evidence["stage"], "verification_required")
        self.assertIs(evidence["authenticated"], False)
        self.assertEqual(evidence["next_action"], "wait_for_provider_captcha")
        self.assertFalse(evidence["verification"]["requires_human"])
        self.assertEqual(evidence["verification"]["wait_remaining_seconds"], 45)
        current.browser.captcha_status.assert_awaited_once_with(current.page.url)

    async def test_captcha_on_generic_challenge_path_can_use_supported_solver(self):
        evidence = await self.inspect(session(captcha=True,
            url="https://fixture.example/challenge/recaptcha"))
        self.assertEqual(evidence["next_action"], "wait_for_provider_captcha")

    async def test_not_running_is_never_reported_as_solved_or_authenticated(self):
        evidence = await self.inspect(session(captcha=True, provider={
            "enabled": True, "status": "not_running", "solved": True}))
        self.assertEqual(evidence["next_action"], "check_current_page_after_captcha")
        self.assertFalse(evidence["verification"]["completion_confirmed"])
        self.assertIs(evidence["authenticated"], False)
        self.assertNotIn("solved", evidence["verification"])

    async def test_client_response_never_bypasses_password_guard_or_proves_auth(self):
        current = session(captcha=True, provider={"requested": True, "enabled": True,
            "provider_confirmed": True, "availability": "enabled", "status": "not_running"})
        current.page.items[app.CAPTCHA_RESPONSE] = Locator(response_present=True)
        evidence = await self.inspect(current)
        self.assertEqual(evidence["stage"], "verification_required")
        self.assertIs(evidence["authenticated"], False)
        self.assertEqual(evidence["next_action"], "inspect_current_page_after_captcha")
        self.assertTrue(evidence["verification"]["response_present"])
        self.assertFalse(evidence["verification"]["completion_confirmed"])
        self.assertFalse(evidence["verification"]["automatic_login_retry"])
        self.clock.return_value = 145
        evidence = await self.inspect(current)
        self.assertTrue(evidence["verification"]["requires_human"])
        self.assertNotIn("response_present", evidence["verification"])
        self.assertEqual(current.browser.captcha_status.await_count, 1)

    async def test_unconfirmed_provider_never_promotes_response_hint(self):
        current = session(captcha=True, provider={"enabled": True, "status": "not_running"})
        current.page.items[app.CAPTCHA_RESPONSE] = Locator(response_present=True)
        evidence = await self.inspect(current)
        self.assertNotIn("response_present", evidence["verification"])
        self.assertEqual(evidence["stage"], "verification_required")

    async def test_nonboolean_response_evidence_is_not_returned(self):
        current = session(captcha=True, provider={"enabled": True,
            "provider_confirmed": True, "status": "not_running"})
        current.page.items[app.CAPTCHA_RESPONSE] = Locator(response_present="SYNTHETIC_PRIVATE_VALUE")
        evidence = await self.inspect(current)
        self.assertNotIn("response_present", evidence["verification"])
        self.assertNotIn("SYNTHETIC_PRIVATE_VALUE", json.dumps(evidence))

    async def test_redirect_during_response_check_discards_evidence(self):
        current = session(captcha=True, provider={"enabled": True,
            "provider_confirmed": True, "status": "not_running"})
        current.page.items[app.CAPTCHA_RESPONSE] = Locator(response_present=True,
            change=lambda: setattr(current.page, "url", "https://other.example/"))
        evidence = await self.inspect(current)
        self.assertEqual(evidence["reason"], "page_changed_during_check")

    async def test_response_check_cannot_extend_wait_budget(self):
        current = session(captcha=True, provider={"enabled": True,
            "provider_confirmed": True, "status": "not_running"})
        current.page.items[app.CAPTCHA_RESPONSE] = Locator(response_present=True,
            change=lambda: setattr(self.clock, "return_value", 145))
        evidence = await self.inspect(current)
        self.assertEqual(evidence["verification"]["reason"], "captcha_wait_budget_exhausted")
        self.assertTrue(evidence["verification"]["requires_human"])

    async def test_unreported_and_unavailable_do_not_claim_provider_success(self):
        for state in ("not_reported", "unavailable"):
            with self.subTest(state=state):
                evidence = await self.inspect(session(captcha=True, provider={
                    "enabled": True, "status": state}))
                self.assertFalse(evidence["verification"]["completion_confirmed"])
                self.assertEqual(evidence["verification"]["provider_status"], state)

    async def test_disabled_or_absent_provider_uses_owner_fallback(self):
        for current in (session(captcha=True, provider={"enabled": False, "status": "disabled"}),
                        session(captcha=True)):
            if current.browser.captcha_status.return_value["enabled"]:
                del current.browser.captcha_status
            evidence = await self.inspect(current)
            self.assertTrue(evidence["verification"]["requires_human"])
            self.assertEqual(evidence["next_action"], "stop_automatic_login")

    async def test_repeated_status_reads_cannot_renew_deadline(self):
        current = session(captcha=True)
        await self.inspect(current)
        self.clock.return_value = 140
        evidence = await self.inspect(current)
        self.assertEqual(evidence["verification"]["wait_remaining_seconds"], 5)
        self.clock.return_value = 145
        expired = await self.inspect(current)
        self.assertEqual(expired["verification"]["reason"], "captcha_wait_budget_exhausted")
        self.assertTrue(expired["verification"]["requires_human"])
        self.assertEqual(current.browser.captcha_status.await_count, 2)

    async def test_remaining_owner_budget_clamps_wait(self):
        evidence = await self.inspect(session(captcha=True), remaining_seconds=7)
        self.assertEqual(evidence["verification"]["wait_remaining_seconds"], 7)

    async def test_zero_owner_budget_never_queries_provider(self):
        current = session(captcha=True)
        evidence = await self.inspect(current, remaining_seconds=0)
        self.assertTrue(evidence["verification"]["requires_human"])
        current.browser.captcha_status.assert_not_awaited()

    async def test_slow_status_read_consumes_challenge_budget(self):
        current = session(captcha=True)
        async def slow(_url):
            self.clock.return_value = 108
            return {"enabled": True, "status": "solving"}
        current.browser.captcha_status.side_effect = slow
        evidence = await self.inspect(current, remaining_seconds=7)
        self.assertEqual(evidence["verification"]["wait_remaining_seconds"], 0)
        self.assertTrue(evidence["verification"]["requires_human"])

    async def test_changed_url_cannot_renew_continuous_challenge_budget(self):
        current = session(captcha=True)
        await self.inspect(current)
        self.clock.return_value = 140
        current.page.url = "https://fixture.example/login?nonce=second"
        evidence = await self.inspect(current)
        self.assertEqual(evidence["verification"]["wait_remaining_seconds"], 5)
        self.clock.return_value = 145
        current.page.url = "https://fixture.example/captcha?nonce=third"
        expired = await self.inspect(current)
        self.assertEqual(expired["verification"]["reason"], "captcha_wait_budget_exhausted")
        self.assertEqual(current.browser.captcha_status.await_count, 2)

    async def test_changed_url_still_clamps_to_smaller_owner_budget(self):
        current = session(captcha=True)
        await self.inspect(current)
        self.clock.return_value = 140
        current.page.url = "https://fixture.example/other"
        evidence = await self.inspect(current, remaining_seconds=4)
        self.assertEqual(evidence["verification"]["wait_remaining_seconds"], 4)

    async def test_no_challenge_resets_only_local_wait_marker(self):
        current = session(captcha=True)
        await self.inspect(current)
        current.page.items[app.CAPTCHA].n = 0
        evidence = await self.inspect(current)
        self.assertEqual(evidence["stage"], "unverified")
        self.assertFalse(hasattr(current.page, "_aib_captcha_wait"))
        self.assertEqual(current.browser.captcha_status.await_count, 1)
        self.clock.return_value = 140
        current.page.items[app.CAPTCHA].n = 1
        evidence = await self.inspect(current)
        self.assertEqual(evidence["verification"]["wait_remaining_seconds"], 45)

    async def test_account_access_fallback_is_distinct_from_disabled(self):
        evidence = await self.inspect(session(captcha=True, provider={
            "requested": True, "enabled": False, "provider_confirmed": False,
            "availability": "account_access_required", "status": "disabled"}))
        verification = evidence["verification"]
        self.assertEqual(verification["reason"], "provider_account_access_required")
        self.assertEqual(verification["availability"], "account_access_required")
        self.assertFalse(verification["provider_enabled"])
        self.assertFalse(verification["provider_confirmed"])
        self.assertTrue(verification["enabled_requested"])
        self.assertTrue(verification["requires_human"])

    async def test_request_and_provider_confirmation_are_separate(self):
        for confirmed, availability in ((True, "enabled"), (False, "provider_unconfirmed")):
            with self.subTest(confirmed=confirmed):
                evidence = await self.inspect(session(captcha=True, provider={
                    "enabled": True, "provider_confirmed": confirmed,
                    "availability": availability, "status": "solving"}))
                verification = evidence["verification"]
                self.assertIs(verification["provider_confirmed"], confirmed)
                self.assertEqual(verification["availability"], availability)
                self.assertFalse(verification["completion_confirmed"])

    async def test_arbitrary_availability_is_not_exported(self):
        evidence = await self.inspect(session(captcha=True, provider={
            "enabled": True, "provider_confirmed": "true",
            "availability": "SYNTHETIC_PRIVATE_VALUE", "status": "solving"}))
        self.assertFalse(evidence["verification"]["provider_confirmed"])
        self.assertEqual(evidence["verification"]["availability"], "not_reported")
        self.assertNotIn("SYNTHETIC_PRIVATE_VALUE", json.dumps(evidence))

    async def test_raw_provider_objects_and_private_urls_are_never_exported(self):
        secret = "SYNTHETIC_PRIVATE_VALUE"
        current = session(captcha=True, url="https://fixture.example/captcha?token=" + secret,
            provider={"enabled": True, "status": "solving", "pageId": secret,
                      "url": secret, "tasks": [{"id": secret}]})
        evidence = json.dumps(await self.inspect(current))
        self.assertNotIn(secret, evidence)
        self.assertNotIn("fixture.example", evidence)
        self.assertNotIn("pageId", evidence)

    async def test_invalid_provider_schema_is_fixed_unavailable_not_raw_text(self):
        for value in (["SYNTHETIC_SECRET"], {"enabled": "yes", "status": "SYNTHETIC_SECRET"}):
            with self.subTest(value=type(value).__name__):
                evidence = await self.inspect(session(captcha=True, provider=value))
                self.assertEqual(evidence["verification"]["provider_status"], "unavailable")
                self.assertNotIn("SYNTHETIC_SECRET", json.dumps(evidence))

    async def test_provider_exception_does_not_leak_or_retry(self):
        current = session(captcha=True)
        current.browser.captcha_status.side_effect = RuntimeError("SYNTHETIC_SECRET")
        evidence = await self.inspect(current)
        self.assertNotIn("SYNTHETIC_SECRET", json.dumps(evidence))
        self.assertEqual(evidence["verification"]["provider_status"], "unavailable")
        self.assertEqual(current.browser.captcha_status.await_count, 1)

    async def test_cancellation_is_not_swallowed(self):
        current = session(captcha=True)
        current.browser.captcha_status.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await self.inspect(current)
        self.assertEqual(current.browser.captcha_status.await_count, 1)

    async def test_url_change_during_provider_read_discards_old_evidence(self):
        current = session(captcha=True)
        async def redirect(_url):
            current.page.url = "https://another.example/"
            return {"enabled": True, "status": "solving"}
        current.browser.captcha_status.side_effect = redirect
        evidence = await self.inspect(current)
        self.assertEqual(evidence["reason"], "page_changed_during_check")
        self.assertEqual(evidence["stage"], "verification_required")
        self.assertIsNone(evidence["authenticated"])
        self.assertEqual(evidence["next_action"], "inspect_current_page_before_login")
        self.assertFalse(evidence["verification"]["automatic_login_retry"])

    async def test_changed_page_during_provider_read_remains_password_blocked(self):
        current = session(captcha=True)
        async def replace_page(_url):
            current.page = Page()
            current.page.items[auth.PASSWORD] = Locator(1)
            return {"enabled": True, "status": "not_running"}
        current.browser.captcha_status.side_effect = replace_page
        evidence = await self.inspect(current)
        self.assertEqual(evidence["stage"], "verification_required")
        self.assertEqual(evidence["reason"], "page_changed_during_check")
        self.assertEqual(evidence["next_action"], "inspect_current_page_before_login")
        # Only a new read bound to the new page may classify its login form.
        current.browser.captcha_status.side_effect = None
        fresh = await self.inspect(current)
        self.assertEqual(fresh["stage"], "login_form")

    async def test_page_change_during_dom_detection_discards_evidence(self):
        current = session(captcha=True)
        current.page.items[app.CAPTCHA].change = lambda: setattr(
            current, "page", Page(captcha=True))
        evidence = await self.inspect(current)
        self.assertEqual(evidence["reason"], "page_changed_during_check")
        current.browser.captcha_status.assert_not_awaited()

    async def test_mfa_and_checkpoint_take_priority_over_captcha(self):
        for path, kind in (("/two_step_verification", "multi_factor"),
                           ("/checkpoint/123", "security_checkpoint")):
            with self.subTest(path=path):
                current = session(captcha=True, url="https://fixture.example" + path)
                evidence = await self.inspect(current)
                self.assertEqual(evidence["verification"]["kind"], kind)
                self.assertTrue(evidence["verification"]["requires_human"])
                current.browser.captcha_status.assert_not_awaited()

    async def test_mixed_code_and_captcha_does_not_downgrade_security(self):
        current = session(captcha=True, code=True)
        evidence = await self.inspect(current)
        self.assertTrue(evidence["verification"]["requires_human"])
        self.assertEqual(evidence["verification"]["reason"], "mixed_verification_challenge")
        current.browser.captcha_status.assert_not_awaited()

    async def test_ordinary_email_confirmation_selects_connected_mailbox_hint(self):
        evidence = await self.inspect(session(url="https://fixture.example/verify-email",
            body="Verify your email. Check your inbox, owner@example.test."))
        self.assertEqual(evidence["verification"]["kind"], "email_confirmation")
        self.assertEqual(evidence["next_action"], "check_connected_mailbox_for_matching_confirmation")
        self.assertFalse(evidence["verification"]["backend_mailbox_access"])
        self.assertFalse(evidence["verification"]["code_auto_submission_supported"])
        self.assertNotIn("owner@example.test", json.dumps(evidence))

    async def test_ordinary_email_code_keeps_secure_input_path(self):
        evidence = await self.inspect(session(code=True, body="Confirm your email address"))
        self.assertEqual(evidence["verification"]["kind"], "email_confirmation")
        self.assertEqual(evidence["verification"]["method"], "code")
        self.assertTrue(evidence["verification"]["requires_human"])
        self.assertEqual(evidence["next_action"], "complete_code_in_secure_owner_view")
        self.assertEqual(evidence["stage"], "verification_required")

    async def test_ambiguous_code_is_not_assumed_to_be_email_confirmation(self):
        evidence = await self.inspect(session(code=True, body="Enter the code"))
        self.assertEqual(evidence["verification"]["kind"], "multi_factor")
        self.assertTrue(evidence["verification"]["requires_human"])

    async def test_email_words_cannot_authorize_unrelated_security_flow(self):
        for operation in ("Reset your password", "Change your email", "Two-factor authentication",
                          "Verify your identity", "Recovery", "Potwierdź tożsamość"):
            with self.subTest(operation=operation):
                evidence = await self.inspect(session(url="https://fixture.example/verify-email",
                    body="Verify your email. " + operation))
                self.assertNotEqual(evidence["verification"]["kind"], "email_confirmation")
                self.assertTrue(evidence["verification"]["requires_human"])

    async def test_email_path_without_matching_content_is_not_verified(self):
        evidence = await self.inspect(session(url="https://fixture.example/verify-email",
            body="Unrelated page"))
        self.assertEqual(evidence["verification"]["kind"], "unknown")

    async def test_page_change_during_email_check_is_discarded(self):
        current = session(url="https://fixture.example/verify-email", body="Verify your email")
        current.page.items["body"].change = lambda: setattr(
            current.page, "url", "https://another.example/")
        evidence = await self.inspect(current)
        self.assertEqual(evidence["reason"], "page_changed_during_check")


if __name__ == "__main__":
    unittest.main(verbosity=2)
