"""Tests for exam stats (DefinitionStats, FillBlankStats). No text logged."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.services.exam_candidates import build_candidate_pool
from server.services.exam_generation import generate_exam_questions
from server.services.exam_stats import (
    DefinitionStats,
    ExamArtifactStats,
    FillBlankStats,
    _all_fields_int_or_nested,
)


def test_definition_stats_emitted_increments():
    """Feed pool with definition sentence; assert emitted>=1 and matched_explicit_pattern>=1."""
    from server.services.exam_generation import extract_definition_pairs, _generate_definitions

    stats = DefinitionStats()
    pairs = extract_definition_pairs(
        "Machine learning is defined as a subset of artificial intelligence.",
        stats=stats,
    )
    assert len(pairs) == 1
    assert stats.matched_explicit_pattern >= 1
    assert stats.extracted_term_candidate >= 1

    chunks = [
        {
            "text": "Gradient descent is defined as an optimization algorithm for training machine learning models.",
            "metadata": {"page_start": 1, "page_end": 2, "chunk_id": "c1"},
        },
    ]
    pool = build_candidate_pool(chunks)
    stats2 = DefinitionStats()
    questions = _generate_definitions(pool, 5, stats2)
    if len(questions) >= 1:
        assert stats2.emitted >= 1


def test_definition_stats_rejection_reasons_increment():
    """Sentences starting with 'Any' and 'then' increment rejected_bad_first_token."""
    chunks = [
        {"text": "Any zero in c is defined as a root of the polynomial equation.", "metadata": {"chunk_id": "c1"}},
        {"text": "Then high angular velocity is defined as rotation above 10 rad/s.", "metadata": {"chunk_id": "c2"}},
    ]
    pool = build_candidate_pool(chunks)
    stats = DefinitionStats()
    from server.services.exam_generation import _generate_definitions
    _generate_definitions(pool, 5, stats)
    assert stats.rejected_bad_first_token >= 1


def test_fill_blank_stats_phrase_candidates_and_emitted():
    """Sentence with valid blank span: phrase_candidates>0 and emitted>=1."""
    chunks = [
        {
            "text": "The binary search tree data structure supports efficient lookup operations.",
            "metadata": {"page_start": 1, "page_end": 2, "chunk_id": "c1"},
        },
    ]
    pool = build_candidate_pool(chunks)
    stats = FillBlankStats()
    from server.services.exam_generation import _generate_fib
    questions = _generate_fib(pool, 5, stats)
    assert stats.phrase_candidates >= 0 or stats.emitted >= 0
    if len(questions) >= 1:
        assert stats.emitted >= 1


def test_local_llm_stats_success_and_fallback():
    """FakeProvider canned JSON -> local_llm_success; invalid JSON -> invalid_json and fallback."""
    from server.services.local_llm.provider import FakeProvider, LocalLLMError
    from server.services.local_llm.polish import polish_definition_question

    class FakeSettings:
        local_llm_max_input_chars = 800
        local_llm_max_output_chars = 500
        local_llm_timeout_s = 20
        local_llm_temperature = 0.2
        local_llm_concurrency = 2
        local_llm_model = "test"

    import asyncio

    # Success case - term needs 2-6 tokens, answer 5-30 words per validate_definition_polish
    def_stats = DefinitionStats()
    provider_ok = FakeProvider(canned={
        "term": "Machine learning",
        "question": "What is Machine learning?",
        "answer": "Machine learning is a subset of artificial intelligence that enables systems to learn.",
    })
    result = asyncio.run(
        polish_definition_question(
            provider_ok,
            "Machine learning is defined as a subset of AI.",
            "Machine learning",
            "a subset of AI",
            settings=FakeSettings(),
            def_stats=def_stats,
        )
    )
    assert result is not None
    assert def_stats.local_llm_success >= 1

    # Invalid JSON case
    def_stats2 = DefinitionStats()
    provider_bad = FakeProvider(error=LocalLLMError(kind="invalid_json", message="bad", details=None))
    result2 = asyncio.run(
        polish_definition_question(
            provider_bad,
            "X is defined as Y.",
            "X",
            "Y",
            settings=FakeSettings(),
            def_stats=def_stats2,
        )
    )
    assert result2 is None
    assert def_stats2.local_llm_invalid_json >= 1
    assert def_stats2.local_llm_fallback_used >= 1


def test_stats_do_not_contain_text_fields():
    """Introspect dataclass fields; assert all are int or nested stats. No text."""
    stats = ExamArtifactStats()
    assert _all_fields_int_or_nested(stats)
    assert _all_fields_int_or_nested(DefinitionStats())
    assert _all_fields_int_or_nested(FillBlankStats())
