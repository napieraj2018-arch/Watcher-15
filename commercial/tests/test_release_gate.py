"""Fail-closed commercialization checklist tests; offline, no customer data."""
from __future__ import annotations
import copy
from datetime import datetime,timedelta,timezone
import json
import pathlib
import sys
import tempfile
import unittest

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from release_gate import REQUIRED, evaluate, GateError, load, main

NOW=datetime(2026,10,9,7,0,tzinfo=timezone.utc)
def manifest(status="blocked"):
    return {"schema_version":1,"note":"Synthetic commercial evaluation.",
            "controls":[{"id":key,"status":status,"notes":"Test-only.",
                         "attestations":[]} for key in REQUIRED]}
def attestation(when=None,url="https://github.com/example/test/actions/runs/123"):
    return {"kind":"automated","url":url,
            "verified_at":(when or NOW).isoformat(),
            "artifact_sha256":"a"*64}
def verified_manifest():
    m=manifest("verified")
    for row in m["controls"]: row["attestations"]=[attestation()]
    return m

class GateTests(unittest.TestCase):
    def test_current_manifest_no_go(self):
        from_project=json.loads((ROOT/"release_evidence.json").read_text(encoding="utf-8"))
        result=evaluate(from_project,now=NOW)
        self.assertFalse(result["commercial_launch_approved"])
        self.assertFalse(result["ready_for_independent_acceptance"])
        self.assertEqual(result["total_controls"],20)
        self.assertEqual(result["status_counts"]["blocked"],13)
        self.assertEqual(result["status_counts"]["partial"],7)

    def test_no_status_is_automatically_verified(self):
        result=evaluate(manifest("partial"),now=NOW)
        self.assertFalse(result["ready_for_independent_acceptance"])
        self.assertEqual(len(result["blocking_controls"]),20)

    def test_all_attested_still_requires_independent_acceptance(self):
        result=evaluate(verified_manifest(),now=NOW)
        self.assertTrue(result["ready_for_independent_acceptance"])
        self.assertFalse(result["commercial_launch_approved"])

    def test_verified_without_evidence_rejected(self):
        m=verified_manifest();m["controls"][0]["attestations"]=[]
        with self.assertRaisesRegex(GateError,"VERIFIED_WITHOUT_EVIDENCE"):
            evaluate(m,now=NOW)

    def test_missing_required_control_rejected(self):
        m=manifest();m["controls"].pop()
        with self.assertRaises(GateError):evaluate(m,now=NOW)

    def test_duplicate_control_rejected(self):
        m=manifest();m["controls"][1]["id"]=m["controls"][0]["id"]
        with self.assertRaisesRegex(GateError,"DUPLICATE"):
            evaluate(m,now=NOW)

    def test_unknown_status_rejected(self):
        m=manifest();m["controls"][0]["status"]="approved_by_owner"
        with self.assertRaisesRegex(GateError,"INVALID_CONTROL_STATUS"):
            evaluate(m,now=NOW)

    def test_fake_extra_field_rejected(self):
        m=manifest();m["api_key"]="FAKE"
        with self.assertRaisesRegex(GateError,"INVALID_MANIFEST_FIELDS"):
            evaluate(m,now=NOW)

    def test_secret_attestation_query_rejected(self):
        m=verified_manifest()
        m["controls"][0]["attestations"][0]["url"]="https://github.com/example/test/actions/runs/1?token=FAKE"
        with self.assertRaisesRegex(GateError,"ATTESTATION_URL_NOT_ALLOWED"):
            evaluate(m,now=NOW)

    def test_internal_host_attestation_rejected(self):
        m=verified_manifest()
        m["controls"][0]["attestations"][0]["url"]="https://internal.local/evidence"
        with self.assertRaises(GateError):
            evaluate(m,now=NOW)

    def test_external_userinfo_attestation_rejected(self):
        m=verified_manifest()
        m["controls"][0]["attestations"][0]["url"]="https://fake@github.com/example"
        with self.assertRaises(GateError):
            evaluate(m,now=NOW)

    def test_expired_evidence_rejected(self):
        m=verified_manifest()
        m["controls"][0]["attestations"][0]["verified_at"]=(NOW-timedelta(days=31)).isoformat()
        with self.assertRaisesRegex(GateError,"ATTESTATION_STALE"):
            evaluate(m,now=NOW)

    def test_future_evidence_rejected(self):
        m=verified_manifest()
        m["controls"][0]["attestations"][0]["verified_at"]=(NOW+timedelta(days=1)).isoformat()
        with self.assertRaisesRegex(GateError,"ATTESTATION_STALE"):
            evaluate(m,now=NOW)

    def test_evidence_requires_timezone(self):
        m=verified_manifest()
        m["controls"][0]["attestations"][0]["verified_at"]="2026-10-09T07:00:00"
        with self.assertRaisesRegex(GateError,"TIMEZONE_REQUIRED"):
            evaluate(m,now=NOW)

    def test_invalid_hash_rejected(self):
        m=verified_manifest()
        m["controls"][0]["attestations"][0]["artifact_sha256"]="deadbeef"
        with self.assertRaisesRegex(GateError,"INVALID_ATTESTATION_HASH"):
            evaluate(m,now=NOW)

    def test_report_never_echoes_notes_or_attestation(self):
        m=verified_manifest()
        m["controls"][0]["notes"]="SYNTHETIC_PRIVATE_SECRET"
        result=evaluate(m,now=NOW)
        self.assertNotIn("SYNTHETIC_PRIVATE_SECRET",json.dumps(result))
        self.assertNotIn("github.com",json.dumps(result))

    def test_blockers_sorted_by_severity(self):
        result=evaluate(manifest(),now=NOW)
        severities=[x["severity"] for x in result["blocking_controls"]]
        self.assertEqual(severities,sorted(severities,key=lambda s:0 if s=="critical" else 1))

    def test_duplicate_json_key_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path=pathlib.Path(td)/"bad.json"
            path.write_text('{"schema_version":1,"schema_version":2}')
            with self.assertRaisesRegex(GateError,"DUPLICATE_JSON_KEY"):
                load(path)

    def test_nan_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path=pathlib.Path(td)/"bad.json"
            path.write_text('{"schema_version":NaN}')
            with self.assertRaisesRegex(GateError,"INVALID_NUMBER"):
                load(path)

    def test_file_size_cap(self):
        with tempfile.TemporaryDirectory() as td:
            path=pathlib.Path(td)/"large.json"
            path.write_bytes(b" " * 160000)
            with self.assertRaisesRegex(GateError,"MANIFEST_TOO_LARGE"):
                load(path)

    def test_exit_code_no_go(self):
        self.assertEqual(main([str(ROOT/"release_evidence.json")]),1)

    def test_exit_code_invalid(self):
        with tempfile.TemporaryDirectory() as td:
            path=pathlib.Path(td)/"bad.json"
            path.write_text("{}")
            self.assertEqual(main([str(path)]),2)

if __name__=="__main__":
    unittest.main(verbosity=2)
