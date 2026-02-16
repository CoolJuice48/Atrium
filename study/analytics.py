"""Topic mastery analytics for the study engine."""

from datetime import date
from typing import Dict, List, Tuple

from study.models import Card


def _card_mastery(card: Card) -> float:
    """
    Compute mastery score for a single card (0..1).

    Heuristics:
        - base = min(1.0, interval_days / 30)
        - penalty for lapses: -0.05 per lapse (floored at 0)
        - boost for ease > 2.5: +0.05 per 0.1 above 2.5 (capped)
        - recency decay: if last_reviewed is stale, reduce by up to 30%
    """
    # Base: how far along the 30-day interval scale
    base = min(1.0, card.interval_days / 30.0)

    # Lapse penalty
    lapse_penalty = card.lapses * 0.05

    # Ease boost (relative to default 2.5)
    ease_delta = card.ease_factor - 2.5
    ease_boost = max(0.0, ease_delta) * 0.5  # 0.05 per 0.1 above 2.5

    score = base - lapse_penalty + ease_boost

    # Recency decay: weight recent reviews more
    if card.last_reviewed:
        try:
            reviewed = date.fromisoformat(card.last_reviewed)
            days_since = (date.today() - reviewed).days
            if days_since > 60:
                score *= 0.7  # stale: 30% penalty
            elif days_since > 30:
                decay = 1.0 - 0.3 * ((days_since - 30) / 30.0)
                score *= max(0.7, decay)
        except ValueError:
            pass  # malformed date, skip decay
    else:
        # Never reviewed: heavy penalty
        score *= 0.5

    return max(0.0, min(1.0, score))


def _section_key(card: Card) -> str:
    """Build a section key from the card's first citation."""
    if card.citations:
        c = card.citations[0]
        parts = []
        if card.book_name:
            parts.append(card.book_name)
        if c.section:
            parts.append(f'\u00a7{c.section}')
        return ', '.join(parts) if parts else 'unknown'
    return card.book_name or 'unknown'


def compute_mastery(cards: List[Card]) -> Dict:
    """
    Compute mastery analytics across a card collection.

    Returns:
        {
            overall_mastery: float 0..1,
            by_book: {book_name: score},
            by_section: {section_key: score},
            weakest_sections: [(section_key, score), ...],  # up to 5
            strongest_sections: [(section_key, score), ...], # up to 5
        }
    """
    if not cards:
        return {
            'overall_mastery': 0.0,
            'by_book': {},
            'by_section': {},
            'weakest_sections': [],
            'strongest_sections': [],
        }

    # Compute per-card mastery
    scores = [(card, _card_mastery(card)) for card in cards]

    # Overall
    overall = sum(s for _, s in scores) / len(scores)

    # By book
    book_scores: Dict[str, List[float]] = {}
    for card, s in scores:
        bk = card.book_name or 'unknown'
        book_scores.setdefault(bk, []).append(s)
    by_book = {bk: sum(ss) / len(ss) for bk, ss in book_scores.items()}

    # By section
    section_scores: Dict[str, List[float]] = {}
    for card, s in scores:
        sk = _section_key(card)
        section_scores.setdefault(sk, []).append(s)
    by_section = {sk: sum(ss) / len(ss) for sk, ss in section_scores.items()}

    # Sorted sections
    sorted_sections = sorted(by_section.items(), key=lambda x: x[1])
    weakest = sorted_sections[:5]
    strongest = sorted_sections[-5:][::-1]

    return {
        'overall_mastery': round(overall, 4),
        'by_book': {k: round(v, 4) for k, v in by_book.items()},
        'by_section': {k: round(v, 4) for k, v in by_section.items()},
        'weakest_sections': [(k, round(v, 4)) for k, v in weakest],
        'strongest_sections': [(k, round(v, 4)) for k, v in strongest],
    }
