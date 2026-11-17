"""Run against the real runtime/router in the deployment image; no real accounts."""
import ast
import asyncio
import base64
import json
import os
import secrets
import unittest

os.environ.setdefault("AIB_FRESH_DATABASE_URL", "postgresql://fixture.invalid/db")
os.environ.setdefault("AIB_FRESH_ADMIN_TOKEN", secrets.token_urlsafe(40))
os.environ.setdefault("AIB_FRESH_MCP_TOKEN", secrets.token_urlsafe(40))
os.environ.setdefault("AIB_FRESH_DATA_KEY", base64.b64encode(secrets.token_bytes(32)).decode())

import admission_runtime
import server
from command_admission import CommandLock, bounded_entry
from fastapi import HTTPException


class Request:
    def __init__(self, action, authorized=True):
        self.headers = {"authorization": "Bearer " + server.MCP_TOKEN} if authorized else {}
        self.msg = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
            "name": "fresh_browser", "arguments": {"action": action, "name": "synthetic-admission-test"}}}

    async def json(self): return self.msg


class RealRuntime(unittest.IsolatedAsyncioTestCase):
    async def test_01_status_from_real_mcp_has_new_capability_and_no_open(self):
        before = server.workspace.context
        response = await server.mcp(Request("runtime_status"))
        self.assertNotIn("isError", response["result"])
        data = json.loads(response["result"]["content"][0]["text"])
        self.assertEqual(data["version"], "2.0.3")
        self.assertIn("wordpress_rest", data["capabilities"])
        self.assertIn("wordpress_css_patch", data["capabilities"])
        self.assertEqual(data["command_admission"]["lock_wait_timeout_seconds"], 5)
        self.assertFalse(data["command_admission"]["replays_commands"])
        self.assertIs(server.workspace.context, before)

    async def test_02_busy_real_save_is_error_not_late_queued_action(self):
        lock = server.workspace.lock
        self.assertIsInstance(lock, CommandLock)
        await lock.acquire()
        try:
            response = await bounded_entry(server.mcp, .03)(Request("save"))
            self.assertTrue(response["result"]["isError"])
            detail = ast.literal_eval(response["result"]["content"][0]["text"])
            self.assertEqual(detail["code"], "browser_busy_before_start")
            self.assertEqual(detail["outcome"], "not_started")
            self.assertFalse(detail["queued"])
        finally:
            lock.release()
        await asyncio.sleep(.05)
        self.assertIsNone(server.workspace.context)
        self.assertEqual(lock.waiting_commands, 0)

    async def test_03_missing_mcp_authorization_still_rejected(self):
        with self.assertRaises(HTTPException) as cm:
            await server.mcp(Request("runtime_status", authorized=False))
        self.assertEqual(cm.exception.status_code, 401)
        self.assertIsNone(server.workspace.context)

    async def test_04_status_works_while_real_workspace_lock_is_held(self):
        await server.workspace.lock.acquire()
        try:
            response = await server.mcp(Request("runtime_status"))
            data = json.loads(response["result"]["content"][0]["text"])
            self.assertTrue(data["busy"])
        finally:
            server.workspace.lock.release()


if __name__ == "__main__": unittest.main()
