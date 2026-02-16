"""Tests for graph/terminality.py -- terminality scoring."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from graph.terminality import compute_terminality


def test_high_confidence_high_terminality():
    """High confidence with no contradiction → high terminality."""
    score = compute_terminality({
        'level': 'high',
        'redundancy_score': 0.8,
        'contradiction_flag': False,
    })
    assert score > 0.8


def test_low_confidence_low_terminality():
    """Low confidence → low terminality."""
    score = compute_terminality({
        'level': 'low',
        'redundancy_score': 0.0,
        'contradiction_flag': False,
    })
    assert score < 0.5


def test_contradiction_reduces_terminality():
    """Contradiction flag halves the score."""
    # Use medium confidence so the score doesn't hit the 1.0 cap
    no_contra = compute_terminality({
        'level': 'medium',
        'redundancy_score': 0.0,
        'contradiction_flag': False,
    })
    with_contra = compute_terminality({
        'level': 'medium',
        'redundancy_score': 0.0,
        'contradiction_flag': True,
    })
    assert with_contra < no_contra
    # Contradiction applies 0.5 multiplier to the full score
    assert abs(with_contra / no_contra - 0.5) < 0.01


def test_redundancy_boosts_terminality():
    """Higher redundancy → higher terminality."""
    low_red = compute_terminality({
        'level': 'medium',
        'redundancy_score': 0.0,
        'contradiction_flag': False,
    })
    high_red = compute_terminality({
        'level': 'medium',
        'redundancy_score': 1.0,
        'contradiction_flag': False,
    })
    assert high_red > low_red


def test_medium_confidence_medium_terminality():
    """Medium confidence sits between low and high."""
    low = compute_terminality({'level': 'low', 'redundancy_score': 0.0,
                               'contradiction_flag': False})
    med = compute_terminality({'level': 'medium', 'redundancy_score': 0.0,
                               'contradiction_flag': False})
    high = compute_terminality({'level': 'high', 'redundancy_score': 0.0,
                                'contradiction_flag': False})
    assert low < med < high


def test_terminality_capped_at_1():
    """Terminality never exceeds 1.0."""
    score = compute_terminality({
        'level': 'high',
        'redundancy_score': 1.0,
        'contradiction_flag': False,
    })
    assert score <= 1.0


def test_empty_snapshot_defaults():
    """Empty snapshot uses defaults (low confidence)."""
    score = compute_terminality({})
    assert 0.0 <= score <= 1.0
    assert score < 0.5  # low confidence default
