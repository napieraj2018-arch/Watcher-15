"""Offline ESAVS reader: no live network or user credentials in regression tests."""
import base64
import io
import os
import secrets
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("AIB_FRESH_DATABASE_URL", "postgresql://fixture.invalid/db")
os.environ.setdefault("AIB_FRESH_ADMIN_TOKEN", secrets.token_urlsafe(40))
os.environ.setdefault("AIB_FRESH_MCP_TOKEN", secrets.token_urlsafe(40))
os.environ.setdefault("AIB_FRESH_DATA_KEY", base64.b64encode(secrets.token_bytes(32)).decode())

import esavs_offline as offline
from fastapi import HTTPException
from pypdf import PdfWriter


class ESAVSOfflineSafety(unittest.TestCase):
    def test_urls_must_stay_on_same_https_esavs_origin(self):
        base = "https://e-campus.esavs.eu/course/view.php?id=1"
        self.assertEqual(
            offline._same_origin(base, "/mod/resource/view.php?id=3"),
            "https://e-campus.esavs.eu/mod/resource/view.php?id=3")
        for url in [
            "http://e-campus.esavs.eu/pluginfile.php/1/a.pdf",
            "https://www.esavs.eu/pluginfile.php/1/a.pdf",
            "https://example.com/pluginfile.php/1/a.pdf",
            "file:///etc/passwd",
            "javascript:alert(1)",
            "//localhost/private",
            "https://e-campus.esavs.eu:8989/pluginfile.php/1/a.pdf",
            "https://user:pass@e-campus.esavs.eu/pluginfile.php/1/a.pdf",
        ]:
            with self.subTest(url=url):
                with self.assertRaises(HTTPException):
                    offline._same_origin(base, url)

    def test_parser_only_resource_links(self):
        doc = """<!doctype html><html><body>
        <section class="section" id="section-2"><h3 class="sectionname">Course Notes</h3>
          <a href="https://bad.example.com/x">malicious external</a>
          <a href="/mod/resource/view.php?id=101">
            <span class="instancename">Gould, Lacrimal system ESAVS 2026 <span class="accesshide">File</span></span>
          </a>
          <a href="/mod/resource/view.php?id=102">
            <span class="instancename">Matas, Eyelid surgeries 2026</span>
          </a>
          <a href="/mod/quiz/view.php?id=222">Quiz</a>
        </section></body></html>"""
        res = offline._course_resource_links(doc, "https://e-campus.esavs.eu/course/view.php?id=55")
        self.assertEqual([x["title"] for x in res], [
            "Gould, Lacrimal system ESAVS 2026",
            "Matas, Eyelid surgeries 2026"])
        self.assertTrue(all(x["url"].startswith("https://e-campus.esavs.eu/mod/resource/view.php") for x in res))

    def test_private_cookie_filter(self):
        state = {"cookies":[
            {"name":"MoodleSession","value":"secret-not-exported","domain":"e-campus.esavs.eu","path":"/"},
            {"name":"other","value":"private","domain":"perlego.com","path":"/"},
        ]}
        with offline._client(state) as client:
            jar = str(client.cookies)
            self.assertIn("MoodleSession", jar)
            self.assertNotIn("other", jar)
            self.assertNotIn("perlego.com", jar)

    def test_synthetic_pdf_extract_and_page_bounds(self):
        writer = PdfWriter()
        for _ in range(7):
            writer.add_blank_page(width=300, height=300)
        stream = io.BytesIO()
        writer.write(stream)
        with tempfile.TemporaryDirectory() as dirname:
            path = Path(dirname) / "synthetic.pdf"
            path.write_bytes(stream.getvalue())
            first = offline._extract_pdf(path, 0)
            self.assertEqual(first["total_pages"], 7)
            self.assertEqual(len(first["pages"]), 6)
            self.assertEqual(first["next_start_page"], 6)
            tail = offline._extract_pdf(path, 6)
            self.assertIsNone(tail["next_start_page"])
            self.assertEqual([p["page"] for p in tail["pages"]],[7])
            with self.assertRaises(HTTPException):
                offline._extract_pdf(path, 7)
            with self.assertRaises(HTTPException):
                offline._extract_pdf(path, -1)


    def test_fallback_to_exact_saved_course_with_full_title_verification(self):
        course_url = "https://e-campus.esavs.eu/course/view.php?id=4321"
        dashboard = "<html><body>dashboard without cards</body></html>"
        course = ('<html><head><title>'+offline.COURSE+'</title></head><body>'
                  '<h3 class="sectionname">Course Notes</h3>'
                  '<section><a href="/mod/resource/view.php?id=123">'
                  '<span class="instancename">Matas, Eyelid surgeries 2026</span>'
                  '</a></section></body></html>')
        class Fake:
            def __init__(self, text): self.text=text
            def close(self): pass
        def fake_request(_client, url):
            if url.endswith("/my/"):return Fake(dashboard),url
            if url == course_url:return Fake(course),url
            raise AssertionError("Unexpected URL "+url)
        state = {"aib_tabs":[course_url],"aib_history":[]}
        with patch.object(offline,"_request",side_effect=fake_request):
            res=offline._index(None,state)
        self.assertEqual(res[0]["title"],"Matas, Eyelid surgeries 2026")
        self.assertEqual(len(res),1)

    def test_saved_foreign_course_does_not_bypass_exact_title_check(self):
        course_url = "https://e-campus.esavs.eu/course/view.php?id=4321"
        class Fake:
            def __init__(self,text):self.text=text
            def close(self):pass
        def fake_request(_client,url):
            return (Fake("<html>Dashboard</html>"),url) if url.endswith("/my/") else (Fake("<html><h3>Course Notes</h3><h1>Different course</h1></html>"),url)
        with patch.object(offline,"_request",side_effect=fake_request):
            with self.assertRaises(HTTPException):
                offline._index(None,{"aib_tabs":[course_url]})


    def test_probe_returns_aggregate_only(self):
        from unittest.mock import Mock, patch
        html = """<html><head><title>Dashboard | ESAVS</title></head><body>
        <a href='/course/view.php?id=21'>Ophthalmology I Residential Course, 2 - 11 Nov 2026, Palma</a>
        <p>private secret bob@e-campus.esavs.eu</p></body></html>"""
        r=Mock(text=html,content=html.encode())
        with patch.object(offline,"_request",return_value=(r,"https://e-campus.esavs.eu/my/")):
            result=offline._probe(Mock())
        self.assertEqual(result["course_match_count"],1)
        self.assertEqual(result["final_path"],"/my/")
        self.assertTrue(result["course_text_present"])
        self.assertNotIn("bob@",str(result))
        r.close.assert_called_once()

    def test_disallows_wrong_profile_without_decrypting(self):
        with self.assertRaises(HTTPException):
            offline.run("esavs_offline_index",{"name":"perlego-slatter"},lambda p:None,lambda x:x,b"a"*32)


if __name__ == "__main__":
    unittest.main()
