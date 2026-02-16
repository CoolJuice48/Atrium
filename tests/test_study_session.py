"""Tests for study/session.py -- review session runner."""

import sys
import tempfile
from pathlib import Path
from datetime import date, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from study.models import Card, Citation
from study.storage import CardStore
from study.session import run_review_session
from study.card_types import CardType


def _make_due_cards(n=3):
    """Create n due cards."""
    cards = []
    for i in range(n):
        cards.append(Card(
            card_id=f'session_card_{i}',
            book_name='TestBook',
            tags=['TestBook'],
            prompt=f'What is concept {i}?',
            answer=f'Concept {i} is a specific data structure used in computing.',
            card_type=CardType.SHORT_ANSWER.value,
            citations=[Citation(chunk_id=f'chunk_{i}')],
            due_date=(date.today() - timedelta(days=1)).isoformat(),
        ))
    return cards


def _make_store_with_cards(tmp_dir, cards):
    """Create a CardStore and populate it."""
    store = CardStore(Path(tmp_dir) / 'session_test.jsonl')
    store.upsert_cards(cards)
    return store


def test_full_session():
    """Complete session: answer all cards, verify summary counts."""
    with tempfile.TemporaryDirectory() as tmp:
        cards = _make_due_cards(3)
        store = _make_store_with_cards(tmp, cards)

        # Mock IO: give a reasonable answer each time
        answers = iter([
            "Concept 0 is a data structure",
            "Concept 1 is a data structure",
            "Concept 2 is a data structure",
        ])
        output_lines = []

        summary = run_review_session(
            store, cards,
            input_fn=lambda _: next(answers),
            output_fn=lambda s: output_lines.append(s),
        )

        assert summary['reviewed'] == 3
        assert summary['skipped'] == 0
        assert summary['reviewed'] == summary['correct'] + summary['incorrect']


def test_quit_early():
    """Typing 'q' should end the session early."""
    with tempfile.TemporaryDirectory() as tmp:
        cards = _make_due_cards(3)
        store = _make_store_with_cards(tmp, cards)

        answers = iter(['q'])
        output_lines = []

        summary = run_review_session(
            store, cards,
            input_fn=lambda _: next(answers),
            output_fn=lambda s: output_lines.append(s),
        )

        assert summary['reviewed'] == 0


def test_skip_card():
    """Typing 's' should skip a card without grading."""
    with tempfile.TemporaryDirectory() as tmp:
        cards = _make_due_cards(2)
        store = _make_store_with_cards(tmp, cards)

        answers = iter(['s', 'Concept 1 is a data structure'])
        output_lines = []

        summary = run_review_session(
            store, cards,
            input_fn=lambda _: next(answers),
            output_fn=lambda s: output_lines.append(s),
        )

        assert summary['skipped'] == 1
        assert summary['reviewed'] == 1


def test_schedule_updated_after_review():
    """After answering, the card's scheduling fields should be updated in storage."""
    with tempfile.TemporaryDirectory() as tmp:
        cards = _make_due_cards(1)
        store = _make_store_with_cards(tmp, cards)
        original_due = cards[0].due_date

        answers = iter(["Concept 0 is a data structure used in computing"])
        output_lines = []

        run_review_session(
            store, cards,
            input_fn=lambda _: next(answers),
            output_fn=lambda s: output_lines.append(s),
        )

        updated = store.get_card(cards[0].card_id)
        assert updated.last_reviewed == date.today().isoformat()
        assert updated.due_date >= date.today().isoformat()


def test_feedback_displayed():
    """Output should include score and feedback text."""
    with tempfile.TemporaryDirectory() as tmp:
        cards = _make_due_cards(1)
        store = _make_store_with_cards(tmp, cards)

        answers = iter(["Concept 0 is a data structure"])
        output_lines = []

        run_review_session(
            store, cards,
            input_fn=lambda _: next(answers),
            output_fn=lambda s: output_lines.append(s),
        )

        joined = '\n'.join(output_lines)
        assert 'Score:' in joined
        assert 'Expected:' in joined
        assert 'SESSION COMPLETE' in joined


# ============================================================================
# TESTS: Auto-card expansion on repeated failure (Part G4)
# ============================================================================

def test_auto_expand_on_repeated_failure():
    """If a card with prior lapses fails again, new cards should be generated."""
    with tempfile.TemporaryDirectory() as tmp:
        # Create a card that already has 1 lapse (failed before)
        card = Card(
            card_id='repeat_fail',
            book_name='TestBook',
            tags=['TestBook'],
            prompt='What is a Binary Search Tree?',
            answer='A Binary Search Tree is a data structure that maintains sorted order for efficient lookup.',
            card_type=CardType.DEFINITION.value,
            citations=[Citation(chunk_id='chunk_bst', section='2.1', pages='10-15')],
            due_date=(date.today() - timedelta(days=1)).isoformat(),
            lapses=1,  # Already failed once before
            reps=0,
        )
        store = _make_store_with_cards(tmp, [card])
        initial_count = store.count()

        # Give a completely wrong answer to trigger failure (quality < 3)
        answers = iter(["something totally unrelated xyz"])
        output_lines = []

        summary = run_review_session(
            store, [card],
            input_fn=lambda _: next(answers),
            output_fn=lambda s: output_lines.append(s),
        )

        assert summary['expanded'] >= 1
        # Storage should have more cards now
        assert store.count() > initial_count
        joined = '\n'.join(output_lines)
        assert 'supplementary' in joined


def test_no_expand_on_first_failure():
    """First-time failure (lapses=0) should NOT trigger auto-expansion."""
    with tempfile.TemporaryDirectory() as tmp:
        card = Card(
            card_id='first_fail',
            book_name='TestBook',
            tags=['TestBook'],
            prompt='What is a hash table?',
            answer='A hash table maps keys to values using a hash function.',
            card_type=CardType.SHORT_ANSWER.value,
            citations=[Citation(chunk_id='chunk_ht')],
            due_date=(date.today() - timedelta(days=1)).isoformat(),
            lapses=0,  # No prior lapses
        )
        store = _make_store_with_cards(tmp, [card])
        initial_count = store.count()

        answers = iter(["completely wrong answer xyz"])
        output_lines = []

        summary = run_review_session(
            store, [card],
            input_fn=lambda _: next(answers),
            output_fn=lambda s: output_lines.append(s),
        )

        assert summary['expanded'] == 0
        assert store.count() == initial_count


def test_no_expand_on_correct_answer():
    """Correct answers should never trigger auto-expansion."""
    with tempfile.TemporaryDirectory() as tmp:
        card = Card(
            card_id='correct_card',
            book_name='TestBook',
            tags=['TestBook'],
            prompt='What is a linked list?',
            answer='A linked list is a data structure with nodes connected by pointers.',
            card_type=CardType.SHORT_ANSWER.value,
            citations=[Citation(chunk_id='chunk_ll')],
            due_date=(date.today() - timedelta(days=1)).isoformat(),
            lapses=3,  # Many prior lapses
        )
        store = _make_store_with_cards(tmp, [card])
        initial_count = store.count()

        # Give a good answer
        answers = iter(["A linked list is a data structure with nodes connected by pointers"])
        output_lines = []

        summary = run_review_session(
            store, [card],
            input_fn=lambda _: next(answers),
            output_fn=lambda s: output_lines.append(s),
        )

        assert summary['expanded'] == 0
        assert store.count() == initial_count
