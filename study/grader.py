"""Token-overlap grading with synonym expansion."""

import re
from typing import Dict


# Small synonym list for common academic/CS terms
SYNONYMS: Dict[str, set] = {
    'fast': {'quick', 'rapid', 'speedy'},
    'quick': {'fast', 'rapid', 'speedy'},
    'big': {'large', 'huge', 'enormous'},
    'large': {'big', 'huge', 'enormous'},
    'small': {'tiny', 'little', 'compact'},
    'function': {'method', 'procedure', 'routine'},
    'method': {'function', 'procedure', 'routine'},
    'array': {'list', 'vector'},
    'list': {'array', 'vector'},
    'error': {'bug', 'fault', 'defect'},
    'bug': {'error', 'fault', 'defect'},
    'increase': {'grow', 'rise', 'expand'},
    'decrease': {'shrink', 'reduce', 'decline'},
    'optimal': {'best', 'ideal'},
    'best': {'optimal', 'ideal'},
}


def _tokenize(text: str) -> set:
    """Lowercase word tokens."""
    return set(re.findall(r'[a-z0-9_]+', text.lower()))


def _expand_synonyms(tokens: set) -> set:
    """Expand a token set with known synonyms."""
    expanded = set(tokens)
    for tok in tokens:
        if tok in SYNONYMS:
            expanded |= SYNONYMS[tok]
    return expanded


def grade(
    user_answer: str,
    expected_answer: str,
    card_type: str,
) -> Dict:
    """
    Grade a user answer against the expected answer.

    Uses token overlap with synonym expansion. Scoring:
        5: >= 70% overlap (perfect recall)
        4: >= 50% overlap
        3: >= 30% overlap (passable)
        2: >= 15% overlap
        1: >= 5% overlap
        0: < 5% overlap

    For cloze cards, exact substring match (case-insensitive) gives full marks.

    Returns:
        Dict with 'score' (0-5) and 'feedback' (str)
    """
    if not user_answer.strip():
        return {'score': 0, 'feedback': 'No answer provided.'}

    # Special handling for cloze: exact match check first
    if card_type == 'cloze':
        if expected_answer.strip().lower() in user_answer.strip().lower():
            return {
                'score': 5,
                'feedback': f'Correct! The answer is "{expected_answer}".',
            }

    user_tokens = _tokenize(user_answer)
    expected_tokens = _tokenize(expected_answer)

    if not expected_tokens:
        return {'score': 3, 'feedback': 'Unable to grade (empty expected answer).'}

    # Expand user tokens with synonyms
    user_expanded = _expand_synonyms(user_tokens)

    overlap = len(user_expanded & expected_tokens)
    ratio = overlap / len(expected_tokens)

    if ratio >= 0.70:
        score = 5
        feedback = 'Excellent -- thorough answer.'
    elif ratio >= 0.50:
        score = 4
        feedback = 'Good answer, most key points covered.'
    elif ratio >= 0.30:
        score = 3
        feedback = 'Passable, but missing some key points.'
    elif ratio >= 0.15:
        score = 2
        feedback = 'Partial understanding. Review the material.'
    elif ratio >= 0.05:
        score = 1
        feedback = 'Very incomplete. Needs significant review.'
    else:
        score = 0
        feedback = 'Incorrect or unrelated answer.'

    return {'score': score, 'feedback': feedback}
