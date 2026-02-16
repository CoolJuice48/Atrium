"""Tests for study/storage.py -- JSONL card storage."""

import sys
import tempfile
from pathlib import Path
from datetime import date, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from study.models import Card, Citation, make_card_id
from study.storage import CardStore
from study.card_types import CardType
import pytest


def _make_card(prompt="What is X?", book="TestBook", due_offset=0):
    """Create a test card with a deterministic ID."""
    cid = make_card_id(prompt, ['chunk1'])
    due = (date.today() + timedelta(days=due_offset)).isoformat()
    return Card(
        card_id=cid,
        book_name=book,
        tags=[book, 'test'],
        prompt=prompt,
        answer="X is a thing.",
        card_type=CardType.DEFINITION.value,
        citations=[Citation(chunk_id='chunk1', chapter='1', section='1.1', pages='5')],
        due_date=due,
    )


def test_upsert_and_get():
    """Upsert a card, then get it by ID."""
    with tempfile.TemporaryDirectory() as tmp:
        store = CardStore(Path(tmp) / 'cards.jsonl')
        card = _make_card()
        store.upsert_card(card)
        retrieved = store.get_card(card.card_id)
        assert retrieved is not None
        assert retrieved.prompt == card.prompt
        assert retrieved.card_id == card.card_id


def test_upsert_overwrites():
    """Upserting same card_id overwrites the old one."""
    with tempfile.TemporaryDirectory() as tmp:
        store = CardStore(Path(tmp) / 'cards.jsonl')
        card = _make_card()
        store.upsert_card(card)
        card.answer = "Updated answer"
        store.upsert_card(card)
        assert store.count() == 1
        assert store.get_card(card.card_id).answer == "Updated answer"


def test_get_due_cards():
    """Only cards with due_date <= today should be returned."""
    with tempfile.TemporaryDirectory() as tmp:
        store = CardStore(Path(tmp) / 'cards.jsonl')
        past = _make_card("past card", due_offset=-1)
        today = _make_card("today card", due_offset=0)
        future = _make_card("future card", due_offset=5)
        store.upsert_cards([past, today, future])

        due = store.get_due_cards()
        due_ids = {c.card_id for c in due}
        assert past.card_id in due_ids
        assert today.card_id in due_ids
        assert future.card_id not in due_ids


def test_get_due_cards_sorted():
    """Due cards should be sorted by due_date ascending."""
    with tempfile.TemporaryDirectory() as tmp:
        store = CardStore(Path(tmp) / 'cards.jsonl')
        c1 = _make_card("card A", due_offset=-3)
        c2 = _make_card("card B", due_offset=-1)
        c3 = _make_card("card C", due_offset=0)
        store.upsert_cards([c2, c3, c1])  # insert out of order

        due = store.get_due_cards()
        dates = [c.due_date for c in due]
        assert dates == sorted(dates)


def test_update_review():
    """update_review should modify scheduling fields."""
    with tempfile.TemporaryDirectory() as tmp:
        store = CardStore(Path(tmp) / 'cards.jsonl')
        card = _make_card()
        store.upsert_card(card)

        new_schedule = {
            'due_date': (date.today() + timedelta(days=6)).isoformat(),
            'interval_days': 6,
            'ease_factor': 2.6,
            'reps': 2,
            'lapses': 0,
        }
        store.update_review(card.card_id, quality=4, new_schedule=new_schedule)

        updated = store.get_card(card.card_id)
        assert updated.interval_days == 6
        assert updated.ease_factor == 2.6
        assert updated.reps == 2
        assert updated.last_reviewed == date.today().isoformat()


def test_update_review_missing_card():
    """update_review on nonexistent card should raise KeyError."""
    with tempfile.TemporaryDirectory() as tmp:
        store = CardStore(Path(tmp) / 'cards.jsonl')
        with pytest.raises(KeyError):
            store.update_review('nonexistent', 3, {})


def test_persistence_across_reloads():
    """Cards should persist when creating a new CardStore on the same path."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'cards.jsonl'
        store1 = CardStore(path)
        card = _make_card()
        store1.upsert_card(card)

        # Reload from disk
        store2 = CardStore(path)
        assert store2.count() == 1
        retrieved = store2.get_card(card.card_id)
        assert retrieved.prompt == card.prompt
        assert len(retrieved.citations) == 1
        assert retrieved.citations[0].chunk_id == 'chunk1'


def test_empty_store():
    """New store on nonexistent path should be empty."""
    with tempfile.TemporaryDirectory() as tmp:
        store = CardStore(Path(tmp) / 'nonexistent.jsonl')
        assert store.count() == 0
        assert store.all_cards() == []
        assert store.get_due_cards() == []


def test_get_cards_by_book():
    """Filter cards by book name."""
    with tempfile.TemporaryDirectory() as tmp:
        store = CardStore(Path(tmp) / 'cards.jsonl')
        store.upsert_cards([
            _make_card("Q1", book="BookA"),
            _make_card("Q2", book="BookB"),
            _make_card("Q3", book="BookA"),
        ])
        book_a = store.get_cards_by_book("BookA")
        assert len(book_a) == 2
        assert all(c.book_name == "BookA" for c in book_a)


def test_get_cards_by_tag():
    """Filter cards by tag."""
    with tempfile.TemporaryDirectory() as tmp:
        store = CardStore(Path(tmp) / 'cards.jsonl')
        store.upsert_cards([
            _make_card("Q1"),
            _make_card("Q2"),
        ])
        tagged = store.get_cards_by_tag("test")
        assert len(tagged) == 2
