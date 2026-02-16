"""Tests for study/scheduler.py -- SM-2 spaced repetition."""

import sys
from pathlib import Path
from datetime import date, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from study.scheduler import sm2_schedule


def test_quality_5_ease_increases():
    """Perfect recall (quality=5) should increase ease factor."""
    result = sm2_schedule(quality=5, reps=2, ease_factor=2.5, interval_days=6, lapses=0)
    assert result['ease_factor'] > 2.5
    assert result['reps'] == 3
    assert result['lapses'] == 0


def test_quality_4_ease_stable():
    """Good recall (quality=4) should keep ease roughly stable."""
    result = sm2_schedule(quality=4, reps=2, ease_factor=2.5, interval_days=6, lapses=0)
    assert result['ease_factor'] == 2.5  # SM-2: q=4 → delta = 0
    assert result['reps'] == 3


def test_quality_3_ease_decreases():
    """Passable recall (quality=3) should decrease ease slightly."""
    result = sm2_schedule(quality=3, reps=2, ease_factor=2.5, interval_days=6, lapses=0)
    assert result['ease_factor'] < 2.5
    assert result['ease_factor'] >= 1.3  # floor
    assert result['reps'] == 3


def test_quality_2_lapse():
    """Quality < 3 is a lapse: interval=1, reps reset, lapses increment."""
    result = sm2_schedule(quality=2, reps=5, ease_factor=2.5, interval_days=15, lapses=1)
    assert result['interval_days'] == 1
    assert result['reps'] == 0
    assert result['lapses'] == 2
    assert result['ease_factor'] < 2.5


def test_quality_0_blackout():
    """Complete blackout (quality=0) behaves like a lapse."""
    result = sm2_schedule(quality=0, reps=3, ease_factor=2.0, interval_days=10, lapses=0)
    assert result['interval_days'] == 1
    assert result['reps'] == 0
    assert result['lapses'] == 1


def test_reps_0_first_review():
    """First review (reps=0): interval should be 1 day."""
    result = sm2_schedule(quality=4, reps=0, ease_factor=2.5, interval_days=1, lapses=0)
    assert result['interval_days'] == 1
    assert result['reps'] == 1


def test_reps_1_second_review():
    """Second review (reps=1): interval should be 6 days."""
    result = sm2_schedule(quality=4, reps=1, ease_factor=2.5, interval_days=1, lapses=0)
    assert result['interval_days'] == 6
    assert result['reps'] == 2


def test_reps_2_uses_ease():
    """Third+ review (reps>=2): interval = round(interval * ease)."""
    result = sm2_schedule(quality=4, reps=2, ease_factor=2.5, interval_days=6, lapses=0)
    assert result['interval_days'] == round(6 * 2.5)  # 15
    assert result['reps'] == 3


def test_ease_floor_at_1_3():
    """Ease factor never drops below 1.3."""
    result = sm2_schedule(quality=0, reps=3, ease_factor=1.3, interval_days=10, lapses=5)
    assert result['ease_factor'] >= 1.3


def test_due_date_is_future():
    """Due date should be today + interval_days."""
    result = sm2_schedule(quality=5, reps=0, ease_factor=2.5, interval_days=1, lapses=0)
    expected = (date.today() + timedelta(days=result['interval_days'])).isoformat()
    assert result['due_date'] == expected


def test_quality_out_of_range_raises():
    """Quality outside 0-5 should raise ValueError."""
    with pytest.raises(ValueError):
        sm2_schedule(quality=6, reps=0, ease_factor=2.5, interval_days=1, lapses=0)
    with pytest.raises(ValueError):
        sm2_schedule(quality=-1, reps=0, ease_factor=2.5, interval_days=1, lapses=0)


def test_successive_correct_reviews_grow_interval():
    """Multiple successive correct reviews should grow the interval."""
    intervals = []
    reps = 0
    ease = 2.5
    interval = 1
    lapses = 0
    for _ in range(5):
        result = sm2_schedule(quality=4, reps=reps, ease_factor=ease,
                              interval_days=interval, lapses=lapses)
        intervals.append(result['interval_days'])
        reps = result['reps']
        ease = result['ease_factor']
        interval = result['interval_days']
        lapses = result['lapses']
    # Intervals should be non-decreasing after the first two
    assert intervals[2] >= intervals[1]
    assert intervals[3] >= intervals[2]
