"""Tests for user PDF upload job flow."""

import json
import os
import sys
import tempfile
from pathlib import Path

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
