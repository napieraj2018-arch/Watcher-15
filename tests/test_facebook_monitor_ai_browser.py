import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import facebook_monitor_ai_browser as adapter


class AI_BrowserAdapterTests(unittest.TestCase):
    def test_unwrap_text_mcp(self):
        class Text:
            text = '{"result":[{"name":"Meta - Maciej - Monitoring"}]}'
        class Result:
            isError = False
            structuredContent = None
            content = [Text()]
        result = adapter.unwrap(Result())
        self.assertEqual(adapter.as_items(result)[0]["name"],
                         "Meta - Maciej - Monitoring")

    def test_unwrap_error_fails_closed(self):
        class Result:
            isError = True
            structuredContent = None
            content = []
        with self.assertRaises(RuntimeError):
            adapter.unwrap(Result())

    def test_login_detected_by_url(self):
        self.assertTrue(adapter.is_login({
            "url": "https://www.facebook.com/two_step_verification/authentication/",
            "text": "",
        }))

    def test_login_detected_by_form_text(self):
        self.assertTrue(adapter.is_login({
            "url": "https://www.facebook.com/",
            "text": "Log into Facebook\nEmail or mobile number\nPassword",
        }))

    def test_legitimate_page_not_treated_as_login(self):
        self.assertFalse(adapter.is_login({
            "url": "https://www.facebook.com/p/example/",
            "text": "Posty na stronie i aktualności w Radomiu",
        }))

    def test_first_source_baseline_state(self):
        with tempfile.TemporaryDirectory() as temp:
            file = Path(temp) / "state.json"
            with patch.object(adapter, "STATE", file):
                seen, sources = adapter.load_remote_state()
                self.assertEqual((seen, sources), (set(), set()))
                adapter.save_remote_state({"hash1"}, {"spotted_radom"})
                seen, sources = adapter.load_remote_state()
                self.assertEqual(seen, {"hash1"})
                self.assertEqual(sources, {"spotted_radom"})

    def test_corrupt_state_no_silent_reset(self):
        with tempfile.TemporaryDirectory() as temp:
            file = Path(temp) / "state.json"
            file.write_text("{bad")
            with patch.object(adapter, "STATE", file):
                with self.assertRaises(RuntimeError):
                    adapter.load_remote_state()


if __name__ == "__main__":
    unittest.main()
