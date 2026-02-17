"""
Build a clean candidate sentence pool from scoped chunks for practice exam generation.

Deterministic, LLM-free. Uses text_quality filters and score_hint for prioritization.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List

from server.services.text_quality import (
    normalize_ws,
    passes_quality_filters,
    split_sentences_robust,
)


@dataclass
class Candidate:
    """Single candidate sentence with metadata."""
    text: str
    chunk_id: str
    page_start: Any
    page_end: Any
    score_hint: int


@dataclass
class CandidatePool:
    """Pool of filtered, scored candidate sentences."""
    candidates: List[Candidate] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.candidates)


# Definition cues: +2
_DEF_CUES = ("is defined as", "refers to", "means", "is called", "consists of")

# Causal/contrast cues: +1
_CAUSAL_CUES = ("therefore", "however", "because", "thus", "hence", "consequently")

# Penalty patterns: -2
_PENALTY_PATTERNS = ("figure", "table", "chapter")


def _score_hint(text: str) -> int:
    """Simple deterministic score. Higher = better candidate."""
    lower = text.lower()
    score = 0
    for cue in _DEF_CUES:
        if cue in lower:
            score += 2
            break
    for cue in _CAUSAL_CUES:
        if cue in lower:
            score += 1
            break
    for pat in _PENALTY_PATTERNS:
        if pat in lower:
            score -= 2
            break
    digit_count = sum(1 for c in text if c.isdigit())
    if digit_count > 2:
        score -= 2
    return score


def _normalize_chunk_id(chunk: Dict[str, Any]) -> str:
    """Stable chunk identifier."""
    meta = chunk.get("metadata", chunk)
    cid = meta.get("chunk_id", chunk.get("chunk_id", ""))
    if cid:
        return cid
    book = meta.get("book_id", meta.get("book", meta.get("book_name", "")))
    ch = str(meta.get("chapter", meta.get("chapter_number", "")))
    sec = str(meta.get("section", meta.get("section_number", "")))
    idx = meta.get("chunk_index", 0)
    return f"{book}|ch{ch}|sec{sec}|i{idx}"


def build_candidate_pool(
    chunks: List[Dict[str, Any]],
    *,
    max_sentences: int = 4000,
) -> CandidatePool:
    """
    Build candidate pool from already-scoped chunks.
    Splits into sentences, applies quality filters, scores, and caps.
    """
    candidates: List[Candidate] = []
    for chunk in chunks:
        text = chunk.get("text", "")
        if not text or not isinstance(text, str):
            continue
        meta = chunk.get("metadata", chunk)
        chunk_id = _normalize_chunk_id(chunk)
        page_start = meta.get("page_start", chunk.get("page_start"))
        page_end = meta.get("page_end", chunk.get("page_end"))

        for sent in split_sentences_robust(text):
            sent = normalize_ws(sent)
            if not passes_quality_filters(sent):
                continue
            score = _score_hint(sent)
            candidates.append(Candidate(
                text=sent,
                chunk_id=chunk_id,
                page_start=page_start,
                page_end=page_end,
                score_hint=score,
            ))

    if len(candidates) <= max_sentences:
        return CandidatePool(candidates=candidates)

    sorted_candidates = sorted(candidates, key=lambda c: (-c.score_hint, c.text))
    return CandidatePool(candidates=sorted_candidates[:max_sentences])
