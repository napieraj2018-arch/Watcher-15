import json
import tempfile
import unittest
from pathlib import Path

from src.facebook_group_access_probe import (
    group_id, group_access_status, joined_private_group,
    login_shell, post_reference, sources_from_config, unique_group_posts,
)


class GroupAccessTests(unittest.TestCase):
    def test_links_are_scoped_to_exact_group(self):
        links = [
            {"href": "https://www.facebook.com/groups/1886172518407420/posts/123/?tracking=1"},
            {"href": "https://m.facebook.com/groups/1886172518407420/posts/123/"},
            {"href": "https://www.facebook.com/groups/158171638326502/posts/999/"},
            {"href": "https://www.facebook.com/groups/1886172518407420/permalink/456/"},
            {"href": "https://steal.example/groups/1886172518407420/posts/123/"},
        ]
        refs = unique_group_posts(links, "1886172518407420")
        self.assertEqual(refs, [
            "https://www.facebook.com/groups/1886172518407420/posts/123",
            "https://www.facebook.com/groups/1886172518407420/permalink/456",
        ])

    def test_bad_group_id_is_rejected(self):
        self.assertRaises(ValueError, group_id, {
            "url": "https://attacker.example/groups/123/"
        })
        self.assertRaises(ValueError, group_id, {
            "url": "https://www.facebook.com/share/g/abcd/"
        })

    def test_strict_canonical_group(self):
        self.assertEqual(group_id({
            "url": "https://www.facebook.com/groups/3046642772082014/"
        }), "3046642772082014")

    def test_login_shell_for_polish_and_english(self):
        self.assertTrue(login_shell(
            "https://www.facebook.com/",
            "Log into Facebook Email or mobile number Password Log in Forgot password"
        ))
        self.assertTrue(login_shell(
            "https://www.facebook.com/",
            "Log in to Facebook Email address or mobile number Password"
        ))
        self.assertTrue(login_shell(
            "https://www.facebook.com/login/?next=/groups/123",
            ""
        ))
        self.assertTrue(login_shell(
            "https://www.facebook.com/",
            "Zaloguj się do Facebooka Numer telefonu Hasło"
        ))

    def test_signed_in_home_is_not_login(self):
        self.assertFalse(login_shell(
            "https://www.facebook.com/",
            "Strona główna, Grupy, Powiadomienia, Messenger"
        ))

    def test_private_join_requires_membership(self):
        self.assertFalse(joined_private_group(
            "PORADY WETERYNARYJNE Private group Join group Discussion"
        ))
        self.assertFalse(joined_private_group(
            "Grupa prywatna Dołącz do grupy O grupie"
        ))
        self.assertTrue(joined_private_group(
            "Private group Discussion New posts Joined Notifications"
        ))

    def test_private_without_member_access_remains_unread(self):
        state, n = group_access_status(
            canonical_url="https://www.facebook.com/groups/3046642772082014/",
            final_url="https://www.facebook.com/groups/3046642772082014/",
            visible_text="Private group Join group",
            links=[{"href": "https://www.facebook.com/groups/3046642772082014/posts/444/"}],
            is_private=True, logged_in=True, expected_group_id="3046642772082014",
        )
        self.assertEqual((state, n), ("membership_required", 0))

    def test_private_not_read_without_authentication(self):
        state, n = group_access_status(
            canonical_url="https://www.facebook.com/groups/3046642772082014/",
            final_url="https://www.facebook.com/groups/3046642772082014/",
            visible_text="Private group",
            links=[{"href": "https://www.facebook.com/groups/3046642772082014/posts/444/"}],
            is_private=True, logged_in=False, expected_group_id="3046642772082014",
        )
        self.assertEqual((state, n), ("authentication_required", 0))

    def test_no_post_links_does_not_count_as_coverage(self):
        state, n = group_access_status(
            canonical_url="https://www.facebook.com/groups/158171638326502/",
            final_url="https://www.facebook.com/groups/158171638326502/",
            visible_text="RADOM-OGŁOSZENIA Public group 63K members",
            links=[], is_private=False, logged_in=True, expected_group_id="158171638326502",
        )
        self.assertEqual((state, n), ("no_visible_post_links", 0))

    def test_group_post_count_works_if_signed_in(self):
        state, n = group_access_status(
            canonical_url="https://www.facebook.com/groups/158171638326502/",
            final_url="https://www.facebook.com/groups/158171638326502/",
            visible_text="RADOM-OGŁOSZENIA Public group recent posts",
            links=[
                {"href": "https://www.facebook.com/groups/158171638326502/posts/111/"},
                {"href": "https://www.facebook.com/groups/158171638326502/posts/222/"},
            ],
            is_private=False, logged_in=True, expected_group_id="158171638326502",
        )
        self.assertEqual((state, n), ("public_or_member_visible", 2))

    def test_four_group_sources_are_unique(self):
        src = [
            {"id": "a", "name": "Spotted Radom", "type": "facebook_group",
             "url": "https://www.facebook.com/groups/1886172518407420/"},
            {"id": "b", "name": "RADOM-OGŁOSZENIA", "type": "facebook_group",
             "url": "https://www.facebook.com/groups/158171638326502/"},
            {"id": "c", "name": "PORADY WETERYNARYJNE (prywatna)", "type": "facebook_group",
             "url": "https://www.facebook.com/groups/3046642772082014/"},
            {"id": "d", "name": "Buldog Francuski Polska (prywatna)", "type": "facebook_group",
             "url": "https://www.facebook.com/groups/1756386991256822/"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "fb.json"
            file.write_text(json.dumps({"sources": src}), "utf-8")
            res = sources_from_config(file)
            self.assertEqual(len(res), 4)
            self.assertEqual([s["private"] for s in res], [False, False, True, True])


if __name__ == "__main__":
    unittest.main()
