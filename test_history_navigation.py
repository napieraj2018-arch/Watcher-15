"""Offline history adapter regressions; no provider, browser or account I/O."""
from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace
import unittest

from history_navigation import install_context_history


class Page:
    def __init__(self):
        self.calls = []
        self.response = object()
        self.failure = None

    async def _navigate(self, name, **kwargs):
        self.calls.append((name, kwargs))
        if self.failure is not None:
            raise self.failure
        return self.response

    async def go_back(self, **kwargs):
        return await self._navigate("back", **kwargs)

    async def go_forward(self, **kwargs):
        return await self._navigate("forward", **kwargs)

    async def goto(self, **kwargs):
        return await self._navigate("goto", **kwargs)

    async def reload(self, **kwargs):
        return await self._navigate("reload", **kwargs)


class Context:
    def __init__(self, *pages):
        self.pages = list(pages)
        self.handlers = {}

    def on(self, event, handler):
        self.handlers.setdefault(event, []).append(handler)

    def add_page(self, page):
        self.pages.append(page)
        for handler in self.handlers.get("page", []):
            handler(page)

    async def set_storage_state(self, state):
        raise AssertionError("No profile mutation expected")


class HistoryNavigationTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_and_future_pages_use_commit_once(self):
        existing, future = Page(), Page()
        context = Context(existing)
        install_context_history(context)
        context.add_page(future)
        self.assertFalse(inspect.iscoroutinefunction(context.handlers["page"][0]))
        for page in (existing, future):
            for name in ("go_back", "go_forward"):
                reply = await getattr(page, name)(wait_until="domcontentloaded", timeout=1234)
                self.assertIs(reply, page.response)
            self.assertEqual(page.calls, [
                ("back", {"wait_until": "commit", "timeout": 1234}),
                ("forward", {"wait_until": "commit", "timeout": 1234}),
            ])

    async def test_default_and_explicit_wait_modes_do_not_extend_timeout(self):
        page = Page()
        install_context_history(Context(page))
        await page.go_back()
        for value in (None, "load", "domcontentloaded", "networkidle", "commit"):
            await page.go_forward(wait_until=value, timeout=0)
        self.assertEqual(page.calls[0], ("back", {"wait_until": "commit"}))
        self.assertEqual(page.calls[1:], [
            ("forward", {"wait_until": "commit", "timeout": 0})
        ] * 5)

    async def test_no_history_none_response_is_preserved(self):
        page = Page()
        page.response = None
        install_context_history(Context(page))
        self.assertIsNone(await page.go_back(timeout=500))
        self.assertEqual(len(page.calls), 1)

    async def test_timeout_and_unexpected_error_are_not_masked_or_retried(self):
        page = Page()
        install_context_history(Context(page))
        for failure in (TimeoutError("synthetic timeout"), RuntimeError("synthetic failure")):
            page.failure = failure
            with self.assertRaises(type(failure)) as caught:
                await page.go_forward(timeout=500)
            self.assertIs(caught.exception, failure)
        self.assertEqual(len(page.calls), 2)

    async def test_cancellation_reaches_original_without_retry(self):
        page = Page()
        started = asyncio.Event()
        cancelled = asyncio.Event()
        calls = []

        async def pending(**kwargs):
            calls.append(kwargs)
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        page.go_back = pending
        install_context_history(Context(page))
        task = asyncio.create_task(page.go_back(timeout=700))
        await asyncio.wait_for(started.wait(), 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(cancelled.is_set())
        self.assertEqual(calls, [{"timeout": 700, "wait_until": "commit"}])

    async def test_repeated_install_and_duplicate_page_event_are_idempotent(self):
        page = Page()
        context = Context(page)
        install_context_history(context)
        back, forward = page.go_back, page.go_forward
        install_context_history(context)
        context.handlers["page"][0](page)
        self.assertIs(page.go_back, back)
        self.assertIs(page.go_forward, forward)
        self.assertEqual(len(context.handlers["page"]), 1)
        await page.go_back(timeout=200)
        self.assertEqual(len(page.calls), 1)

    async def test_other_context_and_non_history_methods_are_unchanged(self):
        owned, other = Page(), Page()
        original_class_back = Page.go_back
        original_goto, original_reload = owned.goto, owned.reload
        install_context_history(Context(owned))
        self.assertIs(Page.go_back, original_class_back)
        self.assertEqual(owned.goto, original_goto)
        self.assertEqual(owned.reload, original_reload)
        await other.go_back(wait_until="load", timeout=333)
        await owned.goto(wait_until="domcontentloaded", timeout=444)
        await owned.reload(wait_until="domcontentloaded", timeout=555)
        self.assertEqual(other.calls, [("back", {"wait_until": "load", "timeout": 333})])
        self.assertEqual(owned.calls, [
            ("goto", {"wait_until": "domcontentloaded", "timeout": 444}),
            ("reload", {"wait_until": "domcontentloaded", "timeout": 555}),
        ])

    async def test_native_context_installs_hook_without_replacing_context(self):
        from steel_context_fix import native_context
        existing, future = Page(), Page()
        context = Context(existing)
        other_context = Context(Page())
        remote = SimpleNamespace(
            browser=SimpleNamespace(contexts=[context, other_context]),
            engine=SimpleNamespace(_native_bindings={}), remote_id="synthetic")
        self.assertIs(await native_context(remote), context)
        context.add_page(future)
        await existing.go_back(wait_until="load")
        await future.go_forward(wait_until="domcontentloaded")
        self.assertEqual(existing.calls, [("back", {"wait_until": "commit"})])
        self.assertEqual(future.calls, [("forward", {"wait_until": "commit"})])
        self.assertFalse(other_context.handlers)


if __name__ == "__main__":
    unittest.main(verbosity=2)
