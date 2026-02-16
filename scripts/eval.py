#!/usr/bin/env python3
"""
Evaluation runner -- measure retrieval + answer quality over a golden set.

Usage:
    python scripts/eval.py \\
        --golden eval/golden_sets/sample.jsonl \\
        --root textbook_index \\
        --out eval/results/latest.json

    python scripts/eval.py \\
        --golden eval/golden_sets/sample.jsonl \\
        --root textbook_index \\
        --out eval/results/latest.json \\
        --baseline eval/results/baseline.json
"""

import argparse
import json
import sys
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval.evaluator import run_eval, compare_results


def main():
    parser = argparse.ArgumentParser(
        description="Run evaluation harness over a golden question set",
    )
    parser.add_argument(
        '--golden', required=True,
        help='Path to golden set JSONL file',
    )
    parser.add_argument(
        '--root', default='textbook_index',
        help='Path to textbook_index directory (default: textbook_index)',
    )
    parser.add_argument(
        '--out', default=None,
        help='Path to write results JSON (optional)',
    )
    parser.add_argument(
        '--top-k', type=int, default=10,
        help='Number of chunks to retrieve per question (default: 10)',
    )
    parser.add_argument(
        '--baseline', default=None,
        help='Path to baseline results JSON for regression comparison',
    )

    args = parser.parse_args()

    golden_path = Path(args.golden)
    if not golden_path.exists():
        print(f"Golden set not found: {golden_path}")
        sys.exit(1)

    root_path = Path(args.root)
    if not root_path.exists():
        print(f"Index root not found: {root_path}")
        sys.exit(1)

    # Run evaluation
    print(f"Running evaluation on {golden_path} ...")
    print(f"  Index root: {root_path}")
    print(f"  Top-K: {args.top_k}")

    results = run_eval(
        golden_path,
        index_root=str(root_path),
        top_k=args.top_k,
    )

    # Print summary
    summary = results['summary']
    print(f"\n{'='*60}")
    print("EVALUATION SUMMARY")
    print(f"{'='*60}")
    print(f"  Total questions:      {summary['total']}")
    print(f"  Concept coverage avg: {summary['concept_coverage_avg']:.3f}")
    print(f"  Citation OK rate:     {summary['cite_ok_rate']:.3f}")
    print(f"  Confidence OK rate:   {summary['confidence_ok_rate']:.3f}")
    print(f"  Contradictions:       {summary['contradiction_count']}")

    # Print per-question details
    print(f"\n{'='*60}")
    print("PER-QUESTION RESULTS")
    print(f"{'='*60}")
    for r in results['per_question']:
        status_parts = []
        if r['cite_ok']:
            status_parts.append('cite:OK')
        else:
            status_parts.append('cite:FAIL')
        if r['confidence_ok']:
            status_parts.append('conf:OK')
        else:
            status_parts.append('conf:FAIL')
        status = '  '.join(status_parts)

        print(f"\n  [{r['id']}] {r['question'][:60]}")
        print(f"    coverage={r['concept_coverage']:.3f}  "
              f"{status}  level={r['confidence_level']}")
        if r.get('error'):
            print(f"    ERROR: {r['error']}")

    # Save results
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"\nResults saved to {out_path}")

    # Regression comparison
    if args.baseline:
        baseline_path = Path(args.baseline)
        if not baseline_path.exists():
            print(f"\nBaseline file not found: {baseline_path}")
            sys.exit(1)

        with open(baseline_path, 'r', encoding='utf-8') as f:
            baseline = json.load(f)

        comparison = compare_results(results, baseline)

        print(f"\n{'='*60}")
        print("REGRESSION COMPARISON")
        print(f"{'='*60}")

        for metric, diff in comparison['summary_diff'].items():
            delta = diff['delta']
            arrow = '+' if delta >= 0 else ''
            print(f"  {metric}: {diff['baseline']:.3f} -> {diff['current']:.3f} "
                  f"({arrow}{delta:.3f})")

        regressions = comparison['regressions']
        if regressions:
            print(f"\n  REGRESSIONS ({len(regressions)}):")
            for reg in regressions:
                print(f"    [{reg['id']}] {reg['metric']}: "
                      f"{reg['baseline']} -> {reg['current']}")
                print(f"      {reg['question'][:60]}")
        else:
            print("\n  No regressions detected.")

        improvements = comparison['improvements']
        if improvements:
            print(f"\n  IMPROVEMENTS ({len(improvements)}):")
            for imp in improvements:
                print(f"    [{imp['id']}] {imp['metric']}: "
                      f"{imp['baseline']} -> {imp['current']}")


if __name__ == '__main__':
    main()
