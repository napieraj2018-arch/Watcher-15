"""Static production bootstrap checks. No encrypted payload or credentials."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]

class BootstrapHookTests(unittest.TestCase):
    def test_bootstrap_compiles(self):
        ast.parse((ROOT/"bootstrap.py").read_text(encoding="utf-8"))
    def test_guard_has_explicit_opt_in_and_is_off_by_default(self):
        text=(ROOT/"bootstrap.py").read_text(encoding="utf-8")
        self.assertIn('AI_BROWSER_SESSION_GUARD", "0"',text)
        self.assertIn('from capability_guard import install as _install_capability_guard',text)
        self.assertIn('_install_capability_guard(globals())',text)
    def test_guard_installed_after_error_reporting(self):
        text=(ROOT/"bootstrap.py").read_text(encoding="utf-8")
        self.assertLess(text.index('_install_error_reporting(globals())'),
                        text.index('_install_capability_guard(globals())'))
    def test_docker_contains_guard_but_production_flag_not_enabled(self):
        text=(ROOT/"Dockerfile").read_text(encoding="utf-8")
        self.assertIn("COPY session_ownership/capability_guard.py /app/capability_guard.py",text)
        self.assertIn("python -m unittest discover",text)
        self.assertNotIn("AI_BROWSER_SESSION_GUARD=1",text)
    def test_original_encrypted_payload_unchanged(self):
        text=(ROOT/"bootstrap.py").read_text(encoding="utf-8")
        self.assertIn("PAYLOAD_URL =",text)
        self.assertIn("REPAIR_SHA256 =",text)
        self.assertIn("AI_BROWSER_PROFILE_STORE_URL",text)

if __name__=="__main__":
    unittest.main(verbosity=2)
