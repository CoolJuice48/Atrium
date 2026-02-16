"""Tests for Study Artifacts v0.1: per-book cards, progress, generate, due, review."""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from study import artifacts as study_artifacts
from server.services import study_artifacts_service
from fastapi.testclient import TestClient
from server.app import app
from server.config import Settings
from server.dependencies import get_settings


def _book_fixture(tmp: Path, book_id: str = "abc123") -> Path:
    """Create a book folder with chunks.jsonl."""
    index_root = tmp / "index"
    book_dir = index_root / "books" / book_id
    book_dir.mkdir(parents=True)
    chunks = [
        {"text": "Machine learning is a subset of artificial intelligence.", "book_id": book_id, "chunk_index": 0, "page_start": 1, "page_end": 1},
        {"text": "Neural networks consist of layers of neurons.", "book_id": book_id, "chunk_index": 1, "page_start": 2, "page_end": 2},
        {"text": "Gradient descent optimizes the loss function.", "book_id": book_id, "chunk_index": 2, "page_start": 3, "page_end": 3},
    ]
    with open(book_dir / "chunks.jsonl", "w") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    lib = {
        "version": "0.2",
        "books": [{"book_id": book_id, "filename": "test.pdf", "title": "Test", "status": "ready", "chunk_count": 3}],
    }
    (index_root / "library.json").write_text(json.dumps(lib))
    return index_root


def test_generate_creates_cards_and_progress():
    """generate creates cards.jsonl and progress.json, dedupes by chunk_id."""
    with tempfile.TemporaryDirectory() as tmp:
        index_root = _book_fixture(Path(tmp))
        book_id = "abc123"
        book_dir = index_root / "books" / book_id

        result = study_artifacts.generate_cards_for_book(index_root, book_id, max_cards=5)

        assert result["generated_count"] >= 1
        assert (book_dir / "study" / "cards.jsonl").exists()
        assert (book_dir / "study" / "progress.json").exists()
        assert (book_dir / "study" / "study_meta.json").exists()

        cards = study_artifacts.load_cards(book_dir)
        progress = study_artifacts.load_progress(book_dir)
        assert len(cards) == result["generated_count"]
        assert len(progress) == len(cards)
        chunk_ids = [c["chunk_id"] for c in cards]
        assert len(chunk_ids) == len(set(chunk_ids))


def test_generate_dedupes_by_chunk_id():
    """Second generate skips chunks that already have cards."""
    with tempfile.TemporaryDirectory() as tmp:
        index_root = _book_fixture(Path(tmp))
        book_id = "abc123"

        r1 = study_artifacts.generate_cards_for_book(index_root, book_id, max_cards=10)
        r2 = study_artifacts.generate_cards_for_book(index_root, book_id, max_cards=10)

        assert r1["generated_count"] >= 1
        assert r2["generated_count"] == 0
        assert r2["skipped_count"] >= r1["generated_count"]


def test_due_returns_only_cards_with_due_at_before_now():
    """due returns only cards with due_at <= now."""
    with tempfile.TemporaryDirectory() as tmp:
        index_root = _book_fixture(Path(tmp))
        book_id = "abc123"
        book_dir = index_root / "books" / book_id
        study_artifacts.generate_cards_for_book(index_root, book_id, max_cards=2)

        due = study_artifacts.get_due_cards(book_dir, limit=20)
        assert len(due) >= 1
        assert all("question" in c and "answer" in c for c in due)


def test_review_updates_interval_ease():
    """review updates interval/ease in expected direction (grade>=3 grows, grade<3 resets)."""
    with tempfile.TemporaryDirectory() as tmp:
        index_root = _book_fixture(Path(tmp))
        book_id = "abc123"
        book_dir = index_root / "books" / book_id
        study_artifacts.generate_cards_for_book(index_root, book_id, max_cards=1)
        cards = study_artifacts.load_cards(book_dir)
        card_id = cards[0]["card_id"]

        r_bad = study_artifacts.review_card(book_dir, card_id, grade=1)
        assert r_bad["interval_days"] == 0.0

        r_good = study_artifacts.review_card(book_dir, card_id, grade=5)
        assert r_good["interval_days"] >= 1.0
        assert r_good["ease"] >= 1.3


def test_exam_generate_returns_questions():
    """POST /books/{book_id}/study/exam/generate returns ok, book_id, title, exam, meta."""
    with tempfile.TemporaryDirectory() as tmp:
        index_root = _book_fixture(Path(tmp))
        book_id = "abc123"
        settings = Settings(index_root=index_root)
        app.dependency_overrides[get_settings] = lambda: settings
        try:
            client = TestClient(app)
            resp = client.post(
                f"/books/{book_id}/study/exam/generate",
                json={"exam_size": 10, "seed": 42},
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body.get("ok") is True
            assert body["book_id"] == book_id
            assert "title" in body
            assert "exam" in body
            assert "questions" in body["exam"]
            assert "meta" in body
            assert "counts_by_type" in body["meta"]
            questions = body["exam"]["questions"]
            assert body["meta"]["total"] == len(questions)
            for q in questions:
                assert "card_id" in q
                assert "prompt" in q
                assert "answer" in q
                assert "card_type" in q
        finally:
            app.dependency_overrides.clear()


def test_exam_generate_book_not_found():
    """Exam generate returns 404 for unknown book."""
    with tempfile.TemporaryDirectory() as tmp:
        index_root = Path(tmp) / "index"
        index_root.mkdir()
        (index_root / "library.json").write_text('{"version":"0.2","books":[]}')
        settings = Settings(index_root=index_root)
        app.dependency_overrides[get_settings] = lambda: settings
        try:
            client = TestClient(app)
            resp = client.post("/books/nonexistent/study/exam/generate", json={})
            assert resp.status_code == 404
        finally:
            app.dependency_overrides.clear()


def test_exam_generate_no_text_extracted_returns_400():
    """Exam generate returns 400 when book has chunks but no extractable text."""
    with tempfile.TemporaryDirectory() as tmp:
        index_root = Path(tmp) / "index"
        book_id = "empty123"
        book_dir = index_root / "books" / book_id
        book_dir.mkdir(parents=True)
        chunks = [
            {"text": "", "book_id": book_id, "chunk_index": 0},
            {"text": "   ", "book_id": book_id, "chunk_index": 1},
        ]
        with open(book_dir / "chunks.jsonl", "w") as f:
            for c in chunks:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")
        lib = {"version": "0.2", "books": [{"book_id": book_id, "filename": "empty.pdf", "title": "Empty", "status": "ready", "chunk_count": 2}]}
        (index_root / "library.json").write_text(json.dumps(lib))
        settings = Settings(index_root=index_root)
        app.dependency_overrides[get_settings] = lambda: settings
        try:
            client = TestClient(app)
            resp = client.post(f"/books/{book_id}/study/exam/generate", json={})
            assert resp.status_code == 400
            assert "No text extracted" in resp.json().get("detail", "")
        finally:
            app.dependency_overrides.clear()


def test_verify_study_creates_missing_files():
    """verify_study creates study folder and files if missing."""
    with tempfile.TemporaryDirectory() as tmp:
        index_root = _book_fixture(Path(tmp))
        book_id = "abc123"
        book_dir = index_root / "books" / book_id
        study_dir = book_dir / "study"
        if study_dir.exists():
            import shutil
            shutil.rmtree(study_dir)

        study_artifacts.verify_study(index_root, book_id)

        assert (book_dir / "study" / "cards.jsonl").exists()
        assert (book_dir / "study" / "progress.json").exists()
        assert (book_dir / "study" / "study_meta.json").exists()


def test_endpoint_generate():
    """POST /books/{book_id}/study/generate returns report."""
    with tempfile.TemporaryDirectory() as tmp:
        index_root = _book_fixture(Path(tmp))
        book_id = "abc123"
        pdf_dir = Path(tmp) / "pdfs"
        pdf_dir.mkdir()
        settings = Settings(
            index_root=index_root,
            pdf_dir=pdf_dir,
            study_db_path=index_root / "study_cards.jsonl",
            session_log_path=index_root / "session_log.jsonl",
            graph_registry_path=index_root / "graph_registry.json",
            golden_sets_dir=index_root / "golden_sets",
        )
        app.dependency_overrides[get_settings] = lambda: settings
        try:
            client = TestClient(app)
            resp = client.post(f"/books/{book_id}/study/generate", json={"max_cards": 5})
            assert resp.status_code == 200
            body = resp.json()
            assert "generated_count" in body
            assert "skipped_count" in body
            assert "elapsed_ms" in body
        finally:
            app.dependency_overrides.clear()


def test_endpoint_due():
    """GET /books/{book_id}/study/due returns due cards."""
    with tempfile.TemporaryDirectory() as tmp:
        index_root = _book_fixture(Path(tmp))
        book_id = "abc123"
        study_artifacts.generate_cards_for_book(index_root, book_id, max_cards=2)
        pdf_dir = Path(tmp) / "pdfs"
        pdf_dir.mkdir()
        settings = Settings(
            index_root=index_root,
            pdf_dir=pdf_dir,
            study_db_path=index_root / "study_cards.jsonl",
            session_log_path=index_root / "session_log.jsonl",
            graph_registry_path=index_root / "graph_registry.json",
            golden_sets_dir=index_root / "golden_sets",
        )
        app.dependency_overrides[get_settings] = lambda: settings
        try:
            client = TestClient(app)
            resp = client.get(f"/books/{book_id}/study/due")
            assert resp.status_code == 200
            body = resp.json()
            assert "cards" in body
            assert isinstance(body["cards"], list)
        finally:
            app.dependency_overrides.clear()


def test_endpoint_review():
    """POST /books/{book_id}/study/review updates card."""
    with tempfile.TemporaryDirectory() as tmp:
        index_root = _book_fixture(Path(tmp))
        book_id = "abc123"
        study_artifacts.generate_cards_for_book(index_root, book_id, max_cards=1)
        cards = study_artifacts.load_cards(index_root / "books" / book_id)
        card_id = cards[0]["card_id"]
        pdf_dir = Path(tmp) / "pdfs"
        pdf_dir.mkdir()
        settings = Settings(
            index_root=index_root,
            pdf_dir=pdf_dir,
            study_db_path=index_root / "study_cards.jsonl",
            session_log_path=index_root / "session_log.jsonl",
            graph_registry_path=index_root / "graph_registry.json",
            golden_sets_dir=index_root / "golden_sets",
        )
        app.dependency_overrides[get_settings] = lambda: settings
        try:
            client = TestClient(app)
            resp = client.post(f"/books/{book_id}/study/review", json={"card_id": card_id, "grade": 4})
            assert resp.status_code == 200
            body = resp.json()
            assert "ease" in body
            assert "interval_days" in body
            assert "due_at" in body
        finally:
            app.dependency_overrides.clear()


def test_get_books_returns_study_stats():
    """GET /books returns books with study stats (requires auth)."""
    import os
    from server.db.session import init_db, reset_engine

    reset_engine()
    with tempfile.TemporaryDirectory() as tmp:
        index_root = _book_fixture(Path(tmp))
        book_id = "abc123"
        study_artifacts.generate_cards_for_book(index_root, book_id, max_cards=2)
        pdf_dir = Path(tmp) / "pdfs"
        pdf_dir.mkdir()
        db_path = Path(tmp) / "test.db"
        os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
        settings = Settings(
            index_root=index_root,
            pdf_dir=pdf_dir,
            study_db_path=index_root / "study_cards.jsonl",
            session_log_path=index_root / "session_log.jsonl",
            graph_registry_path=index_root / "graph_registry.json",
            golden_sets_dir=index_root / "golden_sets",
        )
        init_db(settings)
        app.dependency_overrides[get_settings] = lambda: settings
        try:
            client = TestClient(app)
            r = client.post("/auth/register", json={"email": "books@test.com", "password": "password123"})
            assert r.status_code == 200
            resp = client.get("/books", cookies=r.cookies)
            assert resp.status_code == 200
            body = resp.json()
            assert "books" in body
            assert len(body["books"]) >= 1
            b = body["books"][0]
            assert "book_id" in b
            assert "study" in b
            assert "card_count" in b["study"]
            assert "due_count" in b["study"]
        finally:
            app.dependency_overrides.clear()
