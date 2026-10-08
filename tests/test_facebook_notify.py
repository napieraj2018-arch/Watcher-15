import unittest
from unittest.mock import patch, call

from src import facebook_notify


class GitHubNotificationsTests(unittest.TestCase):
    def sample(self):
        return [{
            "source": "Spotted Radom",
            "category": "ARCHITEKT",
            "text": "Prywatny cytat i nazwisko, którego nie wolno publikować w Issue",
            "url": "https://www.facebook.com/SomePage/posts/123?fbclid=tracking",
        }]

    def test_requires_opt_in_even_with_token(self):
        with patch.dict("os.environ", {
            "GITHUB_TOKEN": "secret", "GITHUB_REPOSITORY": "napieraj2018-arch/Watcher-15",
            "FB_GITHUB_ISSUE_ALERTS": "false",
        }), patch.object(facebook_notify, "request_json") as request:
            self.assertFalse(facebook_notify.notify_via_github(self.sample()))
            request.assert_not_called()

    def test_open_issue_without_personal_excerpt(self):
        responses = [[], {"number": 71}]
        with patch.dict("os.environ", {
            "GITHUB_TOKEN": "secret", "GITHUB_REPOSITORY": "napieraj2018-arch/Watcher-15",
            "FB_GITHUB_ISSUE_ALERTS": "true",
        }), patch.object(facebook_notify, "request_json", side_effect=responses) as request:
            self.assertTrue(facebook_notify.notify_via_github(self.sample()))
            self.assertEqual(request.call_count, 2)
            payload = request.call_args.args[3]
            self.assertIn("https://www.facebook.com/SomePage/posts/123", payload["body"])
            self.assertNotIn("Prywatny cytat", payload["body"])
            self.assertNotIn("fbclid=", payload["body"])
            self.assertEqual(payload["assignees"], ["napieraj2018-arch"])

    def test_existing_issue_prevents_duplicate(self):
        fingerprint = facebook_notify.digest("https://www.facebook.com/SomePage/posts/123")
        issue = {"body": "<!-- fbwatch:" + fingerprint + " -->"}
        with patch.dict("os.environ", {
            "GITHUB_TOKEN": "secret", "GITHUB_REPOSITORY": "napieraj2018-arch/Watcher-15",
            "FB_GITHUB_ISSUE_ALERTS": "true",
        }), patch.object(facebook_notify, "request_json", return_value=[issue]) as request:
            self.assertTrue(facebook_notify.notify_via_github(self.sample()))
            request.assert_called_once()

    def test_http_failure_does_not_report_success(self):
        with patch.dict("os.environ", {
            "GITHUB_TOKEN": "secret", "GITHUB_REPOSITORY": "napieraj2018-arch/Watcher-15",
            "FB_GITHUB_ISSUE_ALERTS": "true",
        }), patch.object(facebook_notify, "request_json", side_effect=TimeoutError()):
            self.assertFalse(facebook_notify.notify_via_github(self.sample()))


if __name__ == "__main__":
    unittest.main()
