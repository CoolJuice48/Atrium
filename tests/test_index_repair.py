"""Tests for POST /index/repair and repair_library."""

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
from server.services.index_service import repair_library


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


def test_repair_reconstructs_book_json_when_missing():
    """Missing book.json but chunks.jsonl exists → repair reconstructs book.json and library entry becomes ready."""
    with tempfile.TemporaryDirectory() as tmp:
        index_root = Path(tmp) / "index"
        books_dir = index_root / "books"
        books_dir.mkdir(parents=True)
        book_id = "abc123def456"
        book_dir = books_dir / book_id
        book_dir.mkdir()
        (book_dir / "chunks.jsonl").write_text(
            '{"text":"sample chunk","book_name":"TestBook","page_start":1,"page_end":2}\n'
        )

        with patch("scripts.ingest_library.rebuild_search_index"):
            result = repair_library(index_root, mode="repair", prune_tmp=True)

        report = result["report"]
        assert report["repaired_books"]
        assert any(r["book_id"] == book_id and "reconstructed book.json" in r["actions"] for r in report["repaired_books"])
        assert (book_dir / "book.json").exists()
        book_meta = json.loads((book_dir / "book.json").read_text())
        assert book_meta["book_id"] == book_id
        assert book_meta["status"] == "ready"
        assert book_meta["chunk_count"] == 1
        assert result["stats"]["chunk_count"] == 1


def test_repair_replaces_corrupt_library_json():
    """Corrupt/invalid library.json → repair replaces it with valid JSON rebuilt from disk."""
    with tempfile.TemporaryDirectory() as tmp:
        index_root = Path(tmp) / "index"
        books_dir = index_root / "books"
        books_dir.mkdir(parents=True)
        book_id = "xyz789"
        book_dir = books_dir / book_id
        book_dir.mkdir()
        (book_dir / "chunks.jsonl").write_text(
            '{"text":"chunk","book_name":"X","page_start":1,"page_end":1}\n'
        )
        (index_root / "library.json").write_text("{ invalid json")

        with patch("scripts.ingest_library.rebuild_search_index"):
            result = repair_library(index_root, mode="repair", prune_tmp=True)

        lib_path = index_root / "library.json"
        assert lib_path.exists()
        lib = json.loads(lib_path.read_text())
        assert "version" in lib
        assert "books" in lib
        assert len(lib["books"]) >= 1
        assert lib["books"][0]["book_id"] == book_id


def test_prune_tmp_removes_leftover_tmp_without_deleting_artifacts():
    """prune_tmp removes leftover .tmp without deleting real artifacts."""
    with tempfile.TemporaryDirectory() as tmp:
        index_root = Path(tmp) / "index"
        books_dir = index_root / "books"
        books_dir.mkdir(parents=True)
        book_id = "tid1"
        book_dir = books_dir / book_id
        book_dir.mkdir()
        (book_dir / "chunks.jsonl").write_text(
            '{"text":"x","book_name":"T","page_start":1,"page_end":1}\n'
        )
        (book_dir / "chunks.jsonl.tmp").write_text("leftover")
        (book_dir / "book.json.tmp").write_text("{}")
        (index_root / "library.json.tmp").write_text("{}")

        with patch("scripts.ingest_library.rebuild_search_index"):
            result = repair_library(index_root, mode="repair", prune_tmp=True)

        assert result["report"]["pruned_tmp_count"] >= 1
        assert not (book_dir / "chunks.jsonl.tmp").exists()
        assert (book_dir / "chunks.jsonl").exists()
        assert (book_dir / "book.json").exists()


def test_rebuild_search_index_runs_only_when_repairs_changed_state():
    """rebuild_search_index runs only when repairs_changed_state is true (mock rebuild)."""
    with tempfile.TemporaryDirectory() as tmp:
        index_root = Path(tmp) / "index"
        books_dir = index_root / "books"
        books_dir.mkdir(parents=True)
        book_id = "bid1"
        book_dir = books_dir / book_id
        book_dir.mkdir()
        (book_dir / "chunks.jsonl").write_text(
            '{"text":"valid chunk content here","book_name":"B","page_start":1,"page_end":1}\n'
        )
        (book_dir / "book.json").write_text(json.dumps({
            "book_id": book_id,
            "filename": "B.pdf",
            "title": "B",
            "status": "ready",
            "chunk_count": 1,
            "updated_at": "2025-01-01T00:00:00Z",
        }))
        lib = {"version": "0.2", "books": [{"book_id": book_id, "filename": "B.pdf", "status": "ready", "chunk_count": 1}]}
        (index_root / "library.json").write_text(json.dumps(lib))

        with patch("scripts.ingest_library.rebuild_search_index") as mock_rebuild:
            result = repair_library(index_root, mode="repair", prune_tmp=False)
            mock_rebuild.assert_not_called()

        assert result["report"]["repairs_changed_state"] is False
        assert result["report"]["rebuilt_search_index"] is False


def test_verify_mode_does_not_write():
    """Verify mode scans and reports but does not write book.json or library.json."""
    with tempfile.TemporaryDirectory() as tmp:
        index_root = Path(tmp) / "index"
        books_dir = index_root / "books"
        books_dir.mkdir(parents=True)
        book_id = "v1"
        book_dir = books_dir / book_id
        book_dir.mkdir()
        (book_dir / "chunks.jsonl").write_text(
            '{"text":"v","book_name":"V","page_start":1,"page_end":1}\n'
        )
        # No book.json - verify would report it as repairable

        result = repair_library(index_root, mode="verify", prune_tmp=False)

        assert not (book_dir / "book.json").exists()
        assert not (index_root / "library.json").exists()
        assert result["report"]["repaired_books"]
        assert result["report"]["rebuilt_library_json"] is False


def test_repair_endpoint_returns_report():
    """POST /index/repair returns RepairResponse with report and stats."""
    with tempfile.TemporaryDirectory() as tmp:
        index_root = Path(tmp) / "index"
        index_root.mkdir()
        pdf_dir = Path(tmp) / "pdfs"
        pdf_dir.mkdir()
        books_dir = index_root / "books"
        books_dir.mkdir(parents=True)
        book_id = "e2e1"
        book_dir = books_dir / book_id
        book_dir.mkdir()
        (book_dir / "chunks.jsonl").write_text(
            '{"text":"endpoint test","book_name":"E","page_start":1,"page_end":1}\n'
        )

        settings = _override_settings(index_root, pdf_dir)
        app.dependency_overrides[get_settings] = lambda: settings
        with patch("scripts.ingest_library.rebuild_search_index"):
            try:
                client = TestClient(app)
                resp = client.post("/index/repair", json={"index_root": str(index_root), "mode": "repair"})
                assert resp.status_code == 200
                body = resp.json()
                assert body["ok"] is True
                assert "report" in body
                report = body["report"]
                assert "scanned_books" in report
                assert "repaired_books" in report
                assert "error_books" in report
                assert "pruned_tmp_count" in report
                assert "rebuilt_library_json" in report
                assert "rebuilt_search_index" in report
                assert "consistency" in report
                assert "stats" in body
            finally:
                app.dependency_overrides.clear()
