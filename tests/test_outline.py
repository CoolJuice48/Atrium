"""Tests for outline and scoped summary."""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.outline import (
    build_outline,
    compute_outline_id,
    filter_chunks_by_page_ranges,
    get_or_build_outline,
    load_outline,
    resolve_scope_to_page_ranges,
    save_outline,
)


def test_outline_generation_produces_stable_items():
    """Outline from chunks produces stable items with correct structure."""
    with tempfile.TemporaryDirectory() as tmp:
        book_dir = Path(tmp) / "books" / "b1"
        book_dir.mkdir(parents=True)
        chunks = [
            {
                "text": "Ch1 intro",
                "chapter_number": "1",
                "section_number": "1.1",
                "section_title": "Introduction",
                "page_start": 10,
                "page_end": 12,
            },
            {
                "text": "Ch1 section 2",
                "chapter_number": "1",
                "section_number": "1.2",
                "section_title": "Background",
                "page_start": 13,
                "page_end": 18,
            },
            {
                "text": "Ch2 intro",
                "chapter_number": "2",
                "section_number": "2.1",
                "section_title": "Methods",
                "page_start": 25,
                "page_end": 30,
            },
        ]
        with open(book_dir / "chunks.jsonl", "w") as f:
            for c in chunks:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")

        outline_id, items = build_outline(book_dir)
        assert outline_id
        assert len(items) >= 2
        ids = {it["id"] for it in items}
        assert any("ch_1" in i for i in ids)
        assert any("ch_2" in i for i in ids)
        for it in items:
            assert "id" in it
            assert "title" in it
            assert "level" in it
            assert "start_page" in it
            assert "end_page" in it
            assert "title_terms" in it
            assert isinstance(it["title_terms"], list)


def test_title_terms_extracted():
    """Outline items expose title_terms (1-3 grams from title, stopword filtered)."""
    with tempfile.TemporaryDirectory() as tmp:
        book_dir = Path(tmp) / "books" / "b1"
        book_dir.mkdir(parents=True)
        chunks = [
            {
                "text": "Content here.",
                "chapter_number": "1",
                "section_number": "1.1",
                "section_title": "Gradient Descent Optimization",
                "page_start": 1,
                "page_end": 5,
            },
        ]
        with open(book_dir / "chunks.jsonl", "w") as f:
            for c in chunks:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")

        outline_id, items = build_outline(book_dir)
        assert outline_id
        section_items = [it for it in items if it.get("level") == 2]
        assert len(section_items) >= 1
        sec = section_items[0]
        terms = sec.get("title_terms", [])
        assert isinstance(terms, list)
        assert len(terms) >= 1
        assert any("gradient" in t or "descent" in t or "optimization" in t for t in terms)


def test_scope_selection_filters_chunks_correctly():
    """filter_chunks_by_page_ranges keeps only chunks in selected ranges."""
    chunks = [
        {"text": "a", "page_start": 1, "page_end": 5},
        {"text": "b", "page_start": 10, "page_end": 15},
        {"text": "c", "page_start": 20, "page_end": 25},
        {"text": "d", "page_start": 30, "page_end": 35},
    ]
    ranges = [(10, 15), (20, 22)]
    filtered = filter_chunks_by_page_ranges(chunks, ranges)
    assert len(filtered) == 2
    assert filtered[0]["text"] == "b"
    assert filtered[1]["text"] == "c"


def test_409_when_outline_id_mismatched():
    """POST summaries returns 409 when outline_id does not match."""
    from fastapi.testclient import TestClient
    from server.app import app
    from server.config import Settings
    from server.dependencies import get_settings

    with tempfile.TemporaryDirectory() as tmp:
        index_dir = Path(tmp) / "index"
        index_dir.mkdir()
        (index_dir / "library.json").write_text(
            '{"version":"0.2","books":[{"book_id":"b1","title":"T","status":"ready"}]}'
        )
        book_dir = index_dir / "books" / "b1"
        book_dir.mkdir(parents=True)
        chunks = [
            {"text": "x", "chapter_number": "1", "section_number": "1", "page_start": 1, "page_end": 5},
        ]
        with open(book_dir / "chunks.jsonl", "w") as f:
            for c in chunks:
                f.write(json.dumps(c) + "\n")
        (book_dir / "book.json").write_text('{"book_id":"b1","title":"T","status":"ready"}')

        settings = Settings(index_root=index_dir)
        app.dependency_overrides[get_settings] = lambda: settings

        try:
            client = TestClient(app)
            resp = client.post(
                f"/books/b1/summaries",
                json={
                    "outline_id": "wrong_id_12345",
                    "scope": {"item_ids": ["ch_1"]},
                },
            )
            assert resp.status_code == 409
            assert "outline" in resp.json().get("detail", "").lower()
        finally:
            app.dependency_overrides.clear()


def test_summary_on_scope_excludes_exercise_prompts():
    """Scoped summary uses summary_compose which filters exercise prompts."""
    from server.services import summary_service

    with tempfile.TemporaryDirectory() as tmp:
        index_dir = Path(tmp) / "index"
        index_dir.mkdir()
        book_dir = index_dir / "books" / "b1"
        book_dir.mkdir(parents=True)
        chunks = [
            {
                "text": "Reinforcement learning is a type of machine learning. "
                "The agent learns by interacting with the environment. "
                "What would the sequence of states be? Exercise 10: Prove convergence.",
                "chapter_number": "1",
                "section_number": "1.1",
                "section_title": "Intro",
                "page_start": 1,
                "page_end": 5,
            },
        ]
        with open(book_dir / "chunks.jsonl", "w") as f:
            for c in chunks:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")

        outline_id, items = build_outline(book_dir)
        assert items
        save_outline(book_dir, outline_id, items)

        result = summary_service.generate_scoped_summary(
            index_dir, "b1", outline_id, [items[0]["id"]], max_pages=50
        )
        summary = result["summary_markdown"]
        assert "reinforcement" in summary.lower() or "agent" in summary.lower()
        assert "What would the sequence" not in summary
        assert "Exercise 10" not in summary
