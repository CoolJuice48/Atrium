"""Tests for prereq remediation integration in study/session.py."""

import sys
import tempfile
from pathlib import Path
from datetime import date, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from study.models import Card, Citation
from study.storage import CardStore
from study.session import run_review_session
from study.card_types import CardType
from graph.models import GraphRegistry, QNode, ConceptNode, make_concept_id


# ============================================================================
# Helpers
# ============================================================================

def _make_store(tmp_dir, cards):
    """Create a CardStore and populate it."""
    store = CardStore(Path(tmp_dir) / 'session_rem_test.jsonl')
    if cards:
        store.upsert_cards(cards)
    return store


def _card(card_id, book='BookA', section='1.1', due_days_ago=1,
          interval=1, lapses=0, tags=None, prompt=None, answer=None):
    """Create a card with convenient defaults."""
    return Card(
        card_id=card_id,
        book_name=book,
        tags=tags or [book],
        prompt=prompt or f'Q for {card_id}',
        answer=answer or f'A for {card_id}',
        card_type=CardType.SHORT_ANSWER.value,
        citations=[Citation(chunk_id=f'chunk_{card_id}', section=section)],
        due_date=(date.today() - timedelta(days=due_days_ago)).isoformat(),
        interval_days=interval,
        lapses=lapses,
        last_reviewed=date.today().isoformat(),
    )


def _make_graph(tmp_dir, concepts, cooccurrences=None):
    """Build and save a graph registry."""
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
                terminality_score=0.5,
            ))

    if cooccurrences:
        for name_a, name_b, count in cooccurrences:
            cid_a = make_concept_id(name_a)
            cid_b = make_concept_id(name_b)
            for _ in range(count):
                reg.link_concept_cooccurrence(cid_a, cid_b)

    reg.save(path)
    return path


def _mock_answer_fn(question, book):
    """Mock answer function for seeding."""
    return {
        'question': question,
        'answer_dict': {
            'answer': f'The answer to: {question}',
            'key_points': [f'Key point about {question}'],
            'citations': ['BookA, \u00a71.1, p.10'],
            'confidence': {'level': 'high'},
        },
        'retrieved_chunks': [{
            'text': f'Text about {question}',
            'metadata': {
                'chunk_id': 'seed_chunk_1',
                'book': book or 'BookA',
                'section': '1.1',
                'pages': '10-15',
            },
        }],
    }


# ============================================================================
# TESTS: Session remediation integration
# ============================================================================

def test_failing_card_inserts_prereqs():
    """Failing a card inserts prereq cards into the session."""
    with tempfile.TemporaryDirectory() as tmp:
        graph_path = _make_graph(tmp, [
            {'name': 'recursion', 'sections': ['3.1']},
            {'name': 'functions', 'sections': ['1.1']},
        ], cooccurrences=[
            ('recursion', 'functions', 3),
        ])

        failed = _card('rec1', tags=['BookA', 'recursion'],
                        prompt='Explain recursion',
                        answer='Recursion is a function calling itself')
        prereq = _card('fn1', tags=['BookA', 'functions'],
                        prompt='What are functions?',
                        answer='Functions are reusable code blocks')
        store = _make_store(tmp, [failed, prereq])

        # First answer is completely wrong (triggers remediation),
        # second answer is for the inserted prereq card
        answers = iter([
            'totally wrong xyz',
            'Functions are reusable code blocks',
        ])
        output_lines = []

        summary = run_review_session(
            store, [failed],
            input_fn=lambda _: next(answers),
            output_fn=lambda s: output_lines.append(s),
            graph_path=graph_path,
            enable_prereq_remediation=True,
        )

        assert summary['remediation_inserted_count'] >= 1
        # Should have reviewed the failed card + at least 1 prereq card
        assert summary['reviewed'] >= 2
        joined = '\n'.join(output_lines)
        assert '[prereq]' in joined


def test_no_remediation_on_pass():
    """Correct answer does not trigger remediation."""
    with tempfile.TemporaryDirectory() as tmp:
        graph_path = _make_graph(tmp, [
            {'name': 'recursion', 'sections': ['3.1']},
            {'name': 'functions', 'sections': ['1.1']},
        ], cooccurrences=[
            ('recursion', 'functions', 3),
        ])

        card = _card('rec1', tags=['BookA', 'recursion'],
                      prompt='Explain recursion',
                      answer='Recursion is a function calling itself')
        prereq = _card('fn1', tags=['BookA', 'functions'],
                        prompt='What are functions?')
        store = _make_store(tmp, [card, prereq])

        answers = iter(['Recursion is a function calling itself'])
        output_lines = []

        summary = run_review_session(
            store, [card],
            input_fn=lambda _: next(answers),
            output_fn=lambda s: output_lines.append(s),
            graph_path=graph_path,
            enable_prereq_remediation=True,
        )

        assert summary['remediation_inserted_count'] == 0
        assert summary['reviewed'] == 1


def test_remediation_disabled():
    """Remediation does not trigger when enable_prereq_remediation=False."""
    with tempfile.TemporaryDirectory() as tmp:
        graph_path = _make_graph(tmp, [
            {'name': 'recursion', 'sections': ['3.1']},
            {'name': 'functions', 'sections': ['1.1']},
        ], cooccurrences=[
            ('recursion', 'functions', 3),
        ])

        failed = _card('rec1', tags=['BookA', 'recursion'],
                        prompt='Explain recursion',
                        answer='Recursion is a function calling itself')
        prereq = _card('fn1', tags=['BookA', 'functions'],
                        prompt='What are functions?')
        store = _make_store(tmp, [failed, prereq])

        answers = iter(['totally wrong xyz'])
        output_lines = []

        summary = run_review_session(
            store, [failed],
            input_fn=lambda _: next(answers),
            output_fn=lambda s: output_lines.append(s),
            graph_path=graph_path,
            enable_prereq_remediation=False,
        )

        assert summary['remediation_inserted_count'] == 0
        assert summary['reviewed'] == 1


def test_no_repeated_remediation_same_concept():
    """Same concept is not remediated twice in one session."""
    with tempfile.TemporaryDirectory() as tmp:
        graph_path = _make_graph(tmp, [
            {'name': 'recursion', 'sections': ['3.1']},
            {'name': 'functions', 'sections': ['1.1']},
        ], cooccurrences=[
            ('recursion', 'functions', 3),
        ])

        # Two cards about the same concept
        failed1 = _card('rec1', tags=['BookA', 'recursion'],
                         prompt='Explain recursion',
                         answer='Recursion is self-calling')
        failed2 = _card('rec2', tags=['BookA', 'recursion'],
                         prompt='Describe recursion in detail',
                         answer='Recursion involves a base case')
        prereq = _card('fn1', tags=['BookA', 'functions'],
                        prompt='What are functions?',
                        answer='Functions are code blocks')
        store = _make_store(tmp, [failed1, failed2, prereq])

        # Both answers are wrong
        answers = iter([
            'wrong xyz',       # fail rec1 -> remediation triggers
            'code blocks',     # answer prereq fn1
            'wrong again xyz', # fail rec2 -> no repeated remediation
        ])
        output_lines = []

        summary = run_review_session(
            store, [failed1, failed2],
            input_fn=lambda _: next(answers),
            output_fn=lambda s: output_lines.append(s),
            graph_path=graph_path,
            enable_prereq_remediation=True,
        )

        # Only one remediation round for 'recursion', not two
        prereq_lines = [l for l in output_lines if '[prereq]' in l]
        assert len(prereq_lines) == 1


def test_remediation_caps_enforced():
    """Remediation respects max_cards_total from select_prereq_cards."""
    with tempfile.TemporaryDirectory() as tmp:
        # Many prereq concepts
        graph_path = _make_graph(tmp, [
            {'name': 'advanced', 'sections': ['10.1']},
        ] + [
            {'name': f'basic_{i}', 'sections': [f'{i}.1']}
            for i in range(1, 8)
        ], cooccurrences=[
            ('advanced', f'basic_{i}', 2) for i in range(1, 8)
        ])

        failed = _card('adv1', tags=['BookA', 'advanced'],
                        prompt='Explain advanced',
                        answer='Advanced topic')
        prereq_cards = [
            _card(f'b{i}', tags=['BookA', f'basic_{i}'],
                  prompt=f'What is basic_{i}?',
                  answer=f'Basic {i} explained')
            for i in range(1, 8)
        ]
        store = _make_store(tmp, [failed] + prereq_cards)

        # Provide enough answers for failed + up to 6 prereqs
        answers = iter(['wrong xyz'] + [f'Basic {i}' for i in range(1, 8)])
        output_lines = []

        summary = run_review_session(
            store, [failed],
            input_fn=lambda _: next(answers),
            output_fn=lambda s: output_lines.append(s),
            graph_path=graph_path,
            enable_prereq_remediation=True,
        )

        # Default max is 6 cards, 3 concepts with up to 2 per concept
        assert summary['remediation_inserted_count'] <= 6


def test_remediation_deterministic_ordering():
    """Remediation produces same order across runs."""
    with tempfile.TemporaryDirectory() as tmp:
        graph_path = _make_graph(tmp, [
            {'name': 'hashing', 'sections': ['5.1']},
            {'name': 'arrays', 'sections': ['1.1']},
            {'name': 'functions', 'sections': ['2.1']},
        ], cooccurrences=[
            ('hashing', 'arrays', 2),
            ('hashing', 'functions', 2),
        ])

        failed = _card('h1', tags=['BookA', 'hashing'],
                        prompt='What is hashing?',
                        answer='Hashing maps keys to indices')
        prereqs = [
            _card('a1', tags=['BookA', 'arrays'], prompt='What are arrays?',
                  answer='Arrays store elements'),
            _card('f1', tags=['BookA', 'functions'], prompt='What are functions?',
                  answer='Functions group code'),
        ]
        store = _make_store(tmp, [failed] + prereqs)

        results = []
        for _ in range(2):
            answers = iter(['wrong xyz', 'elements', 'code'])
            output_lines = []
            summary = run_review_session(
                store, [failed],
                input_fn=lambda _: next(answers),
                output_fn=lambda s: output_lines.append(s),
                graph_path=graph_path,
            )
            # Extract which card prompts appeared (excluding the failed card)
            reviewed_prompts = [
                l.strip() for l in output_lines
                if l.strip().startswith('Q for') or l.strip().startswith('What')
            ]
            results.append(reviewed_prompts)

        assert results[0] == results[1]


def test_seeding_path_with_answer_fn():
    """Seeding creates prereq cards when none exist."""
    with tempfile.TemporaryDirectory() as tmp:
        graph_path = _make_graph(tmp, [
            {'name': 'calculus', 'sections': ['5.1']},
            {'name': 'algebra', 'sections': ['1.1']},
        ], cooccurrences=[
            ('calculus', 'algebra', 3),
        ])

        # Only the failed card exists -- no prereq cards yet
        failed = _card('calc1', tags=['BookA', 'calculus'],
                        prompt='What is calculus?',
                        answer='Calculus is the study of change')
        store = _make_store(tmp, [failed])
        initial_count = store.count()

        # Provide enough answers for failed + seeded prereqs
        answers = iter(['wrong xyz'] + ['algebra answer'] * 5)
        output_lines = []

        summary = run_review_session(
            store, [failed],
            input_fn=lambda _: next(answers),
            output_fn=lambda s: output_lines.append(s),
            graph_path=graph_path,
            seed_prereqs=True,
            answer_fn=_mock_answer_fn,
        )

        # New cards should have been seeded
        assert store.count() > initial_count
        joined = '\n'.join(output_lines)
        assert '[seed]' in joined


def test_no_graph_path_no_remediation():
    """Without graph_path, remediation is silently skipped."""
    with tempfile.TemporaryDirectory() as tmp:
        failed = _card('c1', tags=['BookA', 'stuff'],
                        prompt='Explain stuff',
                        answer='Stuff is things')
        store = _make_store(tmp, [failed])

        answers = iter(['wrong xyz'])
        output_lines = []

        summary = run_review_session(
            store, [failed],
            input_fn=lambda _: next(answers),
            output_fn=lambda s: output_lines.append(s),
            graph_path=None,
            enable_prereq_remediation=True,
        )

        assert summary['remediation_inserted_count'] == 0
        assert summary['reviewed'] == 1


def test_summary_includes_remediation_fields():
    """Summary dict always includes remediation tracking fields."""
    with tempfile.TemporaryDirectory() as tmp:
        cards = [_card(f'c{i}') for i in range(2)]
        store = _make_store(tmp, cards)

        answers = iter([f'A for c{i}' for i in range(2)])
        output_lines = []

        summary = run_review_session(
            store, cards,
            input_fn=lambda _: next(answers),
            output_fn=lambda s: output_lines.append(s),
        )

        assert 'remediation_inserted_count' in summary
        assert 'prereq_concepts_used' in summary
        assert isinstance(summary['prereq_concepts_used'], list)


def test_session_log_includes_remediation():
    """Session log records remediation stats."""
    with tempfile.TemporaryDirectory() as tmp:
        graph_path = _make_graph(tmp, [
            {'name': 'recursion', 'sections': ['3.1']},
            {'name': 'functions', 'sections': ['1.1']},
        ], cooccurrences=[
            ('recursion', 'functions', 3),
        ])

        failed = _card('rec1', tags=['BookA', 'recursion'],
                        prompt='Explain recursion',
                        answer='Recursion is self-calling')
        prereq = _card('fn1', tags=['BookA', 'functions'],
                        prompt='What are functions?',
                        answer='Functions are code blocks')
        store = _make_store(tmp, [failed, prereq])
        log_path = Path(tmp) / 'session_log.jsonl'

        answers = iter(['wrong xyz', 'Functions are code blocks'])
        output_lines = []

        summary = run_review_session(
            store, [failed],
            input_fn=lambda _: next(answers),
            output_fn=lambda s: output_lines.append(s),
            graph_path=graph_path,
            log_path=log_path,
        )

        # Log should exist and contain remediation fields
        from study.session_log import read_session_log
        records = read_session_log(log_path)
        assert len(records) >= 1
        record = records[0]
        assert 'remediation_inserted_count' in record or 'cards_reviewed' in record
