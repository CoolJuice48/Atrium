"""Tests for study-related API endpoints."""

import json
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient
from server.app import app
from server.config import Settings
from server.dependencies import get_card_store, get_settings
from study.models import Card
from study.storage import CardStore


# ============================================================================
# Helpers
# ============================================================================

def _make_settings(tmp_dir: Path) -> Settings:
    return Settings(
        index_root=tmp_dir,
        study_db_path=tmp_dir / 'study_cards.jsonl',
        session_log_path=tmp_dir / 'session_log.jsonl',
        graph_registry_path=tmp_dir / 'graph_registry.json',
        golden_sets_dir=tmp_dir / 'golden_sets',
    )


def _make_card(
    card_id: str = 'c1',
    prompt: str = 'What is X?',
    answer: str = 'X is a thing.',
    card_type: str = 'definition',
    book_name: str = 'TestBook',
    due_date: str = None,
    tags: list = None,
) -> Card:
    if due_date is None:
        due_date = str(date.today() - timedelta(days=1))  # already due
    if tags is None:
        tags = ['test']
    return Card(
        card_id=card_id,
        prompt=prompt,
        answer=answer,
        card_type=card_type,
        book_name=book_name,
        due_date=due_date,
        tags=tags,
    )


def _populate_store(store: CardStore, cards: list):
    store.upsert_cards(cards)


# ============================================================================
# Tests: /study/plan
# ============================================================================

def test_study_plan_returns_expected_keys():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        settings = _make_settings(tmp_path)
        store = CardStore(settings.study_db_path)
        cards = [_make_card(card_id=f'c{i}', prompt=f'Q{i}?', answer=f'A{i}')
                 for i in range(5)]
        _populate_store(store, cards)

        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_card_store] = lambda: CardStore(settings.study_db_path)
        try:
            client = TestClient(app)
            resp = client.post("/study/plan", json={"minutes": 30})
            assert resp.status_code == 200
            body = resp.json()
            assert 'total_minutes' in body
            assert 'review' in body
            assert 'boost' in body
            assert 'quiz' in body
            assert 'gap_boost' in body
            assert 'mastery_snapshot' in body
        finally:
            app.dependency_overrides.clear()


# ============================================================================
# Tests: /study/due
# ============================================================================

def test_due_cards_empty_store():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        settings = _make_settings(tmp_path)

        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_card_store] = lambda: CardStore(settings.study_db_path)
        try:
            client = TestClient(app)
            resp = client.get("/study/due")
            assert resp.status_code == 200
            body = resp.json()
            assert body['due_count'] == 0
            assert body['cards'] == []
        finally:
            app.dependency_overrides.clear()


def test_due_cards_returns_due():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        settings = _make_settings(tmp_path)
        store = CardStore(settings.study_db_path)
        cards = [
            _make_card(card_id='due1', due_date=str(date.today() - timedelta(days=1))),
            _make_card(card_id='future1', due_date=str(date.today() + timedelta(days=10))),
        ]
        _populate_store(store, cards)

        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_card_store] = lambda: CardStore(settings.study_db_path)
        try:
            client = TestClient(app)
            resp = client.get("/study/due")
            body = resp.json()
            assert body['due_count'] == 1
            assert body['cards'][0]['card_id'] == 'due1'
        finally:
            app.dependency_overrides.clear()


# ============================================================================
# Tests: /study/review
# ============================================================================

def test_review_card_success():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        settings = _make_settings(tmp_path)
        store = CardStore(settings.study_db_path)
        card = _make_card(card_id='rev1', prompt='Define X', answer='X is something')
        _populate_store(store, [card])

        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_card_store] = lambda: CardStore(settings.study_db_path)
        try:
            client = TestClient(app)
            resp = client.post("/study/review", json={
                "card_id": "rev1",
                "user_answer": "X is something",
            })
            assert resp.status_code == 200
            body = resp.json()
            assert 'score' in body
            assert 'feedback' in body
            assert 'new_schedule' in body
            assert isinstance(body['score'], int)
        finally:
            app.dependency_overrides.clear()


def test_review_card_not_found():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        settings = _make_settings(tmp_path)

        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_card_store] = lambda: CardStore(settings.study_db_path)
        try:
            client = TestClient(app)
            resp = client.post("/study/review", json={
                "card_id": "nonexistent",
                "user_answer": "anything",
            })
            assert resp.status_code == 404
        finally:
            app.dependency_overrides.clear()


# ============================================================================
# Tests: /cards/from_last_answer
# ============================================================================

def test_cards_from_last_answer_no_file():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        settings = _make_settings(tmp_path)

        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_card_store] = lambda: CardStore(settings.study_db_path)
        try:
            client = TestClient(app)
            resp = client.post("/cards/from_last_answer", json={"max_cards": 6})
            assert resp.status_code == 200
            body = resp.json()
            assert body['cards_generated'] == 0
            assert body['cards'] == []
        finally:
            app.dependency_overrides.clear()


def test_cards_from_last_answer_with_file():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        settings = _make_settings(tmp_path)

        last_answer = {
            'question': 'What is gradient descent?',
            'answer_dict': {
                'answer': 'Gradient descent is an optimization algorithm that minimizes a loss function.',
                'key_points': ['iterative optimization', 'loss minimization'],
                'citations': ['DeepLearningBook, §4.3, p.80-83'],
                'confidence': {'level': 'high'},
            },
            'retrieved_chunks': [
                {
                    'text': 'Gradient descent is widely used in machine learning.',
                    'metadata': {'book': 'DeepLearningBook', 'section': '4.3'},
                },
            ],
        }
        with open(tmp_path / '_last_answer.json', 'w') as f:
            json.dump(last_answer, f)

        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_card_store] = lambda: CardStore(settings.study_db_path)
        try:
            client = TestClient(app)
            resp = client.post("/cards/from_last_answer", json={"max_cards": 4})
            assert resp.status_code == 200
            body = resp.json()
            assert body['cards_generated'] > 0
            assert len(body['cards']) == body['cards_generated']
            # Each card should have the expected fields
            for card in body['cards']:
                assert 'card_id' in card
                assert 'prompt' in card
                assert 'answer' in card
        finally:
            app.dependency_overrides.clear()


# ============================================================================
# Tests: /progress
# ============================================================================

def test_progress_empty_store():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        settings = _make_settings(tmp_path)

        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_card_store] = lambda: CardStore(settings.study_db_path)
        try:
            client = TestClient(app)
            resp = client.get("/progress")
            assert resp.status_code == 200
            body = resp.json()
            assert body['total_cards'] == 0
            assert body['due_count'] == 0
            assert body['overall_mastery'] == 0.0
        finally:
            app.dependency_overrides.clear()


def test_progress_with_cards():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        settings = _make_settings(tmp_path)
        store = CardStore(settings.study_db_path)
        cards = [_make_card(card_id=f'p{i}') for i in range(3)]
        _populate_store(store, cards)

        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_card_store] = lambda: CardStore(settings.study_db_path)
        try:
            client = TestClient(app)
            resp = client.get("/progress")
            body = resp.json()
            assert body['total_cards'] == 3
            assert 'by_book' in body
            assert 'weakest_sections' in body
            assert 'strongest_sections' in body
        finally:
            app.dependency_overrides.clear()
