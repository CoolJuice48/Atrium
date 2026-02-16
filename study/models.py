"""Data models for the study engine: Card and Citation dataclasses."""

import hashlib
from dataclasses import dataclass, field, asdict
from datetime import datetime, date
from typing import Dict, List, Optional

from study.card_types import CardType


@dataclass
class Citation:
    """A single citation linking a card to a source chunk."""
    chunk_id: str
    chapter: str = ''
    section: str = ''
    pages: str = ''

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> 'Citation':
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class Card:
    """
    A study card with SM-2 scheduling metadata.

    card_id is a deterministic SHA-256 hash of (prompt + sorted citation chunk_ids).
    """
    card_id: str
    book_name: str
    tags: List[str] = field(default_factory=list)
    prompt: str = ''
    answer: str = ''
    card_type: str = CardType.SHORT_ANSWER.value

    # Citations
    citations: List[Citation] = field(default_factory=list)

    # Timestamps
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    # SM-2 scheduling fields
    due_date: str = field(default_factory=lambda: date.today().isoformat())
    interval_days: int = 1
    ease_factor: float = 2.5
    reps: int = 0
    lapses: int = 0
    last_reviewed: Optional[str] = None

    def to_dict(self) -> Dict:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, data: Dict) -> 'Card':
        data = dict(data)  # shallow copy
        if 'citations' in data and data['citations']:
            data['citations'] = [
                Citation.from_dict(c) if isinstance(c, dict) else c
                for c in data['citations']
            ]
        # Filter to known fields only
        known = cls.__dataclass_fields__
        data = {k: v for k, v in data.items() if k in known}
        return cls(**data)


def make_card_id(prompt: str, citation_chunk_ids: List[str]) -> str:
    """
    Deterministic card ID from prompt text + citation chunk IDs.
    SHA-256 truncated to 16 hex chars for readability.
    """
    key = prompt.strip().lower() + '|' + '|'.join(sorted(citation_chunk_ids))
    return hashlib.sha256(key.encode('utf-8')).hexdigest()[:16]


def make_structure_card_id(
    card_type: str,
    normalized_prompt: str,
    chunk_id: str,
    term: Optional[str] = None,
) -> str:
    """
    Stable ID for structure-first cards. Re-running generation yields same IDs.
    Based on (card_type, normalized_prompt, chunk_id, optional term).
    """
    parts = [card_type, normalized_prompt.strip().lower(), chunk_id]
    if term:
        parts.append(term.strip().lower())
    key = '|'.join(parts)
    return hashlib.sha256(key.encode('utf-8')).hexdigest()[:16]
