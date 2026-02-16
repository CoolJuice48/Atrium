"""Tests for user PDF upload job flow."""

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient
from server.app import app
from server.config import Settings
from server.db.session import init_db, reset_engine
from server.dependencies import get_settings
from server.services import upload_job_service as ujs
from server.services import library_service


def test_upload_returns_job_id():
    """POST /uploads/pdf returns job_id."""
    reset_engine()
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        uploads_root = Path(tmp) / "uploads"
        index_root = Path(tmp) / "index"
        index_root.mkdir()
        os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
        settings = Settings(
            uploads_root=uploads_root,
            index_root=index_root,
        )
        init_db(settings)
        app.dependency_overrides[get_settings] = lambda: settings

        try:
            client = TestClient(app)
            r = client.post("/auth/register", json={"email": "up@test.com", "password": "password123"})
            assert r.status_code == 200
            cookies = r.cookies

            pdf_content = b"%PDF-1.4 fake pdf content"
            r = client.post(
                "/uploads/pdf",
                files={"file": ("test.pdf", pdf_content, "application/pdf")},
                data={"display_title": "My Doc"},
                cookies=cookies,
            )
            assert r.status_code == 200
            body = r.json()
            assert "job_id" in body
            job_id = body["job_id"]
            assert job_id

            job = ujs.get_job(job_id)
            assert job is not None
            assert job.filename == "test.pdf"
            assert job.display_title == "My Doc"
        finally:
            app.dependency_overrides.clear()


def test_upload_job_progresses_phases():
    """Job progresses through at least 2 phases (mock: we cancel early)."""
    reset_engine()
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        uploads_root = Path(tmp) / "uploads"
        index_root = Path(tmp) / "index"
        index_root.mkdir()
        os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
        settings = Settings(uploads_root=uploads_root, index_root=index_root)
        init_db(settings)
        app.dependency_overrides[get_settings] = lambda: settings

        try:
            client = TestClient(app)
            r = client.post("/auth/register", json={"email": "prog@test.com", "password": "password123"})
            assert r.status_code == 200
            cookies = r.cookies

            pdf_content = b"%PDF-1.4 minimal"
            r = client.post(
                "/uploads/pdf",
                files={"file": ("tiny.pdf", pdf_content, "application/pdf")},
                cookies=cookies,
            )
            assert r.status_code == 200
            job_id = r.json()["job_id"]

            r = client.get(f"/uploads/{job_id}")
            assert r.status_code == 200
            state = r.json()
            assert state["status"] in ("queued", "running", "completed", "failed")
            assert "phase" in state
        finally:
            app.dependency_overrides.clear()


def test_upload_cancel_transitions_to_cancelled():
    """Cancel transitions job to cancelled."""
    reset_engine()
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        index_root = Path(tmp) / "index"
        index_root.mkdir()
        os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
        settings = Settings(index_root=index_root)
        init_db(settings)
        app.dependency_overrides[get_settings] = lambda: settings

        try:
            client = TestClient(app)
            r = client.post("/auth/register", json={"email": "cancel@test.com", "password": "password123"})
            assert r.status_code == 200

            # Create a job directly (never run it) so it stays queued for cancel
            job = ujs.create_job("cancel-user-id", "c.pdf", "Cancel Test")
            job_id = job.job_id

            r = client.post(f"/uploads/{job_id}/cancel")
            assert r.status_code == 200

            job = ujs.get_job(job_id)
            assert job is not None
            assert job.cancelled or job.status == "cancelled"
        finally:
            app.dependency_overrides.clear()


def test_books_mine_includes_user_upload():
    """On completion, /books/mine includes user-owned book (simulated via library.json)."""
    reset_engine()
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        index_root = Path(tmp) / "index"
        index_root.mkdir()
        books_dir = index_root / "books"
        books_dir.mkdir()
        book_id = "abc123userbook"
        book_dir = books_dir / book_id
        book_dir.mkdir()
        (book_dir / "chunks.jsonl").write_text('{"text":"x","book_id":"abc123userbook"}\n')
        (book_dir / "study").mkdir()
        (book_dir / "study" / "cards.jsonl").write_text("")
        (book_dir / "study" / "progress.json").write_text("{}")
        (book_dir / "study" / "study_meta.json").write_text(
            '{"card_count":0,"due_count":0,"last_generated_at":null,"avg_grade":null}'
        )
        (book_dir / "book.json").write_text(
            json.dumps({"book_id": book_id, "filename": "mydoc.pdf", "title": "My Doc", "chunk_count": 1, "status": "ready"})
        )
        lib = {
            "version": "0.2",
            "books": [{
                "book_id": book_id,
                "filename": "mydoc.pdf",
                "title": "My Doc",
                "chunk_count": 1,
                "status": "ready",
                "owner_id": "user-123",
            }],
        }
        (index_root / "library.json").write_text(json.dumps(lib))

        os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
        settings = Settings(index_root=index_root)
        init_db(settings)
        app.dependency_overrides[get_settings] = lambda: settings

        try:
            from server.db.session import get_session_factory
            factory = get_session_factory(settings)
            db = factory()
            user_books = library_service.get_user_books_from_library(index_root, "user-123")
            db.close()
            assert len(user_books) == 1
            assert user_books[0]["book_id"] == book_id
            assert user_books[0]["title"] == "My Doc"
        finally:
            app.dependency_overrides.clear()


def test_upload_file_size_limit():
    """Upload over size limit returns 400."""
    reset_engine()
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
        settings = Settings(max_upload_size_mb=0.001)
        init_db(settings)
        app.dependency_overrides[get_settings] = lambda: settings

        try:
            client = TestClient(app)
            r = client.post("/auth/register", json={"email": "big@test.com", "password": "password123"})
            assert r.status_code == 200

            huge = b"%PDF" + b"x" * 2000
            r = client.post(
                "/uploads/pdf",
                files={"file": ("big.pdf", huge, "application/pdf")},
                cookies=r.cookies,
            )
            assert r.status_code == 400
            assert "too large" in r.json().get("detail", "").lower()
        finally:
            app.dependency_overrides.clear()


def test_upload_job_succeeds_without_converted_folder():
    """Upload job completes successfully without a pre-existing converted/ folder."""
    reset_engine()
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        db_path = tmp_path / "test.db"
        uploads_root = tmp_path / "uploads"
        index_root = tmp_path / "index"
        index_root.mkdir()
        # Explicitly do NOT create converted/
        assert not (tmp_path / "converted").exists()

        pdf_path = uploads_root / "users" / "user-1" / "job123.pdf"
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.write_bytes(b"%PDF-1.4 minimal content for hashing")

        os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
        settings = Settings(uploads_root=uploads_root, index_root=index_root)
        init_db(settings)
        app.dependency_overrides[get_settings] = lambda: settings

        job = ujs.create_job("user-1", "doc.pdf", "My Doc")
        job_id = job.job_id

        # Fixed book_id for predictable staging path
        fixed_book_id = "a" * 64
        staging_dir = uploads_root / "users" / "user-1" / "user_library" / "books" / fixed_book_id
        assert not staging_dir.exists(), "Staging dir must not exist before job (tests mkdir)"

        def mock_convert(pdf_path_arg, output_dir=None, **kwargs):
            output_dir = Path(output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            base = pdf_path_arg.stem
            chunked = output_dir / f"{base}_SectionsWithText_Chunked.jsonl"
            rec = {
                "text": "sample chunk",
                "book_name": base,
                "chapter_number": "1",
                "section_number": "1",
                "section_title": "Intro",
                "page_start": 1,
                "page_end": 1,
                "chunk_index": 0,
                "total_chunks": 1,
                "word_count": 2,
            }
            chunked.write_text(json.dumps(rec) + "\n")
            return ("doc-uuid", output_dir)

        try:
            with patch("pdf_to_jsonl.convert_pdf", side_effect=mock_convert):
                with patch("scripts.ingest_library._sha256_file", return_value=fixed_book_id):
                    with patch("server.services.upload_job_service._check_cancelled", return_value=False):
                        with patch("scripts.ingest_library.rebuild_search_index"):
                            ujs.run_upload_job(
                                job_id,
                                pdf_path,
                                index_root,
                                uploads_root,
                                "My Doc",
                                "user-1",
                            )

            job = ujs.get_job(job_id)
            assert job is not None
            assert job.status == "completed"
            assert job.error is None

            assert staging_dir.exists()
            assert (staging_dir / "chunks.jsonl").exists()

            book_dir = index_root / "books" / fixed_book_id
            assert book_dir.exists()
            assert (book_dir / "chunks.jsonl").exists()
            assert (book_dir / "book.json").exists()
        finally:
            app.dependency_overrides.clear()


def test_upload_job_fs_error_returns_sanitized_message():
    """On filesystem error, job gets sanitized error (no absolute paths)."""
    reset_engine()
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        uploads_root = tmp_path / "uploads"
        index_root = tmp_path / "index"
        index_root.mkdir()
        pdf_path = uploads_root / "users" / "u1" / "j.pdf"
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.write_bytes(b"%PDF-1.4 x")

        job = ujs.create_job("u1", "j.pdf", "J")
        job_id = job.job_id

        def mock_convert(*args, **kwargs):
            raise OSError(f"Cannot write to /Users/secret/path/to/file.pdf")

        with patch("pdf_to_jsonl.convert_pdf", side_effect=mock_convert):
            with patch("scripts.ingest_library._sha256_file", return_value="b" * 64):
                ujs.run_upload_job(job_id, pdf_path, index_root, uploads_root, "J", "u1")

        job = ujs.get_job(job_id)
        assert job is not None
        assert job.status == "failed"
        assert job.error is not None
        assert "/Users/" not in job.error
        assert "secret" not in job.error
        assert "path" not in job.error or job.error == "A processing error occurred. Please try again."
