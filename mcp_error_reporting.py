"""Report anticipated errors through MCP 2.3, preserving the legacy sanitizer.

No session changes, credential access, retries or concurrency changes occur here.
"""
from __future__ import annotations
from collections.abc import Callable, MutableMapping
from typing import Any, NoReturn

from playwright._impl._errors import TargetClosedError

FIX_REVISION = "2026-10-10.1"
BUSY_MESSAGE = (
    "AI_BROWSER_BUSY: The configured browser session limit is occupied. "
    "Use browser_sessions to inspect it. Do not stop another active task or "
    "retry login automatically; retry this operation after the session is released."
)

PAGE_CLOSED_MESSAGE = (
    "AI_BROWSER_REMOTE_PAGE_CLOSED: The remote Chromium page closed during "
    "navigation or status inspection. Login state was NOT confirmed. "
    "Do not repeat authentication automatically. Retry only after checking "
    "that the prior remote session has been reconciled or released."
)


def classify_known_remote_failure(exc: Exception) -> str | None:
    """Precise exception class, never pattern-match private exception text."""
    if isinstance(exc, TargetClosedError):
        return PAGE_CLOSED_MESSAGE
    return None


def build_failure_handler(
    original_fail: Callable[[Exception], Any],
    tool_error_type: type[Exception],
) -> Callable[[Exception], NoReturn]:
    """Reuse the existing classification and sanitization, not guessed helpers.

    Legacy _fail deliberately raises a sanitized ValueError for anticipated
    domain errors and a masked RuntimeError for other errors. Only a ValueError
    raised directly by that handler is translated. An error inside its sanitizer
    remains unexpected and must not expose its text to the MCP client.
    """
    original_code = getattr(original_fail, "__code__", None)
    if original_code is None:
        raise RuntimeError("AI_BROWSER_ERROR_REPORTING_INCOMPATIBLE")

    def fail(exc: Exception) -> NoReturn:
        known = classify_known_remote_failure(exc)
        if known is not None:
            raise tool_error_type(known) from None
        try:
            original_fail(exc)
        except ValueError as sanitized:
            tail = sanitized.__traceback__
            while tail is not None and tail.tb_next is not None:
                tail = tail.tb_next
            if tail is None or tail.tb_frame.f_code is not original_code:
                raise
            message = str(sanitized)
            if not message.strip():
                message = "AI_BROWSER_EXPECTED_ERROR: Browser operation was not completed."
            if message.startswith("AI Browser session limit reached"):
                message = BUSY_MESSAGE
            raise tool_error_type(message) from None
        raise RuntimeError("AI_BROWSER_FAILURE_HANDLER_RETURNED") from None
    return fail


def _tool_error_type() -> type[Exception]:
    from mcp.server.mcpserver.exceptions import ToolError
    return ToolError


def install(namespace: MutableMapping[str, Any]) -> None:
    """Install after the runtime hooks; do not depend on manager helper names."""
    if namespace.get("_AI_BROWSER_MCP_ERROR_FIX") == FIX_REVISION:
        return
    original_fail = namespace.get("_fail")
    if not callable(original_fail):
        raise RuntimeError("AI_BROWSER_ERROR_REPORTING_INCOMPATIBLE")
    namespace["_fail"] = build_failure_handler(original_fail, _tool_error_type())
    namespace["_AI_BROWSER_MCP_ERROR_FIX"] = FIX_REVISION
    print("AI_BROWSER_MCP_ERROR_REPORTING_READY", FIX_REVISION, flush=True)
