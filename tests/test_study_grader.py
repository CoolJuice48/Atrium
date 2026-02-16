"""Tests for study/grader.py -- token-overlap grading."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from study.grader import grade


def test_perfect_match():
    """Exact answer should score 5."""
    result = grade(
        "A binary search tree maintains sorted order for efficient lookups",
        "A binary search tree maintains sorted order for efficient lookups",
        "short_answer",
    )
    assert result['score'] == 5


def test_high_overlap():
    """High overlap should score 4-5."""
    result = grade(
        "binary search tree sorted order efficient lookup insertion",
        "A binary search tree is a data structure that maintains sorted order for efficient lookup and insertion",
        "short_answer",
    )
    assert result['score'] >= 4


def test_partial_overlap():
    """Moderate overlap should score 2-3."""
    result = grade(
        "trees store data",
        "A binary search tree is a data structure that maintains sorted order for efficient lookup and insertion operations",
        "short_answer",
    )
    assert 1 <= result['score'] <= 3


def test_no_overlap():
    """Completely unrelated answer should score 0."""
    result = grade(
        "the weather is sunny today",
        "binary search tree maintains sorted order for efficient lookups",
        "short_answer",
    )
    assert result['score'] == 0


def test_empty_user_answer():
    """Empty answer should score 0."""
    result = grade("", "binary search tree", "short_answer")
    assert result['score'] == 0
    assert 'No answer' in result['feedback']


def test_synonym_expansion():
    """'quick' should match 'fast' via synonym expansion."""
    result = grade(
        "the quick algorithm runs fast",
        "the fast algorithm runs rapidly",
        "short_answer",
    )
    # 'quick' expands to include 'fast', 'rapid' — should get decent overlap
    assert result['score'] >= 3


def test_cloze_exact_match():
    """Cloze: exact substring match gives score 5."""
    result = grade(
        "Binary Search",
        "Binary Search",
        "cloze",
    )
    assert result['score'] == 5


def test_cloze_case_insensitive():
    """Cloze: case-insensitive match still gives 5."""
    result = grade(
        "binary search",
        "Binary Search",
        "cloze",
    )
    assert result['score'] == 5


def test_cloze_partial_falls_back():
    """Cloze: partial (non-exact) match falls back to token overlap."""
    result = grade(
        "something unrelated entirely",
        "Binary Search Tree",
        "cloze",
    )
    assert result['score'] < 3


def test_feedback_present():
    """Every grade result should have a feedback string."""
    result = grade("test", "test answer", "short_answer")
    assert 'feedback' in result
    assert isinstance(result['feedback'], str)
    assert len(result['feedback']) > 0
