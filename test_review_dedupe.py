"""All review names and quotes are synthetic. No Meta/Google calls."""
import json
import unittest

from review_dedupe import classify_reviews, normalize, ReviewEvidenceError


def slides():
    return [{
        "index":i, "author":f"Test Author {i}",
        "quote":f"Synthetic custom design project and reliable contacts number {i}.",
        "verified":True,
        "private_image_evidence":f"private-test-evidence-{i}"
    } for i in range(1,9)]


class ReviewDedupeTests(unittest.TestCase):
    def test_unread_highlight_forbids_unused(self):
        r=[{"review_id":"rev1","author":"Sample","quote":"Wonderful architecture services"}]
        out=classify_reviews(r,[],set())
        self.assertEqual(out[0]["status"],"blocked_incomplete_highlight")

    def test_incomplete_even_when_7_of_8(self):
        r=[{"review_id":"a","author":"Someone","quote":"Quality work and precision."}]
        for missing in [slides()[:7],slides()[1:]]:
            self.assertEqual(classify_reviews(r,missing,set())[0]["status"],
                             "blocked_incomplete_highlight")

    def test_unverified_slide_not_counted_as_read(self):
        records=slides()
        records[4]["verified"]=False
        r=[{"review_id":"one","author":"Author","quote":"Good detailed design."}]
        self.assertEqual(classify_reviews(r,records,set())[0]["status"],
                         "blocked_incomplete_highlight")

    def test_missing_visual_proof_invalidates_all_unused(self):
        records=slides()
        records[0]["private_image_evidence"]=""
        result=classify_reviews([{
            "review_id":"one","author":"Author","quote":"Good detailed design"
        }],records,set())
        self.assertEqual(result[0]["status"],"blocked_incomplete_highlight")

    def test_exact_same_author_and_quote_is_used(self):
        records=slides()
        r=[{"review_id":"one","author":"Test Author 2","quote":records[1]["quote"]}]
        d=classify_reviews(r,records,set())[0]
        self.assertEqual(d["status"],"used")
        self.assertEqual(d["matched_slides"],[2])

    def test_shorter_quote_same_author_is_used_when_substantial(self):
        records=slides()
        records[2]["quote"]="Synthetic custom design project and reliable contacts number 3. Very helpful."
        r=[{"review_id":"one","author":"Test Author 3",
            "quote":"Synthetic custom design project and reliable contacts number 3."}]
        d=classify_reviews(r,records,set())[0]
        self.assertEqual(d["status"],"used")
        self.assertEqual(d["matched_slides"],[3])

    def test_same_quote_different_author_requires_manual_verification(self):
        records=slides()
        r=[{"review_id":"one","author":"Different Author","quote":records[1]["quote"]}]
        d=classify_reviews(r,records,set())[0]
        self.assertEqual(d["status"],"needs_verification")
        self.assertEqual(d["matched_slides"],[2])

    def test_short_quote_different_author_not_marked_used(self):
        records=slides()
        records[4]["quote"]="Polecam!"
        r=[{"review_id":"one","author":"Someone Else","quote":"Polecam!"}]
        self.assertEqual(classify_reviews(r,records,set())[0]["status"],
                         "needs_verification")

    def test_unmatched_review_unused_only_with_8_evidenced_slides(self):
        r=[{"review_id":"one","author":"Unique Human",
            "quote":"This synthetic review says something completely different about landscape."}]
        d=classify_reviews(r,slides(),set())[0]
        self.assertEqual(d["status"],"unused")

    def test_known_previously_used_stays_used_without_highlight(self):
        r=[{"review_id":"used123","author":"Name","quote":"Original quote."}]
        d=classify_reviews(r,[],{"used123"})[0]
        self.assertEqual(d["status"],"used")
        self.assertEqual(d["reason"],"previously_used")

    def test_blank_review_has_no_quotable_text(self):
        r=[{"review_id":"empty","author":"Anonymous","quote":""}]
        self.assertEqual(classify_reviews(r,slides(),set())[0]["status"],"no_text")

    def test_author_normalization_handles_polish_accents(self):
        records=slides()
        records[3]["author"]="ŻÓŁĆ łańcuch"
        r=[{"review_id":"one","author":"zolc lancuch","quote":records[3]["quote"]}]
        self.assertEqual(classify_reviews(r,records,set())[0]["status"],"used")

    def test_fuzzy_similar_quote_is_needs_verification_not_used(self):
        records=slides()
        records[1]["quote"]="Excellent custom design project, exceptionally reliable contacts number 2."
        r=[{"review_id":"one","author":"Test Author 2",
            "quote":"Excellent custom design project, extremely reliable contacts number 2."}]
        d=classify_reviews(r,records,set())[0]
        self.assertEqual(d["status"],"needs_verification")

    def test_duplicate_reviews_rejected(self):
        r=[{"review_id":"same","author":"a","quote":"one"},
           {"review_id":"same","author":"b","quote":"two"}]
        with self.assertRaisesRegex(ReviewEvidenceError,"IDS_INVALID"):
            classify_reviews(r,slides(),set())

    def test_no_private_quotes_returned_in_results(self):
        needle="Never output this private-typed synthetic quote 1234"
        r=[{"review_id":"test","author":"A person","quote":needle}]
        out=classify_reviews(r,slides(),set())
        self.assertNotIn(needle,json.dumps(out))
        self.assertNotIn("A person",json.dumps(out))

    def test_bad_input_cannot_pass(self):
        with self.assertRaises(ReviewEvidenceError):
            classify_reviews("not list",slides(),set())
        with self.assertRaises(ReviewEvidenceError):
            normalize(None)


if __name__=="__main__":
    unittest.main(verbosity=2)
