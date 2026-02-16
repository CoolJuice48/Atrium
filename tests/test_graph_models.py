"""Tests for graph/models.py -- QNode, ConceptNode, GraphRegistry."""

import sys
import json
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from graph.models import (
    QNode, ConceptNode, GraphRegistry,
    make_question_id, make_concept_id,
)


# ============================================================================
# TESTS: Deterministic IDs
# ============================================================================

def test_question_id_deterministic():
    """Same question text always produces the same ID."""
    q = "What is a binary search tree?"
    assert make_question_id(q) == make_question_id(q)


def test_question_id_normalized():
    """IDs are case-insensitive and strip whitespace."""
    assert make_question_id("What is X?") == make_question_id("  what is x?  ")


def test_question_id_differs_for_different_questions():
    """Different questions produce different IDs."""
    assert make_question_id("What is X?") != make_question_id("What is Y?")


def test_concept_id_deterministic():
    """Same term always produces the same ID."""
    assert make_concept_id("gradient") == make_concept_id("gradient")


def test_concept_id_normalized():
    """IDs are case-insensitive and strip whitespace."""
    assert make_concept_id("Gradient") == make_concept_id("  gradient  ")


# ============================================================================
# TESTS: QNode serialization
# ============================================================================

def test_qnode_to_dict_from_dict():
    """QNode round-trips through dict serialization."""
    qn = QNode(
        question_id='abc123',
        question_text='What is X?',
        citations=['chunk_1', 'chunk_2'],
        books=['BookA'],
        sections=['1.1'],
        terminality_score=0.8,
        confidence_snapshot={'level': 'high'},
    )
    d = qn.to_dict()
    restored = QNode.from_dict(d)
    assert restored.question_id == qn.question_id
    assert restored.question_text == qn.question_text
    assert restored.citations == qn.citations
    assert restored.terminality_score == 0.8


# ============================================================================
# TESTS: ConceptNode serialization
# ============================================================================

def test_concept_node_to_dict_from_dict():
    """ConceptNode round-trips through dict serialization."""
    cn = ConceptNode(
        concept_id='def456',
        name='gradient descent',
        occurrences=3,
        books=['BookA', 'BookB'],
        sections=['2.1'],
        mastery_score=0.5,
        linked_qnodes=['q1', 'q2'],
    )
    d = cn.to_dict()
    restored = ConceptNode.from_dict(d)
    assert restored.concept_id == cn.concept_id
    assert restored.name == cn.name
    assert restored.occurrences == 3
    assert restored.linked_qnodes == ['q1', 'q2']


# ============================================================================
# TESTS: GraphRegistry CRUD
# ============================================================================

def test_registry_add_qnode():
    """Adding a QNode and retrieving it."""
    reg = GraphRegistry()
    qn = QNode(question_id='q1', question_text='What is X?')
    reg.add_qnode(qn)
    assert reg.get_qnode('q1') is not None
    assert reg.count_qnodes() == 1


def test_registry_add_concept_merge():
    """Adding a concept twice merges occurrences and books."""
    reg = GraphRegistry()
    c1 = ConceptNode(concept_id='c1', name='tree', occurrences=1,
                     books=['BookA'], sections=['1.1'])
    c2 = ConceptNode(concept_id='c1', name='tree', occurrences=1,
                     books=['BookB'], sections=['2.1'])
    reg.add_concept(c1)
    reg.add_concept(c2)
    assert reg.count_concepts() == 1
    merged = reg.get_concept('c1')
    assert merged.occurrences == 2
    assert 'BookA' in merged.books
    assert 'BookB' in merged.books


def test_registry_link_qnode_concepts():
    """Linking QNode to concepts updates concept.linked_qnodes."""
    reg = GraphRegistry()
    reg.add_qnode(QNode(question_id='q1', question_text='What is X?'))
    reg.add_concept(ConceptNode(concept_id='c1', name='tree'))
    reg.add_concept(ConceptNode(concept_id='c2', name='graph'))
    reg.link_qnode_concepts('q1', ['c1', 'c2'])
    assert 'q1' in reg.get_concept('c1').linked_qnodes
    assert 'q1' in reg.get_concept('c2').linked_qnodes


def test_registry_cooccurrence():
    """Co-occurrence is bidirectional and accumulates."""
    reg = GraphRegistry()
    reg.add_concept(ConceptNode(concept_id='a', name='alpha'))
    reg.add_concept(ConceptNode(concept_id='b', name='beta'))
    reg.link_concept_cooccurrence('a', 'b')
    reg.link_concept_cooccurrence('a', 'b')
    assert reg.get_cooccurrences('a') == {'b': 2}
    assert reg.get_cooccurrences('b') == {'a': 2}


def test_registry_self_cooccurrence_ignored():
    """A concept cannot co-occur with itself."""
    reg = GraphRegistry()
    reg.add_concept(ConceptNode(concept_id='a', name='alpha'))
    reg.link_concept_cooccurrence('a', 'a')
    assert reg.get_cooccurrences('a') == {}


# ============================================================================
# TESTS: Persistence
# ============================================================================

def test_registry_save_load():
    """Registry round-trips through JSON."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'registry.json'

        reg = GraphRegistry()
        reg.add_qnode(QNode(question_id='q1', question_text='What is X?',
                            terminality_score=0.9))
        reg.add_concept(ConceptNode(concept_id='c1', name='tree',
                                    occurrences=2, books=['BookA']))
        reg.link_concept_cooccurrence('c1', 'c2')
        reg.save(path)

        assert path.exists()

        reg2 = GraphRegistry()
        reg2.load(path)
        assert reg2.count_qnodes() == 1
        assert reg2.count_concepts() == 1
        assert reg2.get_qnode('q1').terminality_score == 0.9
        assert reg2.get_cooccurrences('c1') == {'c2': 1}


def test_registry_load_nonexistent():
    """Loading from a nonexistent file doesn't crash."""
    reg = GraphRegistry()
    reg.load(Path('/tmp/nonexistent_graph_registry_abc.json'))
    assert reg.count_qnodes() == 0


def test_registry_deterministic_ordering():
    """Saved JSON has deterministic key ordering."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'registry.json'

        reg = GraphRegistry()
        # Add in reverse order
        reg.add_concept(ConceptNode(concept_id='z', name='zeta'))
        reg.add_concept(ConceptNode(concept_id='a', name='alpha'))
        reg.add_qnode(QNode(question_id='q2', question_text='Q2'))
        reg.add_qnode(QNode(question_id='q1', question_text='Q1'))
        reg.save(path)

        with open(path) as f:
            data = json.load(f)

        # Concepts and qnodes should be sorted by ID
        assert data['concepts'][0]['concept_id'] == 'a'
        assert data['concepts'][1]['concept_id'] == 'z'
        assert data['qnodes'][0]['question_id'] == 'q1'
        assert data['qnodes'][1]['question_id'] == 'q2'


def test_registry_get_concept_by_name():
    """Look up a concept by its name."""
    reg = GraphRegistry()
    cid = make_concept_id('gradient descent')
    reg.add_concept(ConceptNode(concept_id=cid, name='gradient descent'))
    found = reg.get_concept_by_name('gradient descent')
    assert found is not None
    assert found.name == 'gradient descent'


def test_registry_get_concept_by_name_not_found():
    """Return None for unknown concept name."""
    reg = GraphRegistry()
    assert reg.get_concept_by_name('nonexistent') is None
