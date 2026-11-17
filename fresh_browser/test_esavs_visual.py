"""Offline tests only: no live course files, accounts or credentials."""
import base64
import io
import os
import secrets
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("AIB_FRESH_DATABASE_URL", "postgresql://fixture.invalid/db")
os.environ.setdefault("AIB_FRESH_ADMIN_TOKEN", secrets.token_urlsafe(40))
os.environ.setdefault("AIB_FRESH_MCP_TOKEN", secrets.token_urlsafe(40))
os.environ.setdefault("AIB_FRESH_DATA_KEY", base64.b64encode(secrets.token_bytes(32)).decode())

from fastapi import HTTPException
from PIL import Image
from pypdf import PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, NameObject, NumberObject, TextStringObject
import visual_runtime as visual


class VisualReviewTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / "synthetic.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=600, height=450)
        writer.add_blank_page(width=600, height=450)
        with self.path.open("wb") as output:
            writer.write(output)

    def tearDown(self):
        self.folder.cleanup()

    def test_single_page_render(self):
        raw, meta = visual.render_pdf(self.path, 1)
        self.assertEqual(meta["visual_pages"], [2])
        self.assertIsNone(meta["next_start_page"])
        self.assertFalse(meta["visual_review_performed_by_tool"])
        with Image.open(io.BytesIO(raw)) as im:
            self.assertEqual(im.format, "PNG")
            self.assertLessEqual(max(im.size), 1800)

    def test_contact_sheet_has_page_numbers_and_bounds(self):
        raw, meta = visual.render_pdf(self.path, 0, contact=True)
        self.assertEqual(meta["visual_pages"], [1, 2])
        self.assertTrue(meta["contact_sheet"])
        with Image.open(io.BytesIO(raw)) as im:
            self.assertEqual(im.size, (1620, 440))

    def test_crops_and_invalid_page(self):
        raw, meta = visual.render_pdf(self.path, 0, crop="top-left")
        self.assertEqual(meta["pixels"], [900, 675])
        for number in (-1, 2, 999):
            with self.assertRaises(HTTPException):
                visual.render_pdf(self.path, number)
        with self.assertRaises(HTTPException):
            visual.render_pdf(self.path, 0, crop="external-script")

    def test_profile_scope(self):
        valid = {"name":"esavs-ophthalmology-i", "index":136,"delta":0}
        self.assertEqual(visual.validate_visual(valid), (0,136,"full"))
        for change in ({"name":"perlego-slatter"}, {"index":-1}, {"delta":-1}, {"delta":True}, {"key":"invalid"}):
            with self.assertRaises(HTTPException):
                visual.validate_visual({**valid, **change})

    def test_media_inventory_does_not_execute_or_expose_links(self):
        writer = PdfWriter()
        page = writer.add_blank_page(width=600, height=450)
        movie = DictionaryObject({NameObject("/Type"):NameObject("/Annot"),
                                  NameObject("/Subtype"):NameObject("/Movie"),
                                  NameObject("/Rect"):ArrayObject([NumberObject(0)]*4)})
        page[NameObject("/Annots")] = ArrayObject([writer._add_object(movie)])
        with self.path.open("wb") as output:
            writer.write(output)
        data = visual.media_inventory(self.path)
        self.assertEqual(data["total_pages"], 1)
        self.assertEqual(data["media_candidates"][0]["kind"], "/Movie")
        self.assertEqual(data["embedded_file_count"], 0)
        self.assertNotIn("http", str(data))


if __name__ == "__main__":
    unittest.main()
