"""
Deterministic heuristics to detect TOC/index/structural-only chunks.

Used to filter or down-rank structural chunks before answer composition,
so summary-style answers use explanatory content instead of TOC dumps.
"""

import re
from typing import List, Tuple


def is_structural_chunk(text: str, strict: bool = False) -> bool:
    """
    Return True if chunk appears to be TOC/index/structural-only (no explanatory content).

    A chunk is structural if 2+ of these heuristics are true:
    - Dotted leader density (.... or . . .) > 3 occurrences
    - Lines ending with page numbers: >30% of non-empty lines
    - High numeric density: digits / total chars > 0.12
    - Very low avg sentence length with many short fragments

    Conservative: only flags clear TOC/index chunks. Avoids over-filtering bullet lists.

    Args:
        text: Chunk text to evaluate.
        strict: If True (summary-type questions), require 2+ sentences and avg > 10 words
                to NOT be structural. Used for stricter filtering.
    """
    if not text or not text.strip():
        return True  # Empty is not useful

    text = text.strip()
    hits = 0

    # 1. Dotted leader density: "...." or " . . ." more than 3 occurrences
    dotted = len(re.findall(r"\.{4,}|\.\s+\.\s+\.", text))
    if dotted > 3:
        hits += 1

    # 2. Lines ending with page numbers: >30% of non-empty lines match
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if lines:
        page_end = re.compile(r".\s*\d+$|\s\d{1,4}$")
        page_lines = sum(1 for ln in lines if page_end.search(ln))
        if page_lines / len(lines) > 0.30:
            hits += 1

    # 3. High numeric density: digits / total chars > 0.12
    total_chars = len(text.replace(" ", "").replace("\n", "")) or 1
    digit_count = sum(1 for c in text if c.isdigit())
    if digit_count / total_chars > 0.12:
        hits += 1

    # 4. Very low avg sentence length and many short fragments
    sentences = [s.strip() for s in re.split(r"[.!?]+", text) if s.strip()]
    if sentences:
        words_per_sent = [len(s.split()) for s in sentences]
        avg_words = sum(words_per_sent) / len(words_per_sent)
        short_lines = sum(1 for ln in lines if len(ln.split()) < 6)
        if avg_words < 8 and short_lines >= max(2, len(lines) * 0.4):
            hits += 1

    if hits >= 2:
        return True

    # Strict mode (summary-type): prefer chunks with 2+ sentences and avg > 10 words
    if strict and sentences:
        avg_words = sum(len(s.split()) for s in sentences) / len(sentences)
        if len(sentences) < 2 or avg_words < 10:
            return True

    return False


def is_summary_type_question(question: str) -> bool:
    """Return True if question asks for summary/overview/key points."""
    q = question.lower().strip()
    keywords = [
        "summary",
        "summarize",
        "overview",
        "main ideas",
        "key points",
        "explain the chapter",
        "chapter summary",
        "brief summary",
        "give me a summary",
        "10-bullet",
        "bullet summary",
    ]
    return any(kw in q for kw in keywords)


def partition_chunks(
    chunks: List[dict],
    question: str,
) -> Tuple[List[dict], List[dict]]:
    """
    Partition retrieved chunks into explanatory vs structural.

    Returns:
        (explanatory_chunks, structural_chunks)
    """
    strict = is_summary_type_question(question)
    explanatory = []
    structural = []

    for ch in chunks:
        text = ch.get("text", "")
        meta = ch.get("metadata", ch)
        if isinstance(meta, dict):
            pass
        else:
            meta = {}
        # Allow text in metadata for alternate shapes
        if not text and isinstance(ch, dict):
            text = meta.get("text", "")
        if is_structural_chunk(text, strict=strict):
            structural.append(ch)
        else:
            explanatory.append(ch)

    return explanatory, structural
