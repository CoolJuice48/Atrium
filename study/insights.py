"""Learning outcome analytics -- concept difficulty, remediation effectiveness, book quality."""

from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from study.models import Card
from study.storage import CardStore
from study.session_log import read_session_log


# ============================================================================
# Helpers
# ============================================================================

def _cards_for_concept(concept_name: str, cards: List[Card]) -> List[Card]:
    """Find cards matching a concept by tag or prompt substring."""
    concept_lower = concept_name.lower()
    matching = []
    seen: Set[str] = set()
    for card in cards:
        if card.card_id in seen:
            continue
        # Check tags (substring match in both directions)
        for t in card.tags:
            t_lower = t.lower()
            if concept_lower in t_lower or t_lower in concept_lower:
                matching.append(card)
                seen.add(card.card_id)
                break
        else:
            # Check prompt
            if concept_lower in card.prompt.lower():
                matching.append(card)
                seen.add(card.card_id)
    return matching


# ============================================================================
# M1: Concept Difficulty Metrics
# ============================================================================

def compute_concept_difficulty(
    store: CardStore,
    session_log_path: Optional[Path] = None,
    graph_path: Optional[Path] = None,
) -> Dict:
    """
    Compute difficulty metrics for each concept found in the card deck.

    Concepts are derived from card tags and optionally from the graph registry.
    Metrics per concept:
        failure_rate:              fraction of cards with lapses > 0
        avg_lapses:                mean lapses across matching cards
        remediation_trigger_rate:  fraction of sessions where this concept triggered remediation
        avg_time_to_mastery:       mean days from creation to interval >= 7  (-1 if none mastered)
        difficulty_score:          composite 0..1

    Returns:
        {
            'concepts': [per-concept dicts],
            'hardest': [(name, score), ...],         top 5
            'most_remediated': [(name, rate), ...],  top 5
            'slowest_mastery': [(name, days), ...],  top 5
        }
    """
    all_cards = store.all_cards()
    empty = {
        'concepts': [],
        'hardest': [],
        'most_remediated': [],
        'slowest_mastery': [],
    }
    if not all_cards:
        return empty

    # Collect unique concept names from tags
    concept_names: Set[str] = set()
    for card in all_cards:
        for tag in card.tags:
            concept_names.add(tag)

    # Also pull concepts from graph registry if available
    if graph_path and graph_path.exists():
        from graph.models import GraphRegistry
        registry = GraphRegistry()
        registry.load(graph_path)
        for cn in registry.all_concepts():
            concept_names.add(cn.name)

    # Load session log for remediation data
    remediation_counts: Dict[str, int] = defaultdict(int)
    total_sessions = 0
    if session_log_path and session_log_path.exists():
        sessions = read_session_log(session_log_path)
        total_sessions = len(sessions)
        for sess in sessions:
            for concept in sess.get('prereq_concepts_used', []):
                remediation_counts[concept.lower()] += 1

    # Compute per-concept metrics
    results = []
    for name in sorted(concept_names):
        matching = _cards_for_concept(name, all_cards)
        if not matching:
            continue

        card_count = len(matching)

        # Failure rate: fraction of cards that have ever lapsed
        failed_count = sum(1 for c in matching if c.lapses > 0)
        failure_rate = failed_count / card_count

        # Average lapses
        avg_lapses = sum(c.lapses for c in matching) / card_count

        # Remediation trigger rate: sessions that used this concept / total sessions
        rem_count = remediation_counts.get(name.lower(), 0)
        remediation_trigger_rate = (
            rem_count / total_sessions if total_sessions > 0 else 0.0
        )

        # Average time to mastery (interval >= 7 days = "mastered")
        mastery_days: List[float] = []
        for card in matching:
            if card.interval_days >= 7 and card.last_reviewed and card.created_at:
                try:
                    created = date.fromisoformat(card.created_at[:10])
                    reviewed = date.fromisoformat(card.last_reviewed[:10])
                    days = (reviewed - created).days
                    if days >= 0:
                        mastery_days.append(float(days))
                except ValueError:
                    pass
        avg_time_to_mastery = (
            sum(mastery_days) / len(mastery_days) if mastery_days else -1.0
        )

        # Difficulty score: composite normalized 0..1
        # Weight: failure_rate(0.4) + lapse_norm(0.3) + mastery_speed(0.3)
        lapse_norm = min(1.0, avg_lapses / 5.0)  # 5+ lapses = max difficulty
        if avg_time_to_mastery > 0:
            mastery_speed = min(1.0, avg_time_to_mastery / 30.0)  # 30+ days = max
        elif avg_time_to_mastery < 0:
            mastery_speed = 0.5  # not yet mastered -> moderate difficulty
        else:
            mastery_speed = 0.0  # mastered immediately

        difficulty_score = round(
            0.4 * failure_rate + 0.3 * lapse_norm + 0.3 * mastery_speed, 3,
        )

        results.append({
            'name': name,
            'card_count': card_count,
            'failure_rate': round(failure_rate, 3),
            'avg_lapses': round(avg_lapses, 3),
            'remediation_trigger_rate': round(remediation_trigger_rate, 3),
            'avg_time_to_mastery': round(avg_time_to_mastery, 1),
            'difficulty_score': difficulty_score,
        })

    # Rankings (deterministic: sorted by score desc, then name asc for tiebreak)
    hardest = sorted(
        results, key=lambda x: (-x['difficulty_score'], x['name']),
    )[:5]
    most_remediated = sorted(
        [r for r in results if r['remediation_trigger_rate'] > 0],
        key=lambda x: (-x['remediation_trigger_rate'], x['name']),
    )[:5]
    slowest = sorted(
        [r for r in results if r['avg_time_to_mastery'] > 0],
        key=lambda x: (-x['avg_time_to_mastery'], x['name']),
    )[:5]

    return {
        'concepts': results,
        'hardest': [(r['name'], r['difficulty_score']) for r in hardest],
        'most_remediated': [
            (r['name'], r['remediation_trigger_rate']) for r in most_remediated
        ],
        'slowest_mastery': [
            (r['name'], r['avg_time_to_mastery']) for r in slowest
        ],
    }


# ============================================================================
# M2: Remediation Effectiveness
# ============================================================================

def compute_remediation_effectiveness(
    session_log_path: Path,
) -> Dict:
    """
    Analyze remediation effectiveness from session logs.

    Per-session comparison: sessions with remediation_inserted_count > 0 vs without.
    Per-card comparison: when card_details are available, compare quality of cards
    reviewed before vs after remediation insertion within a session.

    Returns:
        {
            'total_sessions': int,
            'sessions_with_remediation': int,
            'sessions_without_remediation': int,
            'avg_quality_with_remediation': float,
            'avg_quality_without_remediation': float,
            'uplift_rate': float,        fraction of remediated sessions above overall avg
            'avg_quality_delta': float,  with - without
        }
    """
    empty = {
        'total_sessions': 0,
        'sessions_with_remediation': 0,
        'sessions_without_remediation': 0,
        'avg_quality_with_remediation': 0.0,
        'avg_quality_without_remediation': 0.0,
        'uplift_rate': 0.0,
        'avg_quality_delta': 0.0,
    }

    if not session_log_path.exists():
        return empty

    sessions = read_session_log(session_log_path)
    if not sessions:
        return empty

    with_rem: List[float] = []
    without_rem: List[float] = []

    for sess in sessions:
        rem_count = sess.get('remediation_inserted_count', 0)
        avg_q = sess.get('avg_quality', 0.0)
        if rem_count > 0:
            with_rem.append(avg_q)
        else:
            without_rem.append(avg_q)

    total = len(sessions)
    avg_with = sum(with_rem) / len(with_rem) if with_rem else 0.0
    avg_without = sum(without_rem) / len(without_rem) if without_rem else 0.0

    # Uplift rate: fraction of remediated sessions with above-overall-average quality
    overall_avg = (sum(with_rem) + sum(without_rem)) / total if total else 0.0
    uplift_count = sum(1 for q in with_rem if q > overall_avg)
    uplift_rate = uplift_count / len(with_rem) if with_rem else 0.0

    # Delta only meaningful when both groups exist
    delta = round(avg_with - avg_without, 3) if with_rem and without_rem else 0.0

    return {
        'total_sessions': total,
        'sessions_with_remediation': len(with_rem),
        'sessions_without_remediation': len(without_rem),
        'avg_quality_with_remediation': round(avg_with, 3),
        'avg_quality_without_remediation': round(avg_without, 3),
        'uplift_rate': round(uplift_rate, 3),
        'avg_quality_delta': delta,
    }


# ============================================================================
# M3: Book Quality Metrics
# ============================================================================

def compute_book_quality(
    graph_path: Path,
) -> Dict:
    """
    Compute quality metrics per book from the graph registry.

    Uses QNode confidence_snapshot data to derive terminality,
    contradiction rates, and average confidence per book.

    Returns:
        {
            'books': [
                {
                    'book': str,
                    'question_count': int,
                    'avg_terminality': float,
                    'contradiction_rate': float,
                    'avg_confidence': float,   numeric: high=1.0, medium=0.6, low=0.3
                },
                ...
            ],
        }
    """
    if not graph_path.exists():
        return {'books': []}

    from graph.models import GraphRegistry
    from graph.terminality import compute_terminality

    registry = GraphRegistry()
    registry.load(graph_path)

    qnodes = registry.all_qnodes()
    if not qnodes:
        return {'books': []}

    _CONF_WEIGHTS = {'high': 1.0, 'medium': 0.6, 'low': 0.3}

    # Group QNodes by book
    book_data: Dict[str, list] = defaultdict(list)
    for qn in qnodes:
        for book in qn.books:
            book_data[book].append(qn)

    results = []
    for book in sorted(book_data):
        nodes = book_data[book]
        terminality_scores: List[float] = []
        contradiction_count = 0
        confidence_scores: List[float] = []

        for qn in nodes:
            snap = qn.confidence_snapshot
            if snap:
                term = compute_terminality(snap)
                terminality_scores.append(term)
                if snap.get('contradiction_flag', False):
                    contradiction_count += 1
                level = snap.get('level', 'low')
                confidence_scores.append(_CONF_WEIGHTS.get(level, 0.3))

        q_count = len(nodes)
        avg_term = (
            sum(terminality_scores) / len(terminality_scores)
            if terminality_scores else 0.0
        )
        contradiction_rate = contradiction_count / q_count if q_count else 0.0
        avg_conf = (
            sum(confidence_scores) / len(confidence_scores)
            if confidence_scores else 0.0
        )

        results.append({
            'book': book,
            'question_count': q_count,
            'avg_terminality': round(avg_term, 3),
            'contradiction_rate': round(contradiction_rate, 3),
            'avg_confidence': round(avg_conf, 3),
        })

    return {'books': results}
