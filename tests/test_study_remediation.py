"""Tests for study/remediation.py -- prerequisite remediation selector."""

import sys
import tempfile
from pathlib import Path
from datetime import date, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from study.models import Card, Citation
from study.storage import CardStore
from study.remediation import select_prereq_cards
from study.card_types import CardType
from graph.models import GraphRegistry, QNode, ConceptNode, make_concept_id


# ============================================================================
# Helpers
# ============================================================================

def _make_store(tmp_dir, cards):
    """Create a CardStore and populate it."""
    store = CardStore(Path(tmp_dir) / 'remediation_test.jsonl')
    if cards:
        store.upsert_cards(cards)
    return store


def _card(card_id, book='BookA', section='1.1', due_days_ago=1,
          interval=1, lapses=0, tags=None, prompt=None):
    """Create a card with convenient defaults."""
    return Card(
        card_id=card_id,
        book_name=book,
        tags=tags or [book],
        prompt=prompt or f'Q for {card_id}',
        answer=f'A for {card_id}',
        card_type=CardType.SHORT_ANSWER.value,
        citations=[Citation(chunk_id=f'chunk_{card_id}', section=section)],
        due_date=(date.today() - timedelta(days=due_days_ago)).isoformat(),
        interval_days=interval,
        lapses=lapses,
        last_reviewed=date.today().isoformat(),
    )


def _make_graph(tmp_dir, concepts, cooccurrences=None):
    """Build and save a graph registry.

    concepts: list of dicts with keys: name, mastery, sections, books, linked_qnodes
    cooccurrences: list of (name_a, name_b, count) tuples
    Returns the registry path.
    """
    path = Path(tmp_dir) / 'graph_registry.json'
    reg = GraphRegistry()

    for spec in concepts:
        cid = make_concept_id(spec['name'])
        reg.add_concept(ConceptNode(
            concept_id=cid,
            name=spec['name'],
            occurrences=spec.get('occurrences', 1),
            books=spec.get('books', ['BookA']),
            sections=spec.get('sections', ['1.1']),
            mastery_score=spec.get('mastery', 0.0),
            linked_qnodes=spec.get('linked_qnodes', []),
        ))
        for qid in spec.get('linked_qnodes', []):
            reg.add_qnode(QNode(
                question_id=qid,
                question_text=f'Q about {spec["name"]}',
                terminality_score=spec.get('terminality', 0.5),
            ))

    if cooccurrences:
        for name_a, name_b, count in cooccurrences:
            cid_a = make_concept_id(name_a)
            cid_b = make_concept_id(name_b)
            for _ in range(count):
                reg.link_concept_cooccurrence(cid_a, cid_b)

    reg.save(path)
    return path


# ============================================================================
# TESTS: select_prereq_cards
# ============================================================================

def test_selects_earlier_section_prereqs():
    """Prereqs from earlier sections are selected."""
    with tempfile.TemporaryDirectory() as tmp:
        graph_path = _make_graph(tmp, [
            {'name': 'recursion', 'sections': ['3.1']},
            {'name': 'functions', 'sections': ['1.1']},
            {'name': 'variables', 'sections': ['1.2']},
        ], cooccurrences=[
            ('recursion', 'functions', 3),
            ('recursion', 'variables', 2),
        ])

        failed = _card('failed_1', tags=['BookA', 'recursion'],
                        prompt='Explain recursion')
        prereq_cards = [
            _card('fn1', section='1.1', tags=['BookA', 'functions'],
                  prompt='What are functions?'),
            _card('var1', section='1.2', tags=['BookA', 'variables'],
                  prompt='What are variables?'),
        ]
        store = _make_store(tmp, [failed] + prereq_cards)

        result = select_prereq_cards(
            store=store, graph_path=graph_path, failed_card=failed,
        )

        assert result['concept'] == 'recursion'
        assert len(result['prereq_concepts']) >= 1
        assert len(result['selected_card_ids']) >= 1
        # Both prereq cards should be selected (from earlier sections)
        assert 'fn1' in result['selected_card_ids']
        assert 'var1' in result['selected_card_ids']


def test_prioritizes_low_mastery_prereqs():
    """Lower mastery prereq concepts are selected first."""
    with tempfile.TemporaryDirectory() as tmp:
        graph_path = _make_graph(tmp, [
            {'name': 'sorting', 'sections': ['5.1']},
            {'name': 'arrays', 'sections': ['2.1']},
            {'name': 'comparison', 'sections': ['2.2']},
            {'name': 'iteration', 'sections': ['3.1']},
        ], cooccurrences=[
            ('sorting', 'arrays', 2),
            ('sorting', 'comparison', 2),
            ('sorting', 'iteration', 2),
        ])

        failed = _card('sort_fail', tags=['BookA', 'sorting'],
                        prompt='Explain sorting')
        # 'arrays' card has high interval (high mastery)
        # 'comparison' card has low interval + lapses (low mastery)
        prereq_cards = [
            _card('arr1', section='2.1', tags=['BookA', 'arrays'],
                  prompt='What are arrays?', interval=30, lapses=0),
            _card('cmp1', section='2.2', tags=['BookA', 'comparison'],
                  prompt='What is comparison?', interval=1, lapses=3),
            _card('iter1', section='3.1', tags=['BookA', 'iteration'],
                  prompt='What is iteration?', interval=1, lapses=2),
        ]
        store = _make_store(tmp, [failed] + prereq_cards)

        result = select_prereq_cards(
            store=store, graph_path=graph_path, failed_card=failed,
            max_prereq_concepts=2,
        )

        # comparison and iteration have lower mastery, should be prioritized
        assert 'cmp1' in result['selected_card_ids']
        assert 'iter1' in result['selected_card_ids']


def test_respects_max_prereq_concepts():
    """max_prereq_concepts limits concepts used."""
    with tempfile.TemporaryDirectory() as tmp:
        graph_path = _make_graph(tmp, [
            {'name': 'target', 'sections': ['5.1']},
            {'name': 'prereq_a', 'sections': ['1.1']},
            {'name': 'prereq_b', 'sections': ['2.1']},
            {'name': 'prereq_c', 'sections': ['3.1']},
            {'name': 'prereq_d', 'sections': ['4.1']},
        ], cooccurrences=[
            ('target', 'prereq_a', 2),
            ('target', 'prereq_b', 2),
            ('target', 'prereq_c', 2),
            ('target', 'prereq_d', 2),
        ])

        failed = _card('t1', tags=['BookA', 'target'], prompt='Explain target')
        prereq_cards = [
            _card(f'p{i}', tags=['BookA', f'prereq_{c}'],
                  prompt=f'What is prereq_{c}?')
            for i, c in enumerate(['a', 'b', 'c', 'd'])
        ]
        store = _make_store(tmp, [failed] + prereq_cards)

        result = select_prereq_cards(
            store=store, graph_path=graph_path, failed_card=failed,
            max_prereq_concepts=2,
        )

        assert len(result['prereq_concepts']) <= 2


def test_respects_max_cards_total():
    """max_cards_total limits total cards returned."""
    with tempfile.TemporaryDirectory() as tmp:
        graph_path = _make_graph(tmp, [
            {'name': 'target', 'sections': ['5.1']},
            {'name': 'prereq_a', 'sections': ['1.1']},
            {'name': 'prereq_b', 'sections': ['2.1']},
        ], cooccurrences=[
            ('target', 'prereq_a', 3),
            ('target', 'prereq_b', 3),
        ])

        failed = _card('t1', tags=['BookA', 'target'], prompt='Explain target')
        # Multiple cards per prereq concept
        prereq_cards = [
            _card(f'pa{i}', tags=['BookA', 'prereq_a'],
                  prompt=f'Q about prereq_a #{i}')
            for i in range(5)
        ] + [
            _card(f'pb{i}', tags=['BookA', 'prereq_b'],
                  prompt=f'Q about prereq_b #{i}')
            for i in range(5)
        ]
        store = _make_store(tmp, [failed] + prereq_cards)

        result = select_prereq_cards(
            store=store, graph_path=graph_path, failed_card=failed,
            max_cards_total=3,
        )

        assert len(result['selected_card_ids']) <= 3


def test_deterministic_selection():
    """Same inputs produce same output."""
    with tempfile.TemporaryDirectory() as tmp:
        graph_path = _make_graph(tmp, [
            {'name': 'hashing', 'sections': ['4.1']},
            {'name': 'arrays', 'sections': ['1.1']},
            {'name': 'functions', 'sections': ['2.1']},
        ], cooccurrences=[
            ('hashing', 'arrays', 2),
            ('hashing', 'functions', 2),
        ])

        failed = _card('h1', tags=['BookA', 'hashing'], prompt='What is hashing?')
        prereq_cards = [
            _card('a1', tags=['BookA', 'arrays'], prompt='What are arrays?'),
            _card('f1', tags=['BookA', 'functions'], prompt='What are functions?'),
        ]
        store = _make_store(tmp, [failed] + prereq_cards)

        r1 = select_prereq_cards(
            store=store, graph_path=graph_path, failed_card=failed,
        )
        r2 = select_prereq_cards(
            store=store, graph_path=graph_path, failed_card=failed,
        )

        assert r1['selected_card_ids'] == r2['selected_card_ids']
        assert r1['prereq_concepts'] == r2['prereq_concepts']


def test_empty_graph_returns_empty():
    """No graph returns empty result."""
    with tempfile.TemporaryDirectory() as tmp:
        graph_path = _make_graph(tmp, [])
        failed = _card('c1', tags=['BookA', 'stuff'])
        store = _make_store(tmp, [failed])

        result = select_prereq_cards(
            store=store, graph_path=graph_path, failed_card=failed,
        )

        assert result['concept'] is None
        assert result['prereq_concepts'] == []
        assert result['selected_card_ids'] == []


def test_no_prereqs_returns_empty():
    """Concept with no co-occurrences returns empty prereqs."""
    with tempfile.TemporaryDirectory() as tmp:
        graph_path = _make_graph(tmp, [
            {'name': 'isolated', 'sections': ['1.1']},
        ])

        failed = _card('c1', tags=['BookA', 'isolated'],
                        prompt='Explain isolated')
        store = _make_store(tmp, [failed])

        result = select_prereq_cards(
            store=store, graph_path=graph_path, failed_card=failed,
        )

        assert result['concept'] == 'isolated'
        assert result['prereq_concepts'] == []
        assert result['selected_card_ids'] == []


def test_concept_from_prompt_fallback():
    """Concept can be guessed from prompt if not in tags."""
    with tempfile.TemporaryDirectory() as tmp:
        graph_path = _make_graph(tmp, [
            {'name': 'polymorphism', 'sections': ['5.1']},
            {'name': 'inheritance', 'sections': ['3.1']},
        ], cooccurrences=[
            ('polymorphism', 'inheritance', 3),
        ])

        # Card tags don't mention concept -- only prompt does
        failed = _card('p1', tags=['BookA'],
                        prompt='What is polymorphism?')
        prereq_cards = [
            _card('inh1', tags=['BookA', 'inheritance'],
                  prompt='What is inheritance?'),
        ]
        store = _make_store(tmp, [failed] + prereq_cards)

        result = select_prereq_cards(
            store=store, graph_path=graph_path, failed_card=failed,
        )

        assert result['concept'] == 'polymorphism'
        assert 'inheritance' in result['prereq_concepts']
        assert 'inh1' in result['selected_card_ids']


def test_excludes_failed_card():
    """The failed card itself is never in the selected prereq cards."""
    with tempfile.TemporaryDirectory() as tmp:
        graph_path = _make_graph(tmp, [
            {'name': 'stacks', 'sections': ['3.1']},
            {'name': 'arrays', 'sections': ['1.1']},
        ], cooccurrences=[
            ('stacks', 'arrays', 2),
        ])

        failed = _card('s1', tags=['BookA', 'stacks'],
                        prompt='What is a stack?')
        prereq_cards = [
            _card('a1', tags=['BookA', 'arrays'],
                  prompt='What are arrays?'),
        ]
        store = _make_store(tmp, [failed] + prereq_cards)

        result = select_prereq_cards(
            store=store, graph_path=graph_path, failed_card=failed,
        )

        assert 's1' not in result['selected_card_ids']


def test_prefers_due_cards():
    """Among matching cards, due/overdue cards are preferred."""
    with tempfile.TemporaryDirectory() as tmp:
        graph_path = _make_graph(tmp, [
            {'name': 'trees', 'sections': ['4.1']},
            {'name': 'nodes', 'sections': ['2.1']},
        ], cooccurrences=[
            ('trees', 'nodes', 3),
        ])

        failed = _card('t1', tags=['BookA', 'trees'],
                        prompt='What are trees?')
        prereq_cards = [
            _card('n_due', tags=['BookA', 'nodes'],
                  prompt='What are nodes?', due_days_ago=5),
            _card('n_future', tags=['BookA', 'nodes'],
                  prompt='Explain nodes', due_days_ago=-10),
        ]
        store = _make_store(tmp, [failed] + prereq_cards)

        result = select_prereq_cards(
            store=store, graph_path=graph_path, failed_card=failed,
        )

        assert result['selected_card_ids'][0] == 'n_due'


def test_book_filter():
    """Book filter restricts prereq card selection."""
    with tempfile.TemporaryDirectory() as tmp:
        graph_path = _make_graph(tmp, [
            {'name': 'queues', 'sections': ['4.1'], 'books': ['BookA', 'BookB']},
            {'name': 'linked lists', 'sections': ['2.1'], 'books': ['BookA', 'BookB']},
        ], cooccurrences=[
            ('queues', 'linked lists', 3),
        ])

        failed = _card('q1', book='BookA', tags=['BookA', 'queues'],
                        prompt='What is a queue?')
        prereq_cards = [
            _card('ll_a', book='BookA', tags=['BookA', 'linked lists'],
                  prompt='What is a linked list?'),
            _card('ll_b', book='BookB', tags=['BookB', 'linked lists'],
                  prompt='What is a linked list?'),
        ]
        store = _make_store(tmp, [failed] + prereq_cards)

        result = select_prereq_cards(
            store=store, graph_path=graph_path, failed_card=failed,
            book='BookA',
        )

        assert 'll_a' in result['selected_card_ids']
        assert 'll_b' not in result['selected_card_ids']
