"""Prerequisite remediation -- select prereq cards for failed concepts."""

from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

from study.models import Card
from study.storage import CardStore
from study.analytics import _card_mastery


# Minimal stopwords for concept extraction from tags (subset of graph/concepts._STOPWORDS)
_TAG_STOPWORDS = {
    'about', 'also', 'been', 'both', 'does', 'each', 'even', 'from',
    'have', 'into', 'just', 'like', 'more', 'most', 'much', 'must',
    'only', 'other', 'over', 'same', 'some', 'such', 'than', 'that',
    'them', 'then', 'this', 'very', 'well', 'were', 'what', 'when',
    'will', 'with', 'your',
}


def _guess_target_concept(card: Card, registry) -> Optional[str]:
    """
    Guess the concept being tested by a failed card.

    Strategy:
        1. Check card tags for known concept names in the registry.
        2. Fall back to extracting concept tokens from the prompt.
    """
    # 1. Match tags against known registry concepts
    for tag in card.tags:
        tag_lower = tag.strip().lower()
        # Skip book-name tags and short/stopword tags
        if tag_lower == (card.book_name or '').lower():
            continue
        if len(tag_lower) <= 3 or tag_lower in _TAG_STOPWORDS:
            continue
        # Check if this tag matches a known concept
        concept = registry.get_concept_by_name(tag_lower)
        if concept is not None:
            return concept.name

    # 2. Extract from prompt text
    import re
    words = re.findall(r'\b[a-zA-Z]{4,}\b', card.prompt)
    for w in words:
        w_lower = w.lower()
        if w_lower in _TAG_STOPWORDS:
            continue
        concept = registry.get_concept_by_name(w_lower)
        if concept is not None:
            return concept.name

    # 3. Try multi-word tags not matched above
    for tag in card.tags:
        tag_lower = tag.strip().lower()
        if tag_lower == (card.book_name or '').lower():
            continue
        if len(tag_lower) > 3 and tag_lower not in _TAG_STOPWORDS:
            return tag_lower

    return None


def _concept_mastery_from_cards(
    concept_name: str,
    all_cards: List[Card],
) -> float:
    """Compute average mastery of cards matching a concept (by tag or prompt)."""
    concept_lower = concept_name.lower()
    matching = []
    for card in all_cards:
        tags_lower = [t.lower() for t in card.tags]
        if concept_lower in tags_lower or concept_lower in card.prompt.lower():
            matching.append(card)
    if not matching:
        return 0.0
    return sum(_card_mastery(c) for c in matching) / len(matching)


def select_prereq_cards(
    *,
    store: CardStore,
    graph_path: Path,
    failed_card: Card,
    max_prereq_concepts: int = 3,
    max_cards_total: int = 6,
    book: Optional[str] = None,
) -> Dict:
    """
    Select prerequisite review cards for a failed card.

    Logic:
        1. Determine target concept from the failed card
        2. Get prereqs from graph registry
        3. Rank by lowest mastery, then section order
        4. Select matching cards (tag or prompt match)
        5. Prefer due/overdue, deterministic ordering
        6. Enforce caps

    Args:
        store:                CardStore instance
        graph_path:           Path to graph_registry.json
        failed_card:          The card the user failed
        max_prereq_concepts:  Max number of prereq concepts to use
        max_cards_total:      Max total prereq cards to return
        book:                 Optional book filter

    Returns:
        {
            "concept": target concept name or None,
            "prereq_concepts": [concept_name, ...],
            "selected_card_ids": [card_id, ...],
        }
    """
    empty = {
        'concept': None,
        'prereq_concepts': [],
        'selected_card_ids': [],
    }

    # Load graph registry
    from graph.models import GraphRegistry
    registry = GraphRegistry()
    if graph_path.exists():
        registry.load(graph_path)

    if registry.count_concepts() == 0:
        return empty

    # 1. Determine target concept
    target = _guess_target_concept(failed_card, registry)
    if target is None:
        return empty

    # 2. Get prereqs
    from graph.prereqs import get_prereqs
    prereqs = get_prereqs(target, registry, top_n=10)
    if not prereqs:
        return {
            'concept': target,
            'prereq_concepts': [],
            'selected_card_ids': [],
        }

    # 3. Rank prereq concepts by lowest mastery, then section order
    all_cards = store.all_cards()
    if book:
        all_cards = [c for c in all_cards if c.book_name == book]

    from graph.prereqs import _earliest_section
    ranked_prereqs = []
    for concept, cooccurrence_count in prereqs:
        mastery = _concept_mastery_from_cards(concept.name, all_cards)
        ranked_prereqs.append((concept, mastery, cooccurrence_count))

    # Sort: lowest mastery first, then earliest section, then name for determinism
    ranked_prereqs.sort(key=lambda x: (
        x[1],                        # lowest mastery first
        _earliest_section(x[0]),     # earlier section first
        x[0].name,                   # deterministic tiebreak
    ))

    # 4. Select top prereq concepts
    top_prereqs = ranked_prereqs[:max_prereq_concepts]
    prereq_names = [p[0].name for p in top_prereqs]

    # 5. Select cards matching prereq concepts
    today = date.today().isoformat()
    selected: List[Card] = []
    selected_ids = set()
    # Don't select the failed card itself
    selected_ids.add(failed_card.card_id)

    for concept, _mastery, _count in top_prereqs:
        if len(selected) >= max_cards_total:
            break
        concept_lower = concept.name.lower()
        matching = []
        for card in all_cards:
            if card.card_id in selected_ids:
                continue
            tags_lower = [t.lower() for t in card.tags]
            if concept_lower in tags_lower or concept_lower in card.prompt.lower():
                matching.append(card)
        if not matching:
            continue

        # Sort: due/overdue first, then lowest mastery, deterministic tiebreak
        matching.sort(key=lambda c: (
            0 if c.due_date <= today else 1,
            _card_mastery(c),
            c.card_id,
        ))

        # Take up to 2 cards per concept for coverage
        per_concept = min(2, max_cards_total - len(selected))
        for card in matching[:per_concept]:
            selected.append(card)
            selected_ids.add(card.card_id)

    return {
        'concept': target,
        'prereq_concepts': prereq_names,
        'selected_card_ids': [c.card_id for c in selected],
    }
