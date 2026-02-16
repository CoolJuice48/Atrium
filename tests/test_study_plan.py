"""Tests for study/plan.py -- study plan generator."""

import sys
import tempfile
from pathlib import Path
from datetime import date, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from study.models import Card, Citation
from study.storage import CardStore
from study.plan import make_study_plan, SECONDS_PER_CARD, SECONDS_PER_QUIZ_Q
from study.card_types import CardType


def _make_store(tmp_dir, cards):
    """Create a CardStore and populate it."""
    store = CardStore(Path(tmp_dir) / 'plan_test.jsonl')
    if cards:
        store.upsert_cards(cards)
    return store


def _card(card_id, book='BookA', section='1.1', due_days_ago=1,
          interval=1, lapses=0, last_reviewed=None):
    """Create a card with convenient defaults."""
    return Card(
        card_id=card_id,
        book_name=book,
        tags=[book],
        prompt=f'Q for {card_id}',
        answer=f'A for {card_id}',
        card_type=CardType.SHORT_ANSWER.value,
        citations=[Citation(chunk_id=f'chunk_{card_id}', section=section)],
        due_date=(date.today() - timedelta(days=due_days_ago)).isoformat(),
        interval_days=interval,
        lapses=lapses,
        last_reviewed=last_reviewed or date.today().isoformat(),
    )


def test_empty_deck():
    """Plan with empty deck returns zeros."""
    with tempfile.TemporaryDirectory() as tmp:
        store = _make_store(tmp, [])
        plan = make_study_plan(store, minutes=30)
        assert plan['review']['cards'] == []
        assert plan['boost']['cards'] == []
        assert plan['mastery_snapshot']['overall'] == 0.0


def test_plan_has_required_keys():
    """Plan dict contains all required sections."""
    with tempfile.TemporaryDirectory() as tmp:
        cards = [_card(f'c{i}') for i in range(5)]
        store = _make_store(tmp, cards)
        plan = make_study_plan(store, minutes=30)
        assert 'total_minutes' in plan
        assert 'review' in plan
        assert 'boost' in plan
        assert 'quiz' in plan
        assert 'gap_boost' in plan
        assert 'mastery_snapshot' in plan
        assert 'gap_snapshot' in plan
        assert 'cards' in plan['review']
        assert 'estimated_minutes' in plan['review']
        assert 'sections' in plan['boost']
        assert 'n_questions' in plan['quiz']
        assert 'cards' in plan['gap_boost']
        assert 'concepts' in plan['gap_boost']


def test_due_cards_in_review():
    """Due cards should appear in the review section."""
    with tempfile.TemporaryDirectory() as tmp:
        due = [_card(f'due_{i}', due_days_ago=1) for i in range(3)]
        future = [_card(f'future_{i}', due_days_ago=-10) for i in range(2)]
        store = _make_store(tmp, due + future)
        plan = make_study_plan(store, minutes=30)
        review_ids = {c.card_id for c in plan['review']['cards']}
        for c in due:
            assert c.card_id in review_ids


def test_non_due_weak_cards_in_boost():
    """Non-due cards with low mastery should appear in boost section."""
    with tempfile.TemporaryDirectory() as tmp:
        due = [_card('due_0', due_days_ago=1, interval=20)]
        weak_future = [_card(f'weak_{i}', due_days_ago=-5, interval=1,
                             lapses=3) for i in range(3)]
        store = _make_store(tmp, due + weak_future)
        plan = make_study_plan(store, minutes=30)
        boost_ids = {c.card_id for c in plan['boost']['cards']}
        # At least some weak future cards should be in boost
        assert len(boost_ids) >= 1


def test_book_filter():
    """Book filter restricts plan to cards from that book only."""
    with tempfile.TemporaryDirectory() as tmp:
        book_a = [_card(f'a_{i}', book='BookA') for i in range(3)]
        book_b = [_card(f'b_{i}', book='BookB') for i in range(3)]
        store = _make_store(tmp, book_a + book_b)
        plan = make_study_plan(store, minutes=30, book='BookA')
        all_plan_cards = plan['review']['cards'] + plan['boost']['cards']
        for c in all_plan_cards:
            assert c.book_name == 'BookA'


def test_time_budget_respected():
    """Review card count should not exceed time budget."""
    with tempfile.TemporaryDirectory() as tmp:
        # 100 due cards, but only 5 min budget
        cards = [_card(f'c{i}') for i in range(100)]
        store = _make_store(tmp, cards)
        plan = make_study_plan(store, minutes=5)
        total_seconds = 5 * 60
        max_review = int(total_seconds * 0.55) // SECONDS_PER_CARD
        assert len(plan['review']['cards']) <= max_review + 1


def test_quiz_questions_present():
    """Plan should include quiz questions."""
    with tempfile.TemporaryDirectory() as tmp:
        cards = [_card(f'c{i}') for i in range(5)]
        store = _make_store(tmp, cards)
        plan = make_study_plan(store, minutes=30)
        assert plan['quiz']['n_questions'] >= 1


def test_mastery_snapshot_included():
    """Plan should include a mastery snapshot."""
    with tempfile.TemporaryDirectory() as tmp:
        cards = [_card(f'c{i}', interval=15) for i in range(3)]
        store = _make_store(tmp, cards)
        plan = make_study_plan(store, minutes=30)
        snap = plan['mastery_snapshot']
        assert 'overall' in snap
        assert 'by_book' in snap
        assert 'weakest_sections' in snap
        assert 0.0 <= snap['overall'] <= 1.0
