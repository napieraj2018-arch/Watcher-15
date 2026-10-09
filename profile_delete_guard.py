"""Production-safety interlock for the legacy destructive profile_delete tool.

Floot currently pauses incomplete erasure, but an MCP tool must not report
complete deletion or remove mappings on only one storage backend. This guard
prevents that tool from being called until independent Steel-native deletion,
backup purge, tenant auth and step-up confirmation are implemented.

Scope: MCP tool registry only. Other deletion APIs must be audited separately.
No profile or provider operation is made during installation.
"""
from __future__ import annotations
import inspect
from typing import Any, MutableMapping

ERROR = "PROFILE_ERASURE_PAUSED_PROVIDER_UNVERIFIED"
FIX = "2026-10-09.1"


class ErasureGuardError(RuntimeError):
    """Fixed error code; never echo profile names or credentials."""


def install(namespace: MutableMapping[str, Any]) -> None:
    if namespace.get("_AIB_PROFILE_ERASURE_GUARD") == FIX:
        return
    mcp = namespace.get("mcp")
    registry = getattr(getattr(mcp, "_tool_manager", None), "_tools", None)
    if not isinstance(registry, dict) or "profile_delete" not in registry:
        raise ErasureGuardError("PROFILE_ERASURE_GUARD_CATALOG_UNAVAILABLE")
    tool = registry["profile_delete"]
    original = getattr(tool, "fn", None)
    if not callable(original) or not getattr(tool, "is_async", False):
        raise ErasureGuardError("PROFILE_ERASURE_GUARD_CONTRACT_MISMATCH")
    if not inspect.iscoroutinefunction(original):
        raise ErasureGuardError("PROFILE_ERASURE_GUARD_FUNCTION_MISMATCH")

    async def refuse_unsafe_erase(*_args: Any, **_kwargs: Any) -> Any:
        try:
            from mcp.server.mcpserver.exceptions import ToolError
        except ImportError:
            raise ErasureGuardError(ERROR) from None
        raise ToolError(ERROR)

    # Assignment is the only intentional side effect; no profile records
    # are read or mutated, no Steel endpoint is contacted.
    tool.fn = refuse_unsafe_erase
    namespace["_AIB_PROFILE_ERASURE_GUARD"] = FIX
    print("AI_BROWSER_PROFILE_ERASURE_GUARD_READY", FIX, flush=True)
