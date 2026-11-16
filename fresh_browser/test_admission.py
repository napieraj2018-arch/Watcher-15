"""Synthetic concurrency regression tests. No database, credentials or websites."""
import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from command_admission import CommandLock, bounded_entry, install_workspace


class FakeWorkspace:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.profile = "wordpress-klinika"
        self.human = False
        self.context = object()
        self.writes = []
        self.finished = 0

    async def action(self, args, automated=False, owner_context=None):
        if args.get("action") == "runtime_status":
            return {"version": "2.0.2", "commit": "synthetic", "busy": self.lock.locked(),
                    "capabilities": ["wordpress_rest"], "background_execution": False}
        async with self.lock:
            if automated and (self.human or args.get("name") != self.profile):
                raise HTTPException(409, "owner/profile protected")
            if owner_context is not None and owner_context is not self.context:
                raise HTTPException(409, "stale owner context")
            self.writes.append(args.get("value", "test"))
            if args.get("entered"): args["entered"].set()
            if args.get("release"): await args["release"].wait()
            if args.get("raise"): raise RuntimeError("original failure")
            self.finished += 1
            return {"ok": True}

    async def screenshot(self, name, owner_context=None, with_metadata=False):
        async with self.lock:
            if name != self.profile: raise HTTPException(409, "profile protected")
            return b"synthetic"

    async def tabs(self, name, owner_context=None):
        async with self.lock:
            if name != self.profile: raise HTTPException(409, "profile protected")
            return ["synthetic"]


class Admission(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.w = FakeWorkspace()
        self.lock = install_workspace(self.w, .03)

    async def test_busy_rejected_before_mutation_not_queued(self):
        await self.lock.acquire()
        try:
            with self.assertRaises(HTTPException) as cm:
                await self.w.action({"value": "must not execute"})
            self.assertEqual(cm.exception.status_code, 409)
            self.assertEqual(cm.exception.detail["outcome"], "not_started")
            self.assertFalse(cm.exception.detail["queued"])
            self.assertFalse(cm.exception.detail["automatic_retry_safe"])
            self.assertEqual(self.w.writes, [])
            self.assertEqual(self.lock.waiting_commands, 0)
        finally: self.lock.release()
        await asyncio.sleep(.05)
        self.assertEqual(self.w.writes, [])

    async def test_free_command_runs_once(self):
        self.assertEqual(await self.w.action({"value": "one"}), {"ok": True})
        self.assertEqual(self.w.writes, ["one"])
        self.assertFalse(self.lock.locked())

    async def test_release_within_budget_proceeds_once(self):
        await self.lock.acquire()
        task = asyncio.create_task(self.w.action({"value": "once"}))
        await asyncio.sleep(.005)
        self.assertEqual(self.lock.waiting_commands, 1)
        self.lock.release()
        await task
        self.assertEqual(self.w.writes, ["once"])

    async def test_started_command_not_cancelled_by_wait_budget(self):
        entered, release = asyncio.Event(), asyncio.Event()
        task = asyncio.create_task(self.w.action({"entered": entered, "release": release}))
        await entered.wait()
        await asyncio.sleep(.07)
        self.assertFalse(task.done())
        release.set()
        self.assertTrue((await task)["ok"])
        self.assertEqual(self.w.finished, 1)

    async def test_competing_command_rejected_active_continues(self):
        entered, release = asyncio.Event(), asyncio.Event()
        first = asyncio.create_task(self.w.action({"value": "first", "entered": entered, "release": release}))
        await entered.wait()
        with self.assertRaises(HTTPException): await self.w.action({"value": "second"})
        self.assertFalse(first.done())
        release.set()
        await first
        self.assertEqual(self.w.writes, ["first"])

    async def test_maintenance_wait_not_bounded(self):
        await self.lock.acquire()
        called = []
        async def maintenance():
            async with self.lock: called.append("saved")
        task = asyncio.create_task(maintenance())
        await asyncio.sleep(.07)
        self.assertFalse(task.done())
        self.lock.release()
        await task
        self.assertEqual(called, ["saved"])

    async def test_status_available_while_busy(self):
        await self.lock.acquire()
        try:
            result = await self.w.action({"action": "runtime_status"})
            self.assertTrue(result["busy"])
        finally: self.lock.release()

    async def test_screenshot_is_bounded(self):
        await self.lock.acquire()
        try:
            with self.assertRaises(HTTPException): await self.w.screenshot(self.w.profile)
        finally: self.lock.release()

    async def test_tabs_is_bounded(self):
        await self.lock.acquire()
        try:
            with self.assertRaises(HTTPException): await self.w.tabs(self.w.profile)
        finally: self.lock.release()

    async def test_owner_control_remains_protected(self):
        self.w.human = True
        with self.assertRaises(HTTPException):
            await self.w.action({"name": self.w.profile}, automated=True)
        self.assertEqual(self.w.writes, [])

    async def test_wrong_profile_remains_protected(self):
        with self.assertRaises(HTTPException):
            await self.w.action({"name": "unrelated"}, automated=True)
        self.assertEqual(self.w.writes, [])

    async def test_stale_owner_context_remains_protected(self):
        with self.assertRaises(HTTPException):
            await self.w.action({}, owner_context=object())
        self.assertEqual(self.w.writes, [])

    async def test_original_failure_not_replayed(self):
        with self.assertRaisesRegex(RuntimeError, "original failure"):
            await self.w.action({"raise": True, "value": "once"})
        self.assertEqual(self.w.writes, ["once"])
        self.assertFalse(self.lock.locked())

    async def test_cancelled_waiter_cannot_execute_later(self):
        await self.lock.acquire()
        task = asyncio.create_task(self.w.action({"value": "never"}))
        await asyncio.sleep(.005)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        self.lock.release()
        await asyncio.sleep(.05)
        self.assertEqual(self.w.writes, [])
        self.assertEqual(self.lock.waiting_commands, 0)

    async def test_budget_context_resets_after_failure(self):
        await self.lock.acquire()
        try:
            with self.assertRaises(HTTPException): await self.w.action({})
        finally: self.lock.release()
        # A later call receives a new attempt, not the previous timeout.
        await self.w.action({"value": "new"})
        self.assertEqual(self.w.writes, ["new"])

    async def test_later_critical_section_not_labelled_not_started(self):
        first_done, proceed, holder_ready, release_holder = [asyncio.Event() for _ in range(4)]
        async def holder():
            await first_done.wait()
            async with self.lock:
                holder_ready.set()
                await release_holder.wait()
        async def operation():
            async with self.lock: self.w.writes.append("started")
            first_done.set()
            await proceed.wait()
            async with self.lock: self.w.writes.append("finished")
        holding = asyncio.create_task(holder())
        task = asyncio.create_task(bounded_entry(operation, .03)())
        await holder_ready.wait()
        proceed.set()
        await asyncio.sleep(.07)
        self.assertFalse(task.done())
        release_holder.set()
        await holding
        await task
        self.assertEqual(self.w.writes, ["started", "finished"])

    async def test_duplicate_install_fails(self):
        with self.assertRaises(RuntimeError): install_workspace(self.w)

    async def test_busy_install_fails_without_change(self):
        w = FakeWorkspace()
        old_lock = w.lock
        await old_lock.acquire()
        try:
            with self.assertRaises(RuntimeError): install_workspace(w)
            self.assertIs(w.lock, old_lock)
        finally: old_lock.release()

    async def test_invalid_timeout_fails_without_change(self):
        for value in (0, -1, float("inf"), float("nan"), "5"):
            w = FakeWorkspace()
            old_lock = w.lock
            with self.assertRaises(ValueError): install_workspace(w, value)
            self.assertIs(w.lock, old_lock)

    async def test_all_expired_waiters_removed(self):
        await self.lock.acquire()
        result = await asyncio.gather(*(self.w.action({"value": str(i)}) for i in range(12)), return_exceptions=True)
        self.assertTrue(all(isinstance(r, HTTPException) for r in result))
        self.assertEqual(self.lock.waiting_commands, 0)
        self.lock.release()
        await self.w.action({"value": "fresh"})
        self.assertEqual(self.w.writes, ["fresh"])

    async def test_current_owner_request_still_allowed(self):
        self.assertTrue((await self.w.action({}, owner_context=self.w.context))["ok"])

    async def test_nested_entry_does_not_reset_started_state(self):
        async def outer():
            async with self.lock: self.w.writes.append("outer")
            return await self.w.action({"value": "inner"})
        self.assertTrue((await bounded_entry(outer, .03)())["ok"])
        self.assertEqual(self.w.writes, ["outer", "inner"])

    async def test_scope_does_not_change_an_independent_child_task(self):
        async def outer():
            async with self.lock:
                async def child():
                    async with self.lock: self.w.writes.append("maintenance")
                task = asyncio.create_task(child())
                await asyncio.sleep(.07)
                self.assertFalse(task.done())
            await task
        await bounded_entry(outer, .03)()
        self.assertEqual(self.w.writes, ["maintenance"])


class Entrypoint(unittest.IsolatedAsyncioTestCase):
    async def test_runtime_preserves_binding_and_original_capabilities(self):
        w = FakeWorkspace()
        server = types.ModuleType("server")
        server.workspace = w
        server.issue_owner_access = w.action
        previous = types.ModuleType("reliability_runtime")
        previous.app = object()
        path = Path(__file__).with_name("admission_runtime.py")
        spec = importlib.util.spec_from_file_location("admission_test_fixture", path)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"server": server, "reliability_runtime": previous}):
            spec.loader.exec_module(module)
            self.assertIs(module.app, previous.app)
            self.assertIs(server.workspace, w)
            result = await w.action({"action": "runtime_status"})
            self.assertEqual(result["version"], "2.0.3")
            self.assertEqual(result["commit"], "synthetic")
            self.assertEqual(result["capabilities"], ["wordpress_rest"])
            self.assertFalse(result["background_execution"])
            self.assertFalse(result["command_admission"]["replays_commands"])
            self.assertFalse(result["command_admission"]["cancels_started_commands"])
            self.assertEqual(result["command_admission"]["lock_wait_timeout_seconds"], 5)


if __name__ == "__main__": unittest.main()
