"""Tests for local LLM polish feature."""

import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.services.local_llm.provider import FakeProvider, LocalLLMError, get_provider, reset_provider
from server.services.local_llm.validate import validate_definition_polish, validate_fill_blank_polish


def test_local_llm_disabled_uses_deterministic_only():
    """When disabled, get_provider returns None."""
    reset_provider()

    class DisabledSettings:
        local_llm_enabled = False

    assert get_provider(DisabledSettings()) is None


def test_local_llm_unavailable_falls_back_cleanly():
    """When provider raises, polish falls back to deterministic."""
    from server.services.local_llm.exam_polish import polish_exam_questions_sync
    from server.services.exam_generation import ExamQuestion

    reset_provider()
    provider = FakeProvider(error=LocalLLMError(kind="unavailable", message="Ollama not running"))
    questions = [
        ExamQuestion(q_type="definition", prompt="What is X?", answer="X is a thing.", citations=[], source_text="X is defined as a thing."),
    ]
    result = polish_exam_questions_sync(questions, provider, None)
    assert len(result) == 1
    assert result[0].prompt == "What is X?"
    assert result[0].answer == "X is a thing."


def test_local_llm_returns_invalid_json_falls_back():
    """When provider returns invalid JSON, fall back."""
    from server.services.local_llm.exam_polish import polish_exam_questions_sync
    from server.services.exam_generation import ExamQuestion

    reset_provider()
    provider = FakeProvider(error=LocalLLMError(kind="invalid_json", message="Not JSON"))
    questions = [
        ExamQuestion(q_type="definition", prompt="What is Y?", answer="Y is something.", citations=[], source_text="Y is defined as something."),
    ]
    result = polish_exam_questions_sync(questions, provider, None)
    assert len(result) == 1
    assert result[0].prompt == "What is Y?"


def test_local_llm_output_validation_rejects_long_answers():
    """Validation rejects answers that are too long."""
    ok, reason = validate_definition_polish({
        "term": "Machine learning",
        "question": "What is Machine learning?",
        "answer": " ".join(["word"] * 35),
    })
    assert not ok
    assert "answer" in reason.lower() or "word" in reason.lower()


def test_local_llm_never_receives_large_input():
    """Input is truncated to max chars."""
    from server.services.local_llm.polish import _normalize_input

    long_sentence = "x" * 1000
    normalized = _normalize_input(long_sentence)
    assert len(normalized) <= 400


def test_definition_polish_blocks_any_then_this_terms():
    """Validation rejects terms starting with Any, then, this."""
    ok, _ = validate_definition_polish({
        "term": "Any zero in c",
        "question": "What is Any zero in c?",
        "answer": "A root of the polynomial.",
    })
    assert not ok
    ok, _ = validate_definition_polish({
        "term": "then high velocity",
        "question": "What is then high velocity?",
        "answer": "Rotation above threshold.",
    })
    assert not ok
    ok, _ = validate_definition_polish({
        "term": "This method",
        "question": "What is This method?",
        "answer": "An optimization approach.",
    })
    assert not ok


def test_fill_blank_polish_produces_single_blank():
    """Validation requires exactly one blank."""
    ok, _ = validate_fill_blank_polish({
        "prompt": "The function ____ is used.",
        "answer": "approximated",
    })
    assert ok
    ok, _ = validate_fill_blank_polish({
        "prompt": "The ____ and ____ are used.",
        "answer": "first",
    })
    assert not ok
    ok, _ = validate_fill_blank_polish({
        "prompt": "No blank here.",
        "answer": "missing",
    })
    assert not ok


def test_fake_provider_returns_canned():
    """FakeProvider returns canned JSON when provided."""
    from server.services.local_llm.exam_polish import polish_exam_questions_sync
    from server.services.exam_generation import ExamQuestion

    reset_provider()
    provider = FakeProvider(canned={
        "term": "Gradient descent",
        "question": "What is Gradient descent?",
        "answer": "An optimization algorithm for minimizing loss.",
    })
    questions = [
        ExamQuestion(q_type="definition", prompt="What is X?", answer="X is a thing.", citations=[], source_text="X is defined as a thing."),
    ]
    result = polish_exam_questions_sync(questions, provider, None)
    assert len(result) == 1
    assert result[0].prompt == "What is Gradient descent?"
    assert result[0].answer == "An optimization algorithm for minimizing loss."
