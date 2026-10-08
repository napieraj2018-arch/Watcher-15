"""Experimental MCP legacy-tool interlock, NOT installed in production.

This cutover mode denies existing browser-control tools once the replacement
capability-bound task API is deployed and connected. Missing or unknown tools
fail closed before any modification. ASGI routes and direct manager calls still
need a separate guard: tool wrapping alone is NOT complete session isolation.
"""
from __future__ import annotations
import inspect
from functools import wraps
from typing import Any, Mapping

LEGACY_TOOLS = frozenset("""
profile_list profile_start_setup profile_cancel_setup browser_start
profile_login_window browser_sessions browser_status browser_set_mode
browser_stop browser_navigate browser_snapshot browser_set_checked
browser_scroll browser_hover browser_scroll_into_view browser_screenshot
browser_back browser_forward browser_reload browser_wait_for_text
browser_wait_for_url browser_links browser_wait browser_click browser_fill
browser_press browser_select browser_tabs browser_new_tab browser_switch_tab
browser_close_tab browser_downloads browser_read_download_text
browser_upload_file profile_flush browser_network_log browser_console_log
browser_clear_diagnostics browser_page_metadata browser_set_viewport
browser_frames browser_frame_snapshot browser_set_next_dialog_action
browser_dialogs browser_staged_files browser_upload_staged_file
browser_read_download_pdf browser_recent_audit profile_delete
""".split())
READ_ONLY_PUBLIC = frozenset({"profile_list","browser_sessions","browser_recent_audit"})
REQUIRED = frozenset({"browser_start","browser_set_mode","browser_stop",
                      "browser_click","browser_fill","browser_navigate",
                      "browser_snapshot","profile_start_setup","profile_delete"})

class LegacyInterlockError(RuntimeError):
    """Fixed error code only; never reveal target URL or client data."""

class LegacyToolInterlock:
    """Works on a Tool registry exposing tool.fn + tool.is_async."""

    def __init__(self, registry: Mapping[str, Any], *, error_type=LegacyInterlockError):
        self.registry=registry
        self.error_type=error_type
        self._original={}

    def install(self) -> int:
        if self._original:
            raise LegacyInterlockError("LEGACY_INTERLOCK_ALREADY_INSTALLED")
        names=set(self.registry)
        if not REQUIRED <= names:
            raise LegacyInterlockError("LEGACY_CATALOG_INCOMPLETE")
        unknown={n for n in names if (n.startswith("browser_") or n.startswith("profile_"))
                 and n not in LEGACY_TOOLS}
        if unknown:
            raise LegacyInterlockError("LEGACY_CATALOG_CHANGED_REVIEW_REQUIRED")
        changed=[]
        try:
            for name in sorted(LEGACY_TOOLS & names):
                if name in READ_ONLY_PUBLIC:
                    continue
                tool=self.registry[name]
                old=tool.fn
                if getattr(tool,"is_async",inspect.iscoroutinefunction(old)):
                    @wraps(old)
                    async def deny_async(*args,**kwargs):
                        raise self.error_type("LEGACY_BROWSER_API_DISABLED_USE_OWNED_TASK")
                    replacement=deny_async
                else:
                    @wraps(old)
                    def deny_sync(*args,**kwargs):
                        raise self.error_type("LEGACY_BROWSER_API_DISABLED_USE_OWNED_TASK")
                    replacement=deny_sync
                tool.fn=replacement
                self._original[name]=old
                changed.append(name)
            return len(changed)
        except Exception:
            for name in reversed(changed):
                self.registry[name].fn=self._original[name]
            self._original.clear()
            raise LegacyInterlockError("LEGACY_INTERLOCK_INSTALL_FAILED") from None

    def restore_for_tests_only(self) -> None:
        for name,old in self._original.items():
            self.registry[name].fn=old
        self._original.clear()
