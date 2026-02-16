"""Tests for /status and /index/build endpoints."""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient
from server.app import app
from server.config import Settings
from server.dependencies import get_settings


def _override_settings(index_dir: Path, pdf_dir: Path = None):
    if pdf_dir is None:
        pdf_dir = index_dir / "pdfs"
    return Settings(
        index_root=index_dir,
        pdf_dir=pdf_dir,
        study_db_path=index_dir / "study_cards.jsonl",
        session_log_path=index_dir / "session_log.jsonl",
        graph_registry_path=index_dir / "graph_registry.json",
        golden_sets_dir=index_dir / "golden_sets",
    )


def _write_library(index_dir: Path, books: list) -> None:
    """Write library.json with given books."""
    index_dir.mkdir(parents=True, exist_ok=True)
    lib = {
        "version": "0.2",
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
        "books": books,
    }
    with open(index_dir / "library.json", "w") as f:
        json.dump(lib, f)


def test_status_returns_index_exists_false_when_library_missing():
    """GET /status returns index_exists false when library.json missing."""
    with tempfile.TemporaryDirectory() as tmp:
        index_dir = Path(tmp) / "index"  # does not exist
        pdf_dir = Path(tmp) / "pdfs"
        pdf_dir.mkdir()
        settings = _override_settings(index_dir, pdf_dir)

        app.dependency_overrides[get_settings] = lambda: settings
        try:
            client = TestClient(app)
            resp = client.get("/status")
            assert resp.status_code == 200
            body = resp.json()
            assert body["ok"] is True
            assert body["index_exists"] is False
            assert body["index_ready"] is False
            assert body["chunk_count"] == 0
            assert body["book_counts"] == []
        finally:
            app.dependency_overrides.clear()


def test_status_returns_index_ready_when_library_has_ready_book():
    """GET /status returns index_ready true when library.json has at least one ready book with chunk_count>0."""
    with tempfile.TemporaryDirectory() as tmp:
        index_dir = Path(tmp) / "index"
        pdf_dir = Path(tmp) / "pdfs"
        pdf_dir.mkdir()

        books = [
            {
                "book_id": "abc123",
                "filename": "BookA.pdf",
                "sha256": "abc123",
                "added_at": "2025-01-01T00:00:00Z",
                "updated_at": "2025-01-01T00:00:00Z",
                "chunk_count": 42,
                "status": "ready",
                "supersedes": [],
                "superseded_by": [],
                "ingest_ms": 100,
            },
        ]
        _write_library(index_dir, books)

        # Create book dir + chunks.jsonl + book.json for verify()
        book_dir = index_dir / "books" / "abc123"
        book_dir.mkdir(parents=True)
        with open(book_dir / "chunks.jsonl", "w") as f:
            f.write('{"text":"x","book_name":"BookA"}\n')
        with open(book_dir / "book.json", "w") as f:
            json.dump(books[0], f)

        settings = _override_settings(index_dir, pdf_dir)
        app.dependency_overrides[get_settings] = lambda: settings
        try:
            client = TestClient(app)
            resp = client.get("/status")
            assert resp.status_code == 200
            body = resp.json()
            assert body["index_exists"] is True
            assert body["index_ready"] is True
            assert body["chunk_count"] == 42
            assert len(body["book_counts"]) == 1
            assert body["book_counts"][0]["book"] == "BookA.pdf"
            assert body["book_counts"][0]["chunks"] == 42
            assert body["book_counts"][0]["status"] == "ready"
        finally:
            app.dependency_overrides.clear()


def test_status_fallback_to_data_json_when_library_missing():
    """GET /status falls back to data.json when library.json absent (legacy)."""
    with tempfile.TemporaryDirectory() as tmp:
        index_dir = Path(tmp) / "index"
        index_dir.mkdir()
        pdf_dir = Path(tmp) / "pdfs"
        pdf_dir.mkdir()

        with open(index_dir / "data.json", "w") as f:
            json.dump({
                "documents": ["doc1", "doc2"],
                "metadatas": [
                    {"book": "BookA", "section": "1"},
                    {"book": "BookA", "section": "2"},
                ],
            }, f)

        settings = _override_settings(index_dir, pdf_dir)
        app.dependency_overrides[get_settings] = lambda: settings
        try:
            client = TestClient(app)
            resp = client.get("/status")
            assert resp.status_code == 200
            body = resp.json()
            assert body["index_exists"] is True
            assert body["index_ready"] is True
            assert body["chunk_count"] == 2
        finally:
            app.dependency_overrides.clear()


def test_index_build_returns_400_when_pdf_dir_empty():
    """POST /index/build returns 400 when pdf_dir has no PDFs."""
    with tempfile.TemporaryDirectory() as tmp:
        index_dir = Path(tmp) / "index"
        index_dir.mkdir()
        pdf_dir = Path(tmp) / "pdfs"
        pdf_dir.mkdir()

        settings = _override_settings(index_dir, pdf_dir)
        app.dependency_overrides[get_settings] = lambda: settings
        try:
            client = TestClient(app)
            resp = client.post("/index/build", json={"pdf_dir": str(pdf_dir)})
            assert resp.status_code == 400
            body = resp.json()
            assert "detail" in body
            assert "No PDFs" in body["detail"]
        finally:
            app.dependency_overrides.clear()


def test_index_build_returns_400_when_pdf_dir_missing():
    """POST /index/build returns 400 when pdf_dir does not exist."""
    with tempfile.TemporaryDirectory() as tmp:
        index_dir = Path(tmp) / "index"
        index_dir.mkdir()
        pdf_dir = Path(tmp) / "nonexistent_pdfs"

        settings = _override_settings(index_dir, pdf_dir)
        app.dependency_overrides[get_settings] = lambda: settings
        try:
            client = TestClient(app)
            resp = client.post("/index/build", json={"pdf_dir": str(pdf_dir)})
            assert resp.status_code == 400
            body = resp.json()
            assert "detail" in body
        finally:
            app.dependency_overrides.clear()


def test_index_build_returns_report_with_ingested_skipped_failed():
    """POST /index/build returns BuildReport with ingested, skipped, failed arrays.
    When all PDFs skipped (already ready), rebuilt_search_index is False."""
    with tempfile.TemporaryDirectory() as tmp:
        index_dir = Path(tmp) / "index"
        pdf_dir = Path(tmp) / "pdfs"
        pdf_dir.mkdir()

        # Create minimal PDF and pre-ingest it so build will skip
        pdf_path = pdf_dir / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 minimal")
        import hashlib
        h = hashlib.sha256()
        h.update(pdf_path.read_bytes())
        book_id = h.hexdigest()

        books = [
            {
                "book_id": book_id,
                "filename": "test.pdf",
                "sha256": book_id,
                "added_at": "2025-01-01T00:00:00Z",
                "updated_at": "2025-01-01T00:00:00Z",
                "chunk_count": 1,
                "status": "ready",
                "supersedes": [],
                "superseded_by": [],
                "ingest_ms": 0,
            },
        ]
        _write_library(index_dir, books)
        book_dir = index_dir / "books" / book_id
        book_dir.mkdir(parents=True)
        (book_dir / "chunks.jsonl").write_text('{"text":"x","book_id":"' + book_id + '"}\n')
        with open(book_dir / "book.json", "w") as f:
            json.dump(books[0], f)

        settings = _override_settings(index_dir, pdf_dir)
        app.dependency_overrides[get_settings] = lambda: settings
        try:
            client = TestClient(app)
            resp = client.post("/index/build", json={"pdf_dir": str(pdf_dir)})
            assert resp.status_code == 200
            body = resp.json()
            assert body["ok"] is True
            assert "report" in body
            report = body["report"]
            assert "ingested" in report
            assert "skipped" in report
            assert "failed" in report
            assert "elapsed_ms" in report
            assert "rebuilt_search_index" in report
            assert isinstance(report["ingested"], list)
            assert isinstance(report["skipped"], list)
            assert isinstance(report["failed"], list)
            assert report["rebuilt_search_index"] is False
            assert len(report["skipped"]) >= 1
            assert "stats" in body
        finally:
            app.dependency_overrides.clear()


def test_index_build_no_op_does_not_invalidate_caches():
    """When ingest is no-op (all skipped), caches are not invalidated."""
    with tempfile.TemporaryDirectory() as tmp:
        index_dir = Path(tmp) / "index"
        pdf_dir = Path(tmp) / "pdfs"
        pdf_dir.mkdir()

        pdf_path = pdf_dir / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 minimal")
        import hashlib
        h = hashlib.sha256()
        h.update(pdf_path.read_bytes())
        book_id = h.hexdigest()

        books = [
            {
                "book_id": book_id,
                "filename": "test.pdf",
                "sha256": book_id,
                "added_at": "2025-01-01T00:00:00Z",
                "updated_at": "2025-01-01T00:00:00Z",
                "chunk_count": 1,
                "status": "ready",
                "supersedes": [],
                "superseded_by": [],
                "ingest_ms": 0,
            },
        ]
        _write_library(index_dir, books)
        book_dir = index_dir / "books" / book_id
        book_dir.mkdir(parents=True)
        (book_dir / "chunks.jsonl").write_text('{"text":"x","book_id":"' + book_id + '"}\n')
        with open(book_dir / "book.json", "w") as f:
            json.dump(books[0], f)

        settings = _override_settings(index_dir, pdf_dir)
        app.dependency_overrides[get_settings] = lambda: settings
        with patch("server.services.query_service.invalidate_searcher_cache") as mock_inv:
            with patch("server.library.invalidate_verify_cache") as mock_verify:
                try:
                    client = TestClient(app)
                    resp = client.post("/index/build", json={"pdf_dir": str(pdf_dir)})
                    assert resp.status_code == 200
                    assert resp.json()["report"]["rebuilt_search_index"] is False
                    mock_inv.assert_not_called()
                    mock_verify.assert_not_called()
                finally:
                    app.dependency_overrides.clear()
