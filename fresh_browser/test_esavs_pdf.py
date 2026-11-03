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


class ESAVSMemoryRelease(unittest.IsolatedAsyncioTestCase):
    async def test_api_response_is_disposed_after_success_and_pdf_cache_released(self):
        from unittest.mock import AsyncMock
        from types import SimpleNamespace
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=300)
        data = io.BytesIO()
        writer.write(data)
        class Response:
            status = 200
            headers = {"content-length": str(len(data.getvalue()))}
            disposed = False
            async def body(self):
                return data.getvalue()
            async def dispose(self):
                self.disposed = True
        response = Response()
        class Request:
            async def get(self, url, **kwargs):
                self.url = url
                return response
        request = Request()
        class Field:
            async def evaluate(self, _js): return "A"
            async def get_attribute(self, key): return "/pluginfile.php/1/mod_resource/content/0/sample.pdf"
            async def inner_text(self): return "sample.pdf"
        class Locator:
            def nth(self, idx): return Field()
        page = SimpleNamespace(
            url="https://e-campus.esavs.eu/mod/resource/view.php?id=1",
            context=SimpleNamespace(request=request),
            locator=lambda *_args: Locator())
        workspace = server.BrowserWorkspace()
        workspace.profile = "esavs-test"
        workspace.context = object()
        workspace.open = AsyncMock()
        workspace.assert_lease = AsyncMock()
        workspace.page = lambda: page
        result = await workspace.action(
            {"name": "esavs-test", "action": "read_esavs_pdf", "index": 0, "delta": 0},
            automated=True)
        self.assertTrue(response.disposed)
        self.assertIsNone(workspace.pdf_cache)
        self.assertEqual(result["total_pages"], 1)
        self.assertEqual(result["resource"], "sample.pdf")

    async def test_api_response_disposed_after_invalid_content(self):
        from unittest.mock import AsyncMock
        from types import SimpleNamespace
        class Response:
            status = 200
            headers = {"content-length": "9"}
            disposed = False
            async def body(self): return b"<html>bad"
            async def dispose(self): self.disposed = True
        response = Response()
        request = SimpleNamespace(get=AsyncMock(return_value=response))
        field = SimpleNamespace(
            evaluate=AsyncMock(return_value="A"),
            get_attribute=AsyncMock(return_value="/pluginfile.php/1/mod_resource/content/0/sample.pdf"),
            inner_text=AsyncMock(return_value="sample.pdf"))
        page = SimpleNamespace(
            url="https://e-campus.esavs.eu/mod/resource/view.php?id=1",
            context=SimpleNamespace(request=request),
            locator=lambda *_args: SimpleNamespace(nth=lambda idx: field))
        workspace = server.BrowserWorkspace()
        workspace.profile = "esavs-test"
        workspace.context = object()
        workspace.open = AsyncMock()
        workspace.assert_lease = AsyncMock()
        workspace.page = lambda: page
        with self.assertRaises(HTTPException):
            await workspace.action(
                {"name": "esavs-test", "action": "read_esavs_pdf", "index": 0, "delta": 0},
                automated=True)
        self.assertTrue(response.disposed)
        self.assertIsNone(workspace.pdf_cache)


if __name__ == "__main__":
    unittest.main()
