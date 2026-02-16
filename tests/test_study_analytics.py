"""Tests for study/analytics.py -- mastery scoring and aggregation."""

import sys
from pathlib import Path
from datetime import date, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from study.analytics import compute_mastery, _card_mastery
from study.models import Card, Citation
from study.card_types import CardType


def _card(
    card_id='c1',
    book='BookA',
    section='1.1',
    interval=1,
    ease=2.5,
    reps=0,
    lapses=0,
    last_reviewed=None,
):
    """Create a card with specific scheduling parameters."""
    return Card(
        card_id=card_id,
        book_name=book,
        tags=[book],
        prompt=f'Q for {card_id}',
        answer=f'A for {card_id}',
        card_type=CardType.SHORT_ANSWER.value,
        citations=[Citation(chunk_id=f'chunk_{card_id}', section=section)],
        interval_days=interval,
        ease_factor=ease,
        reps=reps,
        lapses=lapses,
        last_reviewed=last_reviewed,
    )


# ============================================================================
# TESTS: _card_mastery
# ============================================================================

def test_mastery_increases_with_interval():
    """Longer intervals → higher mastery (base = interval/30)."""
    low = _card(card_id='low', interval=1, last_reviewed=date.today().isoformat())
    high = _card(card_id='high', interval=20, last_reviewed=date.today().isoformat())
    assert _card_mastery(high) > _card_mastery(low)


def test_mastery_caps_at_1():
    """Mastery is capped at 1.0 even with very long intervals."""
    c = _card(interval=100, ease=3.0, reps=10, last_reviewed=date.today().isoformat())
    assert _card_mastery(c) <= 1.0


def test_mastery_decreases_with_lapses():
    """More lapses → lower mastery."""
    no_lapse = _card(card_id='nl', interval=10, lapses=0,
                     last_reviewed=date.today().isoformat())
    many_lapses = _card(card_id='ml', interval=10, lapses=5,
                        last_reviewed=date.today().isoformat())
    assert _card_mastery(no_lapse) > _card_mastery(many_lapses)


def test_mastery_boosts_with_high_ease():
    """Ease > 2.5 gives a mastery boost."""
    normal = _card(card_id='n', interval=10, ease=2.5,
                   last_reviewed=date.today().isoformat())
    boosted = _card(card_id='b', interval=10, ease=3.0,
                    last_reviewed=date.today().isoformat())
    assert _card_mastery(boosted) > _card_mastery(normal)


def test_mastery_decays_with_staleness():
    """Cards not reviewed in > 60 days get a 30% penalty."""
    recent = _card(card_id='r', interval=15,
                   last_reviewed=date.today().isoformat())
    stale = _card(card_id='s', interval=15,
                  last_reviewed=(date.today() - timedelta(days=90)).isoformat())
    assert _card_mastery(recent) > _card_mastery(stale)


def test_mastery_never_reviewed_penalty():
    """Cards that were never reviewed get 50% penalty."""
    reviewed = _card(card_id='rev', interval=10,
                     last_reviewed=date.today().isoformat())
    unreviewed = _card(card_id='unrev', interval=10, last_reviewed=None)
    assert _card_mastery(reviewed) > _card_mastery(unreviewed)


def test_mastery_floor_at_zero():
    """Mastery never goes below 0."""
    c = _card(interval=1, lapses=50, ease=1.3, last_reviewed=None)
    assert _card_mastery(c) >= 0.0


# ============================================================================
# TESTS: compute_mastery
# ============================================================================

def test_compute_mastery_empty():
    """Empty card list returns zero mastery."""
    result = compute_mastery([])
    assert result['overall_mastery'] == 0.0
    assert result['by_book'] == {}
    assert result['weakest_sections'] == []


def test_compute_mastery_overall():
    """Overall mastery is the average of individual card masteries."""
    cards = [
        _card(card_id='c1', interval=30, lapses=0,
              last_reviewed=date.today().isoformat()),
        _card(card_id='c2', interval=1, lapses=3,
              last_reviewed=date.today().isoformat()),
    ]
    result = compute_mastery(cards)
    assert 0.0 < result['overall_mastery'] < 1.0


def test_compute_mastery_by_book():
    """Mastery is broken down by book."""
    cards = [
        _card(card_id='c1', book='BookA', interval=20,
              last_reviewed=date.today().isoformat()),
        _card(card_id='c2', book='BookB', interval=5, lapses=2,
              last_reviewed=date.today().isoformat()),
    ]
    result = compute_mastery(cards)
    assert 'BookA' in result['by_book']
    assert 'BookB' in result['by_book']
    assert result['by_book']['BookA'] > result['by_book']['BookB']


def test_compute_mastery_by_section():
    """Mastery is broken down by section."""
    cards = [
        _card(card_id='c1', section='1.1', interval=20,
              last_reviewed=date.today().isoformat()),
        _card(card_id='c2', section='2.3', interval=2, lapses=3,
              last_reviewed=date.today().isoformat()),
    ]
    result = compute_mastery(cards)
    assert len(result['by_section']) == 2


def test_weakest_and_strongest():
    """Weakest sections have lowest scores, strongest have highest."""
    cards = [
        _card(card_id='strong', section='1.1', interval=30,
              last_reviewed=date.today().isoformat()),
        _card(card_id='weak', section='5.5', interval=1, lapses=4,
              last_reviewed=date.today().isoformat()),
    ]
    result = compute_mastery(cards)
    weakest_keys = [sk for sk, _ in result['weakest_sections']]
    strongest_keys = [sk for sk, _ in result['strongest_sections']]
    # The section with lapses should be weakest
    assert any('5.5' in k for k in weakest_keys)
    assert any('1.1' in k for k in strongest_keys)


def test_repeated_lapses_decrease_mastery():
    """Cards with repeated lapses have progressively lower mastery."""
    m0 = _card_mastery(_card(card_id='l0', interval=10, lapses=0,
                             last_reviewed=date.today().isoformat()))
    m2 = _card_mastery(_card(card_id='l2', interval=10, lapses=2,
                             last_reviewed=date.today().isoformat()))
    m5 = _card_mastery(_card(card_id='l5', interval=10, lapses=5,
                             last_reviewed=date.today().isoformat()))
    assert m0 > m2 > m5


def test_more_reps_longer_interval_increases_mastery():
    """A card with more reps and longer interval should have higher mastery."""
    beginner = _card(card_id='beg', interval=1, reps=0,
                     last_reviewed=date.today().isoformat())
    intermediate = _card(card_id='int', interval=10, reps=3,
                         last_reviewed=date.today().isoformat())
    advanced = _card(card_id='adv', interval=30, reps=8,
                     last_reviewed=date.today().isoformat())
    assert _card_mastery(beginner) < _card_mastery(intermediate) < _card_mastery(advanced)
