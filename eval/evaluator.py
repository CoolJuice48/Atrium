"""Evaluation harness -- measure retrieval + answer quality over a golden set."""

import json
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ============================================================================
# Confidence level ordering (for threshold comparison)
# ============================================================================

_CONFIDENCE_RANK = {'low': 0, 'medium': 1, 'high': 2}


# ============================================================================
# Scoring functions (individually testable)
# ============================================================================

def compute_concept_coverage(
    expected: List[str],
    found: List[str],
) -> float:
    """
    Fraction of expected concepts found in the extracted concepts.

    Matching is case-insensitive substring: an expected concept 'gradient descent'
    matches if any found term contains 'gradient descent' or vice versa.

    Returns:
        Float 0.0 to 1.0.  Returns 1.0 if expected is empty.
    """
    if not expected:
        return 1.0
    found_lower = [f.lower() for f in found]
    hits = 0
    for exp in expected:
        exp_lower = exp.lower()
        if any(exp_lower in f or f in exp_lower for f in found_lower):
            hits += 1
    return hits / len(expected)


def check_cite_ok(
    must_cite_any: List[str],
    cited_books: Set[str],
) -> bool:
    """
    Check if at least one required book was cited.

    Returns True if must_cite_any is empty or at least one match is found.
    """
    if not must_cite_any:
        return True
    return bool(set(must_cite_any) & cited_books)


def check_confidence_ok(
    actual_level: str,
    min_level: str,
) -> bool:
    """Check if actual confidence meets the minimum threshold."""
    return _CONFIDENCE_RANK.get(actual_level, 0) >= _CONFIDENCE_RANK.get(min_level, 0)


def extract_cited_chunks(
    answer_result: Dict,
    top_chunks: List[Dict],
) -> List[Dict]:
    """
    Extract cited chunk info from answer result and top chunks.

    Returns list of {chunk_id, book, section, pages} for each source chunk
    that contributed to the answer.
    """
    cited = []
    seen = set()
    # From top_chunks metadata (these are the retrieval results)
    for chunk in top_chunks:
        meta = chunk.get('metadata', chunk)
        cid = meta.get('chunk_id', '')
        if cid and cid not in seen:
            seen.add(cid)
            cited.append({
                'chunk_id': cid,
                'book': meta.get('book') or meta.get('book_name', ''),
                'section': meta.get('section') or meta.get('section_number', ''),
                'pages': meta.get('pages', ''),
            })
    return cited


def extract_cited_books(
    answer_result: Dict,
    top_chunks: List[Dict],
) -> Set[str]:
    """Extract unique book names from citations and retrieval results."""
    books: Set[str] = set()
    # From citations in the answer
    for cite_str in answer_result.get('citations', []):
        # Citations are formatted as "BookName, §Section, p.Pages"
        parts = cite_str.split(',')
        if parts:
            book = parts[0].strip()
            if book:
                books.add(book)
    # From top_chunks metadata
    for chunk in top_chunks:
        meta = chunk.get('metadata', chunk)
        book = meta.get('book') or meta.get('book_name', '')
        if book:
            books.add(book)
    return books


# ============================================================================
# Per-item evaluation
# ============================================================================

def evaluate_item(
    item: Dict,
    pipeline_fn: Callable,
) -> Dict:
    """
    Evaluate a single golden set item.

    Args:
        item:        Golden set item dict (id, question, book, expected_concepts, ...)
        pipeline_fn: Callable(question, book) -> (answer_result, top_chunks)
                     answer_result is the compose_answer output dict
                     top_chunks is the list of retrieved chunks

    Returns:
        Per-item result dict with scores and diagnostics.
    """
    question = item['question']
    book = item.get('book')
    expected_concepts = item.get('expected_concepts', [])
    must_cite_any = item.get('must_cite_any', [])
    min_confidence = item.get('min_confidence', 'low')

    # Run pipeline
    try:
        answer_result, top_chunks = pipeline_fn(question, book)
    except Exception as e:
        return {
            'id': item['id'],
            'question': question,
            'error': str(e),
            'concept_coverage': 0.0,
            'cite_ok': False,
            'confidence_ok': False,
            'confidence_level': 'low',
            'contradiction_flag': False,
            'found_concepts': [],
            'cited_chunks': [],
        }

    # Extract concepts from answer using graph/concepts.py
    found_concepts = _extract_concepts_from_answer(
        question, answer_result, top_chunks,
    )

    # Extract citation info
    cited_chunks = extract_cited_chunks(answer_result, top_chunks)
    cited_books = extract_cited_books(answer_result, top_chunks)

    # Compute metrics
    coverage = compute_concept_coverage(expected_concepts, found_concepts)
    cite_ok = check_cite_ok(must_cite_any, cited_books)

    confidence = answer_result.get('confidence', {})
    actual_level = confidence.get('level', 'low')
    confidence_ok = check_confidence_ok(actual_level, min_confidence)
    contradiction_flag = confidence.get('contradiction_flag', False)

    return {
        'id': item['id'],
        'question': question,
        'concept_coverage': round(coverage, 3),
        'cite_ok': cite_ok,
        'confidence_ok': confidence_ok,
        'confidence_level': actual_level,
        'contradiction_flag': contradiction_flag,
        'found_concepts': found_concepts,
        'cited_chunks': cited_chunks,
        'expected_concepts': expected_concepts,
        'must_cite_any': must_cite_any,
        'min_confidence': min_confidence,
    }


def _extract_concepts_from_answer(
    question: str,
    answer_result: Dict,
    top_chunks: List[Dict],
) -> List[str]:
    """Extract concepts using graph/concepts.py extractor."""
    try:
        from graph.concepts import extract_concepts
        return extract_concepts(question, answer_result, top_chunks)
    except Exception:
        return []


# ============================================================================
# Aggregate evaluation
# ============================================================================

def load_golden_set(golden_path: Path) -> List[Dict]:
    """Load a golden set JSONL file."""
    items = []
    with open(golden_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def run_eval(
    golden_path: Path,
    *,
    index_root: Optional[str] = None,
    top_k: int = 10,
    pipeline_fn: Optional[Callable] = None,
) -> Dict:
    """
    Run evaluation over a golden question set.

    For each item, runs the retrieval + answer composition pipeline and
    computes concept_coverage, cite_ok, and confidence_ok.

    Args:
        golden_path:  Path to golden set JSONL file
        index_root:   Path to textbook_index directory (used to build pipeline_fn)
        top_k:        Number of chunks to retrieve per question
        pipeline_fn:  Optional injectable pipeline function for testing.
                      If not provided, uses TextbookSearchOffline from index_root.

    Returns:
        {
            'summary': {total, concept_coverage_avg, cite_ok_rate, confidence_ok_rate,
                        contradiction_count},
            'per_question': [per-item result dicts],
        }
    """
    items = load_golden_set(golden_path)

    if pipeline_fn is None:
        pipeline_fn = _make_default_pipeline(index_root, top_k)

    results = []
    for item in items:
        result = evaluate_item(item, pipeline_fn)
        results.append(result)

    # Aggregate
    total = len(results)
    if total == 0:
        return {
            'summary': {
                'total': 0,
                'concept_coverage_avg': 0.0,
                'cite_ok_rate': 0.0,
                'confidence_ok_rate': 0.0,
                'contradiction_count': 0,
            },
            'per_question': [],
        }

    coverage_sum = sum(r['concept_coverage'] for r in results)
    cite_ok_count = sum(1 for r in results if r['cite_ok'])
    conf_ok_count = sum(1 for r in results if r['confidence_ok'])
    contradiction_count = sum(1 for r in results if r.get('contradiction_flag'))

    return {
        'summary': {
            'total': total,
            'concept_coverage_avg': round(coverage_sum / total, 3),
            'cite_ok_rate': round(cite_ok_count / total, 3),
            'confidence_ok_rate': round(conf_ok_count / total, 3),
            'contradiction_count': contradiction_count,
        },
        'per_question': results,
    }


def _make_default_pipeline(index_root: Optional[str], top_k: int) -> Callable:
    """Build the default pipeline function using TextbookSearchOffline."""
    if index_root is None:
        raise ValueError("index_root is required when pipeline_fn is not provided")

    from legacy.textbook_search_offline import TextbookSearchOffline, compose_answer

    searcher = TextbookSearchOffline(db_path=index_root)

    def pipeline_fn(question: str, book: Optional[str]) -> Tuple[Dict, List[Dict]]:
        top_chunks = searcher.search(
            question, n_results=top_k, book_filter=book,
        )
        answer_result = compose_answer(question, top_chunks)
        return answer_result, top_chunks

    return pipeline_fn


# ============================================================================
# Regression comparison
# ============================================================================

def compare_results(
    current: Dict,
    baseline: Dict,
) -> Dict:
    """
    Compare current eval results against a baseline.

    Returns:
        {
            'summary_diff': {metric: {current, baseline, delta}},
            'regressions': [
                {id, question, metric, current_val, baseline_val},
                ...
            ],
            'improvements': [
                {id, question, metric, current_val, baseline_val},
                ...
            ],
        }
    """
    cur_summary = current.get('summary', {})
    base_summary = baseline.get('summary', {})

    summary_diff = {}
    for key in ('concept_coverage_avg', 'cite_ok_rate', 'confidence_ok_rate'):
        cur_val = cur_summary.get(key, 0.0)
        base_val = base_summary.get(key, 0.0)
        summary_diff[key] = {
            'current': cur_val,
            'baseline': base_val,
            'delta': round(cur_val - base_val, 3),
        }

    # Per-question comparison
    base_by_id = {r['id']: r for r in baseline.get('per_question', [])}
    regressions = []
    improvements = []

    for cur_r in current.get('per_question', []):
        qid = cur_r['id']
        base_r = base_by_id.get(qid)
        if base_r is None:
            continue

        for metric in ('concept_coverage', 'cite_ok', 'confidence_ok'):
            cur_val = cur_r.get(metric)
            base_val = base_r.get(metric)
            if cur_val is None or base_val is None:
                continue

            # Normalize booleans to numeric for comparison
            cur_num = float(cur_val) if isinstance(cur_val, bool) else cur_val
            base_num = float(base_val) if isinstance(base_val, bool) else base_val

            if cur_num < base_num:
                regressions.append({
                    'id': qid,
                    'question': cur_r.get('question', ''),
                    'metric': metric,
                    'current': cur_val,
                    'baseline': base_val,
                })
            elif cur_num > base_num:
                improvements.append({
                    'id': qid,
                    'question': cur_r.get('question', ''),
                    'metric': metric,
                    'current': cur_val,
                    'baseline': base_val,
                })

    return {
        'summary_diff': summary_diff,
        'regressions': regressions,
        'improvements': improvements,
    }
