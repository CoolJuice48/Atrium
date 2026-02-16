"""Quiz assembly from card decks."""

import random
from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional

from study.models import Card
from study.analytics import _card_mastery


@dataclass
class QuizQuestion:
    """A single question in a quiz, wrapping a Card."""
    card: Card
    question_number: int = 0
    user_answer: Optional[str] = None
    grade_result: Optional[Dict] = None

    def to_dict(self) -> Dict:
        return {
            'question_number': self.question_number,
            'prompt': self.card.prompt,
            'card_type': self.card.card_type,
            'card_id': self.card.card_id,
            'expected_answer': self.card.answer,
            'user_answer': self.user_answer,
            'grade_result': self.grade_result,
        }


def _adaptive_sort_key(card: Card) -> tuple:
    """
    Sort key for adaptive mode: weakest cards first.

    Priority order:
        1. Cards with lapses > 0 (most lapsed first)
        2. Cards due soonest
        3. Lowest mastery score
    """
    mastery = _card_mastery(card)
    # due_urgency: negative days until due (more negative = more overdue)
    try:
        due = date.fromisoformat(card.due_date)
        days_until = (due - date.today()).days
    except ValueError:
        days_until = 0
    # Sort: high lapses first (negate), then soonest due, then lowest mastery
    return (-card.lapses, days_until, mastery)


def make_quiz(
    topic: str,
    cards: List[Card],
    n: int = 5,
    *,
    adaptive: bool = False,
) -> List[QuizQuestion]:
    """
    Assemble a quiz of n questions from available cards.

    If topic is non-empty, filters cards whose tags or prompt contain the topic.

    Args:
        topic:    Topic string to filter on (empty string = no filter)
        cards:    Available cards to draw from
        n:        Number of questions
        adaptive: If True, prioritize weak cards (high lapses, due soon,
                  low mastery) and favor cloze/compare types

    Returns:
        List of QuizQuestion objects
    """
    if topic:
        topic_lower = topic.lower()
        filtered = [
            c for c in cards
            if topic_lower in c.prompt.lower()
            or any(topic_lower in t.lower() for t in c.tags)
        ]
    else:
        filtered = list(cards)

    if not filtered:
        return []

    if adaptive:
        # Sort by weakness (lowest mastery, most lapses, soonest due)
        filtered.sort(key=_adaptive_sort_key)

        # Boost cloze/compare types: move them towards the front
        priority_types = {'cloze', 'compare'}
        priority = [c for c in filtered if c.card_type in priority_types]
        others = [c for c in filtered if c.card_type not in priority_types]

        # Interleave: take from priority first, fill remainder from others
        selected = []
        pi, oi = 0, 0
        while len(selected) < min(n, len(filtered)):
            # Alternate: 2 priority, 1 other (when available)
            if pi < len(priority) and len(selected) % 3 != 2:
                selected.append(priority[pi])
                pi += 1
            elif oi < len(others):
                selected.append(others[oi])
                oi += 1
            elif pi < len(priority):
                selected.append(priority[pi])
                pi += 1
            else:
                break
    else:
        selected = random.sample(filtered, min(n, len(filtered)))

    return [
        QuizQuestion(card=card, question_number=i)
        for i, card in enumerate(selected, 1)
    ]
