"""Tests for study/card_generator.py -- card generation from compose_answer output."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from study.card_generator import (
    generate_cards,
    generate_cards_from_chunks,
    generate_practice_exam,
    postprocess_cards,
    _extract_tags,
    _make_citations_from_chunks,
)
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


# ---- Structure-first generation tests ----

def _chunk(text: str, chunk_id: str = "c1") -> dict:
    """Fixture chunk with metadata."""
    return {
        "text": text,
        "metadata": {"chunk_id": chunk_id, "book": "TestBook", "section_title": "Test"},
    }


def test_definition_lowercase_pattern():
    """Chunk with 'X is defined as' generates a DEFINITION card."""
    chunks = [
        _chunk(
            "Reinforcement is defined as a learning paradigm where agents learn from rewards.",
            "ch1",
        )
    ]
    cards = generate_cards_from_chunks(chunks, max_cards=10, seed=42)
    def_cards = [c for c in cards if c.card_type == CardType.DEFINITION.value]
    assert len(def_cards) >= 1
    assert "reinforcement" in def_cards[0].prompt.lower() or "Reinforcement" in def_cards[0].prompt
    assert "reward" in def_cards[0].answer.lower()


def test_list_card_generation():
    """Chunk with 3+ bullet items generates LIST card."""
    chunks = [
        _chunk(
            "Key steps:\n- First, gather data.\n- Second, train the model.\n- Third, evaluate.",
            "ch2",
        )
    ]
    cards = generate_cards_from_chunks(chunks, max_cards=10, seed=42)
    list_cards = [c for c in cards if c.card_type == CardType.LIST.value]
    assert len(list_cards) >= 1
    assert "List" in list_cards[0].prompt or "list" in list_cards[0].prompt.lower()
    assert "gather" in list_cards[0].answer or "First" in list_cards[0].answer


def test_true_false_generation():
    """Chunk with declarative sentence generates TRUE_FALSE card."""
    chunks = [
        _chunk(
            "Introduction. Gradient descent is an iterative optimization algorithm used to minimize a loss function by updating parameters in the direction of steepest descent.",
            "ch3",
        )
    ]
    cards = generate_cards_from_chunks(chunks, max_cards=10, seed=42)
    tf_cards = [c for c in cards if c.card_type == CardType.TRUE_FALSE.value]
    assert len(tf_cards) >= 1
    assert "True or False" in tf_cards[0].prompt
    assert "True" in tf_cards[0].answer


def test_exam_blueprint_respected():
    """Exam generation matches blueprint counts or documents fallback."""
    chunks = [
        _chunk("Term A is defined as the first concept. Term B means the second concept.", "c1"),
        _chunk("Steps:\n- One\n- Two\n- Three\n- Four", "c2"),
    ]
    blueprint = {
        CardType.DEFINITION.value: 2,
        CardType.LIST.value: 1,
        CardType.SHORT_ANSWER.value: 2,
    }
    exam = generate_practice_exam(chunks, exam_size=10, blueprint=blueprint, seed=123)
    assert "questions" in exam
    assert "meta" in exam
    assert "counts_by_type" in exam["meta"]
    counts = exam["meta"]["counts_by_type"]
    assert counts.get(CardType.DEFINITION.value, 0) <= 2
    assert counts.get(CardType.LIST.value, 0) <= 1


def test_stable_card_ids():
    """Running generator twice yields same IDs; no duplicates."""
    chunks = [
        _chunk("Reinforcement is defined as reward-based learning.", "ch1"),
        _chunk("Steps:\n- A\n- B\n- C", "ch2"),
    ]
    cards1 = generate_cards_from_chunks(chunks, max_cards=10, seed=99)
    cards2 = generate_cards_from_chunks(chunks, max_cards=10, seed=99)
    ids1 = [c.card_id for c in cards1]
    ids2 = [c.card_id for c in cards2]
    assert ids1 == ids2
    assert len(ids1) == len(set(ids1))


def test_chunks_without_chunk_id_accepted():
    """Chunks without chunk_id (pack/upload format) are accepted; no branching on origin."""
    chunks = [
        {
            "text": "Reinforcement is defined as reward-based learning.",
            "metadata": {
                "book_id": "abc123",
                "book": "MyUpload",
                "chapter_number": "3",
                "section_number": "3.1",
                "chunk_index": 0,
            },
        }
    ]
    cards = generate_cards_from_chunks(chunks, max_cards=5, seed=42)
    assert len(cards) >= 1
    for c in cards:
        assert len(c.citations) >= 1
        assert c.citations[0].chunk_id  # synthesized from metadata
        assert "abc123" in c.citations[0].chunk_id or "MyUpload" in c.citations[0].chunk_id


def test_postprocess_cards_hook():
    """postprocess_cards with mode=none returns cards unchanged."""
    from study.models import Card, Citation
    cards = [
        Card(
            card_id="abc",
            book_name="B",
            tags=[],
            prompt="P",
            answer="A",
            card_type=CardType.SHORT_ANSWER.value,
            citations=[Citation(chunk_id="c1", chapter="", section="", pages="")],
        )
    ]
    result = postprocess_cards(cards, mode="none")
    assert result == cards
