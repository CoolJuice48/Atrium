"""Tests for study/session_log.py -- session logging."""

import sys
import json
import tempfile
from pathlib import Path
from datetime import date, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from study.session_log import log_session, read_session_log
from study.models import Card, Citation
from study.storage import CardStore
from study.session import run_review_session
from study.card_types import CardType


def test_log_session_creates_file():
    """log_session should create the log file and write a record."""
    with tempfile.TemporaryDirectory() as tmp:
        log_path = Path(tmp) / 'session_log.jsonl'
        summary = {'reviewed': 3, 'correct': 2, 'incorrect': 1,
                    'skipped': 0, 'expanded': 0}
        cards_reviewed = [
            {'card_id': 'c1', 'quality': 4, 'card_type': 'short_answer',
             'book': 'BookA', 'tags': ['BookA', 'ch1']},
            {'card_id': 'c2', 'quality': 2, 'card_type': 'definition',
             'book': 'BookA', 'tags': ['BookA', 'ch2']},
            {'card_id': 'c3', 'quality': 5, 'card_type': 'cloze',
             'book': 'BookB', 'tags': ['BookB']},
        ]
        record = log_session(log_path, summary, cards_reviewed)

        assert log_path.exists()
        assert record['cards_reviewed'] == 3
        assert record['correct'] == 2
        assert record['incorrect'] == 1


def test_log_session_quality_histogram():
    """Histogram should tally quality scores."""
    with tempfile.TemporaryDirectory() as tmp:
        log_path = Path(tmp) / 'log.jsonl'
        summary = {'reviewed': 3, 'correct': 2, 'incorrect': 1,
                    'skipped': 0, 'expanded': 0}
        cards_reviewed = [
            {'card_id': 'c1', 'quality': 4, 'tags': []},
            {'card_id': 'c2', 'quality': 4, 'tags': []},
            {'card_id': 'c3', 'quality': 1, 'tags': []},
        ]
        record = log_session(log_path, summary, cards_reviewed)
        assert record['quality_histogram']['4'] == 2
        assert record['quality_histogram']['1'] == 1
        assert record['quality_histogram']['0'] == 0


def test_log_session_books_touched():
    """books_touched should list unique books."""
    with tempfile.TemporaryDirectory() as tmp:
        log_path = Path(tmp) / 'log.jsonl'
        summary = {'reviewed': 2}
        cards_reviewed = [
            {'card_id': 'c1', 'quality': 3, 'book': 'BookA', 'tags': []},
            {'card_id': 'c2', 'quality': 4, 'book': 'BookB', 'tags': []},
        ]
        record = log_session(log_path, summary, cards_reviewed)
        assert 'BookA' in record['books_touched']
        assert 'BookB' in record['books_touched']


def test_log_session_weakest_tags():
    """weakest_tags should identify low-scoring tags."""
    with tempfile.TemporaryDirectory() as tmp:
        log_path = Path(tmp) / 'log.jsonl'
        summary = {'reviewed': 3}
        cards_reviewed = [
            {'card_id': 'c1', 'quality': 1, 'tags': ['weak_tag']},
            {'card_id': 'c2', 'quality': 5, 'tags': ['strong_tag']},
            {'card_id': 'c3', 'quality': 1, 'tags': ['weak_tag']},
        ]
        record = log_session(log_path, summary, cards_reviewed)
        tag_names = [t for t, _ in record['weakest_tags']]
        assert 'weak_tag' in tag_names


def test_log_session_avg_quality():
    """avg_quality should be the mean of all quality scores."""
    with tempfile.TemporaryDirectory() as tmp:
        log_path = Path(tmp) / 'log.jsonl'
        summary = {'reviewed': 2}
        cards_reviewed = [
            {'card_id': 'c1', 'quality': 2, 'tags': []},
            {'card_id': 'c2', 'quality': 4, 'tags': []},
        ]
        record = log_session(log_path, summary, cards_reviewed)
        assert record['avg_quality'] == 3.0


def test_read_session_log():
    """read_session_log returns all records."""
    with tempfile.TemporaryDirectory() as tmp:
        log_path = Path(tmp) / 'log.jsonl'
        summary = {'reviewed': 1}
        cards_reviewed = [{'card_id': 'c1', 'quality': 3, 'tags': []}]
        log_session(log_path, summary, cards_reviewed)
        log_session(log_path, summary, cards_reviewed)

        records = read_session_log(log_path)
        assert len(records) == 2
        assert all('timestamp' in r for r in records)


def test_read_session_log_nonexistent():
    """read_session_log on nonexistent file returns empty list."""
    with tempfile.TemporaryDirectory() as tmp:
        log_path = Path(tmp) / 'nonexistent.jsonl'
        records = read_session_log(log_path)
        assert records == []


def test_session_integration_with_logging():
    """run_review_session with log_path should write a session log."""
    with tempfile.TemporaryDirectory() as tmp:
        log_path = Path(tmp) / 'session_log.jsonl'

        card = Card(
            card_id='log_test',
            book_name='TestBook',
            tags=['TestBook'],
            prompt='What is a queue?',
            answer='A queue is a FIFO data structure.',
            card_type=CardType.SHORT_ANSWER.value,
            citations=[Citation(chunk_id='chunk_q')],
            due_date=(date.today() - timedelta(days=1)).isoformat(),
        )
        store = CardStore(Path(tmp) / 'cards.jsonl')
        store.upsert_cards([card])

        answers = iter(["A queue is a FIFO data structure"])
        output_lines = []

        run_review_session(
            store, [card],
            input_fn=lambda _: next(answers),
            output_fn=lambda s: output_lines.append(s),
            log_path=log_path,
        )

        assert log_path.exists()
        records = read_session_log(log_path)
        assert len(records) == 1
        assert records[0]['cards_reviewed'] == 1
