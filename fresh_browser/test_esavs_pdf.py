"""Synthetic, offline security regressions for the authorized ESAVS PDF reader."""
import base64
import io
import os
import secrets
import unittest

os.environ.setdefault("AIB_FRESH_DATABASE_URL", "postgresql://fixture.invalid/db")
os.environ.setdefault("AIB_FRESH_ADMIN_TOKEN", secrets.token_urlsafe(40))
os.environ.setdefault("AIB_FRESH_MCP_TOKEN", secrets.token_urlsafe(40))
os.environ.setdefault("AIB_FRESH_DATA_KEY", base64.b64encode(secrets.token_bytes(32)).decode())

import server
from fastapi import HTTPException
from pypdf import PdfWriter


class ESAVSPdfAccess(unittest.TestCase):
    def test_only_authorized_esavs_pluginfile(self):
        target = server._esavs_file_url(
            "https://e-campus.esavs.eu/mod/resource/view.php?id=129",
            "/pluginfile.php/555/mod_resource/content/0/lesson.pdf"
        )
        self.assertEqual(target, "https://e-campus.esavs.eu/pluginfile.php/555/mod_resource/content/0/lesson.pdf")

    def test_external_and_nonfile_urls_fail_closed(self):
        page = "https://e-campus.esavs.eu/mod/resource/view.php?id=129"
        bad = [
            "https://example.org/pluginfile.php/test.pdf",
            "http://e-campus.esavs.eu/pluginfile.php/test.pdf",
            "https://e-campus.esavs.eu/mod/resource/view.php?id=25",
            "https://localhost/pluginfile.php/a.pdf",
            "javascript:alert(1)",
            "file:///etc/passwd",
            "//other.esavs.eu/pluginfile.php/a.pdf",
            "https://e-campus.esavs.eu:444/pluginfile.php/a.pdf",
            "https://username:password@e-campus.esavs.eu/pluginfile.php/a.pdf",
        ]
        for link in bad:
            with self.subTest(link=link):
                with self.assertRaises(HTTPException):
                    server._esavs_file_url(page, link)

    def test_synthetic_pdf_pages_and_limits(self):
        writer = PdfWriter()
        writer.add_blank_page(width=512, height=768)
        writer.add_blank_page(width=512, height=768)
        stream = io.BytesIO()
        writer.write(stream)
        first = server._pdf_pages_extract(stream.getvalue(), 0)
        self.assertEqual(first["total_pages"], 2)
        self.assertEqual([p["page"] for p in first["pages"]], [1, 2])
        self.assertIsNone(first["next_start_page"])
        self.assertTrue(first["has_unreadable_pages"])
        second = server._pdf_pages_extract(stream.getvalue(), 1)
        self.assertEqual([p["page"] for p in second["pages"]], [2])
        with self.assertRaises(HTTPException):
            server._pdf_pages_extract(stream.getvalue(), 2)
        with self.assertRaises(HTTPException):
            server._pdf_pages_extract(stream.getvalue(), -1)
        with self.assertRaises(HTTPException):
            server._pdf_pages_extract(b"not a pdf", 0)


if __name__ == "__main__":
    unittest.main()
