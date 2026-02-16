"""Study plan generator -- allocates time across due cards, weak sections, quizzes, and gap boost."""

from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from study.models import Card
from study.storage import CardStore
from study.analytics import compute_mastery, _card_mastery


# Time estimates (seconds)
SECONDS_PER_CARD = 35
SECONDS_PER_QUIZ_Q = 60


def make_study_plan(
    store: CardStore,
    minutes: int = 30,
    book: Optional[str] = None,
    graph_registry_path: Optional[Path] = None,
    gap_cards: Optional[List[Card]] = None,
    graph=None,
) -> Dict:
    """
    Generate a study plan that fits within `minutes`.

    Time allocation:
        55% -- due card review
        20% -- weak-section boost (lowest-mastery cards not already due)
        15% -- adaptive quiz
        10% -- gap boost (cards from high-gap concepts)

    Args:
        store:                CardStore instance
        minutes:              Total study time in minutes
        book:                 Optional book filter
        graph_registry_path:  Path to graph_registry.json (for gap snapshot)
        gap_cards:            Pre-selected gap boost cards (from gap_planning)

    Returns:
        {
            total_minutes: int,
            review:          {cards, estimated_minutes},
            boost:           {cards, estimated_minutes, sections},
            quiz:            {n_questions, estimated_minutes},
            gap_boost:       {cards, estimated_minutes, concepts},
            mastery_snapshot: {overall, by_book, weakest_sections},
            gap_snapshot:     [(concept_name, gap_score), ...],
        }
    """
    total_seconds = minutes * 60

    # Partition time
    review_seconds = int(total_seconds * 0.55)
    boost_seconds = int(total_seconds * 0.20)
    quiz_seconds = int(total_seconds * 0.15)
    gap_seconds = total_seconds - review_seconds - boost_seconds - quiz_seconds  # 10%

    # Collect cards
    all_cards = store.all_cards()
    if book:
        all_cards = [c for c in all_cards if c.book_name == book]

    due_cards = [c for c in all_cards if c.due_date <= date.today().isoformat()]
    due_cards.sort(key=lambda c: c.due_date)

    # --- Review block: due cards that fit in time budget ---
    max_review = max(1, review_seconds // SECONDS_PER_CARD)
    review_cards = due_cards[:max_review]
    review_est = len(review_cards) * SECONDS_PER_CARD / 60.0

    # --- Boost block: weakest non-due cards ---
    due_ids = {c.card_id for c in due_cards}
    non_due = [c for c in all_cards if c.card_id not in due_ids]
    non_due.sort(key=lambda c: _card_mastery(c))

    max_boost = max(1, boost_seconds // SECONDS_PER_CARD)
    boost_cards = non_due[:max_boost]
    boost_est = len(boost_cards) * SECONDS_PER_CARD / 60.0

    # Identify weak sections from boost cards
    boost_sections = []
    seen_sections = set()
    for c in boost_cards:
        sk = _section_key_simple(c)
        if sk not in seen_sections:
            seen_sections.add(sk)
            boost_sections.append(sk)

    # --- Quiz block ---
    n_quiz = max(1, quiz_seconds // SECONDS_PER_QUIZ_Q)
    quiz_est = n_quiz * SECONDS_PER_QUIZ_Q / 60.0

    # --- Gap boost block ---
    max_gap = max(1, gap_seconds // SECONDS_PER_CARD)
    gap_boost_cards = []
    gap_concepts = []
    if gap_cards:
        gap_boost_cards = gap_cards[:max_gap]
        # Extract concept names from tags (concepts are often in tags)
        seen_concepts = set()
        for c in gap_boost_cards:
            for tag in c.tags:
                if tag not in seen_concepts and tag != c.book_name:
                    seen_concepts.add(tag)
                    gap_concepts.append(tag)
    gap_est = len(gap_boost_cards) * SECONDS_PER_CARD / 60.0

    # Mastery snapshot
    mastery = compute_mastery(all_cards)

    # Gap snapshot from graph registry (use cached graph when provided)
    gap_snapshot = _load_gap_snapshot(graph_registry_path, book, graph=graph)

    return {
        'total_minutes': minutes,
        'review': {
            'cards': review_cards,
            'estimated_minutes': round(review_est, 1),
        },
        'boost': {
            'cards': boost_cards,
            'estimated_minutes': round(boost_est, 1),
            'sections': boost_sections,
        },
        'quiz': {
            'n_questions': n_quiz,
            'estimated_minutes': round(quiz_est, 1),
        },
        'gap_boost': {
            'cards': gap_boost_cards,
            'estimated_minutes': round(gap_est, 1),
            'concepts': gap_concepts,
        },
        'mastery_snapshot': {
            'overall': mastery['overall_mastery'],
            'by_book': mastery['by_book'],
            'weakest_sections': mastery['weakest_sections'],
        },
        'gap_snapshot': gap_snapshot,
    }


def _load_gap_snapshot(
    graph_path: Optional[Path],
    book: Optional[str],
    graph=None,
) -> List[Tuple[str, float]]:
    """Load top 5 gap concepts from graph registry (use cached graph when provided)."""
    try:
        from graph.gaps import get_ranked_gaps

        if graph is not None:
            registry = graph
        elif graph_path and graph_path.exists():
            from graph.models import GraphRegistry
            registry = GraphRegistry()
            registry.load(graph_path)
        else:
            return []
        ranked = get_ranked_gaps(registry, top_n=5)
        if book:
            ranked = [(c, s) for c, s in ranked if book in c.books]
        return [(c.name, round(s, 3)) for c, s in ranked]
    except Exception:
        return []


def _section_key_simple(card: Card) -> str:
    """Build a human-readable section key."""
    if card.citations:
        c = card.citations[0]
        parts = []
        if card.book_name:
            parts.append(card.book_name)
        if c.section:
            parts.append(f'\u00a7{c.section}')
        return ', '.join(parts) if parts else 'unknown'
    return card.book_name or 'unknown'
