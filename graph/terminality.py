"""Terminality score for QNodes -- how 'settled' a question's answer is."""

from typing import Dict


# Confidence level weights
_CONFIDENCE_WEIGHTS = {
    'high': 1.0,
    'medium': 0.6,
    'low': 0.3,
}


def compute_terminality(confidence_snapshot: Dict) -> float:
    """
    Compute terminality score from a confidence snapshot.

    terminality = confidence_weight * (1 + redundancy_bonus) * contradiction_penalty

    Args:
        confidence_snapshot: Dict with keys:
            level:                   'high'|'medium'|'low'
            redundancy_score:        float 0..1
            contradiction_flag:      bool

    Returns:
        float 0..1
    """
    level = confidence_snapshot.get('level', 'low')
    base = _CONFIDENCE_WEIGHTS.get(level, 0.3)

    redundancy = confidence_snapshot.get('redundancy_score', 0.0)
    redundancy_bonus = redundancy * 0.3  # up to 0.3 bonus for high redundancy

    contradiction = confidence_snapshot.get('contradiction_flag', False)
    contradiction_penalty = 0.5 if contradiction else 1.0

    score = base * (1.0 + redundancy_bonus) * contradiction_penalty

    return max(0.0, min(1.0, score))
