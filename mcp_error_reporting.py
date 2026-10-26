"""Report anticipated errors through MCP 2.3, preserving the legacy sanitizer.

No session changes, credential access, retries or concurrency changes occur here.
"""
from __future__ import annotations
from collections.abc import Callable, MutableMapping
from typing import Any, NoReturn

from playwright.async_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError
from playwright._impl._errors import TargetClosedError

FIX_REVISION = "2026-10-26.2"
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

REMOTE_TIMEOUT_MESSAGE = (
    "AI_BROWSER_REMOTE_TIMEOUT: The remote browser operation exceeded its wait "
    "limit. Its outcome is unconfirmed; navigation or a submitted action may "
    "already have completed. Inspect browser_status and browser_snapshot for "
    "this same owned session before deciding whether to retry. Do not "
    "automatically repeat writes or authentication."
)

REMOTE_OPERATION_MESSAGE = (
    "AI_BROWSER_REMOTE_OPERATION_UNCONFIRMED: The remote browser could not "
    "confirm this operation. Inspect browser_status and browser_snapshot for "
    "this same owned session before continuing. Do not automatically repeat "
    "writes or authentication; reconcile an uncertain session before release."
)

PROFILE_ORIGIN_BLOCKED_MESSAGE = (
    "AI_BROWSER_PROFILE_RESTORE_PROVIDER_RESTRICTED: The remote browser "
    "provider blocks an origin in this saved profile. The portable state was "
    "not silently filtered or overwritten by this import. Do not retry the "
    "same login, remove credentials, disable provider policy, or clear the "
    "profile. Use the official account dashboard outside this managed "
    "browser, or a supported website/profile; inspect the exact profile "
    "before attempting any migration."
)

PDF_EMPTY_MESSAGE = (
    "AI_BROWSER_PDF_EMPTY: The downloaded file is empty; no PDF content was "
    "read. Inspect browser_downloads for this same owned session and check "
    "the source response. Do not automatically repeat the download or any "
    "action that produced it."
)

PDF_ENCRYPTED_MESSAGE = (
    "AI_BROWSER_PDF_ENCRYPTED: The downloaded PDF requires decryption; its "
    "content was not confirmed. Open it through the owner's secure document "
    "workflow or provide an authorized unencrypted copy. Do not send a "
    "password in chat or automatically repeat the download."
)

PDF_INVALID_MESSAGE = (
    "AI_BROWSER_PDF_UNREADABLE: The downloaded file could not be parsed as "
    "a readable PDF; its content was not confirmed. Inspect browser_downloads "
    "for this same owned session and verify the source file. Do not "
    "automatically repeat the download or the action that produced it."
)


def classify_known_remote_failure(exc: Exception) -> str | None:
    """Precise exception class, never pattern-match private exception text."""
    if isinstance(exc, TargetClosedError):
        return PAGE_CLOSED_MESSAGE
    if isinstance(exc, PlaywrightTimeoutError):
        return REMOTE_TIMEOUT_MESSAGE
    if isinstance(exc, PlaywrightError):
        # Includes observed ERR_ABORTED navigation. Never parse or expose the
        # provider's private URL, error text or exception chain, and never retry.
        return REMOTE_OPERATION_MESSAGE
    from steel_context_fix import ProfileRestoreOriginBlocked
    if isinstance(exc, ProfileRestoreOriginBlocked):
        return PROFILE_ORIGIN_BLOCKED_MESSAGE
    from pypdf.errors import (
        EmptyFileError, FileNotDecryptedError, PdfReadError, WrongPasswordError,
    )
    if isinstance(exc, EmptyFileError):
        return PDF_EMPTY_MESSAGE
    if isinstance(exc, (FileNotDecryptedError, WrongPasswordError)):
        return PDF_ENCRYPTED_MESSAGE
    if isinstance(exc, PdfReadError):
        return PDF_INVALID_MESSAGE
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
