"""Tests for study/insights.py -- learning outcome analytics."""

import sys
import json
import tempfile
from pathlib import Path
from datetime import date, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from study.models import Card, Citation
from study.storage import CardStore
from study.insights import (
    compute_concept_difficulty,
    compute_remediation_effectiveness,
    compute_book_quality,
    _cards_for_concept,
)
from study.card_types import CardType
from graph.models import GraphRegistry, QNode, ConceptNode, make_concept_id


# ============================================================================
# Helpers
# ============================================================================

def _make_store(tmp_dir, cards):
    """Create a CardStore and populate it."""
    store = CardStore(Path(tmp_dir) / 'insight_test.jsonl')
    if cards:
        store.upsert_cards(cards)
    return store


def _card(card_id, book='BookA', tags=None, prompt=None,
          interval=1, lapses=0, reps=0, ease=2.5,
          created_days_ago=14, last_reviewed_days_ago=1):
    """Create a card with convenient defaults."""
    created = (date.today() - timedelta(days=created_days_ago)).isoformat()
    reviewed = (date.today() - timedelta(days=last_reviewed_days_ago)).isoformat()
    return Card(
        card_id=card_id,
        book_name=book,
        tags=tags or [book],
        prompt=prompt or f'Q for {card_id}',
        answer=f'A for {card_id}',
        card_type=CardType.SHORT_ANSWER.value,
        citations=[Citation(chunk_id=f'chunk_{card_id}')],
        due_date=date.today().isoformat(),
        interval_days=interval,
        ease_factor=ease,
        reps=reps,
        lapses=lapses,
        last_reviewed=reviewed,
        created_at=created,
    )


def _write_session_log(tmp_dir, records):
    """Write a session log JSONL file and return its path."""
    log_path = Path(tmp_dir) / 'session_log.jsonl'
    with open(log_path, 'w', encoding='utf-8') as f:
        for rec in records:
            f.write(json.dumps(rec) + '\n')
    return log_path


def _make_graph(tmp_dir, qnodes=None, concepts=None, cooccurrences=None):
    """Build and save a graph registry. Returns the registry path."""
    path = Path(tmp_dir) / 'graph_registry.json'
    reg = GraphRegistry()

    for qn in (qnodes or []):
        reg.add_qnode(qn)

    for cn in (concepts or []):
        reg.add_concept(cn)

    if cooccurrences:
        for a, b in cooccurrences:
            reg.link_concept_cooccurrence(a, b)

    reg.save(path)
    return path


# ============================================================================
# M1: Concept Difficulty
# ============================================================================

def test_concept_difficulty_empty_store():
    """Empty store returns empty results."""
    with tempfile.TemporaryDirectory() as tmp:
        store = _make_store(tmp, [])
        result = compute_concept_difficulty(store)
        assert result['concepts'] == []
        assert result['hardest'] == []


def test_concept_difficulty_basic():
    """Cards with lapses produce higher difficulty than clean cards."""
    with tempfile.TemporaryDirectory() as tmp:
        cards = [
            _card('c1', tags=['gradient descent'], lapses=3, interval=2),
            _card('c2', tags=['gradient descent'], lapses=4, interval=1),
            _card('c3', tags=['easy topic'], lapses=0, interval=10),
        ]
        store = _make_store(tmp, cards)
        result = compute_concept_difficulty(store)

        by_name = {c['name']: c for c in result['concepts']}
        assert 'gradient descent' in by_name
        assert 'easy topic' in by_name

        hard = by_name['gradient descent']
        easy = by_name['easy topic']
        assert hard['difficulty_score'] > easy['difficulty_score']
        assert hard['failure_rate'] == 1.0  # both cards have lapses
        assert easy['failure_rate'] == 0.0


def test_concept_difficulty_failure_rate():
    """Failure rate = cards with lapses>0 / total cards for concept."""
    with tempfile.TemporaryDirectory() as tmp:
        cards = [
            _card('c1', tags=['topic_a'], lapses=0),
            _card('c2', tags=['topic_a'], lapses=2),
            _card('c3', tags=['topic_a'], lapses=0),
            _card('c4', tags=['topic_a'], lapses=1),
        ]
        store = _make_store(tmp, cards)
        result = compute_concept_difficulty(store)

        by_name = {c['name']: c for c in result['concepts']}
        assert by_name['topic_a']['failure_rate'] == 0.5  # 2 of 4


def test_concept_difficulty_avg_lapses():
    """avg_lapses is the mean across matching cards."""
    with tempfile.TemporaryDirectory() as tmp:
        cards = [
            _card('c1', tags=['math'], lapses=2),
            _card('c2', tags=['math'], lapses=4),
        ]
        store = _make_store(tmp, cards)
        result = compute_concept_difficulty(store)

        by_name = {c['name']: c for c in result['concepts']}
        assert by_name['math']['avg_lapses'] == 3.0


def test_concept_difficulty_time_to_mastery():
    """avg_time_to_mastery measured from created_at to last_reviewed for mastered cards."""
    with tempfile.TemporaryDirectory() as tmp:
        # Card mastered (interval >= 7): created 20 days ago, reviewed 5 days ago → 15 days
        cards = [
            _card('c1', tags=['algo'], interval=10,
                  created_days_ago=20, last_reviewed_days_ago=5),
        ]
        store = _make_store(tmp, cards)
        result = compute_concept_difficulty(store)

        by_name = {c['name']: c for c in result['concepts']}
        assert by_name['algo']['avg_time_to_mastery'] == 15.0


def test_concept_difficulty_not_mastered():
    """Cards with interval < 7 yield avg_time_to_mastery = -1."""
    with tempfile.TemporaryDirectory() as tmp:
        cards = [
            _card('c1', tags=['new_topic'], interval=3),
        ]
        store = _make_store(tmp, cards)
        result = compute_concept_difficulty(store)

        by_name = {c['name']: c for c in result['concepts']}
        assert by_name['new_topic']['avg_time_to_mastery'] == -1.0


def test_concept_difficulty_hardest_ranking():
    """hardest list is sorted by difficulty_score descending."""
    with tempfile.TemporaryDirectory() as tmp:
        cards = [
            _card('c1', tags=['hard'], lapses=5, interval=1),
            _card('c2', tags=['medium'], lapses=2, interval=3),
            _card('c3', tags=['easy'], lapses=0, interval=15,
                  created_days_ago=15, last_reviewed_days_ago=0),
        ]
        store = _make_store(tmp, cards)
        result = compute_concept_difficulty(store)

        names = [n for n, _ in result['hardest']]
        assert names[0] == 'hard'
        # Verify scores are descending
        scores = [s for _, s in result['hardest']]
        assert scores == sorted(scores, reverse=True)


def test_concept_difficulty_ranking_deterministic():
    """Same input always produces same ranking."""
    with tempfile.TemporaryDirectory() as tmp:
        cards = [
            _card('c1', tags=['alpha'], lapses=2),
            _card('c2', tags=['beta'], lapses=2),
        ]
        store = _make_store(tmp, cards)
        r1 = compute_concept_difficulty(store)
        r2 = compute_concept_difficulty(store)
        assert r1['hardest'] == r2['hardest']
        assert r1['concepts'] == r2['concepts']


def test_concept_difficulty_with_graph_registry():
    """Concepts from graph registry are included even if no cards have them as tags."""
    with tempfile.TemporaryDirectory() as tmp:
        cards = [
            _card('c1', tags=['BookA'],
                  prompt='What is gradient descent?', lapses=1),
        ]
        store = _make_store(tmp, cards)

        cid = make_concept_id('gradient descent')
        graph_path = _make_graph(tmp, concepts=[
            ConceptNode(concept_id=cid, name='gradient descent',
                        books=['BookA']),
        ])

        result = compute_concept_difficulty(store, graph_path=graph_path)
        by_name = {c['name']: c for c in result['concepts']}
        assert 'gradient descent' in by_name


def test_concept_difficulty_remediation_trigger_rate():
    """Concepts mentioned in session logs as prereq_concepts_used get non-zero trigger rate."""
    with tempfile.TemporaryDirectory() as tmp:
        cards = [
            _card('c1', tags=['calculus'], lapses=1),
        ]
        store = _make_store(tmp, cards)
        log_path = _write_session_log(tmp, [
            {'avg_quality': 3.0, 'prereq_concepts_used': ['calculus'],
             'remediation_inserted_count': 2},
            {'avg_quality': 4.0, 'prereq_concepts_used': [],
             'remediation_inserted_count': 0},
        ])

        result = compute_concept_difficulty(store, session_log_path=log_path)
        by_name = {c['name']: c for c in result['concepts']}
        # 1 session out of 2 triggered remediation for 'calculus'
        assert by_name['calculus']['remediation_trigger_rate'] == 0.5


# ============================================================================
# M1 helper: _cards_for_concept
# ============================================================================

def test_cards_for_concept_by_tag():
    """Matches cards whose tags contain the concept name."""
    cards = [
        _card('c1', tags=['gradient descent']),
        _card('c2', tags=['other']),
    ]
    matched = _cards_for_concept('gradient descent', cards)
    assert len(matched) == 1
    assert matched[0].card_id == 'c1'


def test_cards_for_concept_by_prompt():
    """Falls back to prompt substring matching."""
    cards = [
        _card('c1', tags=['BookA'], prompt='What is gradient descent?'),
        _card('c2', tags=['BookA'], prompt='What is a tree?'),
    ]
    matched = _cards_for_concept('gradient descent', cards)
    assert len(matched) == 1
    assert matched[0].card_id == 'c1'


def test_cards_for_concept_no_duplicates():
    """A card matching both by tag and prompt is only included once."""
    cards = [
        _card('c1', tags=['gradient descent'],
              prompt='Explain gradient descent'),
    ]
    matched = _cards_for_concept('gradient descent', cards)
    assert len(matched) == 1


# ============================================================================
# M2: Remediation Effectiveness
# ============================================================================

def test_remediation_effectiveness_empty():
    """No log file returns zeros."""
    with tempfile.TemporaryDirectory() as tmp:
        log_path = Path(tmp) / 'nonexistent.jsonl'
        result = compute_remediation_effectiveness(log_path)
        assert result['total_sessions'] == 0
        assert result['uplift_rate'] == 0.0


def test_remediation_effectiveness_no_remediation():
    """Sessions without remediation: with counts are 0."""
    with tempfile.TemporaryDirectory() as tmp:
        log_path = _write_session_log(tmp, [
            {'avg_quality': 3.0, 'remediation_inserted_count': 0},
            {'avg_quality': 4.0, 'remediation_inserted_count': 0},
        ])
        result = compute_remediation_effectiveness(log_path)
        assert result['total_sessions'] == 2
        assert result['sessions_with_remediation'] == 0
        assert result['sessions_without_remediation'] == 2
        assert result['avg_quality_delta'] == 0.0


def test_remediation_effectiveness_basic():
    """Sessions with remediation produce correct delta."""
    with tempfile.TemporaryDirectory() as tmp:
        log_path = _write_session_log(tmp, [
            {'avg_quality': 4.0, 'remediation_inserted_count': 3},
            {'avg_quality': 2.0, 'remediation_inserted_count': 0},
        ])
        result = compute_remediation_effectiveness(log_path)
        assert result['total_sessions'] == 2
        assert result['sessions_with_remediation'] == 1
        assert result['sessions_without_remediation'] == 1
        assert result['avg_quality_with_remediation'] == 4.0
        assert result['avg_quality_without_remediation'] == 2.0
        assert result['avg_quality_delta'] == 2.0


def test_remediation_effectiveness_uplift_rate():
    """Uplift rate: fraction of remediated sessions above overall average."""
    with tempfile.TemporaryDirectory() as tmp:
        # Overall avg: (4 + 2 + 3) / 3 = 3.0
        # Remediated sessions: 4.0 (above avg) and 2.0 (below avg)
        # uplift_rate = 1/2 = 0.5
        log_path = _write_session_log(tmp, [
            {'avg_quality': 4.0, 'remediation_inserted_count': 2},
            {'avg_quality': 2.0, 'remediation_inserted_count': 1},
            {'avg_quality': 3.0, 'remediation_inserted_count': 0},
        ])
        result = compute_remediation_effectiveness(log_path)
        assert result['uplift_rate'] == 0.5


def test_remediation_effectiveness_all_remediated():
    """When all sessions have remediation, without count is 0."""
    with tempfile.TemporaryDirectory() as tmp:
        log_path = _write_session_log(tmp, [
            {'avg_quality': 3.5, 'remediation_inserted_count': 1},
            {'avg_quality': 4.5, 'remediation_inserted_count': 2},
        ])
        result = compute_remediation_effectiveness(log_path)
        assert result['sessions_with_remediation'] == 2
        assert result['sessions_without_remediation'] == 0
        assert result['avg_quality_without_remediation'] == 0.0


def test_remediation_effectiveness_legacy_log():
    """Sessions without remediation_inserted_count field are treated as no-remediation."""
    with tempfile.TemporaryDirectory() as tmp:
        log_path = _write_session_log(tmp, [
            {'avg_quality': 3.0},  # no remediation field
            {'avg_quality': 4.0, 'remediation_inserted_count': 1},
        ])
        result = compute_remediation_effectiveness(log_path)
        assert result['sessions_without_remediation'] == 1
        assert result['sessions_with_remediation'] == 1


# ============================================================================
# M3: Book Quality Metrics
# ============================================================================

def test_book_quality_empty_graph():
    """No graph file returns empty books list."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'nonexistent.json'
        result = compute_book_quality(path)
        assert result['books'] == []


def test_book_quality_basic():
    """QNodes with confidence snapshots produce correct per-book metrics."""
    with tempfile.TemporaryDirectory() as tmp:
        qnodes = [
            QNode(
                question_id='q1', question_text='What is X?',
                books=['BookA'],
                confidence_snapshot={
                    'level': 'high',
                    'redundancy_score': 0.5,
                    'contradiction_flag': False,
                },
            ),
            QNode(
                question_id='q2', question_text='What is Y?',
                books=['BookA'],
                confidence_snapshot={
                    'level': 'medium',
                    'redundancy_score': 0.0,
                    'contradiction_flag': False,
                },
            ),
        ]
        graph_path = _make_graph(tmp, qnodes=qnodes)
        result = compute_book_quality(graph_path)

        assert len(result['books']) == 1
        book = result['books'][0]
        assert book['book'] == 'BookA'
        assert book['question_count'] == 2
        assert book['contradiction_rate'] == 0.0
        # avg_confidence: (1.0 + 0.6) / 2 = 0.8
        assert book['avg_confidence'] == 0.8


def test_book_quality_contradiction_rate():
    """Contradiction rate = contradicted QNodes / total QNodes per book."""
    with tempfile.TemporaryDirectory() as tmp:
        qnodes = [
            QNode(
                question_id='q1', question_text='What is X?',
                books=['BookB'],
                confidence_snapshot={
                    'level': 'low',
                    'redundancy_score': 0.0,
                    'contradiction_flag': True,
                },
            ),
            QNode(
                question_id='q2', question_text='What is Y?',
                books=['BookB'],
                confidence_snapshot={
                    'level': 'high',
                    'redundancy_score': 0.0,
                    'contradiction_flag': False,
                },
            ),
        ]
        graph_path = _make_graph(tmp, qnodes=qnodes)
        result = compute_book_quality(graph_path)

        book = result['books'][0]
        assert book['contradiction_rate'] == 0.5


def test_book_quality_multiple_books():
    """QNodes spanning multiple books produce per-book entries."""
    with tempfile.TemporaryDirectory() as tmp:
        qnodes = [
            QNode(
                question_id='q1', question_text='Q?',
                books=['BookA', 'BookB'],
                confidence_snapshot={
                    'level': 'high',
                    'redundancy_score': 0.5,
                    'contradiction_flag': False,
                },
            ),
            QNode(
                question_id='q2', question_text='Q2?',
                books=['BookB'],
                confidence_snapshot={
                    'level': 'low',
                    'redundancy_score': 0.0,
                    'contradiction_flag': True,
                },
            ),
        ]
        graph_path = _make_graph(tmp, qnodes=qnodes)
        result = compute_book_quality(graph_path)

        by_book = {b['book']: b for b in result['books']}
        assert 'BookA' in by_book
        assert 'BookB' in by_book
        assert by_book['BookA']['question_count'] == 1
        assert by_book['BookB']['question_count'] == 2


def test_book_quality_terminality():
    """avg_terminality is computed via compute_terminality for each QNode."""
    with tempfile.TemporaryDirectory() as tmp:
        # high confidence, 0.5 redundancy, no contradiction
        # terminality = 1.0 * (1 + 0.5*0.3) * 1.0 = 1.15 → clamped to 1.0
        qnodes = [
            QNode(
                question_id='q1', question_text='Q?',
                books=['BookC'],
                confidence_snapshot={
                    'level': 'high',
                    'redundancy_score': 0.5,
                    'contradiction_flag': False,
                },
            ),
        ]
        graph_path = _make_graph(tmp, qnodes=qnodes)
        result = compute_book_quality(graph_path)

        book = result['books'][0]
        assert book['avg_terminality'] == 1.0  # clamped


def test_book_quality_no_confidence_snapshot():
    """QNodes without confidence_snapshot don't crash, contribute 0."""
    with tempfile.TemporaryDirectory() as tmp:
        qnodes = [
            QNode(
                question_id='q1', question_text='Q?',
                books=['BookD'],
                confidence_snapshot={},
            ),
            QNode(
                question_id='q2', question_text='Q2?',
                books=['BookD'],
                confidence_snapshot={
                    'level': 'medium',
                    'redundancy_score': 0.0,
                    'contradiction_flag': False,
                },
            ),
        ]
        graph_path = _make_graph(tmp, qnodes=qnodes)
        result = compute_book_quality(graph_path)

        book = result['books'][0]
        assert book['question_count'] == 2
        # Only q2 has a snapshot, so avg_confidence = 0.6 / 1 = 0.6
        assert book['avg_confidence'] == 0.6


def test_book_quality_sorted_by_name():
    """Books are returned in sorted order."""
    with tempfile.TemporaryDirectory() as tmp:
        qnodes = [
            QNode(question_id='q1', question_text='Q?',
                  books=['Zebra'],
                  confidence_snapshot={'level': 'low'}),
            QNode(question_id='q2', question_text='Q2?',
                  books=['Alpha'],
                  confidence_snapshot={'level': 'high'}),
        ]
        graph_path = _make_graph(tmp, qnodes=qnodes)
        result = compute_book_quality(graph_path)

        book_names = [b['book'] for b in result['books']]
        assert book_names == ['Alpha', 'Zebra']


# ============================================================================
# Session log enhancement: remediation fields persisted
# ============================================================================

def test_session_log_records_remediation_fields():
    """log_session should write remediation_inserted_count and prereq_concepts_used."""
    from study.session_log import log_session

    with tempfile.TemporaryDirectory() as tmp:
        log_path = Path(tmp) / 'log.jsonl'
        summary = {
            'reviewed': 2,
            'correct': 1,
            'incorrect': 1,
            'skipped': 0,
            'expanded': 0,
            'remediation_inserted_count': 3,
            'prereq_concepts_used': ['calculus', 'linear algebra'],
        }
        cards_reviewed = [
            {'card_id': 'c1', 'quality': 4, 'tags': ['math']},
            {'card_id': 'c2', 'quality': 1, 'tags': ['math']},
        ]
        record = log_session(log_path, summary, cards_reviewed)

        assert record['remediation_inserted_count'] == 3
        assert record['prereq_concepts_used'] == ['calculus', 'linear algebra']
        assert len(record['card_details']) == 2


def test_session_log_card_details_persisted():
    """card_details in session log can be read back."""
    from study.session_log import log_session, read_session_log

    with tempfile.TemporaryDirectory() as tmp:
        log_path = Path(tmp) / 'log.jsonl'
        summary = {'reviewed': 1}
        cards_reviewed = [
            {'card_id': 'c1', 'quality': 3, 'card_type': 'definition',
             'book': 'BookA', 'tags': ['BookA', 'ch1']},
        ]
        log_session(log_path, summary, cards_reviewed)

        records = read_session_log(log_path)
        assert len(records) == 1
        assert records[0]['card_details'] == cards_reviewed


def test_session_log_remediation_defaults():
    """Summary without remediation fields defaults to 0 / empty."""
    from study.session_log import log_session

    with tempfile.TemporaryDirectory() as tmp:
        log_path = Path(tmp) / 'log.jsonl'
        summary = {'reviewed': 1}
        cards_reviewed = [{'card_id': 'c1', 'quality': 3, 'tags': []}]
        record = log_session(log_path, summary, cards_reviewed)

        assert record['remediation_inserted_count'] == 0
        assert record['prereq_concepts_used'] == []
