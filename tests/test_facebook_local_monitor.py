import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import facebook_local_monitor as watch


class WatcherUnitTests(unittest.TestCase):
    def test_architect_lead(self):
        domain, score = watch.classify("Szukam architekta do podziału mieszkania na dwa lokale.")
        self.assertEqual(domain, "ARCHITEKT")
        self.assertGreaterEqual(score, 4)

    def test_vet_lead(self):
        domain, score = watch.classify("Poleci mi ktoś weterynarza do szczepienia szczeniaka?")
        self.assertEqual(domain, "WETERYNARZ")
        self.assertGreaterEqual(score, 4)

    def test_no_intent_is_not_lead(self):
        domain, _ = watch.classify("Mój pies biega po parku codziennie.")
        self.assertIsNone(domain)

    def test_irrelevant(self):
        domain, score = watch.classify("Sprzedam wózek dziecięcy, odbiór w Radomiu.")
        self.assertIsNone(domain)
        self.assertEqual(score, 0)

    def test_canonical_group_post(self):
        link = watch.canonical_link(
            "https://m.facebook.com/groups/123/posts/456/?fbclid=tracking",
            "https://www.facebook.com/groups/123/"
        )
        self.assertEqual(link, "https://www.facebook.com/groups/123/posts/456")

    def test_canonical_story(self):
        link = watch.canonical_link(
            "/story.php?fbclid=tracking&story_fbid=123&id=456",
            "https://www.facebook.com/somepage/"
        )
        self.assertEqual(
            link, "https://www.facebook.com/story.php?id=456&story_fbid=123")


    def test_permalink_php_with_pfbid(self):
        link = watch.canonical_link(
            "https://www.facebook.com/permalink.php?story_fbid=pfbid0ABC&id=100044524445707&comment_id=123",
            "https://www.facebook.com/p/Spotted-RADOM-100044524445707/"
        )
        self.assertEqual(link, "https://www.facebook.com/permalink.php?id=100044524445707&story_fbid=pfbid0ABC")

    def test_post_timestamp_vs_intro_link(self):
        self.assertTrue(watch.is_time_label("14h"))
        self.assertTrue(watch.is_time_label("14 godz."))
        self.assertTrue(watch.is_time_label("1 dzień"))
        self.assertTrue(watch.is_time_label("20 minut"))
        self.assertTrue(watch.is_time_label("1d"))
        self.assertTrue(watch.is_time_label("a day ago"))
        self.assertTrue(watch.is_time_label("Oct 8"))
        self.assertFalse(watch.is_time_label("https://www.facebook.com/permalink.php?story_fbid=123"))
        self.assertFalse(watch.is_time_label("Reels"))
        self.assertFalse(watch.is_time_label(""))

    def test_recent_post_age(self):
        self.assertEqual(watch.age_minutes("14 godz."), 840)
        self.assertEqual(watch.age_minutes("1 dzień"), 1440)
        self.assertEqual(watch.age_minutes("15 min"), 15)
        self.assertEqual(watch.age_minutes("2h"), 120)
        self.assertEqual(watch.age_minutes("a minute ago"), 1)
        self.assertEqual(watch.age_minutes("an hour ago"), 60)
        self.assertEqual(watch.age_minutes("a week ago"), 10080)

        self.assertEqual(watch.age_minutes("wczoraj"), 1440)
        self.assertIsNone(watch.age_minutes("Oct 8"))

    def test_missing_story_id(self):
        self.assertIsNone(watch.canonical_link(
            "/story.php?fbclid=tracking", "https://www.facebook.com/page"))

    def test_external_domains_rejected(self):
        self.assertIsNone(watch.canonical_link(
            "https://malicious.example/posts/123", "https://www.facebook.com/"))

    def test_link_digest_deterministic(self):
        a = "https://www.facebook.com/groups/123/posts/456"
        self.assertEqual(watch.digest(a), watch.digest(a))
        self.assertEqual(len(watch.digest(a)), 64)

    def test_new_state_is_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(watch, "STATE", Path(directory) / "data.json"):
                hashes, first = watch.load_state()
                self.assertTrue(first)
                self.assertEqual(hashes, set())
                watch.save_state({"abc", "def"})
                seen, first = watch.load_state()
                self.assertFalse(first)
                self.assertEqual(seen, {"abc", "def"})
                contents = json.loads(watch.STATE.read_text())
                self.assertEqual(contents["version"], 1)

    def test_corrupt_state_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "data.json"
            file.write_text("not json", encoding="utf-8")
            with patch.object(watch, "STATE", file):
                with self.assertRaises(RuntimeError):
                    watch.load_state()


if __name__ == "__main__":
    unittest.main()
