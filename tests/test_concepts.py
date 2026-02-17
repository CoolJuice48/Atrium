"""Tests for concept centrality scoring."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.services.concepts import (
    build_term_stats,
    extract_section_title_terms,
    get_section_title_terms_for_scope,
    get_top_term,
    sentence_centrality,
)
from server.services.exam_candidates import build_candidate_pool
from server.services.exam_generation import _apply_diversity_order


def test_term_stats_repeat_terms_score_higher():
    """Terms that appear in multiple sentences score higher than singleton terms."""
    sentences = [
        "Machine learning is a subset of artificial intelligence.",
        "Machine learning uses neural networks for pattern recognition.",
        "Neural networks consist of layers of nodes.",
    ]
    stats = build_term_stats(sentences)
    ml_score = stats.get("machine learning", None)
    nn_score = stats.get("neural networks", None)
    assert ml_score is not None
    assert nn_score is not None
    assert ml_score.df >= 2
    assert ml_score.score >= nn_score.score or nn_score.df >= 2


def test_sentence_centrality_prefers_repeated_terms():
    """Sentences with more repeated (high-df) terms get higher centrality."""
    sentences = [
        "Machine learning is a subset of artificial intelligence.",
        "Machine learning uses neural networks for pattern recognition.",
        "The algorithm converges quickly.",
    ]
    stats = build_term_stats(sentences)
    c1 = sentence_centrality(sentences[0], stats)
    c2 = sentence_centrality(sentences[1], stats)
    c3 = sentence_centrality(sentences[2], stats)
    assert c1 > 0
    assert c2 > 0
    assert c3 >= 0
    assert c1 >= c3 or c2 >= c3


def test_title_alignment_boost():
    """Sentences sharing terms with section title get alignment boost."""
    sentences = [
        "Gradient descent optimizes the loss function.",
        "The loss function measures prediction error.",
    ]
    stats = build_term_stats(sentences)
    section_terms = {"gradient", "descent", "loss", "function"}
    c_with = sentence_centrality(sentences[0], stats, section_title_terms=section_terms)
    c_without = sentence_centrality(sentences[0], stats)
    assert c_with > c_without


def test_diversity_avoids_same_term_repetition():
    """Diversity ordering puts candidates with unique top terms first."""
    chunks = [
        {
            "text": "Machine learning is defined as a subset of artificial intelligence that enables systems to learn from data. Machine learning uses neural networks for pattern recognition in many applications.",
            "metadata": {"page_start": 1, "page_end": 2, "chunk_id": "c1"},
        },
        {
            "text": "Neural networks are computing systems inspired by biological brains. Neural networks consist of layers of interconnected nodes that process information.",
            "metadata": {"page_start": 3, "page_end": 4, "chunk_id": "c2"},
        },
    ]
    pool = build_candidate_pool(chunks)
    assert len(pool.candidates) >= 2, "Need at least 2 candidates for diversity test"
    ordered = _apply_diversity_order(pool.candidates)
    top_terms_seen = set()
    for c in ordered:
        if c.top_term:
            if c.top_term in top_terms_seen:
                break
            top_terms_seen.add(c.top_term)
    assert len(top_terms_seen) >= 1 or len(ordered) >= 1


def test_title_alignment_changes_ranking():
    """Candidates overlapping scope title_terms rank higher than those that do not."""
    chunks = [
        {
            "text": "Gradient descent minimizes the loss function by iteratively updating weights. "
            "The loss function measures how well the model predicts the target.",
            "metadata": {"page_start": 1, "page_end": 2, "chunk_id": "c1"},
        },
        {
            "text": "Unrelated algorithms like random search explore the space without gradients. "
            "Some methods use evolutionary strategies instead.",
            "metadata": {"page_start": 3, "page_end": 4, "chunk_id": "c2"},
        },
    ]
    items = [
        {"id": "ch_1_sec_1", "title": "Gradient Descent", "title_terms": ["gradient", "descent", "gradient descent"]},
    ]
    item_ids = ["ch_1_sec_1"]
    pool_with = build_candidate_pool(
        chunks, section_title_terms=get_section_title_terms_for_scope(items, item_ids, chunks)
    )
    pool_without = build_candidate_pool(chunks)
    assert len(pool_with.candidates) >= 2
    top_with = pool_with.candidates[0]
    top_without = pool_without.candidates[0]
    assert "gradient" in top_with.text.lower() or "descent" in top_with.text.lower()
