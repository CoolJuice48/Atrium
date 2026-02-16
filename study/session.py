"""Interactive review session runner with injectable IO."""

from pathlib import Path
from typing import Callable, Dict, List, Optional, Set

from study.models import Card
from study.storage import CardStore
from study.scheduler import sm2_schedule
from study.grader import grade
from study.card_generator import generate_cards
from study.session_log import log_session


def _expand_failed_card(
    card: Card,
    storage: CardStore,
    output_fn: Callable[[str], None],
) -> int:
    """
    Generate additional cards when a card fails repeatedly.

    Builds a minimal answer_dict from the card's own prompt/answer/citations,
    then calls generate_cards with max_cards=2 to create supplementary cards.

    Returns the number of new cards added.
    """
    answer_dict = {
        'answer': card.answer,
        'key_points': [card.answer[:200]],
        'citations': [],
    }
    # Build retrieved_chunks from the card's citations
    retrieved_chunks = []
    for cite in card.citations:
        retrieved_chunks.append({
            'text': card.answer,
            'metadata': {
                'chunk_id': cite.chunk_id,
                'book': card.book_name,
                'chapter': cite.chapter,
                'section': cite.section,
                'section_title': '',
                'pages': cite.pages,
            },
        })
    if not retrieved_chunks:
        retrieved_chunks = [{
            'text': card.answer,
            'metadata': {'book': card.book_name, 'chunk_id': f'{card.card_id}_expand'},
        }]

    new_cards = generate_cards(
        card.prompt, answer_dict, retrieved_chunks, max_cards=2,
    )

    # Filter out cards that already exist
    existing_ids = {c.card_id for c in storage.all_cards()}
    truly_new = [c for c in new_cards if c.card_id not in existing_ids]

    if truly_new:
        storage.upsert_cards(truly_new)
        output_fn(f"  [auto] Generated {len(truly_new)} supplementary card(s) "
                  f"for repeated failure.")
    return len(truly_new)


def _try_prereq_remediation(
    card: Card,
    storage: CardStore,
    graph_path: Path,
    output_fn: Callable[[str], None],
    remediated_concepts: Set[str],
    seed_prereqs: bool = False,
    answer_fn: Optional[Callable] = None,
) -> tuple:
    """
    Select prerequisite cards for a failed card and optionally seed missing ones.

    Returns (prereq_cards, prereq_concept_names).
    Mutates remediated_concepts to track which concepts have been remediated.
    """
    from study.remediation import select_prereq_cards

    book = card.book_name
    result = select_prereq_cards(
        store=storage,
        graph_path=graph_path,
        failed_card=card,
        book=book,
    )

    target = result['concept']
    if target is None:
        return [], []

    # Skip if already remediated this concept in this session
    if target in remediated_concepts:
        return [], []
    remediated_concepts.add(target)

    selected_ids = result['selected_card_ids']

    # Seed missing prereq cards if enabled and selection is empty
    if seed_prereqs and not selected_ids and answer_fn and result['prereq_concepts']:
        seeded = _seed_prereq_cards(
            result['prereq_concepts'], storage, book, answer_fn, output_fn,
        )
        if seeded:
            # Re-select after seeding
            result = select_prereq_cards(
                store=storage,
                graph_path=graph_path,
                failed_card=card,
                book=book,
            )
            selected_ids = result['selected_card_ids']

    if not selected_ids:
        return [], result['prereq_concepts']

    # Fetch the actual card objects
    prereq_cards = []
    for cid in selected_ids:
        c = storage.get_card(cid)
        if c is not None:
            prereq_cards.append(c)

    if prereq_cards:
        concepts_str = ', '.join(result['prereq_concepts'][:3])
        output_fn(f"  [prereq] Inserting {len(prereq_cards)} prereq card(s) "
                  f"for: {concepts_str}")

    return prereq_cards, result['prereq_concepts']


def _seed_prereq_cards(
    prereq_concepts: List[str],
    storage: CardStore,
    book: Optional[str],
    answer_fn: Callable,
    output_fn: Callable[[str], None],
) -> List[Card]:
    """Seed cards for prereq concepts that have no existing cards."""
    all_cards = storage.all_cards()
    new_cards: List[Card] = []

    for concept_name in prereq_concepts[:2]:  # seed up to 2 concepts
        concept_lower = concept_name.lower()
        # Check if any card already covers this concept
        has_coverage = any(
            concept_lower in t.lower()
            for card in all_cards
            for t in list(card.tags) + [card.prompt]
        )
        if has_coverage:
            continue

        question = f"What is {concept_name}?"
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
            existing_ids = {c.card_id for c in all_cards}
            truly_new = [c for c in cards if c.card_id not in existing_ids]
            if truly_new:
                storage.upsert_cards(truly_new)
                new_cards.extend(truly_new)
                all_cards.extend(truly_new)
                output_fn(f"  [seed] Created {len(truly_new)} prereq card(s) "
                          f"for '{concept_name}'")

    return new_cards


def run_review_session(
    storage: CardStore,
    due_cards: List[Card],
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
    log_path: Optional[Path] = None,
    graph_path: Optional[Path] = None,
    enable_prereq_remediation: bool = True,
    seed_prereqs: bool = False,
    answer_fn: Optional[Callable] = None,
) -> Dict:
    """
    Run an interactive review session over due cards.

    IO is injectable for testability.

    Flow per card:
        1. Show prompt
        2. Collect answer
        3. Grade answer
        4. Show feedback + correct answer
        5. Compute new schedule via SM-2
        6. Update storage
        7. If failed twice in a row (lapses >= 1 before this failure),
           auto-expand with supplementary cards
        8. If failed and prereq remediation enabled, insert prereq cards

    Args:
        storage:                    CardStore instance
        due_cards:                  Cards to review
        input_fn:                   Callable for user input (default: builtin input)
        output_fn:                  Callable for display (default: builtin print)
        log_path:                   Optional path for session log
        graph_path:                 Optional path to graph_registry.json
        enable_prereq_remediation:  Whether to insert prereq cards on failure
        seed_prereqs:               Whether to generate new prereq cards if missing
        answer_fn:                  Injectable answer function for seeding

    Returns:
        Summary dict: {reviewed, correct, incorrect, skipped, expanded,
                       remediation_inserted_count, prereq_concepts_used}
    """
    reviewed = 0
    correct = 0
    incorrect = 0
    skipped = 0
    expanded = 0
    remediation_inserted_count = 0
    prereq_concepts_used: List[str] = []
    cards_reviewed_log: List[Dict] = []
    remediated_concepts: Set[str] = set()

    # Build a mutable card queue
    card_queue: List[Card] = list(due_cards)

    output_fn(f"\n{'='*60}")
    output_fn(f"REVIEW SESSION -- {len(due_cards)} card(s) due")
    output_fn(f"{'='*60}")
    output_fn("Type 'q' to quit early, 's' to skip a card.\n")

    idx = 0
    while idx < len(card_queue):
        card = card_queue[idx]
        display_num = idx + 1
        display_total = len(card_queue)
        output_fn(f"\n--- Card {display_num}/{display_total} [{card.card_type}] ---")
        output_fn(f"  {card.prompt}")

        try:
            user_answer = input_fn("\nYour answer: ")
        except (EOFError, KeyboardInterrupt):
            output_fn("\nSession ended.")
            break

        if user_answer.strip().lower() == 'q':
            output_fn("Ending session early.")
            break

        if user_answer.strip().lower() == 's':
            skipped += 1
            output_fn("  (skipped)")
            idx += 1
            continue

        # Grade
        result = grade(user_answer, card.answer, card.card_type)
        quality = result['score']

        output_fn(f"\n  Score: {quality}/5 -- {result['feedback']}")
        output_fn(f"  Expected: {card.answer[:200]}")

        # Check for repeated failure BEFORE updating schedule
        prior_lapses = card.lapses
        is_failure = quality < 3

        # Schedule
        new_schedule = sm2_schedule(
            quality=quality,
            reps=card.reps,
            ease_factor=card.ease_factor,
            interval_days=card.interval_days,
            lapses=card.lapses,
        )

        output_fn(f"  Next review: {new_schedule['due_date']} "
                  f"(interval: {new_schedule['interval_days']}d)")

        storage.update_review(card.card_id, quality, new_schedule)

        # Auto-expand on repeated failure (failed now AND had prior lapses)
        if is_failure and prior_lapses >= 1:
            added = _expand_failed_card(card, storage, output_fn)
            if added:
                expanded += 1

        # Prereq remediation on failure
        if (is_failure and enable_prereq_remediation
                and graph_path is not None and graph_path.exists()):
            prereq_cards, prereq_concepts = _try_prereq_remediation(
                card, storage, graph_path, output_fn,
                remediated_concepts,
                seed_prereqs=seed_prereqs,
                answer_fn=answer_fn,
            )
            if prereq_cards:
                # Insert prereq cards right after current position
                for j, pc in enumerate(prereq_cards):
                    card_queue.insert(idx + 1 + j, pc)
                remediation_inserted_count += len(prereq_cards)
                for cn in prereq_concepts:
                    if cn not in prereq_concepts_used:
                        prereq_concepts_used.append(cn)

        cards_reviewed_log.append({
            'card_id': card.card_id,
            'quality': quality,
            'card_type': card.card_type,
            'book': card.book_name,
            'tags': list(card.tags),
        })

        reviewed += 1
        if quality >= 3:
            correct += 1
        else:
            incorrect += 1

        idx += 1

    summary = {
        'reviewed': reviewed,
        'correct': correct,
        'incorrect': incorrect,
        'skipped': skipped,
        'expanded': expanded,
        'remediation_inserted_count': remediation_inserted_count,
        'prereq_concepts_used': prereq_concepts_used,
    }

    output_fn(f"\n{'='*60}")
    output_fn("SESSION COMPLETE")
    output_fn(f"  Reviewed: {reviewed}  Correct: {correct}  "
              f"Incorrect: {incorrect}  Skipped: {skipped}")
    if expanded:
        output_fn(f"  Auto-expanded: {expanded} card(s)")
    if remediation_inserted_count:
        output_fn(f"  Prereq remediation: {remediation_inserted_count} card(s) inserted")
    output_fn(f"{'='*60}")

    # Write session log if path provided
    if log_path and cards_reviewed_log:
        log_session(log_path, summary, cards_reviewed_log)

    return summary
