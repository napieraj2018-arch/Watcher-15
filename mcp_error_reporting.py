"""Expose expected AI Browser errors through MCP 2.3 without changing sessions.

Unexpected exceptions keep the existing masked failure path. This module never
logs credentials, starts/stops browsers, raises session limits, or retries work.
"""
from __future__ import annotations

from collections.abc import Callable, MutableMapping
from typing import Any, NoReturn

FIX_REVISION = "2026-10-08.1"
BUSY_MESSAGE = (
    "AI_BROWSER_BUSY: The configured browser session limit is occupied. "
    "Use browser_sessions to inspect it. Do not stop another active task or "
    "retry login automatically; retry this operation after the session is released."
)


def build_failure_handler(
    expected_error_type: type[Exception],
    safe_error: Callable[[Exception], str],
    original_fail: Callable[[Exception], Any],
    tool_error_type: type[Exception],
) -> Callable[[Exception], NoReturn]:
    """Translate anticipated domain failures, not arbitrary internal errors."""
    def fail(exc: Exception) -> NoReturn:
        if not isinstance(exc, expected_error_type):
            original_fail(exc)
            raise RuntimeError("AI_BROWSER_FAILURE_HANDLER_RETURNED") from None
        try:
            message = safe_error(exc)
        except Exception:
            original_fail(exc)
            raise RuntimeError("AI_BROWSER_FAILURE_HANDLER_RETURNED") from None
        if not isinstance(message, str) or not message.strip():
            original_fail(exc)
            raise RuntimeError("AI_BROWSER_FAILURE_HANDLER_RETURNED") from None
        # A fixed message cannot leak profile names or URLs in a busy error.
        if message.startswith("AI Browser session limit reached"):
            message = BUSY_MESSAGE
        raise tool_error_type(message) from None
    return fail


def _tool_error_type() -> type[Exception]:
    # requirements.txt pins MCP >=2.3,<2.4. Do not silently fall back to ValueError.
    from mcp.server.mcpserver.exceptions import ToolError
    return ToolError


def install(namespace: MutableMapping[str, Any]) -> None:
    """Install after the existing runtime hooks and before the server starts."""
    if namespace.get("_AI_BROWSER_MCP_ERROR_FIX") == FIX_REVISION:
        return
    error_type = namespace.get("AIBrowserError")
    original_fail = namespace.get("_fail")
    manager = namespace.get("manager")
    safe_error = getattr(manager, "safe_error", None)
    if not (
        isinstance(error_type, type)
        and issubclass(error_type, Exception)
        and callable(original_fail)
        and callable(safe_error)
    ):
        raise RuntimeError("AI_BROWSER_ERROR_REPORTING_INCOMPATIBLE")
    namespace["_fail"] = build_failure_handler(
        error_type, safe_error, original_fail, _tool_error_type()
    )
    namespace["_AI_BROWSER_MCP_ERROR_FIX"] = FIX_REVISION
