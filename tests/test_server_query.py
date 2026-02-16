"""Tests for /query and /catalog endpoints."""

import json
import pickle
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sklearn.feature_extraction.text import TfidfVectorizer

from fastapi.testclient import TestClient
from server.app import app
from server.config import Settings
from server.dependencies import get_settings
from server.services import query_service


# ============================================================================
# Helpers
# ============================================================================

def _build_mini_index(index_dir: Path):
    """
    Build a minimal 3-doc TF-IDF index that TextbookSearchOffline can load.

    Creates data.json, vectorizer.pkl, vectors.pkl.
    """
    documents = [
        "Gradient descent is an optimization algorithm used in machine learning.",
        "Neural networks consist of layers of interconnected nodes called neurons.",
        "Backpropagation computes gradients for each weight in the network.",
    ]
    metadatas = [
        {
            'book': 'DeepLearningBook',
            'chapter': '4',
            'section': '4.3',
            'section_title': 'Gradient Descent',
            'pages': '80-83',
            'chunk_index': 0,
            'total_chunks': 1,
            'word_count': 10,
            'chunk_id': 'ch4_s3_c0',
        },
        {
            'book': 'DeepLearningBook',
            'chapter': '6',
            'section': '6.1',
            'section_title': 'Neural Network Basics',
            'pages': '164-170',
            'chunk_index': 0,
            'total_chunks': 1,
            'word_count': 10,
            'chunk_id': 'ch6_s1_c0',
        },
        {
            'book': 'MLTextbook',
            'chapter': '5',
            'section': '5.3',
            'section_title': 'Backpropagation',
            'pages': '200-210',
            'chunk_index': 0,
            'total_chunks': 1,
            'word_count': 10,
            'chunk_id': 'ch5_s3_c0',
        },
    ]

    index_dir.mkdir(parents=True, exist_ok=True)

    # data.json
    with open(index_dir / 'data.json', 'w') as f:
        json.dump({'documents': documents, 'metadatas': metadatas}, f)

    # vectorizer + vectors  (min_df=1 so 3 docs work)
    vectorizer = TfidfVectorizer(
        max_features=10000,
        stop_words='english',
        ngram_range=(1, 2),
        min_df=1,
        max_df=0.95,
    )
    vectors = vectorizer.fit_transform(documents)

    with open(index_dir / 'vectorizer.pkl', 'wb') as f:
        pickle.dump(vectorizer, f)
    with open(index_dir / 'vectors.pkl', 'wb') as f:
        pickle.dump(vectors, f)


def _override_settings(index_dir: Path):
    """Return a Settings override pointing at index_dir."""
    return Settings(
        index_root=index_dir,
        study_db_path=index_dir / 'study_cards.jsonl',
        session_log_path=index_dir / 'session_log.jsonl',
        graph_registry_path=index_dir / 'graph_registry.json',
        golden_sets_dir=index_dir / 'golden_sets',
    )


# ============================================================================
# Tests
# ============================================================================

def test_catalog_returns_books():
    with tempfile.TemporaryDirectory() as tmp:
        index_dir = Path(tmp) / 'index'
        _build_mini_index(index_dir)
        settings = _override_settings(index_dir)

        # Clear searcher cache so it picks up our mini index
        query_service._searcher_cache.clear()
        app.dependency_overrides[get_settings] = lambda: settings
        try:
            client = TestClient(app)
            resp = client.get("/catalog")
            assert resp.status_code == 200
            body = resp.json()
            assert body['total_chunks'] == 3
            names = [b['name'] for b in body['books']]
            assert 'DeepLearningBook' in names
            assert 'MLTextbook' in names
        finally:
            app.dependency_overrides.clear()
            query_service._searcher_cache.clear()


def test_query_returns_answer():
    with tempfile.TemporaryDirectory() as tmp:
        index_dir = Path(tmp) / 'index'
        _build_mini_index(index_dir)
        settings = _override_settings(index_dir)

        query_service._searcher_cache.clear()
        app.dependency_overrides[get_settings] = lambda: settings
        try:
            client = TestClient(app)
            resp = client.post("/query", json={
                "question": "What is gradient descent?",
                "top_k": 3,
            })
            assert resp.status_code == 200
            body = resp.json()
            assert 'answer' in body
            assert 'key_points' in body
            assert 'citations' in body
            assert 'confidence' in body
            assert body['question'] == "What is gradient descent?"
        finally:
            app.dependency_overrides.clear()
            query_service._searcher_cache.clear()


def test_query_writes_last_answer():
    with tempfile.TemporaryDirectory() as tmp:
        index_dir = Path(tmp) / 'index'
        _build_mini_index(index_dir)
        settings = _override_settings(index_dir)

        query_service._searcher_cache.clear()
        app.dependency_overrides[get_settings] = lambda: settings
        try:
            client = TestClient(app)
            client.post("/query", json={
                "question": "What are neural networks?",
                "top_k": 2,
                "save_last_answer": True,
            })
            last_answer = index_dir / '_last_answer.json'
            assert last_answer.exists()
            data = json.loads(last_answer.read_text())
            assert data['question'] == "What are neural networks?"
        finally:
            app.dependency_overrides.clear()
            query_service._searcher_cache.clear()


def test_query_no_save():
    with tempfile.TemporaryDirectory() as tmp:
        index_dir = Path(tmp) / 'index'
        _build_mini_index(index_dir)
        settings = _override_settings(index_dir)

        query_service._searcher_cache.clear()
        app.dependency_overrides[get_settings] = lambda: settings
        try:
            client = TestClient(app)
            client.post("/query", json={
                "question": "What is backpropagation?",
                "save_last_answer": False,
            })
            last_answer = index_dir / '_last_answer.json'
            assert not last_answer.exists()
        finally:
            app.dependency_overrides.clear()
            query_service._searcher_cache.clear()


def test_catalog_chunk_counts():
    with tempfile.TemporaryDirectory() as tmp:
        index_dir = Path(tmp) / 'index'
        _build_mini_index(index_dir)
        settings = _override_settings(index_dir)

        query_service._searcher_cache.clear()
        app.dependency_overrides[get_settings] = lambda: settings
        try:
            client = TestClient(app)
            resp = client.get("/catalog")
            body = resp.json()
            books_by_name = {b['name']: b['chunk_count'] for b in body['books']}
            assert books_by_name['DeepLearningBook'] == 2
            assert books_by_name['MLTextbook'] == 1
        finally:
            app.dependency_overrides.clear()
            query_service._searcher_cache.clear()
