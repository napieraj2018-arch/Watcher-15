"""Offline tests for vulnerability summary redaction and validity."""
import pathlib,sys,tempfile,unittest,json
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
import summarize_audit as a

class SummaryTests(unittest.TestCase):
    def test_known_vulnerability_report(self):
        report={"dependencies":[{"name":"example_lib","version":"1.2.3",
                  "vulns":[{"id":"GHSA-abcd-1234-zzzz",
                            "fix_versions":["1.2.4"],"description":"NOT_FOR_LOG_PUBLIC_SECRET"}]}]}
        r=a.summarize(report)
        self.assertEqual(r["status"],"vulnerabilities_found")
        self.assertEqual(r["advisories"],1)
        self.assertEqual(r["affected_packages"],1)
        self.assertEqual(r["packages"][0]["fixed_versions"],["1.2.4"])
        self.assertNotIn("NOT_FOR_LOG_PUBLIC_SECRET",json.dumps(r))
    def test_pypi_no_vulnerabilities(self):
        report={"dependencies":[{"name":"safe-lib","version":"1.0","vulns":[]}]}
        self.assertEqual(a.summarize(report)["status"],"no_known_vulnerabilities")
    def test_unknown_top_level_invalid(self):
        self.assertEqual(a.summarize("NOT_A_REPORT")["status"],"invalid_report")
    def test_untrusted_text_never_logged(self):
        report=[{"name":"x;PASSWORD=LEAK","version":"sh -c SECRET",
                  "vulns":[{"id":"FAKE_PASSWORD=SECRET","description":"password:secret",
                            "fix_versions":["SECRET<script>"]}]}]
        r=a.summarize(report)
        text=json.dumps(r)
        self.assertNotIn("PASSWORD=LEAK",text)
        self.assertNotIn("password:secret",text)
        self.assertNotIn("SECRET<script>",text)
        self.assertIn("[redacted]",text)
    def test_cve_id_valid(self):
        report=[{"name":"demo","version":"2.2",
                 "vulns":[{"id":"CVE-2026-12345","fix_versions":[]}]}]
        self.assertEqual(a.summarize(report)["packages"][0]["advisory_ids"][0],"CVE-2026-12345")
    def test_many_packs_output_bounded(self):
        report=[{"name":"p"+str(i),"version":"1.0",
                 "vulns":[{"id":"CVE-2026-12345"}]} for i in range(300)]
        r=a.summarize(report)
        self.assertEqual(r["affected_packages"],300)
        self.assertEqual(len(r["packages"]),30)
        self.assertEqual(r["advisories"],300)
    def test_many_fixes_are_bounded(self):
        report=[{"name":"p","version":"1",
                 "vulns":[{"id":"CVE-2026-12345","fix_versions":[str(j) for j in range(100)]}]}]
        self.assertLessEqual(len(a.summarize(report)["packages"][0]["fixed_versions"]),12)
    def test_unknown_vuln_item_graceful(self):
        self.assertEqual(a.summarize([{"name":"p","version":"1","vulns":[None]}])["advisories"],1)
    def test_missing_file_hides_exception(self):
        with tempfile.TemporaryDirectory() as td:
            path=pathlib.Path(td)/"missing.json"
            self.assertEqual(a.main(path),0)
    def test_invalid_file_hides_raw_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            path=pathlib.Path(td)/"bad.json"
            path.write_text("{raw-SECRET")
            self.assertEqual(a.main(path),0)

if __name__=="__main__":unittest.main(verbosity=2)
