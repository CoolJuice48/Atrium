"""Tests for study/gap_planning.py -- gap-driven card selection and seeding."""

import sys
import json
import tempfile
from pathlib import Path
from datetime import date, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from study.models import Card, Citation
from study.storage import CardStore
from study.gap_planning import select_gap_cards, seed_gap_cards, load_graph_registry
from study.plan import make_study_plan, SECONDS_PER_CARD
from study.card_types import CardType
from graph.models import GraphRegistry, QNode, ConceptNode, make_concept_id


# ============================================================================
# Helpers
# ============================================================================

def _make_store(tmp_dir, cards):
    """Create a CardStore and populate it."""
    store = CardStore(Path(tmp_dir) / 'gap_test.jsonl')
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


def _make_graph(tmp_dir, concepts):
    """Build and save a graph registry with given concept specs.

    concepts: list of dicts with keys: name, mastery, books, linked_qnodes
    Returns the registry path.
    """
    path = Path(tmp_dir) / 'graph_registry.json'
    reg = GraphRegistry()

    for i, spec in enumerate(concepts):
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
        # Add a QNode for each linked qnode
        for qid in spec.get('linked_qnodes', []):
            reg.add_qnode(QNode(
                question_id=qid,
                question_text=f'Q about {spec["name"]}',
                terminality_score=spec.get('terminality', 0.5),
            ))

    reg.save(path)
    return path


# ============================================================================
# TESTS: select_gap_cards
# ============================================================================

def test_select_gap_cards_basic():
    """select_gap_cards returns cards matching high-gap concepts."""
    with tempfile.TemporaryDirectory() as tmp:
        graph_path = _make_graph(tmp, [
            {'name': 'recursion', 'mastery': 0.0},
            {'name': 'sorting', 'mastery': 0.9},
        ])
        cards = [
            _card('c1', tags=['BookA', 'recursion'],
                  prompt='What is recursion?'),
            _card('c2', tags=['BookA', 'sorting'],
                  prompt='What is sorting?'),
        ]
        store = _make_store(tmp, cards)
        selected = select_gap_cards(graph_path, store, minutes_budget=5)
        # recursion has higher gap (mastery 0.0) so should be selected first
        assert len(selected) >= 1
        assert selected[0].card_id == 'c1'


def test_select_gap_cards_prefers_due():
    """Among matching cards, due/overdue cards are preferred."""
    with tempfile.TemporaryDirectory() as tmp:
        graph_path = _make_graph(tmp, [
            {'name': 'hashing', 'mastery': 0.1},
        ])
        cards = [
            _card('overdue', tags=['BookA', 'hashing'], due_days_ago=5),
            _card('future', tags=['BookA', 'hashing'], due_days_ago=-10),
        ]
        store = _make_store(tmp, cards)
        selected = select_gap_cards(graph_path, store, minutes_budget=5)
        assert len(selected) >= 1
        assert selected[0].card_id == 'overdue'


def test_select_gap_cards_deterministic():
    """Same inputs produce same selection."""
    with tempfile.TemporaryDirectory() as tmp:
        graph_path = _make_graph(tmp, [
            {'name': 'trees', 'mastery': 0.1},
            {'name': 'graphs', 'mastery': 0.2},
        ])
        cards = [
            _card(f'c{i}', tags=['BookA', 'trees' if i < 3 else 'graphs'])
            for i in range(6)
        ]
        store = _make_store(tmp, cards)
        s1 = select_gap_cards(graph_path, store, minutes_budget=5)
        s2 = select_gap_cards(graph_path, store, minutes_budget=5)
        assert [c.card_id for c in s1] == [c.card_id for c in s2]


def test_select_gap_cards_book_filter():
    """Book filter limits selection to matching book."""
    with tempfile.TemporaryDirectory() as tmp:
        graph_path = _make_graph(tmp, [
            {'name': 'pointers', 'mastery': 0.0, 'books': ['BookA']},
            {'name': 'lambdas', 'mastery': 0.0, 'books': ['BookB']},
        ])
        cards = [
            _card('a1', book='BookA', tags=['BookA', 'pointers']),
            _card('b1', book='BookB', tags=['BookB', 'lambdas']),
        ]
        store = _make_store(tmp, cards)
        selected = select_gap_cards(graph_path, store, minutes_budget=5,
                                    book='BookA')
        for c in selected:
            assert c.book_name == 'BookA'


def test_select_gap_cards_empty_graph():
    """Empty graph returns no cards."""
    with tempfile.TemporaryDirectory() as tmp:
        graph_path = _make_graph(tmp, [])
        cards = [_card('c1')]
        store = _make_store(tmp, cards)
        selected = select_gap_cards(graph_path, store, minutes_budget=5)
        assert selected == []


def test_select_gap_cards_respects_budget():
    """Number of selected cards fits within time budget."""
    with tempfile.TemporaryDirectory() as tmp:
        graph_path = _make_graph(tmp, [
            {'name': f'concept_{i}', 'mastery': 0.0}
            for i in range(20)
        ])
        cards = [
            _card(f'c{i}', tags=['BookA', f'concept_{i}'])
            for i in range(20)
        ]
        store = _make_store(tmp, cards)
        # 2-minute budget = 120 seconds / 35 = 3 cards max
        selected = select_gap_cards(graph_path, store, minutes_budget=2)
        max_cards = max(1, int(2 * 60 / SECONDS_PER_CARD))
        assert len(selected) <= max_cards


def test_select_by_prompt_match():
    """Cards can be matched by concept name in prompt."""
    with tempfile.TemporaryDirectory() as tmp:
        graph_path = _make_graph(tmp, [
            {'name': 'dynamic programming', 'mastery': 0.0},
        ])
        cards = [
            _card('dp1', tags=['BookA'],
                  prompt='What is dynamic programming?'),
        ]
        store = _make_store(tmp, cards)
        selected = select_gap_cards(graph_path, store, minutes_budget=5)
        assert len(selected) == 1
        assert selected[0].card_id == 'dp1'


# ============================================================================
# TESTS: seed_gap_cards
# ============================================================================

def _mock_answer_fn(question, book):
    """Mock answer function that returns a fixed payload."""
    return {
        'question': question,
        'answer_dict': {
            'answer': f'The answer to: {question}',
            'key_points': [f'Key point about {question}'],
            'citations': ['BookA, \u00a71.1, p.10'],
            'confidence': {'level': 'high'},
        },
        'retrieved_chunks': [
            {
                'text': f'Text about {question}',
                'metadata': {
                    'chunk_id': 'seed_chunk_1',
                    'book': book or 'BookA',
                    'section': '1.1',
                    'pages': '10-15',
                },
            },
        ],
    }


def test_seed_creates_new_cards():
    """Seeding creates cards for uncovered gap concepts."""
    with tempfile.TemporaryDirectory() as tmp:
        graph_path = _make_graph(tmp, [
            {'name': 'quantum computing', 'mastery': 0.0},
        ])
        store = _make_store(tmp, [])
        initial_count = store.count()

        seeded = seed_gap_cards(
            graph_path, store,
            answer_fn=_mock_answer_fn,
            max_seeds=3,
        )

        assert len(seeded) >= 1
        assert store.count() > initial_count
        # Seeded cards should be in the store
        for card in seeded:
            assert store.get_card(card.card_id) is not None


def test_seed_skips_covered_concepts():
    """Seeding skips concepts that already have cards."""
    with tempfile.TemporaryDirectory() as tmp:
        graph_path = _make_graph(tmp, [
            {'name': 'binary tree', 'mastery': 0.0},
        ])
        # Card already exists for 'binary tree'
        existing = _card('bt1', tags=['BookA', 'binary tree'],
                         prompt='What is binary tree?')
        store = _make_store(tmp, [existing])
        initial_count = store.count()

        seeded = seed_gap_cards(
            graph_path, store,
            answer_fn=_mock_answer_fn,
        )

        assert seeded == []
        assert store.count() == initial_count


def test_seed_no_fn_returns_empty():
    """Without answer_fn, seeding returns empty list."""
    with tempfile.TemporaryDirectory() as tmp:
        graph_path = _make_graph(tmp, [
            {'name': 'topology', 'mastery': 0.0},
        ])
        store = _make_store(tmp, [])
        seeded = seed_gap_cards(graph_path, store, answer_fn=None)
        assert seeded == []


def test_seed_respects_max_seeds():
    """max_seeds limits the number of concepts seeded."""
    with tempfile.TemporaryDirectory() as tmp:
        graph_path = _make_graph(tmp, [
            {'name': f'concept_{i}', 'mastery': 0.0}
            for i in range(10)
        ])
        store = _make_store(tmp, [])
        seeded = seed_gap_cards(
            graph_path, store,
            answer_fn=_mock_answer_fn,
            max_seeds=2,
        )
        # Should seed at most 2 concepts (each may generate 1-2 cards)
        # Count unique "What is X?" prompts to count concepts
        seed_questions = {c.prompt for c in seeded
                          if c.prompt.startswith('What is ')}
        assert len(seed_questions) <= 2


def test_seed_book_filter():
    """Seeding respects book filter."""
    with tempfile.TemporaryDirectory() as tmp:
        graph_path = _make_graph(tmp, [
            {'name': 'tensors', 'mastery': 0.0, 'books': ['BookA']},
            {'name': 'monads', 'mastery': 0.0, 'books': ['BookB']},
        ])
        store = _make_store(tmp, [])
        seeded = seed_gap_cards(
            graph_path, store,
            book='BookA',
            answer_fn=_mock_answer_fn,
        )
        # Only 'tensors' should be seeded (BookA concept)
        for card in seeded:
            assert 'tensor' in card.prompt.lower() or card.book_name == 'BookA'


# ============================================================================
# TESTS: plan integration with gap boost
# ============================================================================

def test_plan_includes_gap_boost():
    """Plan includes gap_boost section with cards."""
    with tempfile.TemporaryDirectory() as tmp:
        graph_path = _make_graph(tmp, [
            {'name': 'stacks', 'mastery': 0.0},
        ])
        cards = [
            _card('s1', tags=['BookA', 'stacks'], prompt='What is a stack?'),
            _card('s2', tags=['BookA'], prompt='General card'),
        ]
        store = _make_store(tmp, cards)

        gap_cards = select_gap_cards(graph_path, store, minutes_budget=3)
        plan = make_study_plan(store, minutes=30,
                               graph_registry_path=graph_path,
                               gap_cards=gap_cards)

        assert 'gap_boost' in plan
        assert 'cards' in plan['gap_boost']
        assert 'concepts' in plan['gap_boost']
        assert 'estimated_minutes' in plan['gap_boost']


def test_plan_gap_snapshot():
    """Plan includes gap_snapshot from graph registry."""
    with tempfile.TemporaryDirectory() as tmp:
        graph_path = _make_graph(tmp, [
            {'name': 'heaps', 'mastery': 0.1},
            {'name': 'queues', 'mastery': 0.9},
        ])
        cards = [_card('c1')]
        store = _make_store(tmp, cards)

        plan = make_study_plan(store, minutes=30,
                               graph_registry_path=graph_path)

        gap_snap = plan['gap_snapshot']
        assert len(gap_snap) >= 1
        # heaps should have higher gap than queues
        names = [name for name, _ in gap_snap]
        assert 'heaps' in names


def test_plan_gap_boost_respects_time():
    """Gap boost cards are limited by the 10% time allocation."""
    with tempfile.TemporaryDirectory() as tmp:
        graph_path = _make_graph(tmp, [
            {'name': f'concept_{i}', 'mastery': 0.0}
            for i in range(20)
        ])
        cards = [
            _card(f'c{i}', tags=['BookA', f'concept_{i}'])
            for i in range(20)
        ]
        store = _make_store(tmp, cards)

        gap_cards = select_gap_cards(graph_path, store, minutes_budget=10)
        plan = make_study_plan(store, minutes=10,
                               graph_registry_path=graph_path,
                               gap_cards=gap_cards)

        # 10 min total, 10% = 1 min = 60s / 35 = 1 card max
        gap_boost = plan['gap_boost']
        max_gap = max(1, int(10 * 60 * 0.10) // SECONDS_PER_CARD)
        assert len(gap_boost['cards']) <= max_gap + 1


def test_plan_without_graph():
    """Plan works fine without a graph registry."""
    with tempfile.TemporaryDirectory() as tmp:
        cards = [_card(f'c{i}') for i in range(3)]
        store = _make_store(tmp, cards)
        plan = make_study_plan(store, minutes=30)
        assert plan['gap_boost']['cards'] == []
        assert plan['gap_snapshot'] == []


# ============================================================================
# TESTS: load_graph_registry helper
# ============================================================================

def test_load_graph_registry_nonexistent():
    """Loading from nonexistent path returns empty registry."""
    reg = load_graph_registry(Path('/tmp/nonexistent_graph_abc.json'))
    assert reg.count_concepts() == 0
    assert reg.count_qnodes() == 0
