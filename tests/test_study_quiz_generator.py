"""Tests for study/quiz_generator.py -- quiz assembly."""

import sys
from pathlib import Path
from datetime import date, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from study.quiz_generator import make_quiz, QuizQuestion
from study.models import Card, Citation
from study.card_types import CardType


def _make_cards(n=5):
    """Create n test cards with distinct prompts and tags."""
    cards = []
    for i in range(n):
        cards.append(Card(
            card_id=f'card_{i}',
            book_name='TestBook',
            tags=['TestBook', f'topic_{i % 3}'],
            prompt=f'What is concept {i}?',
            answer=f'Concept {i} is a thing.',
            card_type=CardType.SHORT_ANSWER.value,
        ))
    return cards


def test_basic_quiz():
    """make_quiz returns QuizQuestion objects with correct numbering."""
    cards = _make_cards(10)
    quiz = make_quiz('', cards, n=5)
    assert len(quiz) == 5
    assert all(isinstance(q, QuizQuestion) for q in quiz)
    numbers = [q.question_number for q in quiz]
    assert numbers == [1, 2, 3, 4, 5]


def test_topic_filter():
    """Only cards matching the topic should appear."""
    cards = _make_cards(10)
    # Add a unique-topic card
    cards.append(Card(
        card_id='special',
        book_name='TestBook',
        tags=['TestBook', 'gradient'],
        prompt='What is gradient descent?',
        answer='An optimization algorithm.',
        card_type=CardType.DEFINITION.value,
    ))
    quiz = make_quiz('gradient', cards, n=10)
    assert len(quiz) >= 1
    for q in quiz:
        assert ('gradient' in q.card.prompt.lower()
                or any('gradient' in t.lower() for t in q.card.tags))


def test_n_exceeds_available():
    """If n > available cards, returns all available."""
    cards = _make_cards(3)
    quiz = make_quiz('', cards, n=10)
    assert len(quiz) == 3


def test_empty_cards():
    """Empty card list returns empty quiz."""
    quiz = make_quiz('anything', [], n=5)
    assert quiz == []


def test_no_matching_topic():
    """No matching cards returns empty quiz."""
    cards = _make_cards(5)
    quiz = make_quiz('nonexistent_xyz_topic', cards, n=5)
    assert quiz == []


# ============================================================================
# TESTS: Adaptive mode (Part G3)
# ============================================================================

def test_adaptive_favors_weak_cards():
    """Adaptive mode should put high-lapse cards first."""
    strong = Card(
        card_id='strong',
        book_name='TestBook',
        tags=['TestBook'],
        prompt='What is concept strong?',
        answer='Strong concept.',
        card_type=CardType.SHORT_ANSWER.value,
        interval_days=30,
        ease_factor=2.8,
        lapses=0,
        reps=8,
        last_reviewed=date.today().isoformat(),
    )
    weak = Card(
        card_id='weak',
        book_name='TestBook',
        tags=['TestBook'],
        prompt='What is concept weak?',
        answer='Weak concept.',
        card_type=CardType.SHORT_ANSWER.value,
        interval_days=1,
        ease_factor=1.3,
        lapses=5,
        reps=0,
        last_reviewed=date.today().isoformat(),
    )
    quiz = make_quiz('', [strong, weak], n=2, adaptive=True)
    assert len(quiz) == 2
    # Weak card (more lapses) should come first
    assert quiz[0].card.card_id == 'weak'


def test_adaptive_prioritizes_due_soon():
    """Adaptive mode should prioritize cards due sooner."""
    overdue = Card(
        card_id='overdue',
        book_name='TestBook',
        tags=['TestBook'],
        prompt='Overdue card',
        answer='Answer.',
        card_type=CardType.SHORT_ANSWER.value,
        due_date=(date.today() - timedelta(days=5)).isoformat(),
        last_reviewed=(date.today() - timedelta(days=6)).isoformat(),
    )
    future = Card(
        card_id='future',
        book_name='TestBook',
        tags=['TestBook'],
        prompt='Future card',
        answer='Answer.',
        card_type=CardType.SHORT_ANSWER.value,
        due_date=(date.today() + timedelta(days=10)).isoformat(),
        last_reviewed=date.today().isoformat(),
    )
    quiz = make_quiz('', [future, overdue], n=2, adaptive=True)
    # Both have 0 lapses, so due_date breaks the tie → overdue first
    assert quiz[0].card.card_id == 'overdue'


def test_adaptive_boosts_cloze_compare():
    """Adaptive mode should prefer cloze/compare card types."""
    cards = []
    # 3 short_answer cards
    for i in range(3):
        cards.append(Card(
            card_id=f'sa_{i}',
            book_name='TestBook',
            tags=['TestBook'],
            prompt=f'SA question {i}',
            answer=f'SA answer {i}.',
            card_type=CardType.SHORT_ANSWER.value,
            lapses=1,
            last_reviewed=date.today().isoformat(),
        ))
    # 2 cloze cards
    for i in range(2):
        cards.append(Card(
            card_id=f'cloze_{i}',
            book_name='TestBook',
            tags=['TestBook'],
            prompt=f'Fill: ______ {i}',
            answer=f'term_{i}',
            card_type=CardType.CLOZE.value,
            lapses=1,
            last_reviewed=date.today().isoformat(),
        ))

    quiz = make_quiz('', cards, n=5, adaptive=True)
    # First two should be cloze (priority types come first in interleave)
    first_two_types = [q.card.card_type for q in quiz[:2]]
    assert CardType.CLOZE.value in first_two_types


def test_adaptive_deterministic():
    """Adaptive mode should be deterministic (no random sampling)."""
    cards = [
        Card(
            card_id=f'card_{i}',
            book_name='TestBook',
            tags=['TestBook'],
            prompt=f'Q{i}',
            answer=f'A{i}',
            card_type=CardType.SHORT_ANSWER.value,
            lapses=i,
            last_reviewed=date.today().isoformat(),
        )
        for i in range(5)
    ]
    q1 = make_quiz('', cards, n=3, adaptive=True)
    q2 = make_quiz('', cards, n=3, adaptive=True)
    assert [q.card.card_id for q in q1] == [q.card.card_id for q in q2]
