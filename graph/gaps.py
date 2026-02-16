"""Gap scoring for concepts -- identifies knowledge gaps."""

from typing import Dict, List, Tuple

from graph.models import ConceptNode, GraphRegistry


def gap_score(concept: ConceptNode, registry: GraphRegistry) -> float:
    """
    Compute gap score for a concept.

    gap = (1 - mastery_score)
        + penalty if linked QNodes have low terminality
        + bonus if concept appears in multiple books but low mastery

    Higher score = bigger knowledge gap.

    Returns:
        float >= 0
    """
    base = 1.0 - concept.mastery_score

    # Penalty for low-terminality linked questions
    terminality_penalty = 0.0
    if concept.linked_qnodes:
        total_terminality = 0.0
        count = 0
        for qid in concept.linked_qnodes:
            qnode = registry.get_qnode(qid)
            if qnode:
                total_terminality += qnode.terminality_score
                count += 1
        if count > 0:
            avg_terminality = total_terminality / count
            # Low terminality means answers aren't settled → bigger gap
            terminality_penalty = (1.0 - avg_terminality) * 0.2

    # Multi-book bonus: concept spans books but mastery is low
    multi_book_bonus = 0.0
    n_books = len(set(concept.books))
    if n_books >= 2 and concept.mastery_score < 0.5:
        multi_book_bonus = min(0.3, (n_books - 1) * 0.1)

    return base + terminality_penalty + multi_book_bonus


def get_ranked_gaps(
    registry: GraphRegistry,
    top_n: int = 10,
) -> List[Tuple[ConceptNode, float]]:
    """
    Return the top-N concepts ranked by gap score (highest gap first).

    Returns:
        List of (ConceptNode, gap_score) tuples.
    """
    concepts = registry.all_concepts()
    scored = [(c, gap_score(c, registry)) for c in concepts]
    scored.sort(key=lambda x: (-x[1], x[0].name))  # highest gap first, tiebreak by name
    return scored[:top_n]
