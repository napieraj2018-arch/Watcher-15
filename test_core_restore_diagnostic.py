import contextlib
import io
import json
import unittest
from unittest.mock import patch

from core_restore_diagnostic import describe, emit


class FixtureManager:
    async def navigate(self, url="synthetic-private-default"):
        """synthetic-private-docstring"""
        script = "localStorage.setItem('synthetic-private-key', 'synthetic-private-value')"
        await self.context.add_init_script(script)
        await self._restore_storage()

    async def _restore_storage(self):
        return {"synthetic-private-key": "synthetic-private-value", "number": 123456789}

    async def unrelated(self):
        return "synthetic-unrelated-private"


class DiagnosticPrivacy(unittest.TestCase):
    def test_only_class_flow_not_runtime_values(self):
        rows = describe(FixtureManager)
        output = json.dumps(rows)
        for private in ("synthetic-private", "synthetic-unrelated-private", "123456789"):
            self.assertNotIn(private, output)
        self.assertEqual([r["method"] for r in rows], ["navigate", "_restore_storage"])
        self.assertTrue(rows[0]["flags"]["localStorage"])
        self.assertIn("self._restore_storage", rows[0]["flow"])

    def test_errors_are_fixed_and_do_not_leak_exception(self):
        output = io.StringIO()
        with patch("core_restore_diagnostic.inspect.getsource", side_effect=ValueError("synthetic-private")):
            with contextlib.redirect_stdout(output):
                emit(FixtureManager())
        self.assertNotIn("synthetic-private", output.getvalue())
        self.assertIn("inspection_unavailable", output.getvalue())

    def test_oversized_source_is_not_partially_exported(self):
        source = "class Huge:\n def navigate(self):\n" + "  self.some_call()\n" * 1000
        with patch("core_restore_diagnostic.inspect.getsource", return_value=source):
            self.assertEqual(describe(FixtureManager), [{"status": "source_exceeds_bound"}])

    def test_callable_wrapper_chain_never_exports_private_closure(self):
        manager = FixtureManager()
        original = manager.navigate
        private = {"cookie": "synthetic-private-runtime-value"}
        async def wrapped(url):
            if private:
                return await original(url)
        manager.navigate = wrapped
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            emit(manager)
        value = output.getvalue()
        self.assertNotIn("synthetic-private", value)
        self.assertIn("navigate.original", value)


if __name__ == "__main__":
    unittest.main()
