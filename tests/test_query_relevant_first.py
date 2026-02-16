"""Tests for relevant-first retrieval and library integration."""

import json
import os
import pickle
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sklearn.feature_extraction.text import TfidfVectorizer

from fastapi.testclient import TestClient
from server.app import app
from server.config import Settings
from server.dependencies import get_settings
from server.services import query_service


def _build_mini_index_with_book_ids(index_dir: Path, metadatas_with_book_id: list):
    """Build TF-IDF index with book_id in metadata."""
    documents = [m.get("_text", "Sample text.") for m in metadatas_with_book_id]
    metadatas = [{k: v for k, v in m.items() if k != "_text"} for m in metadatas_with_book_id]

    index_dir.mkdir(parents=True, exist_ok=True)
    with open(index_dir / "data.json", "w") as f:
        json.dump({"documents": documents, "metadatas": metadatas}, f)

    vectorizer = TfidfVectorizer(
        max_features=10000,
        stop_words="english",
        ngram_range=(1, 2),
        min_df=1,
        max_df=0.95,
    )
    vectors = vectorizer.fit_transform(documents)
    with open(index_dir / "vectorizer.pkl", "wb") as f:
        pickle.dump(vectorizer, f)
    with open(index_dir / "vectors.pkl", "wb") as f:
        pickle.dump(vectors, f)


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


def test_query_response_includes_meta():
    """Query response includes meta.search_ms and meta.expanded."""
    with tempfile.TemporaryDirectory() as tmp:
        index_dir = Path(tmp) / "index"
        metadatas = [
            {
                "book": "BookA",
                "book_id": "id_a",
                "chapter": "1",
                "section": "1.1",
                "section_title": "Intro",
                "pages": "1-2",
                "chunk_index": 0,
                "total_chunks": 1,
                "word_count": 10,
                "_text": "Gradient descent optimizes machine learning models.",
            },
        ]
        _build_mini_index_with_book_ids(index_dir, metadatas)

        query_service._searcher_cache.clear()
        app.dependency_overrides[get_settings] = lambda: _override_settings(index_dir)
        try:
            client = TestClient(app)
            resp = client.post("/query", json={"question": "What is gradient descent?", "top_k": 3})
            assert resp.status_code == 200
            body = resp.json()
            assert "meta" in body
            assert "search_ms" in body["meta"]
            assert "expanded" in body["meta"]
        finally:
            app.dependency_overrides.clear()
            query_service._searcher_cache.clear()


def test_query_restricts_to_candidate_books_when_library_exists():
    """When select_candidate_books returns subset, query restricts results to those books."""
    with tempfile.TemporaryDirectory() as tmp:
        index_dir = Path(tmp) / "index"
        index_dir.mkdir()

        # Two books: GradientBook (matches "gradient") and OtherBook (doesn't match)
        metadatas = [
            {
                "book": "GradientBook",
                "book_id": "grad_book_id",
                "chapter": "1",
                "section": "1",
                "section_title": "Gradient",
                "pages": "1-2",
                "chunk_index": 0,
                "total_chunks": 1,
                "word_count": 10,
                "_text": "Gradient descent is an optimization algorithm.",
            },
            {
                "book": "OtherBook",
                "book_id": "other_book_id",
                "chapter": "1",
                "section": "1",
                "section_title": "Other",
                "pages": "1-2",
                "chunk_index": 0,
                "total_chunks": 1,
                "word_count": 10,
                "_text": "Neural networks have many layers.",
            },
        ]
        _build_mini_index_with_book_ids(index_dir, metadatas)

        # Library with both books; GradientBook.pdf matches "gradient" keyword
        lib = {
            "version": "0.2",
            "books": [
                {
                    "book_id": "grad_book_id",
                    "filename": "GradientBook.pdf",
                    "title": "GradientBook",
                    "status": "ready",
                    "chunk_count": 1,
                },
                {
                    "book_id": "other_book_id",
                    "filename": "OtherBook.pdf",
                    "title": "OtherBook",
                    "status": "ready",
                    "chunk_count": 1,
                },
            ],
        }
        with open(index_dir / "library.json", "w") as f:
            json.dump(lib, f)

        # Create book dirs for verify
        for bid in ["grad_book_id", "other_book_id"]:
            (index_dir / "books" / bid).mkdir(parents=True)
            (index_dir / "books" / bid / "chunks.jsonl").write_text('{"text":"x"}\n')
            (index_dir / "books" / bid / "book.json").write_text("{}")

        query_service._searcher_cache.clear()
        app.dependency_overrides[get_settings] = lambda: _override_settings(index_dir)
        try:
            client = TestClient(app)
            # "gradient" matches GradientBook.pdf -> candidates = [grad_book_id]
            resp = client.post("/query", json={"question": "gradient descent algorithm", "top_k": 5})
            assert resp.status_code == 200
            body = resp.json()
            # Primary search restricted to grad_book_id; results should be from GradientBook
            chunks = body.get("retrieved_chunks", [])
            if chunks:
                for c in chunks:
                    meta = c.get("metadata", {})
                    assert meta.get("book_id") == "grad_book_id" or meta.get("book") == "GradientBook"
        finally:
            app.dependency_overrides.clear()
            query_service._searcher_cache.clear()


def test_query_expands_when_confidence_low():
    """When hits < MIN_HITS_PRIMARY or top_score < threshold, query expands to all books."""
    with tempfile.TemporaryDirectory() as tmp:
        index_dir = Path(tmp) / "index"
        index_dir.mkdir()

        # One book matching "gradient"; only 1 chunk -> hits=1 < MIN_HITS_PRIMARY=5
        metadatas = [
            {
                "book": "GradientBook",
                "book_id": "grad_id",
                "chapter": "1",
                "section": "1",
                "section_title": "Gradient",
                "pages": "1-2",
                "chunk_index": 0,
                "total_chunks": 1,
                "word_count": 10,
                "_text": "Gradient descent optimizes.",
            },
            {
                "book": "OtherBook",
                "book_id": "other_id",
                "chapter": "1",
                "section": "1",
                "section_title": "Other",
                "pages": "1-2",
                "chunk_index": 0,
                "total_chunks": 1,
                "word_count": 10,
                "_text": "Neural networks learn.",
            },
        ]
        _build_mini_index_with_book_ids(index_dir, metadatas)

        lib = {
            "version": "0.2",
            "books": [
                {"book_id": "grad_id", "filename": "GradientBook.pdf", "status": "ready", "chunk_count": 1},
                {"book_id": "other_id", "filename": "OtherBook.pdf", "status": "ready", "chunk_count": 1},
            ],
        }
        with open(index_dir / "library.json", "w") as f:
            json.dump(lib, f)

        for bid in ["grad_id", "other_id"]:
            (index_dir / "books" / bid).mkdir(parents=True)
            (index_dir / "books" / bid / "chunks.jsonl").write_text('{"text":"x"}\n')
            (index_dir / "books" / bid / "book.json").write_text("{}")

        query_service._searcher_cache.clear()
        app.dependency_overrides[get_settings] = lambda: _override_settings(index_dir)
        try:
            client = TestClient(app)
            resp = client.post("/query", json={"question": "gradient optimization", "top_k": 5})
            assert resp.status_code == 200
            body = resp.json()
            # With 1 hit from primary (grad_id only), we expand; meta.expanded should be True
            assert body.get("meta", {}).get("expanded") is True
        finally:
            app.dependency_overrides.clear()
            query_service._searcher_cache.clear()


def test_inconsistent_book_excluded_from_search():
    """When library has one broken book, that book is excluded from search."""
    with tempfile.TemporaryDirectory() as tmp:
        index_dir = Path(tmp) / "index"
        index_dir.mkdir()

        # Only valid book's chunks in index
        metadatas = [
            {
                "book": "ValidBook",
                "book_id": "valid_id",
                "chapter": "1",
                "section": "1",
                "section_title": "Intro",
                "pages": "1-2",
                "chunk_index": 0,
                "total_chunks": 1,
                "word_count": 10,
                "_text": "This is valid content.",
            },
        ]
        _build_mini_index_with_book_ids(index_dir, metadatas)

        # Library: valid_id (has folder) + broken_id (no folder - inconsistent)
        lib = {
            "version": "0.2",
            "books": [
                {"book_id": "valid_id", "filename": "ValidBook.pdf", "status": "ready", "chunk_count": 1},
                {"book_id": "broken_id", "filename": "BrokenBook.pdf", "status": "ready", "chunk_count": 1},
            ],
        }
        with open(index_dir / "library.json", "w") as f:
            json.dump(lib, f)

        # Only valid_id has folder; broken_id has no folder
        (index_dir / "books" / "valid_id").mkdir(parents=True)
        (index_dir / "books" / "valid_id" / "chunks.jsonl").write_text('{"text":"x"}\n')
        (index_dir / "books" / "valid_id" / "book.json").write_text("{}")

        query_service._searcher_cache.clear()
        app.dependency_overrides[get_settings] = lambda: _override_settings(index_dir)
        try:
            client = TestClient(app)
            resp = client.post("/query", json={"question": "valid content", "top_k": 5})
            assert resp.status_code == 200
            # valid_book_ids = [valid_id] only; broken_id excluded
            # Query should succeed and return results from valid_id
            body = resp.json()
            assert "answer" in body or body.get("retrieved_chunks")
        finally:
            app.dependency_overrides.clear()
            query_service._searcher_cache.clear()


def test_query_returns_503_when_library_exists_but_all_books_inconsistent():
    """When library exists but valid_book_ids is empty, /query returns 503."""
    with tempfile.TemporaryDirectory() as tmp:
        index_dir = Path(tmp) / "index"
        index_dir.mkdir()

        lib = {
            "version": "0.2",
            "books": [
                {"book_id": "broken1", "filename": "Broken1.pdf", "status": "ready", "chunk_count": 1},
                {"book_id": "broken2", "filename": "Broken2.pdf", "status": "ready", "chunk_count": 1},
            ],
        }
        with open(index_dir / "library.json", "w") as f:
            json.dump(lib, f)

        query_service._searcher_cache.clear()
        from server.library import invalidate_verify_cache
        invalidate_verify_cache(index_dir)
        app.dependency_overrides[get_settings] = lambda: _override_settings(index_dir)
        try:
            client = TestClient(app)
            resp = client.post("/query", json={"question": "test", "top_k": 5})
            assert resp.status_code == 503
            assert "no valid books" in resp.json().get("detail", "").lower()
        finally:
            app.dependency_overrides.clear()
            query_service._searcher_cache.clear()


def test_verify_library_caching_reduces_calls():
    """Two verify_library_cached calls with same lib use cache (verify_library called once)."""
    from server.library import verify_library, verify_library_cached

    call_count = 0
    original = verify_library

    def counted_verify(idx, lib):
        nonlocal call_count
        call_count += 1
        return original(idx, lib)

    with tempfile.TemporaryDirectory() as tmp:
        index_dir = Path(tmp) / "index"
        index_dir.mkdir()
        lib = {
            "version": "0.2",
            "books": [{"book_id": "x", "filename": "X.pdf", "status": "ready", "chunk_count": 1}],
        }
        with open(index_dir / "library.json", "w") as f:
            json.dump(lib, f)
        (index_dir / "books" / "x").mkdir(parents=True)
        (index_dir / "books" / "x" / "chunks.jsonl").write_text('{"text":"x"}\n')
        (index_dir / "books" / "x" / "book.json").write_text("{}")

        with patch("server.library.verify_library", side_effect=counted_verify):
            verify_library_cached(index_dir, lib)
            verify_library_cached(index_dir, lib)
        assert call_count == 1


def test_thresholds_override_via_env():
    """PRIMARY_MIN_HITS and PRIMARY_MIN_TOP_SCORE can be overridden via env."""
    try:
        os.environ["PRIMARY_MIN_HITS"] = "2"
        os.environ["PRIMARY_MIN_TOP_SCORE"] = "0.15"
        settings = Settings()
        assert settings.primary_min_hits == 2
        assert settings.primary_min_top_score == 0.15
    finally:
        os.environ.pop("PRIMARY_MIN_HITS", None)
        os.environ.pop("PRIMARY_MIN_TOP_SCORE", None)


def test_query_meta_includes_debugging_fields():
    """Query meta includes candidate_book_ids_count, valid_book_ids_count, primary_hits, primary_top_score, expanded_reason."""
    with tempfile.TemporaryDirectory() as tmp:
        index_dir = Path(tmp) / "index"
        index_dir.mkdir()
        metadatas = [
            {
                "book": "BookA",
                "book_id": "id_a",
                "chapter": "1",
                "section": "1",
                "section_title": "Intro",
                "pages": "1-2",
                "chunk_index": 0,
                "total_chunks": 1,
                "word_count": 10,
                "_text": "Gradient descent optimizes.",
            },
        ]
        _build_mini_index_with_book_ids(index_dir, metadatas)
        lib = {
            "version": "0.2",
            "books": [{"book_id": "id_a", "filename": "BookA.pdf", "status": "ready", "chunk_count": 1}],
        }
        with open(index_dir / "library.json", "w") as f:
            json.dump(lib, f)
        (index_dir / "books" / "id_a").mkdir(parents=True)
        (index_dir / "books" / "id_a" / "chunks.jsonl").write_text('{"text":"x"}\n')
        (index_dir / "books" / "id_a" / "book.json").write_text("{}")

        query_service._searcher_cache.clear()
        from server.library import invalidate_verify_cache
        invalidate_verify_cache(index_dir)
        app.dependency_overrides[get_settings] = lambda: _override_settings(index_dir)
        try:
            client = TestClient(app)
            resp = client.post("/query", json={"question": "gradient", "top_k": 5})
            assert resp.status_code == 200
            meta = resp.json().get("meta", {})
            assert "candidate_book_ids_count" in meta
            assert "valid_book_ids_count" in meta
            assert "primary_hits" in meta
            assert "primary_top_score" in meta
            assert "expanded_reason" in meta
        finally:
            app.dependency_overrides.clear()
            query_service._searcher_cache.clear()
