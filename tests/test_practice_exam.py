"""Tests for scoped practice exam generation."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.outline import build_outline, save_outline
from server.services.exam_candidates import build_candidate_pool
from server.services.exam_stems import validate_definition_term, validate_question_stem
from server.services.exam_generation import (
    extract_definition_pairs,
    generate_exam_questions,
)
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


def test_definition_generator_rejects_determiner_or_discourse_terms():
    """Terms like 'Any zero in c', 'then high angular velocity' never appear."""
    assert not validate_definition_term("Any zero in c")
    assert not validate_definition_term("then high angular velocity")
    assert not validate_definition_term("this method")
    assert not validate_definition_term("thus the result")
    assert not validate_definition_term("however the case")
    pairs = extract_definition_pairs("Any zero in c is defined as a root of the polynomial.")
    assert not pairs or not validate_definition_term(pairs[0][0])
    pairs = extract_definition_pairs("Then high angular velocity is defined as rotation above 10 rad/s.")
    assert not pairs or not validate_definition_term(pairs[0][0])


def test_definition_generator_requires_explicit_patterns_or_sentence_initial():
    """Only sentence-initial definition patterns are accepted."""
    pairs = extract_definition_pairs("Machine learning is defined as a subset of artificial intelligence.")
    assert len(pairs) == 1
    assert pairs[0][0] == "Machine learning"
    pairs = extract_definition_pairs("In this context, gradient descent refers to the optimization algorithm.")
    assert not pairs


def test_no_mid_clause_definition_extraction():
    """No extraction from mid-sentence."""
    pairs = extract_definition_pairs("The algorithm then high angular velocity is used for simulation.")
    assert not pairs
    pairs = extract_definition_pairs("We see that any zero in c can be computed.")
    assert not pairs


def test_regression_no_garbage_stems():
    """Hard assert no stems start with bad prefixes."""
    bad_prefixes = ("What is Any", "What is then", "What is This", "What is because")
    chunks = [
        {"text": "Any zero in c is defined as a root. Then high angular velocity is defined as rotation.", "metadata": {"page_start": 1, "page_end": 2, "chunk_id": "c1"}},
        {"text": "This is defined as the main method. Because it works well.", "metadata": {"page_start": 3, "page_end": 4, "chunk_id": "c2"}},
    ]
    pool = build_candidate_pool(chunks)
    questions = generate_exam_questions(pool, distribution={"definition": 10}, total=10)
    bad_short_prefixes = ("Why does 4", "Why does This", "Why does then", "Why does Read")
    for q in questions:
        if q.q_type == "definition":
            for bad in bad_prefixes:
                assert not q.prompt.startswith(bad), f"Bad stem: {q.prompt}"
        if q.q_type == "short":
            for bad in bad_short_prefixes:
                assert not q.prompt.startswith(bad), f"Bad short stem: {q.prompt}"


def test_fill_blank_does_not_break_passive_voice():
    """Blanks do not create '______ approximated' or 'is ______ used' artifacts."""
    chunks = [
        {"text": "The loss function is approximated by gradient descent in each iteration.", "metadata": {"page_start": 1, "page_end": 2, "chunk_id": "c1"}},
        {"text": "The loss function is approximated by gradient descent in each iteration.", "metadata": {"page_start": 1, "page_end": 2, "chunk_id": "c1"}},
    ]
    pool = build_candidate_pool(chunks)
    questions = generate_exam_questions(pool, distribution={"fib": 5}, total=5)
    for q in questions:
        if q.q_type == "fib":
            assert "______ approximated" not in q.prompt
            assert "is ______ used" not in q.prompt
            assert "______ used" not in q.prompt or "is ______" not in q.prompt


def test_exam_generation_reallocates_when_insufficient_candidates():
    """When one type has few candidates, others are used; no garbage output."""
    chunks = [
        {
            "text": "Neural networks are defined as computing systems inspired by biological brains. They consist of layers of nodes.",
            "metadata": {"page_start": 1, "page_end": 2, "chunk_id": "c1"},
        },
        {
            "text": "Gradient descent algorithm is defined as the method for training neural networks by backpropagation.",
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
