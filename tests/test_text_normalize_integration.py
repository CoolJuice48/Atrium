"""Integration tests for text normalization in candidate pool."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.services.exam_candidates import build_candidate_pool
from server.services.concepts import build_term_stats


def test_candidate_pool_normalizes_and_dedupes():
    """Build pool from chunk with duplicated paragraph+bullets and di↵erent."""
    chunk_text = (
        "Machine learning is defined as a subset of artificial intelligence. "
        "Machine learning is defined as a subset of artificial intelligence. "
        "The algorithm uses gradient descent for optimization. "
        "Reinforcement learning is di\u21b5erent from supervised learning in key ways."
    )
    chunks = [
        {
            "text": chunk_text,
            "metadata": {"page_start": 1, "page_end": 2, "chunk_id": "c1"},
        },
    ]
    pool = build_candidate_pool(chunks)
    texts = [c.text for c in pool.candidates]
    # Dedupe should reduce: 2 identical + 2 unique -> at most 3
    assert len(texts) <= 3
    for t in texts:
        assert "\u21b5" not in t
    term_stats = build_term_stats(texts)
    for term in term_stats:
        assert "\u21b5" not in term
        assert "\ufffd" not in term
