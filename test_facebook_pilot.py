"""Synthetic-only regression suite for Facebook Watcher pilot; no real FB calls."""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.facebook_pilot import DraftStore, GROUP_ID, PROFILE, PilotInputError, ingest_evidence, topic_for

NOW = datetime(2026, 10, 11, 20, 0, tzinfo=timezone.utc)


def event(text="Czy ktoś poleci dobrego weterynarza dla psa w Radomiu?", post_id="12345678901"):
    return {"url":f"https://www.facebook.com/groups/{GROUP_ID}/posts/{post_id}/",
            "text": text, "published_at":(NOW-timedelta(hours=2)).isoformat()}


def batch(posts=None, **updates):
    data={"profile":PROFILE,"group_id":GROUP_ID,"status":"ok",
          "observed_at":NOW.isoformat(),"identity_verified":True,
          "membership_verified":True,"posts":[event()] if posts is None else posts}
    return {**data,**updates}


class PilotTests(unittest.TestCase):
    def setUp(self):
        self.store=DraftStore()
        self.addCleanup(self.store.close)

    def test_new_post_creates_transparent_draft_only(self):
        output=ingest_evidence(batch(),self.store,now=NOW)
        self.assertEqual(output["new_drafts"],1)
        self.assertEqual(output["auto_published"],0)
        total, urgent=self.store.counts()
        self.assertEqual((total,urgent),(1,0))
        row=self.store.conn.execute("SELECT draft,state FROM facebook_pilot_drafts").fetchone()
        self.assertIn("Piszemy jako zespół",row[0]);self.assertEqual(row[1],"needs_operator_review")
        self.assertNotIn("poleci dobrego",row[0])

    def test_duplicate_same_post_is_not_processed_twice(self):
        ingest_evidence(batch(),self.store,now=NOW)
        out=ingest_evidence(batch(),self.store,now=NOW)
        self.assertEqual(out["new_drafts"],0)
        self.assertEqual(out["duplicates"],1)
        self.assertEqual(self.store.counts()[0],1)

    def test_duplicate_variants_url_canonicalized(self):
        a=event();b=event();b["url"]=f"https://m.facebook.com/groups/{GROUP_ID}/permalink/12345678901/"
        out=ingest_evidence(batch([a,b]),self.store,now=NOW)
        self.assertEqual((out["new_drafts"],out["duplicates"]),(1,1))

    def test_urgent_cases_are_reviewed_not_published(self):
        out=ingest_evidence(batch([event("Kot połknął igłę, co robić?", "12345678902")]),self.store,now=NOW)
        self.assertEqual(out["new_drafts"],1)
        self.assertEqual(self.store.counts()[1],1)
        draft=self.store.conn.execute("SELECT draft FROM facebook_pilot_drafts").fetchone()[0]
        self.assertIn("pilnej",draft)

    def test_inaccessible_source_never_means_zero_found(self):
        out=ingest_evidence(batch(status="authentication_required",posts=[]),self.store,now=NOW)
        self.assertEqual(out["source_status"],"authentication_required")
        self.assertEqual(out["coverage"],"none")
        self.assertNotIn("scanned",out)

    def test_unverified_identity_cannot_ingest(self):
        out=ingest_evidence(batch(identity_verified=False),self.store,now=NOW)
        self.assertEqual(out["source_status"],"authentication_required")
        self.assertEqual(self.store.counts()[0],0)

    def test_bad_profile_rejected(self):
        with self.assertRaisesRegex(PilotInputError,"WRONG_PILOT_PROFILE_OR_GROUP"):
            ingest_evidence(batch(profile="Meta - Maciej - Monitoring"),self.store,now=NOW)

    def test_other_group_and_lookalike_domains_rejected(self):
        bad_urls=["https://www.facebook.com/groups/1886172518407420/posts/12345678901/",
                  f"https://facebook.com.evil.test/groups/{GROUP_ID}/posts/12345678901/",
                  f"http://www.facebook.com/groups/{GROUP_ID}/posts/12345678901/",
                  f"https://www.facebook.com/groups/{GROUP_ID}/posts/12345678901/?cookie=abc",
                  f"https://user@www.facebook.com/groups/{GROUP_ID}/posts/12345678901/"]
        for url in bad_urls:
            with self.subTest(url=url),self.assertRaises(PilotInputError):
                ingest_evidence(batch([{**event(),"url":url}]),self.store,now=NOW)
        self.assertEqual(self.store.counts()[0],0)

    def test_non_question_is_skipped(self):
        self.assertEqual(ingest_evidence(batch([event("Sprzedam łóżko dla psa")]),self.store,now=NOW)["new_drafts"],0)
        self.assertEqual(ingest_evidence(batch([event("Piękny dzień z moim psem")]),self.store,now=NOW)["new_drafts"],0)

    def test_partial_is_reported_as_partial(self):
        out=ingest_evidence(batch(status="partial"),self.store,now=NOW)
        self.assertEqual(out["coverage"],"partial")

    def test_older_post_is_skipped(self):
        old={**event(),"published_at":(NOW-timedelta(days=7)).isoformat()}
        out=ingest_evidence(batch([old]),self.store,now=NOW)
        self.assertEqual(out["skipped"],1)
        self.assertEqual(self.store.counts()[0],0)

    def test_invalid_time_and_batch_limit(self):
        for obj in (batch(observed_at="not-a-date"),batch(posts=[event()]*31)):
            with self.assertRaises(PilotInputError): ingest_evidence(obj,self.store,now=NOW)

    def test_no_private_post_body_in_database_or_receipt(self):
        secret="REAL_PATIENT_PRIVATE_STRING_DONT_LOG"
        out=ingest_evidence(batch([event("Czy możecie doradzić weterynarza? "+secret)]),self.store,now=NOW)
        self.assertNotIn(secret,json.dumps(out))
        dump=''.join(self.store.conn.iterdump())
        self.assertNotIn(secret,dump)

    def test_sqlite_persists_dedup_between_runs(self):
        with tempfile.TemporaryDirectory() as folder:
            path=str(Path(folder)/"pilot.db")
            store=DraftStore(path)
            self.assertEqual(ingest_evidence(batch(),store,now=NOW)["new_drafts"],1)
            store.close()
            another=DraftStore(path)
            try:
                self.assertEqual(ingest_evidence(batch(),another,now=NOW)["duplicates"],1)
            finally: another.close()

    def test_no_autopublish_method_or_remote_access(self):
        self.assertFalse(any("publish" in name for name in vars(self.store) if callable(getattr(self.store,name))))
        self.assertIsNone(topic_for("Życzę powodzenia."))


if __name__=="__main__":
    unittest.main(verbosity=2)
