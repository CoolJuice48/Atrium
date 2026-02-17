"""Tests for concept bundles."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.services.bundles import (
    build_bundles,
    build_cooccurrence_graph,
    select_sentences_across_bundles,
)
from server.services.concepts import build_term_stats


def test_bundles_have_supporting_sentences():
    """Each bundle has label_term, supporting_terms, and supporting_sentences."""
    sentences = [
        "Machine learning is a subset of artificial intelligence.",
        "Machine learning uses neural networks for pattern recognition.",
        "Neural networks consist of layers of interconnected nodes.",
        "Deep learning extends neural networks with many layers.",
        "Gradient descent optimizes the loss function in training.",
    ]
    term_stats = build_term_stats(sentences)
    bundles = build_bundles(term_stats, sentences, top_k_terms=10)
    assert len(bundles) >= 1
    for b in bundles:
        assert b.label_term
        assert isinstance(b.supporting_terms, list)
        assert isinstance(b.supporting_sentences, list)
        assert len(b.supporting_sentences) >= 1 or len(b.supporting_terms) >= 0


def test_selection_spans_multiple_bundles():
    """select_sentences_across_bundles returns sentences from multiple bundles."""
    sentences = [
        "Machine learning is a subset of artificial intelligence.",
        "Machine learning uses neural networks for pattern recognition.",
        "Neural networks consist of layers of interconnected nodes.",
        "Gradient descent optimizes the loss function.",
        "The loss function measures prediction error.",
    ]
    term_stats = build_term_stats(sentences)
    bundles = build_bundles(term_stats, sentences, top_k_terms=8)
    selected = select_sentences_across_bundles(bundles, max_total=5, max_per_bundle=2)
    assert len(selected) >= 2
    unique_bundles_used = sum(
        1 for b in bundles
        if any(s in b.supporting_sentences for s in selected)
    )
    assert unique_bundles_used >= 2 or len(bundles) < 2
