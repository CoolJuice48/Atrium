"""JSONL-backed card storage with CRUD operations."""

import json
from pathlib import Path
from datetime import date
from typing import Dict, List, Optional

from study.models import Card


class CardStore:
    """
    JSONL-backed card storage.

    Loads entire file into memory on init (fine for <10k cards).
    Writes are atomic: rewrites the entire file on mutation.
    """

    def __init__(self, db_path):
        self.db_path = Path(db_path)
        self._cards: Dict[str, Card] = {}
        self._load()

    def _load(self) -> None:
        if not self.db_path.exists():
            return
        with open(self.db_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                card = Card.from_dict(data)
                self._cards[card.card_id] = card

    def _save(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.db_path, 'w', encoding='utf-8') as f:
            for card in self._cards.values():
                f.write(json.dumps(card.to_dict(), ensure_ascii=False) + '\n')

    def upsert_card(self, card: Card) -> None:
        """Insert or update a card by card_id."""
        self._cards[card.card_id] = card
        self._save()

    def upsert_cards(self, cards: List[Card]) -> None:
        """Batch upsert -- single save at the end."""
        for card in cards:
            self._cards[card.card_id] = card
        self._save()

    def get_card(self, card_id: str) -> Optional[Card]:
        return self._cards.get(card_id)

    def get_due_cards(self, as_of: Optional[date] = None) -> List[Card]:
        """Return all cards with due_date <= as_of, sorted by due_date ASC."""
        if as_of is None:
            as_of = date.today()
        target = as_of.isoformat()
        due = [c for c in self._cards.values() if c.due_date <= target]
        due.sort(key=lambda c: c.due_date)
        return due

    def get_cards_by_book(self, book_name: str) -> List[Card]:
        return [c for c in self._cards.values() if c.book_name == book_name]

    def get_cards_by_tag(self, tag: str) -> List[Card]:
        return [c for c in self._cards.values() if tag in c.tags]

    def update_review(self, card_id: str, quality: int, new_schedule: Dict) -> None:
        """Update a card's scheduling fields after review."""
        card = self._cards.get(card_id)
        if card is None:
            raise KeyError(f"Card not found: {card_id}")
        card.due_date = new_schedule['due_date']
        card.interval_days = new_schedule['interval_days']
        card.ease_factor = new_schedule['ease_factor']
        card.reps = new_schedule['reps']
        card.lapses = new_schedule['lapses']
        card.last_reviewed = date.today().isoformat()
        self._save()

    def all_cards(self) -> List[Card]:
        return list(self._cards.values())

    def count(self) -> int:
        return len(self._cards)
