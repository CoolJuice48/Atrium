"""Card type enumeration for the study engine."""

from enum import Enum


class CardType(str, Enum):
    """Types of study cards that can be generated."""
    DEFINITION = "definition"
    CLOZE = "cloze"
    SHORT_ANSWER = "short_answer"
    COMPARE = "compare"
    LIST = "list"
    TRUE_FALSE = "true_false"
    TRAP = "trap"  # Deprecated; map to TRUE_FALSE for new generation
