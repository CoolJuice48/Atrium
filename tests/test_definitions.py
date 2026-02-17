"""Tests for DefinitionRegistry."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.services.definitions import (
    extract_definitions,
    pick_best_definition,
    registry_terms_ordered_by_centrality,
)
from server.services.exam_candidates import build_candidate_pool


def test_registry_prefers_high_centrality_definition():
    """When multiple definitions exist for a term, registry picks highest centrality."""
    chunks = [
        {
            "text": "Neural networks are defined as computing systems inspired by biological brains. "
            "Neural networks consist of layers of interconnected nodes that process information.",
            "metadata": {"page_start": 1, "page_end": 2, "chunk_id": "c1"},
        },
        {
            "text": "Gradient descent is defined as an optimization algorithm that minimizes the loss function.",
            "metadata": {"page_start": 3, "page_end": 4, "chunk_id": "c2"},
        },
    ]
    pool = build_candidate_pool(chunks)
    registry = extract_definitions(pool)
    assert len(registry) >= 1
    for key, d in registry.items():
        assert d.definition
        assert d.centrality_score >= 0
        assert d.term


def test_no_duplicate_definition_terms():
    """Registry has at most one definition per term (normalized)."""
    chunks = [
        {
            "text": "Neural networks are defined as computing systems inspired by biological brains. "
            "Neural networks consist of layers of interconnected nodes.",
            "metadata": {"page_start": 1, "page_end": 2, "chunk_id": "c1"},
        },
        {
            "text": "Gradient descent is defined as an optimization algorithm that minimizes the loss function.",
            "metadata": {"page_start": 3, "page_end": 4, "chunk_id": "c2"},
        },
    ]
    pool = build_candidate_pool(chunks)
    registry = extract_definitions(pool)
    terms = list(registry.keys())
    assert len(terms) == len(set(terms))
    for t in terms:
        assert registry[t].term
        assert registry[t].definition
