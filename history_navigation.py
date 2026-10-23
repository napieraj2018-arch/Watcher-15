"""History traversal for the provider's existing Chromium context.

Waiting for a fresh DOMContentLoaded/load event after history restoration can
time out after the navigation already happened. Match Playwright MCP's narrowly
scoped fix: acknowledge back/forward at commit, and leave document readiness to
the caller's next observation. See microsoft/playwright#41153.
"""
from __future__ import annotations

from functools import wraps


def _install_page_history(page):
    if getattr(page, "_aib_history_commit", False):
        return

    def wrap(original):
        @wraps(original)
        async def navigate(*args, **kwargs):
            kwargs["wait_until"] = "commit"
            return await original(*args, **kwargs)
        return navigate

    page.go_back = wrap(page.go_back)
    page.go_forward = wrap(page.go_forward)
    page._aib_history_commit = True


def install_context_history(context):
    """Patch only this context's current and future Python Page instances.

    Installation is synchronous, performs no navigation, and never changes the
    global Page class. Timeout, response, cancellation and genuine errors flow
    through the original bound method, which is invoked exactly once.
    """
    if getattr(context, "_aib_history_commit", False):
        return
    context.on("page", _install_page_history)
    for page in getattr(context, "pages", ()):
        _install_page_history(page)
    context._aib_history_commit = True
