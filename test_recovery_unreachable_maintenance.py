"""Fail-closed recovery on BOTH vault HTTP 429 and an unreachable vault.

Tests never connect to a real Steel/Floot service or touch real profile state.
"""
from __future__ import annotations
import ast
import io
import sys
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from threading import Thread
from unittest.mock import patch
import httpx

from provider_recovery_gate import RecoveryRateLimited
from recovery_boot_maintenance import (
    REASON, REASON_UNAVAILABLE, _Server, _MaintenanceHandler,
    wait_until_recovered
)


def _bootstrap_recovery_try():
    tree = ast.parse(Path(__file__).with_name("bootstrap.py").read_text(
        encoding="utf-8"), filename="bootstrap.py")
    recovery = [
        node for node in tree.body if isinstance(node, ast.Try)
        and len(node.body) == 1 and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Call)
        and isinstance(node.body[0].value.func, ast.Name)
        and node.body[0].value.func.id == "run_boot_gate"
    ]
    assert len(recovery) == 1, "expected one exact boot recovery try"
    return recovery[0]


def _run_recovery_fragment(raised):
    calls = []
    module = types.ModuleType("recovery_boot_maintenance")
    module.REASON_UNAVAILABLE = REASON_UNAVAILABLE
    module.wait_until_recovered = lambda gate, provider, **kw: calls.append(kw)
    module.verify_provider_idle = lambda key: True

    def gate():
        raise raised

    code = compile(
        ast.fix_missing_locations(ast.Module(
            body=[_bootstrap_recovery_try()], type_ignores=[])),
        "boot-recovery-only", "exec"
    )
    env = {
        "__name__": "test",
        "run_boot_gate": gate,
        "RecoveryRateLimited": RecoveryRateLimited,
        "os": types.SimpleNamespace(environ={
            "AI_BROWSER_HOST": "127.0.0.1",
            "AI_BROWSER_PORT": "10000",
            "STEEL_API_KEY": "SYNTHETIC_DO_NOT_USE"
        })
    }
    with patch.dict(sys.modules, {"recovery_boot_maintenance": module}):
        exec(code, env)
    return calls


class UnreachableVaultMaintenanceTests(unittest.TestCase):
    def test_429_remains_rate_limited_with_original_retry_after(self):
        calls = _run_recovery_fragment(RecoveryRateLimited(3600))
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["initial_retry_seconds"], 3600)
        self.assertNotIn("reason", calls[0])
        self.assertEqual(calls[0]["port"], 10000)

    def test_unreachable_recovery_gate_enters_maintenance_not_crash_loop(self):
        calls = _run_recovery_fragment(
            RuntimeError("AI_BROWSER_RECOVERY_GATE_BLOCKED"))
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["reason"], REASON_UNAVAILABLE)
        self.assertEqual(calls[0]["initial_retry_seconds"], 900)
        self.assertEqual(calls[0]["host"], "127.0.0.1")
        self.assertEqual(calls[0]["port"], 10000)

    def test_other_boot_errors_are_not_silently_treated_as_recovery(self):
        for message in ["AI_BROWSER_MASTER_KEY missing",
                        "STEEL_API_KEY_invalid", "unexpected"]:
            with self.subTest(message=message):
                with self.assertRaisesRegex(RuntimeError, message):
                    _run_recovery_fragment(RuntimeError(message))

    def test_unavailable_mode_refuses_all_browser_and_owner_routes(self):
        srv = _Server(("127.0.0.1", 0), _MaintenanceHandler)
        srv.recovery_reason = REASON_UNAVAILABLE
        thread = Thread(target=srv.serve_forever, daemon=True)
        thread.start()
        root = f"http://127.0.0.1:{srv.server_port}"
        try:
            with httpx.Client(trust_env=False, timeout=5) as client:
                health = client.get(root + "/health")
                self.assertEqual(health.status_code, 200)
                self.assertEqual(health.json()["status"], "degraded")
                self.assertIs(health.json()["browser_available"], False)
                self.assertIs(health.json()["recovery_confirmed"], False)
                self.assertEqual(health.json()["error"], REASON_UNAVAILABLE)
                self.assertEqual(health.headers.get("cache-control"), "no-store")
                home = client.get(root + "/")
                self.assertIn("tryb ochronny", home.text)
                self.assertIn("niedostępny", home.text)
                for route in (
                    "/mcp/browser_start",
                    "/owner-mobile/login",
                    "/_api/task-vault",
                    "/_api/profile-vault?token=SYNTHETIC_PASSWORD",
                ):
                    with self.subTest(route=route):
                        out = client.post(root + route, json={
                            "password": "SYNTHETIC_PASSWORD"})
                        self.assertEqual(out.status_code, 503)
                        self.assertEqual(out.json()["error"], REASON_UNAVAILABLE)
                        self.assertIs(out.json()["browser_available"], False)
                        self.assertNotIn("SYNTHETIC_PASSWORD", out.text)
        finally:
            srv.shutdown()
            srv.server_close()
            thread.join(timeout=3)

    def test_unreachable_mode_waits_for_both_independent_checks(self):
        attempts, providers, sleeps = [], [], []

        class FakeServer:
            def serve_forever(self): pass
            def shutdown(self): pass
            def server_close(self): pass

        def gate():
            attempts.append(True)
            if len(attempts) < 3:
                raise RuntimeError("PRIVATE_CONNECTION_ERROR_DO_NOT_PRINT")

        def provider():
            providers.append(True)
            return len(providers) > 1

        with redirect_stdout(io.StringIO()) as captured:
            wait_until_recovered(
                gate, provider, reason=REASON_UNAVAILABLE,
                port=10000, retry_seconds=900,
                sleeper=sleeps.append,
                server_factory=lambda *_: FakeServer()
            )
        self.assertEqual(len(attempts), 4)
        self.assertEqual(len(providers), 2)
        self.assertEqual(sleeps, [900, 900, 900, 900])
        output = captured.getvalue()
        self.assertIn("MAINTENANCE_ENTER " + REASON_UNAVAILABLE, output)
        self.assertIn("MAINTENANCE_CLEAR VERIFIED_FRESH_AND_PROVIDER_IDLE", output)
        self.assertNotIn("PRIVATE_CONNECTION_ERROR_DO_NOT_PRINT", output)

    def test_unrecognized_maintenance_reason_refused_before_listener(self):
        with self.assertRaisesRegex(RuntimeError, "RECOVERY_MAINTENANCE_CONFIG_INVALID"):
            wait_until_recovered(lambda: True, lambda: True,
                                 reason="PRIVATE_DO_NOT_LOG", port=10000,
                                 server_factory=lambda *_: None)


if __name__ == "__main__":
    unittest.main(verbosity=2)
