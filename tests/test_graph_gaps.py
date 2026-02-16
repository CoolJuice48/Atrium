"""Tests for graph/gaps.py -- gap scoring and ranking."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from graph.gaps import gap_score, get_ranked_gaps
from graph.models import GraphRegistry, QNode, ConceptNode


def _registry_with_concepts():
    """Build a registry with varied mastery levels."""
    reg = GraphRegistry()

    # High mastery concept
    reg.add_concept(ConceptNode(
        concept_id='strong', name='strong concept',
        mastery_score=0.9, books=['BookA'], linked_qnodes=['q1'],
    ))
    reg.add_qnode(QNode(question_id='q1', question_text='Q1',
                        terminality_score=0.9))

    # Low mastery concept
    reg.add_concept(ConceptNode(
        concept_id='weak', name='weak concept',
        mastery_score=0.1, books=['BookA'], linked_qnodes=['q2'],
    ))
    reg.add_qnode(QNode(question_id='q2', question_text='Q2',
                        terminality_score=0.8))

    # Zero mastery concept
    reg.add_concept(ConceptNode(
        concept_id='zero', name='zero concept',
        mastery_score=0.0, books=['BookA', 'BookB'], linked_qnodes=['q3'],
    ))
    reg.add_qnode(QNode(question_id='q3', question_text='Q3',
                        terminality_score=0.3))

    return reg


def test_low_mastery_high_gap():
    """Low mastery → high gap score."""
    reg = _registry_with_concepts()
    weak = reg.get_concept('weak')
    strong = reg.get_concept('strong')
    assert gap_score(weak, reg) > gap_score(strong, reg)


def test_zero_mastery_highest_gap():
    """Zero mastery concept has highest base gap."""
    reg = _registry_with_concepts()
    zero = reg.get_concept('zero')
    score = gap_score(zero, reg)
    assert score >= 1.0  # base is 1.0 + bonuses


def test_multi_book_bonus():
    """Concepts spanning multiple books with low mastery get bonus."""
    reg = GraphRegistry()
    single_book = ConceptNode(
        concept_id='sb', name='single', mastery_score=0.2,
        books=['BookA'], linked_qnodes=[],
    )
    multi_book = ConceptNode(
        concept_id='mb', name='multi', mastery_score=0.2,
        books=['BookA', 'BookB', 'BookC'], linked_qnodes=[],
    )
    reg.add_concept(single_book)
    reg.add_concept(multi_book)
    assert gap_score(multi_book, reg) > gap_score(single_book, reg)


def test_low_terminality_penalty():
    """Linked questions with low terminality add penalty."""
    reg = GraphRegistry()
    reg.add_qnode(QNode(question_id='q_low', question_text='Q',
                        terminality_score=0.1))
    reg.add_qnode(QNode(question_id='q_high', question_text='Q',
                        terminality_score=0.9))

    c_low_term = ConceptNode(
        concept_id='clt', name='low term', mastery_score=0.5,
        linked_qnodes=['q_low'],
    )
    c_high_term = ConceptNode(
        concept_id='cht', name='high term', mastery_score=0.5,
        linked_qnodes=['q_high'],
    )
    reg.add_concept(c_low_term)
    reg.add_concept(c_high_term)
    assert gap_score(c_low_term, reg) > gap_score(c_high_term, reg)


def test_ranked_gaps_ordering():
    """get_ranked_gaps returns highest gap first."""
    reg = _registry_with_concepts()
    ranked = get_ranked_gaps(reg, top_n=10)
    assert len(ranked) == 3
    scores = [s for _, s in ranked]
    assert scores == sorted(scores, reverse=True)


def test_ranked_gaps_top_n():
    """top_n limits the results."""
    reg = _registry_with_concepts()
    ranked = get_ranked_gaps(reg, top_n=1)
    assert len(ranked) == 1


def test_gap_changes_with_mastery():
    """Gap ranking changes when mastery changes."""
    reg = _registry_with_concepts()
    ranked_before = get_ranked_gaps(reg, top_n=3)
    first_before = ranked_before[0][0].concept_id

    # Improve the weakest concept's mastery
    weak = reg.get_concept(first_before)
    weak.mastery_score = 0.95

    ranked_after = get_ranked_gaps(reg, top_n=3)
    first_after = ranked_after[0][0].concept_id
    # The previously weakest concept should no longer be first
    assert first_after != first_before


def test_empty_registry():
    """Empty registry returns empty gaps."""
    reg = GraphRegistry()
    ranked = get_ranked_gaps(reg)
    assert ranked == []
