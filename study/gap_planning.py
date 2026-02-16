"""Gap-driven card selection and optional gap seeding."""

from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from study.models import Card
from study.storage import CardStore
from study.analytics import _card_mastery
from study.plan import SECONDS_PER_CARD


def load_graph_registry(path: Path):
    """Load a GraphRegistry from a JSON file. Returns None if missing."""
    from graph.models import GraphRegistry
    registry = GraphRegistry()
    if path.exists():
        registry.load(path)
    return registry


def select_gap_cards(
    graph_registry_path: Path,
    store: CardStore,
    minutes_budget: float,
    book: Optional[str] = None,
) -> List[Card]:
    """
    Select cards for gap boost based on graph gap scores.

    Logic:
        1. Get top-20 gap concepts from graph registry
        2. Filter by book if provided
        3. For each concept (highest gap first), find existing cards
           whose tags or prompt contain the concept name
        4. Among matching cards, prefer due/overdue, then lowest mastery
        5. Return up to budget worth of cards

    Deterministic: sorted selection, no randomness.

    Args:
        graph_registry_path: Path to graph_registry.json
        store:               CardStore instance
        minutes_budget:      Time budget in minutes for gap boost
        book:                Optional book filter

    Returns:
        List of Card objects for gap boost review.
    """
    from graph.gaps import get_ranked_gaps

    registry = load_graph_registry(graph_registry_path)
    if registry.count_concepts() == 0:
        return []

    max_cards = max(1, int(minutes_budget * 60 / SECONDS_PER_CARD))
    ranked_gaps = get_ranked_gaps(registry, top_n=20)

    if book:
        ranked_gaps = [(c, s) for c, s in ranked_gaps if book in c.books]

    all_cards = store.all_cards()
    if book:
        all_cards = [c for c in all_cards if c.book_name == book]

    selected: List[Card] = []
    selected_ids = set()

    for concept, _gap_score in ranked_gaps:
        if len(selected) >= max_cards:
            break

        # Find cards matching this concept (by tag or prompt substring)
        concept_lower = concept.name.lower()
        matching = []
        for card in all_cards:
            if card.card_id in selected_ids:
                continue
            tags_lower = [t.lower() for t in card.tags]
            if (concept_lower in tags_lower
                    or concept_lower in card.prompt.lower()):
                matching.append(card)

        if not matching:
            continue

        # Sort: due/overdue first (by due_date ASC), then lowest mastery
        from datetime import date
        today = date.today().isoformat()
        matching.sort(key=lambda c: (
            0 if c.due_date <= today else 1,
            _card_mastery(c),
            c.card_id,  # deterministic tiebreak
        ))

        # Take one card per concept to spread coverage
        card = matching[0]
        selected.append(card)
        selected_ids.add(card.card_id)

    return selected[:max_cards]


def seed_gap_cards(
    graph_registry_path: Path,
    store: CardStore,
    book: Optional[str] = None,
    answer_fn: Optional[Callable] = None,
    max_seeds: int = 3,
) -> List[Card]:
    """
    Generate seed cards for top gap concepts that have no existing cards.

    For each uncovered concept:
        1. Generate question: "What is <concept>?"
        2. Call answer_fn(question, book) to get an answer payload
        3. Feed into card_generator.generate_cards()
        4. Upsert into store

    Args:
        graph_registry_path: Path to graph_registry.json
        store:               CardStore instance
        book:                Optional book filter
        answer_fn:           Callable(question, book) -> {question, answer_dict, retrieved_chunks}
                             If None, seeding is skipped.
        max_seeds:           Maximum concepts to seed cards for

    Returns:
        List of newly created Card objects.
    """
    if answer_fn is None:
        return []

    from graph.gaps import get_ranked_gaps
    from study.card_generator import generate_cards

    registry = load_graph_registry(graph_registry_path)
    if registry.count_concepts() == 0:
        return []

    ranked_gaps = get_ranked_gaps(registry, top_n=20)
    if book:
        ranked_gaps = [(c, s) for c, s in ranked_gaps if book in c.books]

    all_cards = store.all_cards()
    all_cards_lower_tags = set()
    for card in all_cards:
        for t in card.tags:
            all_cards_lower_tags.add(t.lower())
        all_cards_lower_tags.add(card.prompt.lower())

    new_cards: List[Card] = []
    seeded = 0

    for concept, _gap_score in ranked_gaps:
        if seeded >= max_seeds:
            break

        concept_lower = concept.name.lower()

        # Check if any existing card covers this concept
        has_coverage = any(
            concept_lower in t.lower() for card in all_cards
            for t in list(card.tags) + [card.prompt]
        )
        if has_coverage:
            continue

        # Generate seed question
        question = f"What is {concept.name}?"

        try:
            payload = answer_fn(question, book)
        except Exception:
            continue

        if not payload:
            continue

        answer_dict = payload.get('answer_dict', {})
        retrieved_chunks = payload.get('retrieved_chunks', [])

        if not answer_dict or not answer_dict.get('answer'):
            continue

        cards = generate_cards(question, answer_dict, retrieved_chunks, max_cards=2)
        if cards:
            # Filter out existing IDs
            existing_ids = {c.card_id for c in all_cards}
            truly_new = [c for c in cards if c.card_id not in existing_ids]
            if truly_new:
                store.upsert_cards(truly_new)
                new_cards.extend(truly_new)
                all_cards.extend(truly_new)
                seeded += 1

    return new_cards
