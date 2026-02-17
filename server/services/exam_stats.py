"""
Privacy-safe aggregate counters for exam question generation.

No text stored or logged. Counters only. Used when DEBUG_EXAMS or DEBUG_ARTIFACTS enabled.
"""

from dataclasses import dataclass, field, fields
from typing import Any, Dict, Optional, Type

from server.services.exam_short_answer import ShortAnswerStats


@dataclass
class DefinitionStats:
    """Counters for definition question generation. No text fields."""

    seen_sentences: int = 0
    matched_explicit_pattern: int = 0
    extracted_term_candidate: int = 0
    rejected_bad_first_token: int = 0
    rejected_structural: int = 0
    rejected_length: int = 0
    rejected_ocr_junk: int = 0
    rejected_numeric_overload: int = 0
    rejected_meta_text: int = 0
    rejected_validation: int = 0
    emitted: int = 0
    local_llm_attempted: int = 0
    local_llm_success: int = 0
    local_llm_changed_term: int = 0
    local_llm_invalid_json: int = 0
    local_llm_invalid_schema: int = 0
    local_llm_timeout: int = 0
    local_llm_fallback_used: int = 0


@dataclass
class FillBlankStats:
    """Counters for fill-in-the-blank generation. No text fields."""

    seen_sentences: int = 0
    phrase_candidates: int = 0
    rejected_stopword_phrase: int = 0
    rejected_numeric_phrase: int = 0
    rejected_bad_span: int = 0
    rejected_passive_break: int = 0
    rejected_generic_phrase: int = 0
    rejected_validation: int = 0
    emitted: int = 0
    local_llm_attempted: int = 0
    local_llm_success: int = 0
    local_llm_changed_prompt: int = 0
    local_llm_invalid_json: int = 0
    local_llm_invalid_schema: int = 0
    local_llm_timeout: int = 0
    local_llm_fallback_used: int = 0


@dataclass
class ExamArtifactStats:
    """Aggregator for all exam stats. to_log_dict returns plain ints only."""

    definition: DefinitionStats = field(default_factory=DefinitionStats)
    fill_blank: FillBlankStats = field(default_factory=FillBlankStats)
    short_answer: ShortAnswerStats = field(default_factory=ShortAnswerStats)

    def to_log_dict(self) -> Dict[str, int]:
        """Return flat dict of ints for logging. No text."""
        out: Dict[str, int] = {}
        for name, obj in [
            ("def", self.definition),
            ("fib", self.fill_blank),
            ("short", self.short_answer),
        ]:
            for f in fields(obj):
                if isinstance(getattr(obj, f.name), int):
                    out[f"{name}_{f.name}"] = getattr(obj, f.name)
        return out


def _all_fields_int_or_nested(obj: Any) -> bool:
    """Recursively check all fields are int or nested stats dataclasses. No str/text."""
    for f in fields(obj):
        val = getattr(obj, f.name)
        if isinstance(val, int):
            continue
        if hasattr(val, "__dataclass_fields__"):
            if not _all_fields_int_or_nested(val):
                return False
            continue
        return False
    return True
