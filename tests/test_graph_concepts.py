"""Tests for graph/concepts.py -- concept extraction."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from graph.concepts import extract_concepts, _extract_from_text, _normalize_term, make_concept_nodes
from graph.models import make_concept_id


def test_extract_capitalized_terms():
    """Capitalized multi-word terms are extracted."""
    terms = _extract_from_text("A Binary Search Tree stores elements efficiently.")
    term_lower = [t.lower() for t in terms]
    assert any('binary search tree' in t for t in term_lower)


def test_extract_single_capitalized():
    """Single capitalized words >= 4 chars are extracted."""
    terms = _extract_from_text("The Queue is a FIFO structure.")
    term_lower = [t.lower() for t in terms]
    assert 'queue' in term_lower


def test_extract_code_tokens():
    """C++ style tokens like std::vector are extracted."""
    terms = _extract_from_text("Use std::vector for dynamic arrays.")
    assert any('std::vector' in t for t in terms)


def test_extract_namespace_tokens():
    """Namespace::function tokens are extracted."""
    terms = _extract_from_text("Call MyClass::method to process data.")
    assert any('MyClass::method' in t for t in terms)


def test_extract_compound_terms():
    """Hyphenated terms are extracted."""
    terms = _extract_from_text("The red-black tree balances itself.")
    assert any('red-black' in t for t in terms)


def test_extract_noun_like():
    """Long non-stopword tokens are extracted."""
    terms = _extract_from_text("The algorithm performs efficient sorting.")
    term_lower = [t.lower() for t in terms]
    assert 'algorithm' in term_lower
    assert 'sorting' in term_lower


def test_stopwords_excluded():
    """Common stopwords are not extracted as concepts."""
    terms = _extract_from_text("However there should never be anything through those between.")
    term_lower = [t.lower() for t in terms]
    for sw in ['however', 'there', 'should', 'never', 'anything', 'through', 'those', 'between']:
        assert sw not in term_lower


def test_extract_from_answer_dict():
    """extract_concepts pulls terms from key_points and question."""
    answer_dict = {
        'key_points': [
            'Gradient Descent minimizes the loss function.',
            'The learning rate controls step size.',
        ],
    }
    chunks = [
        {'text': '', 'metadata': {'section_title': 'Optimization Methods'}},
    ]
    terms = extract_concepts("How does Gradient Descent work?", answer_dict, chunks)
    term_set = set(terms)
    assert 'gradient descent' in term_set or 'Gradient Descent' in term_set


def test_extract_deduplicated():
    """Extracted concepts are deduplicated."""
    answer_dict = {
        'key_points': [
            'Binary Search finds elements.',
            'Binary Search is efficient.',
        ],
    }
    terms = extract_concepts("What is Binary Search?", answer_dict, [])
    # "binary search" should appear only once
    count = sum(1 for t in terms if 'binary' in t.lower() and 'search' in t.lower())
    assert count == 1


def test_normalize_code_tokens_preserved():
    """Code tokens with :: or <> keep their case."""
    assert _normalize_term('std::vector') == 'std::vector'
    assert _normalize_term('map<string>') == 'map<string>'


def test_normalize_regular_terms_lowered():
    """Regular terms are lowercased."""
    assert _normalize_term('Binary Search') == 'binary search'
    assert _normalize_term('  GRADIENT  ') == 'gradient'


def test_make_concept_nodes():
    """make_concept_nodes builds properly linked ConceptNode objects."""
    terms = ['gradient descent', 'learning rate']
    nodes = make_concept_nodes(terms, ['BookA'], ['2.1'], 'q1')
    assert len(nodes) == 2
    assert all(n.linked_qnodes == ['q1'] for n in nodes)
    assert all('BookA' in n.books for n in nodes)
    names = {n.name for n in nodes}
    assert 'gradient descent' in names
    assert 'learning rate' in names


def test_extract_from_section_title():
    """Section titles from chunk metadata yield concepts."""
    answer_dict = {'key_points': []}
    chunks = [
        {'text': '', 'metadata': {'section_title': 'Dynamic Programming'}},
    ]
    terms = extract_concepts("How does DP work?", answer_dict, chunks)
    term_lower = [t.lower() for t in terms]
    assert any('dynamic' in t for t in term_lower)
