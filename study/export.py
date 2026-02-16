"""Export cards to Anki-compatible CSV format."""

import csv
from pathlib import Path
from typing import List

from study.models import Card


def _format_back(card: Card) -> str:
    """Format the back of an Anki card with answer + citation info."""
    parts = [card.answer]
    if card.citations:
        cite_parts = []
        for c in card.citations:
            cite = []
            if c.section:
                cite.append(f'\u00a7{c.section}')
            if c.pages:
                cite.append(f'pp. {c.pages}')
            if c.chapter:
                cite.append(f'Ch. {c.chapter}')
            if cite:
                cite_parts.append(', '.join(cite))
        if cite_parts:
            parts.append(f'[{"; ".join(cite_parts)}]')
    return ' '.join(parts)


def _format_tags(card: Card) -> str:
    """Format tags as space-separated Anki tags."""
    tags = list(card.tags)
    if card.card_type and card.card_type not in tags:
        tags.append(card.card_type)
    return ' '.join(t.replace(' ', '_') for t in tags)


def export_anki_csv(cards: List[Card], path: Path) -> int:
    """
    Export cards to Anki-compatible CSV.

    Format: Front,Back,Tags (no header row, tab-separated as Anki expects).

    Args:
        cards: Cards to export
        path:  Output file path

    Returns:
        Number of cards exported.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f, delimiter='\t', quoting=csv.QUOTE_MINIMAL)
        for card in cards:
            front = card.prompt
            back = _format_back(card)
            tags = _format_tags(card)
            writer.writerow([front, back, tags])
    return len(cards)
