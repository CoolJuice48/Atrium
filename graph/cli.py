"""Graph CLI -- concept registry commands."""

import sys
import argparse
from pathlib import Path

from graph.models import GraphRegistry, make_question_id
from graph.gaps import get_ranked_gaps
from graph.prereqs import get_prereqs


def cmd_explain(args):
    """Show QNode details for a question."""
    registry = GraphRegistry()
    registry.load(Path(args.registry))

    qid = make_question_id(args.question)
    qnode = registry.get_qnode(qid)

    if qnode is None:
        print(f"No record found for question: {args.question!r}")
        print(f"  (looked up ID: {qid})")
        return

    print(f"\nQuestion: {qnode.question_text}")
    print(f"  ID:          {qnode.question_id}")
    print(f"  Terminality: {qnode.terminality_score:.2f}")

    if qnode.books:
        print(f"  Books:       {', '.join(qnode.books)}")
    if qnode.sections:
        print(f"  Sections:    {', '.join(qnode.sections)}")
    if qnode.citations:
        print(f"  Citations:   {len(qnode.citations)} chunk(s)")
        for cid in qnode.citations[:5]:
            print(f"    {cid}")

    conf = qnode.confidence_snapshot
    if conf:
        print(f"\n  Confidence:  {conf.get('level', 'unknown')}")
        print(f"  Coverage:    {conf.get('evidence_coverage_score', 0):.3f}")
        print(f"  Redundancy:  {conf.get('redundancy_score', 0):.3f}")
        if conf.get('contradiction_flag'):
            print("  WARNING: contradiction detected")

    # Find linked concepts
    linked = []
    for concept in registry.all_concepts():
        if qnode.question_id in concept.linked_qnodes:
            linked.append(concept)

    if linked:
        print(f"\n  Linked concepts ({len(linked)}):")
        for c in sorted(linked, key=lambda x: x.name):
            print(f"    {c.name} (mastery={c.mastery_score:.2f}, "
                  f"occurrences={c.occurrences})")


def cmd_gaps(args):
    """Show top knowledge gap concepts."""
    registry = GraphRegistry()
    registry.load(Path(args.registry))

    if registry.count_concepts() == 0:
        print("No concepts in the registry. Ask some questions first.")
        return

    ranked = get_ranked_gaps(registry, top_n=args.n)

    print(f"\nTOP {len(ranked)} KNOWLEDGE GAPS")
    print("=" * 60)
    for i, (concept, score) in enumerate(ranked, 1):
        books_str = ', '.join(concept.books[:3]) if concept.books else 'unknown'
        print(f"\n  {i}. {concept.name}")
        print(f"     Gap score:  {score:.3f}")
        print(f"     Mastery:    {concept.mastery_score:.2f}")
        print(f"     Books:      {books_str}")
        print(f"     Questions:  {len(concept.linked_qnodes)}")
        print(f"     Occurrences: {concept.occurrences}")


def cmd_prereqs(args):
    """Show prerequisite concepts for a given concept."""
    registry = GraphRegistry()
    registry.load(Path(args.registry))

    prereqs = get_prereqs(args.concept, registry, top_n=args.n)

    if not prereqs:
        concept = registry.get_concept_by_name(args.concept)
        if concept is None:
            print(f"Concept not found: {args.concept!r}")
        else:
            print(f"No prerequisites found for: {args.concept!r}")
        return

    print(f"\nPREREQUISITES for '{args.concept}'")
    print("=" * 60)
    for i, (concept, cooccur) in enumerate(prereqs, 1):
        sections_str = ', '.join(concept.sections[:3]) if concept.sections else '?'
        print(f"  {i}. {concept.name}")
        print(f"     Sections:      {sections_str}")
        print(f"     Co-occurrence: {cooccur}")
        print(f"     Mastery:       {concept.mastery_score:.2f}")


def main():
    parser = argparse.ArgumentParser(
        description="Concept & Question graph registry",
        prog="python -m graph.cli",
    )
    parser.add_argument(
        '--registry', default='textbook_index/graph_registry.json',
        help='Path to graph registry JSON (default: textbook_index/graph_registry.json)',
    )

    subparsers = parser.add_subparsers(dest='command', help='Graph commands')

    explain_parser = subparsers.add_parser('explain', help='Explain a question')
    explain_parser.add_argument('question', help='Question text to look up')

    gaps_parser = subparsers.add_parser('gaps', help='Show knowledge gaps')
    gaps_parser.add_argument('--n', type=int, default=10,
                             help='Number of gaps to show (default: 10)')

    prereqs_parser = subparsers.add_parser('prereqs',
                                            help='Show prerequisites for a concept')
    prereqs_parser.add_argument('concept', help='Concept name')
    prereqs_parser.add_argument('--n', type=int, default=10,
                                help='Number of prereqs to show (default: 10)')

    args = parser.parse_args()

    if args.command == 'explain':
        cmd_explain(args)
    elif args.command == 'gaps':
        cmd_gaps(args)
    elif args.command == 'prereqs':
        cmd_prereqs(args)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
