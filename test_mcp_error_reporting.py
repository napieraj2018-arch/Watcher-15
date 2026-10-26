"""Offline tests for compatibility with the observed legacy _fail behavior."""
import traceback
import io
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
import mcp_error_reporting as fix

class DomainError(Exception):
    pass

class AnticipatedToolError(Exception):
    pass

class ErrorReportingTests(unittest.TestCase):
    def setUp(self):
        self.sanitize = Mock(side_effect=lambda exc: str(exc).replace("SECRET", "[redacted]"))
        self.calls = []
        def legacy_fail(exc):
            self.calls.append(exc)
            message = self.sanitize(exc)
            if isinstance(exc, DomainError):
                raise ValueError(message) from exc
            raise RuntimeError("Browser operation failed") from exc
        self.legacy = legacy_fail
        self.handler = fix.build_failure_handler(self.legacy, AnticipatedToolError)

    def test_target_closed_page_produces_fixed_actionable_mcp_error(self):
        from playwright._impl._errors import TargetClosedError
        reason = "Page.title: private host, cookies and session details must not leak"
        with self.assertRaises(AnticipatedToolError) as caught:
            self.handler(TargetClosedError(reason))
        self.assertEqual(str(caught.exception), fix.PAGE_CLOSED_MESSAGE)
        self.assertNotIn("private host", str(caught.exception))
        self.assertIsNone(caught.exception.__cause__)
        self.assertEqual(self.calls, [])

    def test_target_closed_subclass_does_not_leak_provider_url(self):
        from playwright._impl._errors import TargetClosedError
        class ClosedSubType(TargetClosedError):
            pass
        with self.assertRaises(AnticipatedToolError) as caught:
            self.handler(ClosedSubType("wss://provider.invalid/session/secret"))
        self.assertEqual(str(caught.exception), fix.PAGE_CLOSED_MESSAGE)
        self.assertNotIn("provider.invalid", str(caught.exception))

    def test_unrelated_exception_with_target_closed_words_is_not_reclassified(self):
        with self.assertRaisesRegex(RuntimeError, "Browser operation failed"):
            self.handler(RuntimeError("TargetClosedError fake SECRET"))

    def test_mcp_error_classification_is_only_for_real_playwright_type(self):
        from playwright._impl._errors import TargetClosedError
        self.assertIsNone(fix.classify_known_remote_failure(
            RuntimeError("Target page was closed")))
        self.assertEqual(
            fix.classify_known_remote_failure(TargetClosedError("secret")),
            fix.PAGE_CLOSED_MESSAGE,
        )

    def test_playwright_timeout_reports_unknown_outcome_without_private_details(self):
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError
        detail = ("Page.go_back: Timeout 30000ms exceeded; "
                  "https://private.invalid/account?session=SECRET")
        with self.assertRaises(AnticipatedToolError) as caught:
            self.handler(PlaywrightTimeoutError(detail))
        self.assertEqual(str(caught.exception), fix.REMOTE_TIMEOUT_MESSAGE)
        self.assertIn("outcome is unconfirmed", str(caught.exception))
        self.assertIn("browser_status and browser_snapshot", str(caught.exception))
        self.assertIn("Do not automatically repeat writes or authentication",
                      str(caught.exception))
        self.assertNotIn("private.invalid", str(caught.exception))
        self.assertNotIn("SECRET", str(caught.exception))
        self.assertEqual(self.calls, [])
        self.sanitize.assert_not_called()

    def test_real_navigation_abort_is_actionable_and_never_leaks_url(self):
        from playwright.async_api import Error
        with self.assertRaises(AnticipatedToolError) as caught:
            self.handler(Error('Page.goto: net::ERR_ABORTED at https://private.test/?token=SECRET'))
        self.assertEqual(str(caught.exception),fix.REMOTE_OPERATION_MESSAGE)
        self.assertNotIn('SECRET',str(caught.exception))
        self.assertNotIn('private.test',str(caught.exception))
        self.assertIsNone(caught.exception.__cause__)
        self.assertEqual(self.calls,[])

    def test_other_real_playwright_errors_keep_unknown_outcome_without_retry(self):
        from playwright.async_api import Error
        for detail in ('net::ERR_CONNECTION_RESET SECRET','Page.evaluate: private script SECRET'):
            with self.assertRaises(AnticipatedToolError) as caught:self.handler(Error(detail))
            self.assertEqual(str(caught.exception),fix.REMOTE_OPERATION_MESSAGE)
            self.assertTrue(caught.exception.__suppress_context__)

    def test_spoofed_navigation_abort_is_not_reclassified(self):
        self.assertIsNone(fix.classify_known_remote_failure(RuntimeError('net::ERR_ABORTED SECRET')))

    def assert_pdf_failure(self, operation, message):
        try:
            operation()
        except Exception as error:
            with self.assertRaises(AnticipatedToolError) as caught:
                self.handler(error)
        else:
            self.fail("PDF fixture unexpectedly succeeded")
        self.assertEqual(str(caught.exception), message)
        self.assertIsNone(caught.exception.__cause__)
        self.assertTrue(caught.exception.__suppress_context__)
        self.assertEqual(self.calls, [])
        self.sanitize.assert_not_called()

    def test_real_parser_empty_file_is_actionable(self):
        from pypdf import PdfReader
        self.assert_pdf_failure(lambda: PdfReader(io.BytesIO(b"")), fix.PDF_EMPTY_MESSAGE)

    def test_real_parser_truncated_pdf_is_unreadable(self):
        from pypdf import PdfReader
        self.assert_pdf_failure(
            lambda: PdfReader(io.BytesIO(b"%PDF-1.7\nPRIVATE_DOCUMENT_SECRET")),
            fix.PDF_INVALID_MESSAGE,
        )

    def test_real_encrypted_pdf_requires_owner_decryption(self):
        from pypdf import PdfReader, PdfWriter
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer.encrypt("synthetic-test-only")
        stream = io.BytesIO()
        writer.write(stream)
        stream.seek(0)
        reader = PdfReader(stream)
        self.assert_pdf_failure(lambda: len(reader.pages), fix.PDF_ENCRYPTED_MESSAGE)

    def test_pdf_errors_never_expose_parser_details_or_private_chain(self):
        from pypdf.errors import EmptyFileError, FileNotDecryptedError, PdfReadError, WrongPasswordError
        for error_type, message in (
            (EmptyFileError, fix.PDF_EMPTY_MESSAGE),
            (FileNotDecryptedError, fix.PDF_ENCRYPTED_MESSAGE),
            (WrongPasswordError, fix.PDF_ENCRYPTED_MESSAGE),
            (PdfReadError, fix.PDF_INVALID_MESSAGE),
        ):
            with self.subTest(error_type=error_type):
                try:
                    try:
                        raise RuntimeError("PRIVATE_DOCUMENT_SECRET")
                    except RuntimeError as cause:
                        raise error_type("PRIVATE_DOCUMENT_SECRET") from cause
                except error_type as error:
                    with self.assertRaises(AnticipatedToolError) as caught:
                        self.handler(error)
                self.assertEqual(str(caught.exception), message)
                rendered = "".join(traceback.format_exception(caught.exception))
                self.assertNotIn("PRIVATE_DOCUMENT_SECRET", rendered)

    def test_pdf_error_words_do_not_reclassify_unknown_exceptions(self):
        for error in (RuntimeError("EmptyFileError SECRET"), ValueError("PdfReadError SECRET")):
            self.assertIsNone(fix.classify_known_remote_failure(error))
            with self.assertRaisesRegex(RuntimeError, "Browser operation failed"):
                self.handler(error)

    def test_valid_pdf_is_still_readable(self):
        from pypdf import PdfReader, PdfWriter
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        stream = io.BytesIO()
        writer.write(stream)
        stream.seek(0)
        self.assertEqual(len(PdfReader(stream).pages), 1)

    def test_playwright_timeout_subclass_uses_same_static_message(self):
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError
        class SpecificTimeout(PlaywrightTimeoutError):
            pass
        with self.assertRaises(AnticipatedToolError) as caught:
            self.handler(SpecificTimeout("private page text SECRET"))
        self.assertEqual(str(caught.exception), fix.REMOTE_TIMEOUT_MESSAGE)

    def test_unrelated_timeout_types_and_words_are_not_reclassified(self):
        class TimeoutErrorLookalike(Exception):
            pass
        for exc in (
            RuntimeError("TimeoutError: Page.go_back Timeout 30000ms SECRET"),
            TimeoutError("network timeout SECRET"),
            TimeoutErrorLookalike("Playwright TimeoutError SECRET"),
        ):
            with self.subTest(type=type(exc).__name__):
                self.assertIsNone(fix.classify_known_remote_failure(exc))
                with self.assertRaisesRegex(RuntimeError, "Browser operation failed"):
                    self.handler(exc)

    def test_playwright_timeout_suppresses_private_exception_chain(self):
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError
        private_detail = "PRIVATE_PROVIDER_SESSION_SECRET"
        try:
            try:
                raise RuntimeError(private_detail)
            except RuntimeError as cause:
                raise PlaywrightTimeoutError(private_detail) from cause
        except PlaywrightTimeoutError as timeout:
            try:
                self.handler(timeout)
            except AnticipatedToolError as reported:
                self.assertTrue(reported.__suppress_context__)
                self.assertIsNone(reported.__cause__)
                rendered = "".join(traceback.format_exception(reported))
                self.assertNotIn(private_detail, rendered)
                self.assertIn(fix.REMOTE_TIMEOUT_MESSAGE, rendered)
            else:
                self.fail("Playwright timeout was not reported as a tool error")

    def test_busy_is_actionable(self):
        with self.assertRaises(AnticipatedToolError) as caught:
            self.handler(DomainError("AI Browser session limit reached (1). Stop an existing session first."))
        self.assertEqual(str(caught.exception), fix.BUSY_MESSAGE)

    def test_busy_hides_appended_private_details(self):
        with self.assertRaises(AnticipatedToolError) as caught:
            self.handler(DomainError("AI Browser session limit reached (1). PRIVATE_PROFILE SECRET"))
        self.assertNotIn("PRIVATE_PROFILE", str(caught.exception))
        self.assertNotIn("SECRET", str(caught.exception))

    def test_expected_message_uses_original_sanitizer(self):
        with self.assertRaises(AnticipatedToolError) as caught:
            self.handler(DomainError("request SECRET"))
        self.assertEqual(str(caught.exception), "request [redacted]")
        self.sanitize.assert_called_once()
        self.assertEqual(len(self.calls), 1)

    def test_provider_blocked_profile_error_is_sanitized_actionable(self):
        from steel_context_fix import ProfileRestoreOriginBlocked
        error = ProfileRestoreOriginBlocked('PROFILE_RESTORE_PROVIDER_RESTRICTED')
        with self.assertRaises(AnticipatedToolError) as caught:
            self.handler(error)
        self.assertEqual(str(caught.exception),
                         fix.PROFILE_ORIGIN_BLOCKED_MESSAGE)
        self.assertIn('not silently filtered or overwritten',
                      str(caught.exception))
        self.assertIsNone(caught.exception.__cause__)
        self.assertEqual(self.calls, [])
        self.sanitize.assert_not_called()

    def test_spoofed_provider_restore_error_is_not_reclassified(self):
        with self.assertRaisesRegex(RuntimeError, "Browser operation failed"):
            self.handler(RuntimeError(
                'PROFILE_RESTORE_PROVIDER_RESTRICTED at SECRET'))
        self.assertIsNone(fix.classify_known_remote_failure(
            RuntimeError('PROFILE_RESTORE_PROVIDER_RESTRICTED')))

    def test_unknown_error_keeps_masking(self):
        with self.assertRaisesRegex(RuntimeError, "Browser operation failed"):
            self.handler(RuntimeError("SECRET"))

    def test_plain_value_error_is_not_reclassified(self):
        with self.assertRaisesRegex(RuntimeError, "Browser operation failed"):
            self.handler(ValueError("AI Browser session limit reached (1)."))

    def test_domain_subclass_is_supported(self):
        class SpecializedError(DomainError):
            pass
        with self.assertRaises(AnticipatedToolError):
            self.handler(SpecializedError("expected"))

    def test_sanitizer_runtime_error_is_not_exposed_as_tool_error(self):
        self.sanitize.side_effect = RuntimeError("SECRET")
        with self.assertRaises(RuntimeError):
            self.handler(DomainError("expected"))

    def test_sanitizer_value_error_is_not_exposed_as_tool_error(self):
        self.sanitize.side_effect = ValueError("SECRET")
        with self.assertRaises(ValueError):
            self.handler(DomainError("expected"))

    def test_empty_expected_message_has_static_fallback(self):
        for value in ("", "   "):
            with self.subTest(value=value):
                self.sanitize.side_effect = None
                self.sanitize.return_value = value
                with self.assertRaises(AnticipatedToolError) as caught:
                    self.handler(DomainError("expected"))
                self.assertTrue(str(caught.exception).startswith("AI_BROWSER_EXPECTED_ERROR:"))

    def test_returning_legacy_handler_cannot_signal_success(self):
        def no_raise(exc):
            return None
        handler = fix.build_failure_handler(no_raise, AnticipatedToolError)
        with self.assertRaisesRegex(RuntimeError, "AI_BROWSER_FAILURE_HANDLER_RETURNED"):
            handler(DomainError("expected"))

    def test_install_without_manager_or_domain_type_name(self):
        ns = {"_fail": self.legacy}
        with patch.object(fix, "_tool_error_type", return_value=AnticipatedToolError):
            fix.install(ns)
        with self.assertRaises(AnticipatedToolError):
            ns["_fail"](DomainError("expected"))

    def test_install_is_idempotent(self):
        ns = {"_fail": self.legacy}
        with patch.object(fix, "_tool_error_type", return_value=AnticipatedToolError) as load:
            fix.install(ns)
            installed = ns["_fail"]
            fix.install(ns)
        self.assertIs(ns["_fail"], installed)
        self.assertEqual(load.call_count, 1)

    def test_missing_handler_is_rejected(self):
        for ns in ({}, {"_fail": None}):
            with self.subTest(ns=ns):
                with self.assertRaisesRegex(RuntimeError, "AI_BROWSER_ERROR_REPORTING_INCOMPATIBLE"):
                    fix.install(ns)

    def test_uninspectable_callable_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "AI_BROWSER_ERROR_REPORTING_INCOMPATIBLE"):
            fix.build_failure_handler(Mock(), AnticipatedToolError)

    def test_expected_error_suppresses_private_cause(self):
        with self.assertRaises(AnticipatedToolError) as caught:
            self.handler(DomainError("expected"))
        self.assertTrue(caught.exception.__suppress_context__)
        self.assertIsNone(caught.exception.__cause__)

    def test_manager_sessions_are_untouched(self):
        manager = SimpleNamespace(start=Mock(), stop=Mock())
        ns = {"_fail": self.legacy, "manager": manager}
        with patch.object(fix, "_tool_error_type", return_value=AnticipatedToolError):
            fix.install(ns)
        with self.assertRaises(AnticipatedToolError):
            ns["_fail"](DomainError("AI Browser session limit reached (1)."))
        manager.start.assert_not_called()
        manager.stop.assert_not_called()

if __name__ == "__main__":
    unittest.main(verbosity=2)
