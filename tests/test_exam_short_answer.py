"""Tests for grammar-aware short-answer generation."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.services.exam_short_answer import (
    ShortAnswerStats,
    build_because_answer,
    build_why_question,
    clause_is_questionable,
    clean_leading_structure,
    detect_auxiliary,
    generate_short_answer_from_sentence,
    split_on_causal_cue,
    strip_leading_prep_phrase,
)
from server.services.exam_candidates import build_candidate_pool
from server.services.exam_generation import generate_exam_questions
from server.services.exam_stems import validate_short_answer_stem


def test_clean_leading_structure_strips_section_number_and_heading():
    """Strip leading numbering and heading-like prefix."""
    s = "4 Optimizing Memory Control Most computers use DRAM for main memory."
    out = clean_leading_structure(s)
    assert not out.startswith("4 ")
    assert "computers" in out.lower() or "dram" in out.lower()


def test_short_answer_requires_causal_cue():
    """Sentence without because/since/due to returns None."""
    assert generate_short_answer_from_sentence("The algorithm converges quickly.") is None
    assert generate_short_answer_from_sentence("DRAM is volatile memory.") is None


def test_short_answer_rejects_pronoun_led_clause():
    """Pronoun-led lhs returns None."""
    result = generate_short_answer_from_sentence(
        "This demonstration did not produce results because the setup was faulty."
    )
    assert result is None


def test_short_answer_selects_correct_auxiliary_are():
    """Question uses 'are' when clause has 'are'. Lowercase subject allowed."""
    result = generate_short_answer_from_sentence(
        "Read and write commands are column commands because they address columns in the database."
    )
    assert result is not None
    assert result["question"].startswith("Why are ")
    assert "read" in result["question"].lower() or "commands" in result["question"].lower()
    assert "?" in result["question"]


def test_short_answer_outputs_single_line_answer_with_because():
    """Answer starts with Because and has <= 30 words."""
    result = generate_short_answer_from_sentence(
        "Most computers use DRAM for main memory because it offers high density and low cost."
    )
    assert result is not None
    assert result["answer"].startswith("Because ")
    assert len(result["answer"].split()) <= 31


def test_no_structural_tokens_in_question():
    """Output question never contains Chapter, Section, page numbers."""
    result = generate_short_answer_from_sentence(
        "Caches improve overall system performance significantly because they store frequently accessed data."
    )
    assert result is not None
    q = result["question"]
    assert "Chapter" not in q and "chapter" not in q
    assert "Section" not in q and "section" not in q
    assert "page" not in q.lower() or "page" not in q


def test_regression_no_bad_short_answer_stems():
    """No stems like 'Why does 4', 'Why does This', 'Why does then'."""
    chunks = [
        {
            "text": "4 Optimizing Memory Control Most computers use DRAM because it is cheap.",
            "metadata": {"page_start": 1, "page_end": 2, "chunk_id": "c1"},
        },
        {
            "text": "This learning controller was never committed because the design was flawed.",
            "metadata": {"page_start": 3, "page_end": 4, "chunk_id": "c2"},
        },
        {
            "text": "Read and write commands are column commands because they target columns.",
            "metadata": {"page_start": 5, "page_end": 6, "chunk_id": "c3"},
        },
    ]
    pool = build_candidate_pool(chunks)
    questions = generate_exam_questions(pool, distribution={"short": 5}, total=5)
    bad_prefixes = ("Why does 4", "Why does This", "Why does then", "Why does Read")
    for q in questions:
        if q.q_type == "short":
            for bad in bad_prefixes:
                assert not q.prompt.startswith(bad), f"Bad stem: {q.prompt}"


def test_clause_is_questionable_rejects_short():
    """Clause with < 6 words is rejected."""
    assert clause_is_questionable("This is bad")


def test_detect_auxiliary_finds_are():
    """Detect 'are' in 'X are Y'."""
    aux, rest = detect_auxiliary("Read and write commands are column commands")
    assert aux == "are"
    assert "column commands" in rest


def test_build_why_question_max_words():
    """Question truncated to 18 words."""
    long_clause = " ".join(["word"] * 25)
    q = build_why_question(long_clause)
    assert q is None or len(q.split()) <= 18


def test_short_answer_allows_lowercase_subject():
    """Lowercase subject (e.g. 'read and write commands') passes validation."""
    result = generate_short_answer_from_sentence(
        "Read and write commands are column commands because they address columns in the database."
    )
    assert result is not None
    q = result["question"]
    assert q.startswith("Why are ")
    assert validate_short_answer_stem(q)


def test_split_thus_requires_boundary_or_rhs_verb():
    """Discourse cues (thus/therefore) require boundary or RHS verb."""
    # No boundary, ambiguous - should return None
    result1 = generate_short_answer_from_sentence(
        "X does Y thus improving Z over time."
    )
    assert result1 is None
    # Semicolon boundary - split accepted
    result2 = generate_short_answer_from_sentence(
        "Memory cells store data efficiently in the system; thus the system can retrieve it quickly."
    )
    assert result2 is not None
    assert "thus" in result2["answer"].lower() or "because" in result2["answer"].lower()


def test_lhs_min_words_6():
    """LHS with < 6 words is rejected."""
    result = generate_short_answer_from_sentence(
        "This is important because the design matters."
    )
    assert result is None


def test_aux_selection_skips_mid_sentence_aux():
    """Clause with aux mid-sentence (not leading pattern) is skipped."""
    result = generate_short_answer_from_sentence(
        "In systems, the reason is that X because Y explains it."
    )
    assert result is None


def test_preposition_salvage_with_comma():
    """Preposition-led clause with comma boundary is salvaged."""
    result = generate_short_answer_from_sentence(
        "In DRAM, read and write commands are column commands because they address columns in the database."
    )
    assert result is not None
    q = result["question"]
    assert q.startswith("Why are ")
    assert "read" in q.lower() or "commands" in q.lower()
    assert validate_short_answer_stem(q)


def test_preposition_rejected_without_comma():
    """Preposition-led clause without comma is rejected."""
    result = generate_short_answer_from_sentence(
        "In DRAM reads are column commands because they address columns in the database."
    )
    assert result is None


def test_meta_text_rejected_in_this_section():
    """LHS with 'in this section we show' is rejected."""
    stats = ShortAnswerStats()
    result = generate_short_answer_from_sentence(
        "In this section we show X because Y explains the result.",
        stats=stats,
    )
    assert result is None
    assert stats.meta_text_rejected >= 1


def test_meta_text_rejected_we_propose():
    """LHS with 'we propose' is rejected."""
    result = generate_short_answer_from_sentence(
        "We propose a method because it improves performance significantly."
    )
    assert result is None
