"""Only synthetic test vectors; never decrypt or load private vault archives."""
import copy
import json
import unittest

from r158_archive_provenance import (
    PROFILE, IndexedSelector, R158_SELECTOR, R158EvidenceError,
    compare_protected_candidate as check, compare_protected_batch as batch,
)

SELECT = R158_SELECTOR
SAVED = 1793048000.0
NOW = SAVED + 1000
SECRET = "SYNTHETIC_DO_NOT_PRINT_TEST_MARKER_zf7c8"


def fixture(value=SECRET):
    return {
        "cookies": [dict(name="aibrowser_test_cookie", domain="ai-browser-vault.floot.app",
                         path="/browser-check", value=value, expires=NOW + 5000,
                         secure=True, httpOnly=False)],
        "origins": [dict(origin="https://ai-browser-vault.floot.app",
                         localStorage=[dict(name="aibrowser_public_test_marker", value=value)],
                         indexedDB=[dict(name="aibrowser_neutral_check", stores=[dict(name="markers",
                         records=[dict(key="marker", value=value)])])])],
    }


def result(state, saved=SAVED, now=NOW):
    return check(profile=PROFILE, source_updated_at=saved,
                 decrypted_state=state, selector=SELECT, observed_at=now)


class ProtectedProvenance(unittest.TestCase):
    def test_exact_three_equal(self):
        p = result(fixture())
        self.assertTrue(p["coherent_at_source"])
        self.assertTrue(p["unique_exact_source"])
        self.assertTrue(p["cookie_valid_now"])
        self.assertFalse(p["live_saved_close_reopen_verified"])
        self.assertFalse(p["real_account_authenticated"])

    def test_all_present_but_mismatched_rejected(self):
        s = fixture()
        s["origins"][0]["indexedDB"][0]["stores"][0]["records"][0]["value"] = "old"
        p = result(s)
        self.assertTrue(all(p[k] for k in (
            "cookie_present", "local_storage_present", "indexed_db_present")))
        self.assertFalse(p["coherent_at_source"])

    def test_wrong_exact_profile_scope(self):
        with self.assertRaisesRegex(R158EvidenceError, "R158_PROFILE_SCOPE_DENIED"):
            check(profile="Meta - Anita", source_updated_at=SAVED,
                  decrypted_state=fixture(), selector=SELECT, observed_at=NOW)

    def test_duplicate_cookie_refused(self):
        s = fixture()
        s["cookies"].append(copy.deepcopy(s["cookies"][0]))
        self.assertFalse(result(s)["unique_exact_source"])

    def test_duplicate_indexed_record_refused(self):
        s = fixture()
        rows = s["origins"][0]["indexedDB"][0]["stores"][0]["records"]
        rows.append(copy.deepcopy(rows[0]))
        self.assertFalse(result(s)["coherent_at_source"])

    def test_different_origin_refused(self):
        s = fixture()
        s["origins"][0]["origin"] = "https://evil.test"
        self.assertFalse(result(s)["coherent_at_source"])

    def test_missing_idb_never_partial_pass(self):
        s = fixture()
        s["origins"][0].pop("indexedDB")
        self.assertFalse(result(s)["indexed_db_present"])
        self.assertFalse(result(s)["coherent_at_source"])

    def test_expired_since_archive_separate_current_check(self):
        s = fixture()
        s["cookies"][0]["expires"] = SAVED + 3
        p = result(s)
        self.assertTrue(p["coherent_at_source"])
        self.assertFalse(p["cookie_valid_now"])

    def test_protected_copy_timestamp_cannot_redefine_original_source_time(self):
        s = fixture()
        s["cookies"][0]["expires"] = SAVED + 3
        # Protected archive may be copied much later than original source write.
        proof = batch([dict(profile=PROFILE, source_updated_at=SAVED,
                            archived_at=NOW, protected=True, state=s)],
                      selector=SELECT, observed_at=NOW)
        self.assertEqual(proof["coherent_at_source_count"], 1)
        self.assertEqual(proof["currently_valid_coherent_count"], 0)

    def test_expired_before_archive_rejected(self):
        s = fixture()
        s["cookies"][0]["expires"] = SAVED - 1
        self.assertFalse(result(s)["coherent_at_source"])

    def test_session_cookie_cannot_prove_current_or_archive(self):
        s = fixture()
        s["cookies"][0]["expires"] = -1
        p = result(s)
        self.assertIsNone(p["cookie_valid_at_source"])
        self.assertIsNone(p["cookie_valid_now"])
        self.assertFalse(p["coherent_at_source"])

    def test_encoded_cookie_never_counts_exact(self):
        s = fixture("abc%2Bdef")
        s["origins"][0]["localStorage"][0]["value"] = "abc+def"
        s["origins"][0]["indexedDB"][0]["stores"][0]["records"][0]["value"] = "abc+def"
        p = result(s)
        self.assertTrue(p["decoded_cookie_equal_only"])
        self.assertFalse(p["coherent_at_source"])

    def test_unprotected_batch_fails_closed(self):
        with self.assertRaisesRegex(R158EvidenceError, "R158_UNPROTECTED_CANDIDATE_DENIED"):
            batch([dict(profile=PROFILE, source_updated_at=SAVED,
                        state=fixture(), protected=False)], selector=SELECT, observed_at=NOW)

    def test_batch_only_safe_aggregate(self):
        s = fixture()
        wrong = fixture()
        wrong["origins"][0]["localStorage"][0]["value"] = "wrong"
        p = batch([dict(profile=PROFILE, source_updated_at=SAVED, state=s, protected=True),
                   dict(profile=PROFILE, source_updated_at=SAVED, state=wrong,
                        protected=True)], selector=SELECT, observed_at=NOW)
        self.assertEqual(p["candidate_count"], 2)
        self.assertEqual(p["coherent_at_source_count"], 1)
        self.assertEqual(p["invalid_or_ambiguous_count"], 1)
        self.assertNotIn(SECRET, json.dumps(p))

    def test_no_secret_value_in_results_or_error(self):
        self.assertNotIn(SECRET, repr(result(fixture())))
        with self.assertRaises(R158EvidenceError) as ctx:
            result("SYNTHETIC_DO_NOT_PRINT_TEST_MARKER_zf7c8")
        self.assertNotIn(SECRET, str(ctx.exception))

    def test_unknown_metadata_rejected(self):
        with self.assertRaisesRegex(R158EvidenceError, "R158_TIME_OR_SELECTOR_INVALID"):
            check(profile=PROFILE, source_updated_at=float("nan"),
                  decrypted_state=fixture(), selector=SELECT, observed_at=NOW)

    def test_other_indexed_database_cannot_be_scanned(self):
        other = IndexedSelector(database="unrelated-db", store="markers", key="marker")
        with self.assertRaisesRegex(R158EvidenceError, "R158_INDEX_SELECTOR_INVALID"):
            check(profile=PROFILE, source_updated_at=SAVED,
                  decrypted_state=fixture(), selector=other, observed_at=NOW)

    def test_narrow_selector(self):
        with self.assertRaisesRegex(R158EvidenceError, "R158_INDEX_SELECTOR_INVALID"):
            IndexedSelector(database="", store="state", key="marker")


if __name__ == "__main__":
    unittest.main()
