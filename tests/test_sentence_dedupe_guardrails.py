"""Tests for sentence dedupe flip guardrails (negation, direction, etc.)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.services.sentence_dedupe import dedupe_sentences


def test_near_dedupe_blocks_negation_flip():
    """Negation flip: both sentences remain even with high token overlap."""
    sentences = [
        "The optimization algorithm is stable under these conditions in practice and production.",
        "The optimization algorithm is not stable under these conditions in practice and production.",
    ]
    deduped = dedupe_sentences(sentences, near_dupe_jaccard=0.92)
    assert len(deduped) == 2
    assert any("not" in s for s in deduped)
    assert any("not" not in s for s in deduped)


def test_near_dedupe_blocks_increase_decrease_flip():
    """Increase/decrease flip: both sentences remain."""
    sentences = [
        "The error increases with larger step sizes in this regime and converges slowly.",
        "The error decreases with larger step sizes in this regime and converges slowly.",
    ]
    deduped = dedupe_sentences(sentences, near_dupe_jaccard=0.92)
    assert len(deduped) == 2
    assert any("increases" in s for s in deduped)
    assert any("decreases" in s for s in deduped)


def test_near_dedupe_blocks_max_min_flip():
    """Max/min flip: both sentences remain."""
    sentences = [
        "We maximize the objective by increasing the learning rate in each iteration.",
        "We minimize the objective by increasing the learning rate in each iteration.",
    ]
    deduped = dedupe_sentences(sentences, near_dupe_jaccard=0.92)
    assert len(deduped) == 2
    assert any("maximize" in s for s in deduped)
    assert any("minimize" in s for s in deduped)


def test_near_dedupe_allows_true_duplicates_without_flip():
    """Exact duplicates without flip tokens: one remains."""
    sentences = [
        "The error decreases with smaller step sizes.",
        "The error decreases with smaller step sizes.",
    ]
    deduped = dedupe_sentences(sentences, near_dupe_jaccard=0.92)
    assert len(deduped) == 1
    assert "decreases" in deduped[0]
