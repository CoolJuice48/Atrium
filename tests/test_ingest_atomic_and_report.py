"""Tests for atomic ingest and BuildReport shape."""

import json
import sys
import tempfile
import pathlib
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.ingest_library import (
    _atomic_write,
    ingest_one_pdf,
    ingest_pdfs_incremental,
    get_active_version_per_family,
)


def test_atomic_write_creates_file():
    """_atomic_write creates target file and no .tmp left behind."""
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "out.json"
        _atomic_write(p, '{"x":1}')
        assert p.exists()
        assert not p.with_suffix(p.suffix + ".tmp").exists()
        assert json.loads(p.read_text()) == {"x": 1}


def test_atomic_write_on_failure_leaves_no_partial_target():
    """If rename fails, target file does not exist; only .tmp may remain."""
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "out.json"
        with patch.object(Path, "replace", side_effect=OSError("simulated crash")):
            try:
                _atomic_write(p, '{"x":1}')
            except OSError:
                pass
        assert not p.exists()
        tmp_path = p.with_suffix(p.suffix + ".tmp")
        assert tmp_path.exists()


def test_ingest_failure_mid_write_leaves_no_partial_chunks():
    """When ingest fails during chunks rename, chunks.jsonl does not exist (only .tmp or nothing)."""
    with tempfile.TemporaryDirectory() as tmp:
        pdf_dir = Path(tmp) / "pdfs"
        pdf_dir.mkdir()
        pdf_path = pdf_dir / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 minimal")

        out_dir = Path(tmp) / "converted" / "test"
        out_dir.mkdir(parents=True)
        sections = out_dir / "test_SectionsWithText_Chunked.jsonl"
        chunk_rec = {
            "text": "chunk1",
            "book_name": "test",
            "chapter_number": "1",
            "section_number": "1",
            "section_title": "S1",
            "page_start": 1,
            "page_end": 1,
            "chunk_index": 0,
            "total_chunks": 1,
            "word_count": 5,
        }
        sections.write_text(json.dumps(chunk_rec) + "\n")

        index_root = Path(tmp) / "index"
        index_root.mkdir()

        _original_replace = pathlib.Path.replace

        def mock_replace(self, target):
            if Path(target).name == "chunks.jsonl":
                raise OSError("simulated crash during chunks rename")
            return _original_replace(self, target)

        with patch("pdf_to_jsonl.convert_pdf") as mock_convert:
            mock_convert.return_value = ("doc1", out_dir)
            with patch.object(pathlib.Path, "replace", mock_replace):
                book_id, cnt, ms, status, err = ingest_one_pdf(pdf_path, index_root, copy_source=False)
        assert status == "error"
        book_dir = index_root / "books" / book_id
        assert not (book_dir / "chunks.jsonl").exists()


def test_ingest_failure_preserves_valid_library_json():
    """When ingest fails mid-run, library.json remains valid JSON."""
    with tempfile.TemporaryDirectory() as tmp:
        pdf_dir = Path(tmp) / "pdfs"
        pdf_dir.mkdir()
        pdf_path = pdf_dir / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 minimal")

        out_dir = Path(tmp) / "converted" / "test"
        out_dir.mkdir(parents=True)
        sections = out_dir / "test_SectionsWithText_Chunked.jsonl"
        chunk_rec = {
            "text": "x",
            "book_name": "test",
            "chapter_number": "1",
            "section_number": "1",
            "section_title": "S1",
            "page_start": 1,
            "page_end": 1,
            "chunk_index": 0,
            "total_chunks": 1,
            "word_count": 1,
        }
        sections.write_text(json.dumps(chunk_rec) + "\n")

        index_root = Path(tmp) / "index"
        index_root.mkdir()

        _orig = pathlib.Path.replace

        def mock_replace(self, target):
            if Path(target).name == "chunks.jsonl":
                raise OSError("simulated crash")
            return _orig(self, target)

        with patch("pdf_to_jsonl.convert_pdf") as mock_convert:
            mock_convert.return_value = ("doc1", out_dir)
            with patch.object(pathlib.Path, "replace", mock_replace):
                ingest_pdfs_incremental(pdf_dir, index_root, copy_source=False)

        lib_path = index_root / "library.json"
        assert lib_path.exists()
        lib = json.loads(lib_path.read_text())
        assert "books" in lib
        assert "version" in lib


def test_build_report_shape():
    """BuildReport has elapsed_ms, ingested, skipped, failed, rebuilt_search_index, avg_ingest_ms."""
    with tempfile.TemporaryDirectory() as tmp:
        pdf_dir = Path(tmp) / "pdfs"
        pdf_dir.mkdir()
        index_root = Path(tmp) / "index"
        index_root.mkdir()

        report = ingest_pdfs_incremental(pdf_dir, index_root, copy_source=True)

        assert "elapsed_ms" in report
        assert "ingested" in report
        assert "skipped" in report
        assert "failed" in report
        assert "rebuilt_search_index" in report
        assert "avg_ingest_ms" in report
        assert isinstance(report["ingested"], list)
        assert isinstance(report["skipped"], list)
        assert isinstance(report["failed"], list)


def test_build_report_no_op_rebuilt_false():
    """When no PDFs, rebuilt_search_index is False."""
    with tempfile.TemporaryDirectory() as tmp:
        pdf_dir = Path(tmp) / "pdfs"
        pdf_dir.mkdir()
        index_root = Path(tmp) / "index"
        index_root.mkdir()

        report = ingest_pdfs_incremental(pdf_dir, index_root, copy_source=True)

        assert report["rebuilt_search_index"] is False
        assert report["ingested"] == []
        assert report["skipped"] == []
        assert report["failed"] == []


def test_get_active_version_per_family():
    """get_active_version_per_family returns latest ready per family."""
    lib = {
        "books": [
            {"book_id": "a1", "filename": "Book.pdf", "status": "ready", "updated_at": "2025-01-01T00:00:00Z"},
            {"book_id": "a2", "filename": "Book.pdf", "status": "ready", "updated_at": "2025-01-02T00:00:00Z"},
            {"book_id": "b1", "filename": "Other.pdf", "status": "ready", "updated_at": "2025-01-01T00:00:00Z"},
            {"book_id": "c1", "filename": "Error.pdf", "status": "error", "updated_at": "2025-01-01T00:00:00Z"},
        ]
    }
    active = get_active_version_per_family(lib)
    assert active["book"] == "a2"
    assert active["other"] == "b1"
    assert "error" not in active
