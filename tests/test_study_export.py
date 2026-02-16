"""Tests for study/export.py -- Anki CSV export."""

import sys
import csv
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from study.export import export_anki_csv, _format_back, _format_tags
from study.models import Card, Citation
from study.card_types import CardType


def _card(card_id='c1', book='BookA', section='1.1', pages='10-15',
          chapter='', tags=None):
    """Create a card with citation metadata."""
    return Card(
        card_id=card_id,
        book_name=book,
        tags=tags or [book],
        prompt=f'What is concept {card_id}?',
        answer=f'Concept {card_id} is important.',
        card_type=CardType.SHORT_ANSWER.value,
        citations=[Citation(
            chunk_id=f'chunk_{card_id}',
            section=section,
            pages=pages,
            chapter=chapter,
        )],
    )


def test_export_creates_file():
    """export_anki_csv should create the output file."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'export.csv'
        cards = [_card('c1'), _card('c2')]
        count = export_anki_csv(cards, path)
        assert path.exists()
        assert count == 2


def test_export_tab_separated():
    """Output should be tab-separated."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'export.csv'
        export_anki_csv([_card('c1')], path)
        with open(path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f, delimiter='\t')
            rows = list(reader)
        assert len(rows) == 1
        assert len(rows[0]) == 3  # Front, Back, Tags


def test_export_front_is_prompt():
    """Front column should be the card prompt."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'export.csv'
        card = _card('test')
        export_anki_csv([card], path)
        with open(path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f, delimiter='\t')
            row = next(reader)
        assert row[0] == card.prompt


def test_export_back_includes_citations():
    """Back column should include citation info."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'export.csv'
        card = _card('c1', section='2.3', pages='45-50')
        export_anki_csv([card], path)
        with open(path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f, delimiter='\t')
            row = next(reader)
        back = row[1]
        assert card.answer in back
        assert '\u00a72.3' in back
        assert 'pp. 45-50' in back


def test_export_tags_column():
    """Tags column should have space-separated tags."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'export.csv'
        card = _card('c1', tags=['BookA', 'chapter_1'])
        export_anki_csv([card], path)
        with open(path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f, delimiter='\t')
            row = next(reader)
        tags = row[2]
        assert 'BookA' in tags
        assert 'chapter_1' in tags


def test_export_empty_cards():
    """Empty card list should create an empty file."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'export.csv'
        count = export_anki_csv([], path)
        assert count == 0
        assert path.exists()


def test_format_back_no_citations():
    """Cards without citations should just have the answer."""
    card = Card(
        card_id='no_cite',
        book_name='Book',
        prompt='Q?',
        answer='The answer.',
        card_type=CardType.SHORT_ANSWER.value,
    )
    back = _format_back(card)
    assert back == 'The answer.'


def test_format_tags_includes_card_type():
    """Tags should include the card type."""
    card = _card('c1', tags=['BookA'])
    tags = _format_tags(card)
    assert 'short_answer' in tags


def test_format_back_with_chapter():
    """Back should include chapter info if present."""
    card = _card('c1', chapter='3', section='3.2', pages='30-35')
    back = _format_back(card)
    assert 'Ch. 3' in back
    assert '\u00a73.2' in back
