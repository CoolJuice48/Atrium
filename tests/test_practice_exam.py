"""Tests for scoped practice exam generation."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.outline import build_outline, save_outline
from server.services.exam_candidates import build_candidate_pool
from server.services.exam_stems import validate_definition_term, validate_question_stem
from server.services.exam_generation import generate_exam_questions
from server.services.practice_exam_service import generate_scoped_exam


def test_exam_requires_scope_selection():
    """POST practice-exams returns 400 when no item_ids selected."""
    from fastapi.testclient import TestClient
    from server.app import app
    from server.config import Settings
    from server.dependencies import get_settings

    with __import__("tempfile").TemporaryDirectory() as tmp:
        index_dir = Path(tmp) / "index"
        index_dir.mkdir()
        (index_dir / "library.json").write_text(
            '{"version":"0.2","books":[{"book_id":"b1","title":"T","status":"ready"}]}'
        )
        book_dir = index_dir / "books" / "b1"
        book_dir.mkdir(parents=True)
        chunks = [
            {
                "text": "Machine learning is defined as a subset of AI. It enables systems to learn.",
                "chapter_number": "1",
                "section_number": "1",
                "page_start": 1,
                "page_end": 5,
            },
        ]
        with open(book_dir / "chunks.jsonl", "w") as f:
            for c in chunks:
                f.write(json.dumps(c) + "\n")

        outline_id, items = build_outline(book_dir)
        save_outline(book_dir, outline_id, items)

        settings = Settings(index_root=index_dir)
        app.dependency_overrides[get_settings] = lambda: settings

        try:
            client = TestClient(app)
            resp = client.post(
                "/books/b1/practice-exams",
                json={
                    "outline_id": outline_id,
                    "scope": {"item_ids": []},
                },
            )
            assert resp.status_code == 400
            assert "select" in resp.json().get("detail", "").lower()
        finally:
            app.dependency_overrides.clear()


def test_exam_returns_409_when_outline_id_stale():
    """POST practice-exams returns 409 when outline_id is stale."""
    from fastapi.testclient import TestClient
    from server.app import app
    from server.config import Settings
    from server.dependencies import get_settings

    with __import__("tempfile").TemporaryDirectory() as tmp:
        index_dir = Path(tmp) / "index"
        index_dir.mkdir()
        (index_dir / "library.json").write_text(
            '{"version":"0.2","books":[{"book_id":"b1","title":"T","status":"ready"}]}'
        )
        book_dir = index_dir / "books" / "b1"
        book_dir.mkdir(parents=True)
        chunks = [
            {
                "text": "Gradient descent is defined as an optimization algorithm.",
                "chapter_number": "1",
                "section_number": "1",
                "page_start": 1,
                "page_end": 5,
            },
        ]
        with open(book_dir / "chunks.jsonl", "w") as f:
            for c in chunks:
                f.write(json.dumps(c) + "\n")

        outline_id, items = build_outline(book_dir)
        save_outline(book_dir, outline_id, items)

        settings = Settings(index_root=index_dir)
        app.dependency_overrides[get_settings] = lambda: settings

        try:
            client = TestClient(app)
            resp = client.post(
                "/books/b1/practice-exams",
                json={
                    "outline_id": "stale_wrong_id_xyz",
                    "scope": {"item_ids": [items[0]["id"]]},
                },
            )
            assert resp.status_code == 409
            assert "outline" in resp.json().get("detail", "").lower()
        finally:
            app.dependency_overrides.clear()


def test_candidate_pool_filters_structural_noise():
    """Candidate pool excludes headers, bibliography, exercise prompts."""
    chunks = [
        {"text": "Chapter 3: Methods. This chapter covers the main approach.", "metadata": {"page_start": 1, "page_end": 2, "chunk_id": "c1"}},
        {"text": "References. Smith J (2020). Technical report. University Press.", "metadata": {"page_start": 3, "page_end": 4, "chunk_id": "c2"}},
        {"text": "Exercise 1: Fill in the blank with the correct term.", "metadata": {"page_start": 5, "page_end": 6, "chunk_id": "c3"}},
        {"text": "Gradient descent is defined as an iterative optimization algorithm used to minimize a loss function.", "metadata": {"page_start": 7, "page_end": 8, "chunk_id": "c4"}},
    ]
    pool = build_candidate_pool(chunks)
    texts = [c.text for c in pool.candidates]
    assert not any("Chapter 3" in t and t.startswith("Chapter") for t in texts)
    assert not any("Exercise 1" in t or "Fill in the blank" in t for t in texts)
    assert any("Gradient descent" in t and "defined as" in t for t in texts)


def test_definition_stem_validation_blocks_bad_prompts():
    """Stem validation rejects malformed prompts like 'What is This?' or 'What is because it?'."""
    assert not validate_definition_term("This")
    assert not validate_definition_term("because it")
    assert not validate_definition_term("s right panel")
    assert not validate_definition_term("a")
    assert not validate_question_stem("What is This?")
    assert not validate_question_stem("What is because it?")
    assert validate_definition_term("Machine learning")
    assert validate_definition_term("Gradient descent algorithm")
    assert validate_question_stem("What is gradient descent?")


def test_scope_caps_return_413():
    """Large scope returns 413 with friendly error."""
    from fastapi.testclient import TestClient
    from server.app import app
    from server.config import Settings
    from server.dependencies import get_settings

    with __import__("tempfile").TemporaryDirectory() as tmp:
        index_dir = Path(tmp) / "index"
        index_dir.mkdir()
        (index_dir / "library.json").write_text(
            '{"version":"0.2","books":[{"book_id":"b1","title":"T","status":"ready"}]}'
        )
        book_dir = index_dir / "books" / "b1"
        book_dir.mkdir(parents=True)
        chunks = [
            {
                "text": "Content here. " * 20,
                "chapter_number": "1",
                "section_number": str(i),
                "page_start": i * 5,
                "page_end": i * 5 + 4,
            }
            for i in range(1, 15)
        ]
        with open(book_dir / "chunks.jsonl", "w") as f:
            for c in chunks:
                f.write(json.dumps(c) + "\n")

        outline_id, items = build_outline(book_dir)
        save_outline(book_dir, outline_id, items)
        all_ids = [it["id"] for it in items]

        settings = Settings(index_root=index_dir)
        app.dependency_overrides[get_settings] = lambda: settings

        try:
            client = TestClient(app)
            resp = client.post(
                "/books/b1/practice-exams",
                json={
                    "outline_id": outline_id,
                    "scope": {"item_ids": all_ids},
                    "options": {"max_pages": 10},
                },
            )
            assert resp.status_code == 413
            assert "too large" in resp.json().get("detail", "").lower()
        finally:
            app.dependency_overrides.clear()


def test_exam_generation_reallocates_when_insufficient_candidates():
    """When one type has few candidates, others are used; no garbage output."""
    chunks = [
        {
            "text": "Neural networks are defined as computing systems inspired by biological brains. They consist of layers of nodes.",
            "metadata": {"page_start": 1, "page_end": 2, "chunk_id": "c1"},
        },
        {
            "text": "Backpropagation is defined as the algorithm for training neural networks by gradient descent.",
            "metadata": {"page_start": 3, "page_end": 4, "chunk_id": "c2"},
        },
    ]
    pool = build_candidate_pool(chunks)
    questions = generate_exam_questions(
        pool,
        distribution={"definition": 5, "fib": 5, "tf": 5, "short": 5, "list": 5},
        total=10,
    )
    assert len(questions) <= 10
    assert len(questions) >= 1
    for q in questions:
        assert q.prompt
        assert q.answer
        assert q.q_type in ("definition", "fib", "tf", "short", "list")
        assert not any(bad in q.prompt for bad in ("What is This?", "What is because", "Chapter ", "Figure "))
