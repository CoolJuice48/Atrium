"""Tests for study/card_generator.py -- card generation from compose_answer output."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from study.card_generator import generate_cards, _extract_tags, _make_citations_from_chunks
from study.card_types import CardType
from study.models import make_card_id


def _sample_chunks():
    """Sample retrieved chunks matching the shape compose_answer expects."""
    return [
        {
            'text': (
                "A binary search tree is a data structure that maintains sorted order "
                "for efficient lookup and insertion.  BSTs support O(log n) operations."
            ),
            'metadata': {
                'chunk_id': 'TestBook|ch2|sec2.1|p10-15|i0|s0',
                'book': 'TestBook',
                'chapter': '2',
                'section': '2.1',
                'section_title': 'Binary Search Trees',
                'pages': '10-15',
            },
        },
        {
            'text': (
                "AVL trees maintain balance through rotations, ensuring O(log n) height."
            ),
            'metadata': {
                'chunk_id': 'TestBook|ch3|sec3.1|p20-22|i0|s0',
                'book': 'TestBook',
                'chapter': '3',
                'section': '3.1',
                'section_title': 'Balanced Trees',
                'pages': '20-22',
            },
        },
    ]


def _sample_answer_dict():
    """Sample compose_answer() return value."""
    return {
        'answer': (
            "A binary search tree is a data structure that maintains sorted order "
            "for efficient lookup and insertion."
        ),
        'key_points': [
            "Binary Search Trees maintain sorted order for efficient lookup.",
            "BSTs support O(log n) operations in balanced cases.",
        ],
        'citations': ['TestBook, §2.1, p.10-15', 'TestBook, §2.1, p.10-15'],
        'confidence': {
            'level': 'medium',
            'evidence_coverage_score': 0.35,
            'source_diversity_score': 1,
            'redundancy_score': 0.2,
            'contradiction_flag': False,
        },
    }


def test_definition_question_produces_definition_card():
    """'What is X?' should produce a definition card."""
    cards = generate_cards(
        "What is a binary search tree?",
        _sample_answer_dict(),
        _sample_chunks(),
    )
    types = [c.card_type for c in cards]
    assert CardType.DEFINITION.value in types


def test_cloze_cards_generated():
    """Key points with capitalized terms should produce cloze cards."""
    cards = generate_cards(
        "What is a binary search tree?",
        _sample_answer_dict(),
        _sample_chunks(),
    )
    cloze_cards = [c for c in cards if c.card_type == CardType.CLOZE.value]
    assert len(cloze_cards) >= 1
    # Cloze prompt should have a blank
    for c in cloze_cards:
        assert '______' in c.prompt


def test_compare_card_from_comparison_answer():
    """Answer with 'comparison' key should produce a compare card."""
    answer_dict = {
        'answer': 'SGD is simple. Adam uses adaptive rates.',
        'key_points': ['SGD uses constant learning rate.', 'Adam adapts learning rates.'],
        'citations': ['BookA, §4.1, p.80', 'BookA, §4.3, p.92'],
        'confidence': {'level': 'medium', 'evidence_coverage_score': 0.3,
                       'source_diversity_score': 1, 'redundancy_score': 0.1,
                       'contradiction_flag': False},
        'comparison': {
            'concept_a': {'name': 'SGD', 'summary': 'Simple gradient descent.', 'citations': []},
            'concept_b': {'name': 'Adam', 'summary': 'Adaptive moment estimation.', 'citations': []},
            'differences': ['SGD: constant lr  vs  Adam: adaptive lr'],
        },
    }
    chunks = [{
        'text': 'SGD vs Adam comparison text.',
        'metadata': {'chunk_id': 'B|ch4|sec4.1|p80-92|i0|s0', 'book': 'BookA',
                     'section': '4.1', 'pages': '80-92'},
    }]
    cards = generate_cards("Compare SGD vs Adam", answer_dict, chunks)
    types = [c.card_type for c in cards]
    assert CardType.COMPARE.value in types


def test_every_card_has_citation():
    """Every generated card must have at least 1 citation with a chunk_id."""
    cards = generate_cards(
        "What is a binary search tree?",
        _sample_answer_dict(),
        _sample_chunks(),
    )
    assert len(cards) > 0
    for card in cards:
        assert len(card.citations) >= 1
        assert card.citations[0].chunk_id != ''


def test_tags_include_book_name():
    """Tags should include the book name."""
    cards = generate_cards(
        "What is a binary search tree?",
        _sample_answer_dict(),
        _sample_chunks(),
    )
    for card in cards:
        assert 'TestBook' in card.tags


def test_max_cards_respected():
    """Never returns more than max_cards."""
    cards = generate_cards(
        "What is a binary search tree?",
        _sample_answer_dict(),
        _sample_chunks(),
        max_cards=2,
    )
    assert len(cards) <= 2


def test_empty_answer_returns_empty():
    """Empty answer dict returns no cards."""
    cards = generate_cards("anything", {'answer': '', 'key_points': [], 'citations': []}, [])
    assert cards == []


def test_card_id_determinism():
    """Same inputs always produce the same card_id."""
    id1 = make_card_id("What is X?", ['chunk_a', 'chunk_b'])
    id2 = make_card_id("What is X?", ['chunk_b', 'chunk_a'])  # different order
    assert id1 == id2  # sorted, so order doesn't matter

    id3 = make_card_id("What is Y?", ['chunk_a'])
    assert id1 != id3  # different prompt


def test_short_answer_fallback():
    """Non-definition questions should produce a short_answer card."""
    answer_dict = _sample_answer_dict()
    cards = generate_cards(
        "How do balanced trees work?",
        answer_dict,
        _sample_chunks(),
    )
    types = [c.card_type for c in cards]
    assert CardType.SHORT_ANSWER.value in types
    # Should NOT have a definition card
    assert CardType.DEFINITION.value not in types
