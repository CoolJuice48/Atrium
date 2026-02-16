"""Tests for eval/evaluator.py -- evaluation harness scoring and pipeline."""

import sys
import json
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval.evaluator import (
    compute_concept_coverage,
    check_cite_ok,
    check_confidence_ok,
    extract_cited_books,
    extract_cited_chunks,
    evaluate_item,
    load_golden_set,
    run_eval,
    compare_results,
)


# ============================================================================
# TESTS: concept coverage scoring
# ============================================================================

def test_coverage_exact_match():
    """All expected concepts found gives coverage 1.0."""
    expected = ['gradient descent', 'learning rate']
    found = ['gradient descent', 'learning rate', 'objective function']
    assert compute_concept_coverage(expected, found) == 1.0


def test_coverage_partial_match():
    """Partial match returns fractional coverage."""
    expected = ['gradient descent', 'learning rate', 'regularization']
    found = ['gradient descent']
    assert compute_concept_coverage(expected, found) == 1.0 / 3.0


def test_coverage_no_match():
    """No overlap returns 0.0."""
    expected = ['gradient descent', 'momentum']
    found = ['unrelated', 'concepts']
    assert compute_concept_coverage(expected, found) == 0.0


def test_coverage_empty_expected():
    """Empty expected returns 1.0 (vacuously true)."""
    assert compute_concept_coverage([], ['anything']) == 1.0


def test_coverage_empty_found():
    """No concepts found returns 0.0."""
    expected = ['gradient descent']
    assert compute_concept_coverage(expected, []) == 0.0


def test_coverage_case_insensitive():
    """Matching is case-insensitive."""
    expected = ['Gradient Descent']
    found = ['gradient descent']
    assert compute_concept_coverage(expected, found) == 1.0


def test_coverage_substring_match():
    """A found concept can match as substring of expected or vice versa."""
    # 'gradient' is a substring of 'gradient descent'
    expected = ['gradient descent']
    found = ['gradient']
    assert compute_concept_coverage(expected, found) == 1.0


# ============================================================================
# TESTS: cite_ok logic
# ============================================================================

def test_cite_ok_match():
    """Cited book matches must_cite_any."""
    assert check_cite_ok(['BookA', 'BookB'], {'BookA', 'BookC'}) is True


def test_cite_ok_no_match():
    """No cited book matches must_cite_any."""
    assert check_cite_ok(['BookA'], {'BookB', 'BookC'}) is False


def test_cite_ok_empty_requirement():
    """Empty must_cite_any always passes."""
    assert check_cite_ok([], {'BookB'}) is True


def test_cite_ok_empty_cited():
    """No books cited fails when must_cite_any is specified."""
    assert check_cite_ok(['BookA'], set()) is False


# ============================================================================
# TESTS: confidence threshold checks
# ============================================================================

def test_confidence_ok_exact():
    """Exact confidence match passes."""
    assert check_confidence_ok('medium', 'medium') is True


def test_confidence_ok_higher():
    """Higher confidence than minimum passes."""
    assert check_confidence_ok('high', 'medium') is True


def test_confidence_ok_lower():
    """Lower confidence than minimum fails."""
    assert check_confidence_ok('low', 'medium') is False


def test_confidence_ok_low_minimum():
    """Low minimum passes for any level."""
    assert check_confidence_ok('low', 'low') is True
    assert check_confidence_ok('medium', 'low') is True
    assert check_confidence_ok('high', 'low') is True


# ============================================================================
# TESTS: cited chunks and books extraction
# ============================================================================

def test_extract_cited_chunks():
    """Extracts chunk metadata from top_chunks."""
    top_chunks = [
        {
            'text': 'Some text',
            'metadata': {
                'chunk_id': 'chunk_001',
                'book': 'BookA',
                'section': '1.1',
                'pages': '10-15',
            },
        },
        {
            'text': 'More text',
            'metadata': {
                'chunk_id': 'chunk_002',
                'book_name': 'BookB',
                'section_number': '2.3',
                'pages': '20-25',
            },
        },
    ]
    answer_result = {'citations': []}
    chunks = extract_cited_chunks(answer_result, top_chunks)
    assert len(chunks) == 2
    assert chunks[0]['chunk_id'] == 'chunk_001'
    assert chunks[0]['book'] == 'BookA'
    assert chunks[1]['book'] == 'BookB'


def test_extract_cited_books_from_citations():
    """Extract books from answer citations string."""
    answer_result = {
        'citations': ['BookA, §1.1, p.10', 'BookB, §2.3, p.20'],
    }
    top_chunks = []
    books = extract_cited_books(answer_result, top_chunks)
    assert 'BookA' in books
    assert 'BookB' in books


def test_extract_cited_books_from_chunks():
    """Extract books from chunk metadata."""
    answer_result = {'citations': []}
    top_chunks = [
        {'metadata': {'book': 'BookC'}},
    ]
    books = extract_cited_books(answer_result, top_chunks)
    assert 'BookC' in books


# ============================================================================
# TESTS: evaluate_item with mock pipeline
# ============================================================================

def _mock_pipeline(question, book):
    """Mock pipeline that returns deterministic results."""
    answer_result = {
        'answer': f'Answer about {question}',
        'key_points': [f'Key point about {question}'],
        'citations': [f'{book or "UnknownBook"}, §1.1, p.10'],
        'confidence': {
            'level': 'medium',
            'evidence_coverage_score': 0.25,
            'source_diversity_score': 1,
            'redundancy_score': 0.0,
            'contradiction_flag': False,
        },
    }
    top_chunks = [{
        'text': f'Retrieved text about {question}',
        'metadata': {
            'chunk_id': 'test_chunk_1',
            'book': book or 'UnknownBook',
            'section': '1.1',
            'pages': '10-15',
        },
    }]
    return answer_result, top_chunks


def test_evaluate_item_basic():
    """evaluate_item returns all expected fields."""
    item = {
        'id': 'test_001',
        'question': 'What is testing?',
        'book': 'BookA',
        'expected_concepts': ['testing'],
        'must_cite_any': ['BookA'],
        'min_confidence': 'low',
    }
    result = evaluate_item(item, _mock_pipeline)
    assert result['id'] == 'test_001'
    assert 'concept_coverage' in result
    assert 'cite_ok' in result
    assert 'confidence_ok' in result
    assert 'confidence_level' in result
    assert 'found_concepts' in result
    assert 'cited_chunks' in result


def test_evaluate_item_cite_ok():
    """evaluate_item correctly checks cite_ok."""
    item = {
        'id': 'test_002',
        'question': 'What is X?',
        'book': 'BookA',
        'expected_concepts': [],
        'must_cite_any': ['BookA'],
        'min_confidence': 'low',
    }
    result = evaluate_item(item, _mock_pipeline)
    assert result['cite_ok'] is True


def test_evaluate_item_cite_fail():
    """evaluate_item reports cite failure when wrong book cited."""
    item = {
        'id': 'test_003',
        'question': 'What is Y?',
        'book': 'BookA',
        'expected_concepts': [],
        'must_cite_any': ['BookZ'],
        'min_confidence': 'low',
    }
    result = evaluate_item(item, _mock_pipeline)
    assert result['cite_ok'] is False


def test_evaluate_item_pipeline_error():
    """evaluate_item handles pipeline errors gracefully."""
    def failing_pipeline(q, b):
        raise RuntimeError("Pipeline crashed")

    item = {
        'id': 'test_err',
        'question': 'Crash test',
    }
    result = evaluate_item(item, failing_pipeline)
    assert result['id'] == 'test_err'
    assert result['concept_coverage'] == 0.0
    assert result['cite_ok'] is False
    assert 'error' in result


# ============================================================================
# TESTS: run_eval with golden set file
# ============================================================================

def test_run_eval_with_mock_pipeline():
    """run_eval processes a golden set file and returns summary."""
    with tempfile.TemporaryDirectory() as tmp:
        golden_path = Path(tmp) / 'test_golden.jsonl'
        items = [
            {
                'id': 'q1',
                'question': 'What is testing?',
                'book': 'BookA',
                'expected_concepts': ['testing'],
                'must_cite_any': ['BookA'],
                'min_confidence': 'low',
            },
            {
                'id': 'q2',
                'question': 'What is validation?',
                'book': 'BookB',
                'expected_concepts': ['validation'],
                'must_cite_any': ['BookB'],
                'min_confidence': 'medium',
            },
        ]
        with open(golden_path, 'w') as f:
            for item in items:
                f.write(json.dumps(item) + '\n')

        results = run_eval(golden_path, pipeline_fn=_mock_pipeline)
        summary = results['summary']
        assert summary['total'] == 2
        assert 'concept_coverage_avg' in summary
        assert 'cite_ok_rate' in summary
        assert 'confidence_ok_rate' in summary
        assert len(results['per_question']) == 2


def test_run_eval_empty_golden():
    """run_eval handles empty golden set."""
    with tempfile.TemporaryDirectory() as tmp:
        golden_path = Path(tmp) / 'empty.jsonl'
        golden_path.write_text('')

        results = run_eval(golden_path, pipeline_fn=_mock_pipeline)
        assert results['summary']['total'] == 0


# ============================================================================
# TESTS: load_golden_set
# ============================================================================

def test_load_golden_set():
    """load_golden_set reads JSONL correctly."""
    with tempfile.TemporaryDirectory() as tmp:
        golden_path = Path(tmp) / 'test.jsonl'
        items = [
            {'id': 'a', 'question': 'Q1'},
            {'id': 'b', 'question': 'Q2'},
        ]
        with open(golden_path, 'w') as f:
            for item in items:
                f.write(json.dumps(item) + '\n')

        loaded = load_golden_set(golden_path)
        assert len(loaded) == 2
        assert loaded[0]['id'] == 'a'


# ============================================================================
# TESTS: regression comparison
# ============================================================================

def test_compare_no_regressions():
    """compare_results finds no regressions when current matches baseline."""
    baseline = {
        'summary': {
            'concept_coverage_avg': 0.8,
            'cite_ok_rate': 1.0,
            'confidence_ok_rate': 0.9,
        },
        'per_question': [
            {'id': 'q1', 'question': 'Q1', 'concept_coverage': 0.8,
             'cite_ok': True, 'confidence_ok': True},
        ],
    }
    current = {
        'summary': {
            'concept_coverage_avg': 0.9,
            'cite_ok_rate': 1.0,
            'confidence_ok_rate': 1.0,
        },
        'per_question': [
            {'id': 'q1', 'question': 'Q1', 'concept_coverage': 0.9,
             'cite_ok': True, 'confidence_ok': True},
        ],
    }
    comparison = compare_results(current, baseline)
    assert len(comparison['regressions']) == 0
    assert len(comparison['improvements']) >= 1


def test_compare_detects_regression():
    """compare_results detects when a metric drops."""
    baseline = {
        'summary': {'concept_coverage_avg': 0.8, 'cite_ok_rate': 1.0,
                     'confidence_ok_rate': 1.0},
        'per_question': [
            {'id': 'q1', 'question': 'Q1', 'concept_coverage': 0.8,
             'cite_ok': True, 'confidence_ok': True},
        ],
    }
    current = {
        'summary': {'concept_coverage_avg': 0.5, 'cite_ok_rate': 0.5,
                     'confidence_ok_rate': 0.5},
        'per_question': [
            {'id': 'q1', 'question': 'Q1', 'concept_coverage': 0.5,
             'cite_ok': False, 'confidence_ok': False},
        ],
    }
    comparison = compare_results(current, baseline)
    assert len(comparison['regressions']) >= 1
    regressed_metrics = {r['metric'] for r in comparison['regressions']}
    assert 'concept_coverage' in regressed_metrics


def test_compare_summary_diff():
    """compare_results includes summary diff with delta."""
    baseline = {
        'summary': {'concept_coverage_avg': 0.7, 'cite_ok_rate': 0.8,
                     'confidence_ok_rate': 0.9},
        'per_question': [],
    }
    current = {
        'summary': {'concept_coverage_avg': 0.9, 'cite_ok_rate': 0.6,
                     'confidence_ok_rate': 0.9},
        'per_question': [],
    }
    comparison = compare_results(current, baseline)
    diff = comparison['summary_diff']
    assert diff['concept_coverage_avg']['delta'] == 0.2
    assert diff['cite_ok_rate']['delta'] == -0.2
    assert diff['confidence_ok_rate']['delta'] == 0.0


def test_compare_cite_ok_bool_regression():
    """Regression detection handles boolean cite_ok correctly."""
    baseline = {
        'summary': {'concept_coverage_avg': 1.0, 'cite_ok_rate': 1.0,
                     'confidence_ok_rate': 1.0},
        'per_question': [
            {'id': 'q1', 'question': 'Q', 'concept_coverage': 1.0,
             'cite_ok': True, 'confidence_ok': True},
        ],
    }
    current = {
        'summary': {'concept_coverage_avg': 1.0, 'cite_ok_rate': 0.0,
                     'confidence_ok_rate': 1.0},
        'per_question': [
            {'id': 'q1', 'question': 'Q', 'concept_coverage': 1.0,
             'cite_ok': False, 'confidence_ok': True},
        ],
    }
    comparison = compare_results(current, baseline)
    regressed_metrics = {r['metric'] for r in comparison['regressions']}
    assert 'cite_ok' in regressed_metrics


def test_compare_new_question_ignored():
    """Questions in current but not baseline are not flagged."""
    baseline = {
        'summary': {'concept_coverage_avg': 1.0, 'cite_ok_rate': 1.0,
                     'confidence_ok_rate': 1.0},
        'per_question': [],
    }
    current = {
        'summary': {'concept_coverage_avg': 0.5, 'cite_ok_rate': 0.5,
                     'confidence_ok_rate': 0.5},
        'per_question': [
            {'id': 'new_q', 'question': 'New question', 'concept_coverage': 0.5,
             'cite_ok': False, 'confidence_ok': False},
        ],
    }
    comparison = compare_results(current, baseline)
    assert len(comparison['regressions']) == 0
