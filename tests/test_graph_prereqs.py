"""Tests for graph/prereqs.py -- prerequisite ordering."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from graph.prereqs import get_prereqs, _section_sort_key, _earliest_section
from graph.models import GraphRegistry, ConceptNode, make_concept_id


def _build_prereq_registry():
    """Build a registry with section-ordered concepts and co-occurrences."""
    reg = GraphRegistry()

    # Concept in section 1.1 (earliest)
    c1 = ConceptNode(
        concept_id=make_concept_id('variables'),
        name='variables',
        sections=['1.1'],
        books=['BookA'],
    )
    # Concept in section 2.3
    c2 = ConceptNode(
        concept_id=make_concept_id('functions'),
        name='functions',
        sections=['2.3'],
        books=['BookA'],
    )
    # Concept in section 5.1 (target)
    c3 = ConceptNode(
        concept_id=make_concept_id('recursion'),
        name='recursion',
        sections=['5.1'],
        books=['BookA'],
    )
    # Concept in section 8.2 (after target)
    c4 = ConceptNode(
        concept_id=make_concept_id('dynamic programming'),
        name='dynamic programming',
        sections=['8.2'],
        books=['BookA'],
    )

    for c in [c1, c2, c3, c4]:
        reg.add_concept(c)

    # Create co-occurrences with 'recursion'
    reg.link_concept_cooccurrence(c3.concept_id, c1.concept_id)  # recursion <-> variables
    reg.link_concept_cooccurrence(c3.concept_id, c1.concept_id)  # +1 count
    reg.link_concept_cooccurrence(c3.concept_id, c2.concept_id)  # recursion <-> functions
    reg.link_concept_cooccurrence(c3.concept_id, c4.concept_id)  # recursion <-> DP

    return reg


def test_prereqs_section_order():
    """Prerequisites are sorted by section order (earliest first)."""
    reg = _build_prereq_registry()
    prereqs = get_prereqs('recursion', reg)
    if len(prereqs) >= 2:
        names = [c.name for c, _ in prereqs]
        # 'variables' (1.1) should come before 'functions' (2.3)
        assert names.index('variables') < names.index('functions')


def test_prereqs_excludes_later_sections():
    """Concepts from later sections are not prerequisites."""
    reg = _build_prereq_registry()
    prereqs = get_prereqs('recursion', reg)
    prereq_names = {c.name for c, _ in prereqs}
    # 'dynamic programming' (8.2) should NOT be a prereq for 'recursion' (5.1)
    assert 'dynamic programming' not in prereq_names


def test_prereqs_includes_cooccurrence_count():
    """Each prereq includes its co-occurrence count."""
    reg = _build_prereq_registry()
    prereqs = get_prereqs('recursion', reg)
    for concept, count in prereqs:
        assert count >= 1


def test_prereqs_variables_higher_cooccurrence():
    """'variables' has higher co-occurrence with 'recursion' than 'functions'."""
    reg = _build_prereq_registry()
    prereqs = get_prereqs('recursion', reg)
    prereq_dict = {c.name: count for c, count in prereqs}
    assert prereq_dict.get('variables', 0) > prereq_dict.get('functions', 0)


def test_prereqs_unknown_concept():
    """Unknown concept returns empty list."""
    reg = GraphRegistry()
    assert get_prereqs('nonexistent', reg) == []


def test_prereqs_no_cooccurrences():
    """Concept with no co-occurrences returns empty list."""
    reg = GraphRegistry()
    cid = make_concept_id('lonely')
    reg.add_concept(ConceptNode(concept_id=cid, name='lonely', sections=['1.1']))
    assert get_prereqs('lonely', reg) == []


def test_prereqs_top_n():
    """top_n limits results."""
    reg = _build_prereq_registry()
    prereqs = get_prereqs('recursion', reg, top_n=1)
    assert len(prereqs) <= 1


def test_section_sort_key_numeric():
    """Section keys are parsed numerically."""
    assert _section_sort_key('1.1') < _section_sort_key('2.3')
    assert _section_sort_key('1.1') < _section_sort_key('1.2')
    assert _section_sort_key('2.10') > _section_sort_key('2.3')


def test_section_sort_key_deep():
    """Deep section numbers sort correctly."""
    assert _section_sort_key('1.1.1') < _section_sort_key('1.1.2')
    assert _section_sort_key('1.2') < _section_sort_key('2.1')


def test_earliest_section():
    """_earliest_section returns the minimum section key."""
    c = ConceptNode(concept_id='x', name='x', sections=['3.1', '1.2', '2.5'])
    assert _earliest_section(c) == (1, 2)


def test_earliest_section_empty():
    """Concept with no sections returns high sentinel."""
    c = ConceptNode(concept_id='x', name='x', sections=[])
    assert _earliest_section(c) == (999,)
