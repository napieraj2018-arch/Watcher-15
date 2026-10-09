"""Offline tests for authenticated application archive extraction.

All test archive payloads and paths are synthetic. No master key, server access,
network access or user profiles are required.
"""
from __future__ import annotations
import ast
import io
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import tempfile
import unittest

BOOTSTRAP = Path(__file__).with_name("bootstrap.py")
TREE = ast.parse(BOOTSTRAP.read_text(encoding="utf-8"))
FUN = next(node for node in TREE.body if isinstance(node, ast.FunctionDef)
           and node.name == "safe_extract")
SCOPE = {"Path": Path, "PurePosixPath": PurePosixPath,
         "shutil": shutil, "tarfile": tarfile}
exec(compile(ast.Module(body=[FUN], type_ignores=[]), str(BOOTSTRAP), "exec"), SCOPE)
safe_extract = SCOPE["safe_extract"]


def archive(entries):
    """Create a compressed in-memory tar from (name, type, payload) tuples."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as bundle:
        for name, kind, payload in entries:
            member = tarfile.TarInfo(name)
            if kind == "file":
                data = payload.encode("utf-8") if isinstance(payload, str) else payload
                member.size = len(data)
                bundle.addfile(member, io.BytesIO(data))
            elif kind == "dir":
                member.type = tarfile.DIRTYPE
                bundle.addfile(member)
            elif kind == "symlink":
                member.type = tarfile.SYMTYPE
                member.linkname = payload
                bundle.addfile(member)
            elif kind == "hardlink":
                member.type = tarfile.LNKTYPE
                member.linkname = payload
                bundle.addfile(member)
            elif kind == "fifo":
                member.type = tarfile.FIFOTYPE
                bundle.addfile(member)
            elif kind == "block":
                member.type = tarfile.BLKTYPE
                bundle.addfile(member)
            else:
                raise AssertionError(kind)
    buffer.seek(0)
    return buffer


class ExtractionTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name) / "payload"

    def unpack(self, entries):
        buffer = archive(entries)
        with tarfile.open(fileobj=buffer, mode="r:gz") as bundle:
            safe_extract(bundle, self.root)

    def test_single_file(self):
        self.unpack([("server.py", "file", "print('OK')")])
        self.assertEqual((self.root / "server.py").read_text(), "print('OK')")

    def test_nested_without_explicit_directory(self):
        self.unpack([("app/templates/mobile.html", "file", "<main>OK</main>")])
        self.assertEqual((self.root / "app/templates/mobile.html").read_text(), "<main>OK</main>")

    def test_explicit_directories(self):
        self.unpack([("app/", "dir", None), ("app/server.py", "file", "OK")])
        self.assertTrue((self.root / "app").is_dir())

    def test_unicode_filename(self):
        self.unpack([("szablony/przegladarka.html", "file", "Zażółć")])
        self.assertEqual((self.root / "szablony/przegladarka.html").read_text(), "Zażółć")

    def test_empty_file(self):
        self.unpack([("server.py", "file", b"")])
        self.assertEqual((self.root / "server.py").stat().st_size, 0)

    def test_root_directory_entry_from_standard_tarfile_add(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            source.mkdir()
            (source / "server.py").write_text("SAFE")
            payload = io.BytesIO()
            with tarfile.open(fileobj=payload, mode="w:gz") as tf:
                tf.add(source, arcname=".")
            payload.seek(0)
            with tarfile.open(fileobj=payload, mode="r:gz") as tf:
                safe_extract(tf, self.root)
            self.assertEqual((self.root / "server.py").read_text(), "SAFE")

    def test_repeated_extraction_is_supported(self):
        self.unpack([("server.py", "file", "one")])
        self.unpack([("server.py", "file", "two")])
        self.assertEqual((self.root / "server.py").read_text(), "two")

    def test_relative_parent_rejected(self):
        with self.assertRaises(RuntimeError):
            self.unpack([("../escape.txt", "file", "SECRET")])
        self.assertFalse((self.root.parent / "escape.txt").exists())

    def test_nested_parent_rejected(self):
        with self.assertRaises(RuntimeError):
            self.unpack([("app/../../escape", "file", "BAD")])

    def test_absolute_path_rejected(self):
        with self.assertRaises(RuntimeError):
            self.unpack([("/tmp/not-real-secret", "file", "BAD")])

    def test_windows_path_rejected(self):
        with self.assertRaises(RuntimeError):
            self.unpack([("app\\..\\escape", "file", "BAD")])

    def test_symlink_rejected(self):
        with self.assertRaises(RuntimeError):
            self.unpack([("link", "symlink", "../../outside")])

    def test_hardlink_rejected(self):
        with self.assertRaises(RuntimeError):
            self.unpack([("app/hard", "hardlink", "/etc/passwd")])

    def test_fifo_rejected(self):
        with self.assertRaises(RuntimeError):
            self.unpack([("app/pipe", "fifo", None)])

    def test_device_rejected(self):
        with self.assertRaises(RuntimeError):
            self.unpack([("app/disk", "block", None)])

    def test_duplicate_filename_rejected_before_write(self):
        with self.assertRaises(RuntimeError):
            self.unpack([("good.txt", "file", "ONE"), ("good.txt", "file", "TWO")])
        self.assertFalse((self.root / "good.txt").exists())

    def test_duplicate_normalized_name_rejected(self):
        with self.assertRaises(RuntimeError):
            self.unpack([("safe.txt", "file", "ONE"), ("./safe.txt", "file", "TWO")])

    def test_empty_archive_rejected(self):
        with self.assertRaises(RuntimeError):
            self.unpack([])

    def test_directory_collision_rejected(self):
        with self.assertRaises(RuntimeError):
            self.unpack([("app", "file", "FILE"), ("app/server.py", "file", "BAD")])
        self.assertFalse((self.root / "app").exists())

    def test_preexisting_symlink_to_outside_rejected(self):
        outside = self.root.parent / "outside"
        outside.mkdir()
        self.root.mkdir()
        (self.root / "app").symlink_to(outside)
        with self.assertRaises(RuntimeError):
            self.unpack([("app/server.py", "file", "BAD")])
        self.assertFalse((outside / "server.py").exists())

    def test_preexisting_symlink_to_inside_rejected(self):
        self.root.mkdir()
        (self.root / "existing").mkdir()
        (self.root / "link").symlink_to(self.root / "existing")
        with self.assertRaises(RuntimeError):
            self.unpack([("link/server.py", "file", "BAD")])
        self.assertFalse((self.root / "existing/server.py").exists())

    def test_preexisting_symlink_file_rejected(self):
        self.root.mkdir()
        outside = self.root.parent / "existing.txt"
        outside.write_text("SAFE")
        (self.root / "server.py").symlink_to(outside)
        with self.assertRaises(RuntimeError):
            self.unpack([("server.py", "file", "BAD")])
        self.assertEqual(outside.read_text(), "SAFE")

    def test_archive_validate_all_before_any_write(self):
        with self.assertRaises(RuntimeError):
            self.unpack([("good.txt", "file", "GOOD"), ("link", "symlink", "../outside")])
        self.assertFalse((self.root / "good.txt").exists())

    def test_limits_single_large_file(self):
        f = tarfile.TarInfo("huge.bin")
        f.size = 20_000_001
        class FakeTar:
            def getmembers(self): return [f]
        with self.assertRaises(RuntimeError):
            safe_extract(FakeTar(), self.root)
        self.assertFalse(self.root.exists())

    def test_limits_total_size(self):
        entries = []
        for i in range(5):
            member = tarfile.TarInfo(f"file{i}")
            member.size = 20_000_000
            entries.append(member)
        class FakeTar:
            def getmembers(self): return entries
        with self.assertRaises(RuntimeError):
            safe_extract(FakeTar(), self.root)

    def test_limits_member_count(self):
        members = [tarfile.TarInfo(f"file{i}") for i in range(1001)]
        class FakeTar:
            def getmembers(self): return members
        with self.assertRaises(RuntimeError):
            safe_extract(FakeTar(), self.root)

    def test_rejects_special_control_char(self):
        with self.assertRaises(RuntimeError):
            self.unpack([("evil\nname", "file", "BAD")])

    def test_rejects_too_long_name(self):
        info = tarfile.TarInfo("a"*513)
        class FakeTar:
            def getmembers(self): return [info]
        with self.assertRaises(RuntimeError):
            safe_extract(FakeTar(), self.root)

    def test_valid_payload_not_trusted_for_links(self):
        self.unpack([("./server.py", "file", "WORKS")])
        self.assertEqual((self.root/"server.py").read_text(), "WORKS")

    def test_path_traversal_even_inside_dest_refused(self):
        with self.assertRaises(RuntimeError):
            self.unpack([("app/../server.py", "file", "BAD")])

    def test_file_with_existing_directory_fails_no_escape(self):
        self.root.mkdir()
        (self.root / "server.py").mkdir()
        with self.assertRaises((RuntimeError, IsADirectoryError)):
            self.unpack([("server.py", "file", "BAD")])

    def test_production_bootstrap_still_protects_key(self):
        source = BOOTSTRAP.read_text(encoding="utf-8")
        self.assertIn("AESGCM(key).decrypt(", source)
        self.assertIn('AI_BROWSER_MASTER_KEY', source)
        self.assertNotIn("tf.extractall(dest)", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
