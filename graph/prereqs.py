"""Prerequisite concept ordering heuristic."""

from typing import Dict, List, Tuple

from graph.models import ConceptNode, GraphRegistry


def _section_sort_key(section: str) -> Tuple:
    """
    Parse a section string like '2.3' or '10.1.2' into a sortable tuple.

    Returns tuple of ints for numeric comparison.
    Falls back to (999,) for unparseable sections.
    """
    parts = []
    for part in section.replace('\u00a7', '').strip().split('.'):
        try:
            parts.append(int(part))
        except ValueError:
            parts.append(999)
    return tuple(parts) if parts else (999,)


def _earliest_section(concept: ConceptNode) -> Tuple:
    """Return the earliest section key for a concept."""
    if not concept.sections:
        return (999,)
    return min(_section_sort_key(s) for s in concept.sections)


def get_prereqs(
    concept_name: str,
    registry: GraphRegistry,
    top_n: int = 10,
) -> List[Tuple[ConceptNode, int]]:
    """
    Find likely prerequisite concepts for a given concept.

    Heuristic:
        1. Find all concepts that co-occur with the target concept
        2. Filter to those that appear in earlier sections
        3. Sort by section order (earliest first), tiebreak by co-occurrence frequency
        4. Higher co-occurrence + earlier section = more likely prerequisite

    Args:
        concept_name: Name of the target concept
        registry:     GraphRegistry instance
        top_n:        Max prereqs to return

    Returns:
        List of (ConceptNode, cooccurrence_count) sorted by section order.
    """
    target = registry.get_concept_by_name(concept_name)
    if target is None:
        return []

    target_earliest = _earliest_section(target)
    cooccurrences = registry.get_cooccurrences(target.concept_id)

    if not cooccurrences:
        return []

    candidates: List[Tuple[ConceptNode, int]] = []
    for cid, count in cooccurrences.items():
        concept = registry.get_concept(cid)
        if concept is None:
            continue
        # Only include concepts from earlier or same sections
        concept_earliest = _earliest_section(concept)
        if concept_earliest <= target_earliest:
            candidates.append((concept, count))

    # Sort: earliest section first, then highest co-occurrence
    candidates.sort(key=lambda x: (_earliest_section(x[0]), -x[1]))

    return candidates[:top_n]
