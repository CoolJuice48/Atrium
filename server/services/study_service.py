"""Study engine service wrappers -- all return JSON-serializable dicts."""

import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

_project_root = str(Path(__file__).resolve().parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from study.models import Card
from study.storage import CardStore
from study.scheduler import sm2_schedule
from study.grader import grade
from study.card_generator import generate_cards
from study.plan import make_study_plan
from study.analytics import compute_mastery


def _card_to_summary(card: Card) -> Dict:
    """Convert a Card to a JSON-safe summary dict."""
    return {
        'card_id': card.card_id,
        'prompt': card.prompt,
        'answer': card.answer,
        'card_type': card.card_type,
        'book_name': card.book_name,
        'due_date': card.due_date,
        'tags': list(card.tags),
    }


def _serialize_plan(plan: Dict) -> Dict:
    """Convert a study plan (which contains Card objects) to plain dicts."""
    def _serialize_cards(cards):
        return [_card_to_summary(c) if isinstance(c, Card) else c for c in cards]

    return {
        'total_minutes': plan['total_minutes'],
        'review': {
            'cards': _serialize_cards(plan['review']['cards']),
            'estimated_minutes': plan['review']['estimated_minutes'],
        },
        'boost': {
            'cards': _serialize_cards(plan['boost']['cards']),
            'estimated_minutes': plan['boost']['estimated_minutes'],
            'sections': plan['boost']['sections'],
        },
        'quiz': plan['quiz'],
        'gap_boost': {
            'cards': _serialize_cards(plan['gap_boost']['cards']),
            'estimated_minutes': plan['gap_boost']['estimated_minutes'],
            'concepts': plan['gap_boost']['concepts'],
        },
        'mastery_snapshot': plan['mastery_snapshot'],
        'gap_snapshot': plan.get('gap_snapshot', []),
    }


def get_study_plan(
    store: CardStore,
    minutes: int = 30,
    book: Optional[str] = None,
    graph_registry_path: Optional[Path] = None,
    graph=None,
) -> Dict:
    """Generate and return a serialized study plan."""
    plan = make_study_plan(
        store, minutes=minutes, book=book,
        graph_registry_path=graph_registry_path,
        graph=graph,
    )
    return _serialize_plan(plan)


def get_due_cards(store: CardStore) -> Dict:
    """Return all due cards as serialized summaries."""
    due = store.get_due_cards()
    return {
        'due_count': len(due),
        'cards': [_card_to_summary(c) for c in due],
    }


def review_card(
    store: CardStore,
    card_id: str,
    user_answer: str,
) -> Dict:
    """
    Grade a user's answer and update the card's schedule.

    Returns:
        {score, feedback, new_schedule}

    Raises:
        KeyError if card_id not found.
    """
    card = store.get_card(card_id)
    if card is None:
        raise KeyError(f"Card not found: {card_id}")

    result = grade(user_answer, card.answer, card.card_type)
    quality = result['score']

    new_schedule = sm2_schedule(
        quality=quality,
        reps=card.reps,
        ease_factor=card.ease_factor,
        interval_days=card.interval_days,
        lapses=card.lapses,
    )

    store.update_review(card_id, quality, new_schedule)

    return {
        'score': quality,
        'feedback': result['feedback'],
        'new_schedule': new_schedule,
    }


def cards_from_last_answer(
    index_root: Path,
    store: CardStore,
    max_cards: int = 6,
) -> Dict:
    """
    Generate study cards from the most recent _last_answer.json.

    Returns:
        {cards_generated, cards: [{card_id, prompt, ...}, ...]}
    """
    last_answer_path = index_root / '_last_answer.json'
    if not last_answer_path.exists():
        return {'cards_generated': 0, 'cards': []}

    with open(last_answer_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    question = data.get('question', '')
    answer_dict = data.get('answer_dict', {})
    retrieved_chunks = data.get('retrieved_chunks', [])

    if not question or not answer_dict.get('answer'):
        return {'cards_generated': 0, 'cards': []}

    cards = generate_cards(
        question, answer_dict, retrieved_chunks, max_cards=max_cards,
    )

    if cards:
        store.upsert_cards(cards)

    return {
        'cards_generated': len(cards),
        'cards': [_card_to_summary(c) for c in cards],
    }


def get_progress(store: CardStore) -> Dict:
    """
    Return mastery progress summary.

    Returns:
        {overall_mastery, by_book, weakest_sections, strongest_sections,
         total_cards, due_count}
    """
    all_cards = store.all_cards()
    mastery = compute_mastery(all_cards)
    due = store.get_due_cards()

    return {
        'overall_mastery': mastery['overall_mastery'],
        'by_book': mastery['by_book'],
        'weakest_sections': mastery['weakest_sections'],
        'strongest_sections': mastery['strongest_sections'],
        'total_cards': len(all_cards),
        'due_count': len(due),
    }
