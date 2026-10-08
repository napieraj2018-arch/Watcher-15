"""Offline regression tests; do not access external accounts or services."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
import mcp_error_reporting as fix


class DomainError(Exception):
    pass


class AnticipatedToolError(Exception):
    pass


class MaskedFailure(Exception):
    pass


class ErrorReportingTests(unittest.TestCase):
    def setUp(self):
        self.safe = Mock(side_effect=lambda exc: str(exc).replace("SECRET", "[redacted]"))
        self.original = Mock(side_effect=MaskedFailure("operation failed"))
        self.handler = fix.build_failure_handler(
            DomainError, self.safe, self.original, AnticipatedToolError
        )

    def test_busy_is_actionable_tool_error(self):
        with self.assertRaises(AnticipatedToolError) as caught:
            self.handler(DomainError("AI Browser session limit reached (1). Stop an existing session first."))
        self.assertEqual(str(caught.exception), fix.BUSY_MESSAGE)
        self.original.assert_not_called()

    def test_busy_never_exposes_appended_details(self):
        with self.assertRaises(AnticipatedToolError) as caught:
            self.handler(DomainError("AI Browser session limit reached (1). PRIVATE_PROFILE SECRET"))
        self.assertNotIn("PRIVATE_PROFILE", str(caught.exception))
        self.assertNotIn("SECRET", str(caught.exception))

    def test_expected_error_uses_existing_sanitizer(self):
        with self.assertRaises(AnticipatedToolError) as caught:
            self.handler(DomainError("invalid request SECRET"))
        self.assertEqual(str(caught.exception), "invalid request [redacted]")
        self.safe.assert_called_once()

    def test_unknown_error_keeps_original_masking(self):
        with self.assertRaises(MaskedFailure):
            self.handler(RuntimeError("SECRET"))
        self.safe.assert_not_called()
        self.original.assert_called_once()

    def test_plain_value_error_is_not_reclassified(self):
        with self.assertRaises(MaskedFailure):
            self.handler(ValueError("AI Browser session limit reached (1)."))
        self.original.assert_called_once()

    def test_expected_subclasses_are_supported(self):
        class SpecializedError(DomainError):
            pass
        with self.assertRaises(AnticipatedToolError):
            self.handler(SpecializedError("expected"))

    def test_sanitizer_failure_uses_original_handler(self):
        self.safe.side_effect = RuntimeError("SECRET")
        with self.assertRaises(MaskedFailure):
            self.handler(DomainError("expected"))

    def test_invalid_sanitizer_output_uses_original_handler(self):
        for value in (None, "", "   ", 123):
            with self.subTest(value=value):
                self.safe.side_effect = None
                self.safe.return_value = value
                with self.assertRaises(MaskedFailure):
                    self.handler(DomainError("expected"))

    def test_original_handler_must_not_return_success(self):
        self.original.side_effect = None
        with self.assertRaisesRegex(RuntimeError, "AI_BROWSER_FAILURE_HANDLER_RETURNED"):
            self.handler(RuntimeError("unexpected"))

    def test_install_is_idempotent(self):
        ns = {"AIBrowserError": DomainError, "_fail": self.original,
              "manager": SimpleNamespace(safe_error=self.safe)}
        with patch.object(fix, "_tool_error_type", return_value=AnticipatedToolError) as load:
            fix.install(ns)
            installed = ns["_fail"]
            fix.install(ns)
        self.assertIs(ns["_fail"], installed)
        self.assertEqual(load.call_count, 1)
        self.assertEqual(ns["_AI_BROWSER_MCP_ERROR_FIX"], fix.FIX_REVISION)

    def test_install_rejects_incompatible_namespace(self):
        for ns in ({}, {"AIBrowserError": str}, {"_fail": None}):
            with self.subTest(ns=ns):
                with self.assertRaisesRegex(RuntimeError, "AI_BROWSER_ERROR_REPORTING_INCOMPATIBLE"):
                    fix.install(ns)
                self.assertNotIn("_AI_BROWSER_MCP_ERROR_FIX", ns)

    def test_expected_traceback_cause_is_suppressed(self):
        with self.assertRaises(AnticipatedToolError) as caught:
            self.handler(DomainError("expected"))
        self.assertTrue(caught.exception.__suppress_context__)

    def test_does_not_touch_session_manager_operations(self):
        manager = SimpleNamespace(safe_error=self.safe, start=Mock(), stop=Mock())
        ns = {"AIBrowserError": DomainError, "_fail": self.original, "manager": manager}
        with patch.object(fix, "_tool_error_type", return_value=AnticipatedToolError):
            fix.install(ns)
        with self.assertRaises(AnticipatedToolError):
            ns["_fail"](DomainError("AI Browser session limit reached (1)."))
        manager.start.assert_not_called()
        manager.stop.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
