"""
Study mode CLI.

Usage:
    python -m study.cli --db study_cards.jsonl due
    python -m study.cli --db study_cards.jsonl review [--no-remediate] [--seed-prereqs] [--graph-path PATH]
    python -m study.cli --db study_cards.jsonl add-from-last-answer
    python -m study.cli --db study_cards.jsonl quiz --topic "gradient descent"
    python -m study.cli --db study_cards.jsonl stats
    python -m study.cli --db study_cards.jsonl plan --minutes 30
    python -m study.cli --db study_cards.jsonl show <card_id>
    python -m study.cli --db study_cards.jsonl export --anki out.csv
    python -m study.cli --db study_cards.jsonl insights [--graph-path PATH]
"""

import sys
import json
import argparse
from pathlib import Path

from study.storage import CardStore
from study.session import run_review_session
from study.card_generator import generate_cards
from study.quiz_generator import make_quiz
from study.grader import grade
from study.analytics import compute_mastery
from study.plan import make_study_plan
from study.export import export_anki_csv
from study.gap_planning import select_gap_cards, seed_gap_cards
from study.insights import (
    compute_concept_difficulty,
    compute_remediation_effectiveness,
    compute_book_quality,
)


def cmd_due(args):
    """Show due cards."""
    store = CardStore(args.db)
    due = store.get_due_cards()
    if not due:
        print("No cards due today.")
        return
    print(f"\n{len(due)} card(s) due for review:\n")
    for i, card in enumerate(due, 1):
        print(f"  {i}. [{card.card_type}] {card.prompt[:80]}")
        print(f"     due={card.due_date}  ease={card.ease_factor:.2f}  "
              f"reps={card.reps}  lapses={card.lapses}")


def cmd_review(args):
    """Run interactive review session."""
    store = CardStore(args.db)
    due = store.get_due_cards()
    if not due:
        print("No cards due today. Come back later!")
        return
    log_path = Path(args.db).parent / 'session_log.jsonl'

    # Resolve graph path for prereq remediation
    graph_path = Path(args.graph_path) if args.graph_path else (
        Path(args.db).parent / 'graph_registry.json'
    )
    enable_remediation = not getattr(args, 'no_remediate', False)
    seed_prereqs = getattr(args, 'seed_prereqs', False)

    run_review_session(
        store, due, log_path=log_path,
        graph_path=graph_path,
        enable_prereq_remediation=enable_remediation,
        seed_prereqs=seed_prereqs,
    )


def cmd_add_from_last_answer(args):
    """Generate cards from the last answer JSON file."""
    last_answer_path = Path(args.answer_file)
    if not last_answer_path.exists():
        print(f"Last answer file not found: {last_answer_path}")
        sys.exit(1)

    with open(last_answer_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    question = data.get('question', '')
    answer_dict = data.get('answer_dict', {})
    retrieved_chunks = data.get('retrieved_chunks', [])

    if not question or not answer_dict:
        print("Last answer file is incomplete (missing question or answer_dict).")
        sys.exit(1)

    cards = generate_cards(question, answer_dict, retrieved_chunks)

    if not cards:
        print("No cards could be generated from this answer.")
        return

    store = CardStore(args.db)
    store.upsert_cards(cards)
    print(f"Generated and saved {len(cards)} card(s):")
    for card in cards:
        print(f"  [{card.card_type}] {card.prompt[:70]}")


def cmd_quiz(args):
    """Run a quick quiz."""
    store = CardStore(args.db)
    all_cards = store.all_cards()
    if not all_cards:
        print("No cards in the deck. Add some first.")
        return

    quiz = make_quiz(topic=args.topic or '', cards=all_cards, n=args.n,
                      adaptive=args.adaptive)
    if not quiz:
        print(f"No cards matching topic '{args.topic}'.")
        return

    print(f"\nQUIZ: {len(quiz)} question(s)" +
          (f" on '{args.topic}'" if args.topic else ""))
    print("=" * 60)

    score_total = 0
    for qq in quiz:
        print(f"\nQ{qq.question_number}. [{qq.card.card_type}] {qq.card.prompt}")
        try:
            answer = input("Your answer: ")
        except (EOFError, KeyboardInterrupt):
            print("\nQuiz ended.")
            break
        result = grade(answer, qq.card.answer, qq.card.card_type)
        score_total += result['score']
        print(f"  {result['score']}/5 -- {result['feedback']}")
        print(f"  Expected: {qq.card.answer[:150]}")

    print(f"\nTotal: {score_total}/{len(quiz) * 5}")


def cmd_stats(args):
    """Show deck statistics."""
    store = CardStore(args.db)
    all_cards = store.all_cards()
    due = store.get_due_cards()

    print(f"\nDeck: {args.db}")
    print(f"  Total cards: {store.count()}")
    print(f"  Due today:   {len(due)}")

    if all_cards:
        by_type = {}
        for c in all_cards:
            by_type[c.card_type] = by_type.get(c.card_type, 0) + 1
        print("  By type:")
        for ct, count in sorted(by_type.items()):
            print(f"    {ct}: {count}")

        by_book = {}
        for c in all_cards:
            if c.book_name:
                by_book[c.book_name] = by_book.get(c.book_name, 0) + 1
        if by_book:
            print("  By book:")
            for bk, count in sorted(by_book.items()):
                print(f"    {bk}: {count}")

        # Mastery analytics
        mastery = compute_mastery(all_cards)
        print(f"\n  Overall mastery: {mastery['overall_mastery'] * 100:.1f}%")

        if mastery['by_book']:
            print("  Mastery by book:")
            for bk, score in sorted(mastery['by_book'].items()):
                print(f"    {bk}: {score * 100:.1f}%")

        if mastery['weakest_sections']:
            print("  Weakest sections:")
            for sk, score in mastery['weakest_sections'][:3]:
                print(f"    {sk}: {score * 100:.1f}%")

        if mastery['strongest_sections']:
            print("  Strongest sections:")
            for sk, score in mastery['strongest_sections'][:3]:
                print(f"    {sk}: {score * 100:.1f}%")


def cmd_plan(args):
    """Generate a study plan."""
    store = CardStore(args.db)
    if store.count() == 0:
        print("No cards in the deck. Add some first.")
        return

    # Resolve graph registry path
    graph_path = Path(args.db).parent / 'graph_registry.json'

    # Select gap cards if graph exists
    gap_cards = []
    if graph_path.exists():
        gap_budget = args.minutes * 0.10  # 10% of time
        gap_cards = select_gap_cards(graph_path, store, gap_budget,
                                     book=args.book)

    # Optional gap seeding
    if getattr(args, 'seed_gaps', False) and graph_path.exists():
        seeded = seed_gap_cards(graph_path, store, book=args.book)
        if seeded:
            print(f"Seeded {len(seeded)} new card(s) for gap concepts.")
            # Re-select gap cards now that new cards exist
            gap_cards = select_gap_cards(graph_path, store,
                                         args.minutes * 0.10, book=args.book)

    plan = make_study_plan(store, minutes=args.minutes, book=args.book,
                            graph_registry_path=graph_path,
                            gap_cards=gap_cards)

    print(f"\nSTUDY PLAN -- {plan['total_minutes']} minutes")
    print("=" * 60)

    rev = plan['review']
    print(f"\n1. REVIEW ({rev['estimated_minutes']} min) -- "
          f"{len(rev['cards'])} due card(s)")
    for c in rev['cards'][:10]:
        print(f"   [{c.card_type}] {c.prompt[:70]}")
    if len(rev['cards']) > 10:
        print(f"   ... and {len(rev['cards']) - 10} more")

    boost = plan['boost']
    print(f"\n2. BOOST ({boost['estimated_minutes']} min) -- "
          f"{len(boost['cards'])} weak card(s)")
    if boost['sections']:
        print(f"   Sections: {', '.join(boost['sections'][:5])}")

    quiz = plan['quiz']
    print(f"\n3. QUIZ ({quiz['estimated_minutes']} min) -- "
          f"{quiz['n_questions']} question(s)")

    gap = plan['gap_boost']
    print(f"\n4. GAP BOOST ({gap['estimated_minutes']} min) -- "
          f"{len(gap['cards'])} card(s)")
    if gap['concepts']:
        print(f"   Concepts: {', '.join(gap['concepts'][:5])}")

    snap = plan['mastery_snapshot']
    print(f"\n  Current mastery: {snap['overall'] * 100:.1f}%")
    if snap['weakest_sections']:
        print("  Weakest areas:")
        for sk, score in snap['weakest_sections'][:3]:
            print(f"    {sk}: {score * 100:.1f}%")

    gap_snap = plan.get('gap_snapshot', [])
    if gap_snap:
        print("\n  Top knowledge gaps:")
        for name, score in gap_snap[:5]:
            print(f"    {name}: gap={score:.3f}")


def cmd_show(args):
    """Show details for a specific card."""
    store = CardStore(args.db)
    card = store.get_card(args.card_id)
    if card is None:
        print(f"Card not found: {args.card_id}")
        sys.exit(1)

    print(f"\nCard: {card.card_id}")
    print(f"  Type:     {card.card_type}")
    print(f"  Book:     {card.book_name}")
    print(f"  Tags:     {', '.join(card.tags)}")
    print(f"\n  Prompt:   {card.prompt}")
    print(f"  Answer:   {card.answer}")

    if card.citations:
        print("\n  Citations:")
        for c in card.citations:
            parts = [f"chunk={c.chunk_id}"]
            if c.section:
                parts.append(f"\u00a7{c.section}")
            if c.pages:
                parts.append(f"pp. {c.pages}")
            if c.chapter:
                parts.append(f"Ch. {c.chapter}")
            print(f"    {', '.join(parts)}")

    print(f"\n  Schedule:")
    print(f"    Due:        {card.due_date}")
    print(f"    Interval:   {card.interval_days}d")
    print(f"    Ease:       {card.ease_factor:.2f}")
    print(f"    Reps:       {card.reps}")
    print(f"    Lapses:     {card.lapses}")
    print(f"    Reviewed:   {card.last_reviewed or 'never'}")
    print(f"    Created:    {card.created_at}")


def cmd_export(args):
    """Export cards to Anki CSV."""
    store = CardStore(args.db)
    cards = store.all_cards()

    if args.book:
        cards = [c for c in cards if c.book_name == args.book]
    if args.due_only:
        from datetime import date
        today = date.today().isoformat()
        cards = [c for c in cards if c.due_date <= today]

    if not cards:
        print("No cards to export.")
        return

    out_path = Path(args.anki)
    count = export_anki_csv(cards, out_path)
    print(f"Exported {count} card(s) to {out_path}")


def cmd_insights(args):
    """Show learning outcome analytics."""
    store = CardStore(args.db)
    if store.count() == 0:
        print("No cards in the deck. Add some first.")
        return

    log_path = Path(args.db).parent / 'session_log.jsonl'
    graph_path = Path(args.graph_path) if args.graph_path else (
        Path(args.db).parent / 'graph_registry.json'
    )

    # M1: Concept Difficulty
    difficulty = compute_concept_difficulty(store, log_path, graph_path)

    print(f"\n{'='*60}")
    print("LEARNING OUTCOME ANALYTICS")
    print(f"{'='*60}")

    if difficulty['hardest']:
        print("\n  Hardest concepts:")
        for name, score in difficulty['hardest']:
            print(f"    {name}: difficulty={score:.3f}")

    if difficulty['most_remediated']:
        print("\n  Most remediated:")
        for name, rate in difficulty['most_remediated']:
            print(f"    {name}: trigger_rate={rate:.3f}")

    if difficulty['slowest_mastery']:
        print("\n  Slowest to master:")
        for name, days in difficulty['slowest_mastery']:
            print(f"    {name}: {days:.0f} days")

    # M2: Remediation Effectiveness
    remediation = compute_remediation_effectiveness(log_path)

    print(f"\n  Remediation effectiveness:")
    print(f"    Sessions total:      {remediation['total_sessions']}")
    print(f"    With remediation:    {remediation['sessions_with_remediation']}")
    print(f"    Avg quality (with):  {remediation['avg_quality_with_remediation']:.2f}")
    print(f"    Avg quality (w/o):   {remediation['avg_quality_without_remediation']:.2f}")
    print(f"    Uplift rate:         {remediation['uplift_rate'] * 100:.1f}%")
    print(f"    Quality delta:       {remediation['avg_quality_delta']:+.2f}")

    # M3: Book Quality
    book_quality = compute_book_quality(graph_path)

    if book_quality['books']:
        print(f"\n  Book quality:")
        for bq in book_quality['books']:
            print(f"    {bq['book']}:")
            print(f"      questions={bq['question_count']}  "
                  f"terminality={bq['avg_terminality']:.3f}  "
                  f"contradictions={bq['contradiction_rate']:.3f}  "
                  f"confidence={bq['avg_confidence']:.3f}")

    print(f"\n{'='*60}")


def main():
    parser = argparse.ArgumentParser(
        description="Study mode -- spaced repetition for textbook search",
        prog="python -m study.cli",
    )
    parser.add_argument(
        '--db', default='study_cards.jsonl',
        help="Path to card storage JSONL file (default: study_cards.jsonl)",
    )

    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    subparsers.add_parser('due', help='Show cards due for review')

    review_parser = subparsers.add_parser('review',
                                           help='Run interactive review session')
    review_parser.add_argument(
        '--no-remediate', action='store_true',
        help='Disable prereq remediation on failed cards',
    )
    review_parser.add_argument(
        '--seed-prereqs', action='store_true',
        help='Generate new cards for missing prereq concepts during remediation',
    )
    review_parser.add_argument(
        '--graph-path', default=None,
        help='Path to graph_registry.json (default: <db_dir>/graph_registry.json)',
    )

    add_parser = subparsers.add_parser('add-from-last-answer',
                                       help='Generate cards from last answer')
    add_parser.add_argument(
        '--answer-file', default='textbook_index/_last_answer.json',
        help='Path to last answer JSON (default: textbook_index/_last_answer.json)',
    )

    quiz_parser = subparsers.add_parser('quiz', help='Run a quiz')
    quiz_parser.add_argument('--topic', default='', help='Filter by topic')
    quiz_parser.add_argument('--n', type=int, default=5, help='Number of questions')
    quiz_parser.add_argument('--adaptive', action='store_true',
                             help='Prioritize weak cards and cloze/compare types')

    subparsers.add_parser('stats', help='Show deck statistics')

    plan_parser = subparsers.add_parser('plan', help='Generate a study plan')
    plan_parser.add_argument('--minutes', type=int, default=30,
                             help='Study time in minutes (default: 30)')
    plan_parser.add_argument('--book', default=None, help='Filter by book')
    plan_parser.add_argument('--seed-gaps', action='store_true',
                             help='Generate cards for uncovered gap concepts')

    show_parser = subparsers.add_parser('show', help='Show card details')
    show_parser.add_argument('card_id', help='Card ID to display')

    export_parser = subparsers.add_parser('export', help='Export cards')
    export_parser.add_argument('--anki', required=True,
                               help='Output CSV path for Anki export')
    export_parser.add_argument('--book', default=None, help='Filter by book')
    export_parser.add_argument('--due-only', action='store_true',
                               help='Only export due cards')

    insights_parser = subparsers.add_parser('insights',
                                             help='Show learning outcome analytics')
    insights_parser.add_argument(
        '--graph-path', default=None,
        help='Path to graph_registry.json (default: <db_dir>/graph_registry.json)',
    )

    args = parser.parse_args()

    if args.command == 'due':
        cmd_due(args)
    elif args.command == 'review':
        cmd_review(args)
    elif args.command == 'add-from-last-answer':
        cmd_add_from_last_answer(args)
    elif args.command == 'quiz':
        cmd_quiz(args)
    elif args.command == 'stats':
        cmd_stats(args)
    elif args.command == 'plan':
        cmd_plan(args)
    elif args.command == 'show':
        cmd_show(args)
    elif args.command == 'export':
        cmd_export(args)
    elif args.command == 'insights':
        cmd_insights(args)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
