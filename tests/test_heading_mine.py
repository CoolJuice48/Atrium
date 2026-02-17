"""Tests for heading mining from chunks."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.services.heading_mine import extract_headings_from_chunks


def test_heading_mining_fallback():
    """extract_headings_from_chunks finds heading-like lines (TitleCase, short, no verbs)."""
    chunks = [
        {
            "text": "Introduction\n\nThis chapter introduces the main concepts.\n\n"
            "Neural Network Architecture\n\n"
            "Neural networks consist of layers of nodes.",
            "metadata": {"page_start": 1, "page_end": 2},
        },
        {
            "text": "Backpropagation Algorithm\n\n"
            "The algorithm computes gradients using the chain rule.\n\n"
            "Some body text that is longer and contains verbs like is and are.",
            "metadata": {"page_start": 3, "page_end": 4},
        },
    ]
    headings = extract_headings_from_chunks(chunks)
    assert len(headings) >= 1
    assert any("Neural" in h or "Architecture" in h for h in headings)
    assert any("Backpropagation" in h or "Algorithm" in h for h in headings)
