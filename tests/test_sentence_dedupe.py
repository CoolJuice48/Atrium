"""Tests for sentence deduplication."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.services.sentence_dedupe import dedupe_sentences, normalize_for_dedupe


def test_exact_dedupe():
    """Same sentence twice -> one remains."""
    sentences = [
        "Machine learning is a subset of artificial intelligence.",
        "Machine learning is a subset of artificial intelligence.",
    ]
    deduped = dedupe_sentences(sentences)
    assert len(deduped) == 1
    assert deduped[0] == sentences[0]


def test_near_dedupe_paragraph_vs_bullet():
    """Two sentences with high overlap -> one remains (prefer cleaner)."""
    sentences = [
        "Machine learning is a subset of artificial intelligence that enables systems to learn.",
        "Machine learning is a subset of artificial intelligence that enables systems to learn effectively.",
    ]
    deduped = dedupe_sentences(sentences, near_dupe_jaccard=0.92)
    assert len(deduped) == 1
    assert "machine learning" in deduped[0].lower()
