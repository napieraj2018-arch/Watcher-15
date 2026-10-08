"""Offline tests for compatibility with the observed legacy _fail behavior."""
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
