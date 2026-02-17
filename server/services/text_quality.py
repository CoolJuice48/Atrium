"""
Shared text quality filters for summaries and practice exams.

Deterministic, LLM-free. Used by both summary_compose and exam generation.
"""

import re
from typing import List

# Stopwords for content_ratio and stem validation
_STOPWORDS = frozenset(
    "a an the and or but in on at to for of with by from as is was are were been be "
    "have has had do does did will would could should may might must can shall "
    "this that these those it its".split()
)

# Structural prefixes (hard reject)
_STRUCTURAL_PREFIXES = (
    "chapter", "section", "figure", "table", "appendix", "contents",
    "references", "bibliography", "index",
)

# Exercise/prompt patterns (hard reject)
_EXERCISE_PATTERNS = (
    "true or false", "fill in the blank", "choose", "prove that", "derive",
    "exercise", "problem", "solution", "multiple choice",
)

# Reference-like patterns
_REFERENCE_PATTERNS = (
    r"technical report", r"university", r"journal", r"proceedings",
    r"\(\d{4}\)", r"pp\.\s*\d", r"vol\.\s*\d", r"no\.\s*\d",
)


def normalize_ws(s: str) -> str:
    """Normalize whitespace: collapse spaces, strip."""
    if not s:
        return ""
    return re.sub(r"\s+", " ", s.strip())


def split_sentences_robust(text: str) -> List[str]:
    """Use improved splitter from summary_compose."""
    from server.services.summary_compose import split_sentences
    return split_sentences(text)


def is_structural_noise(s: str) -> bool:
    """Hard reject: headings, TOC, structural labels."""
    if not s or len(s.strip()) < 10:
        return True
    lower = s.strip().lower()
    for prefix in _STRUCTURAL_PREFIXES:
        if lower.startswith(prefix + " ") or lower.startswith(prefix + ":"):
            return True
    if re.search(r"\bchapter\s+\d+|\bsection\s+\d+|\bfigure\s+\d+|\btable\s+\d+", lower):
        return True
    return False


def is_exercise_prompt(s: str) -> bool:
    """Hard reject: exercise instructions, problem prompts."""
    if not s:
        return True
    lower = s.strip().lower()
    for pat in _EXERCISE_PATTERNS:
        if pat in lower:
            return True
    if re.search(r"exercise\s+\d+|problem\s+\d+", lower):
        return True
    return False


def is_reference_line(s: str) -> bool:
    """Hard reject: citation/reference lines, bibliography."""
    if not s or len(s.strip()) < 15:
        return False
    lower = s.strip().lower()
    for pat in _REFERENCE_PATTERNS:
        if re.search(pat, lower, re.I):
            return True
    comma_count = s.count(",")
    if comma_count >= 4 and len(s.split()) < 15:
        return True
    if re.search(r"\d{4}\s*[,.]", s) and len(re.findall(r"\d{4}", s)) >= 2:
        return True
    return False


def content_ratio(s: str) -> float:
    """Content tokens / total tokens. Excludes stopwords from content."""
    if not s:
        return 0.0
    tokens = re.findall(r"[a-zA-Z]+", s.lower())
    if not tokens:
        return 0.0
    content = sum(1 for t in tokens if t not in _STOPWORDS and len(t) > 1)
    return content / len(tokens)


def _numeric_overload(s: str) -> bool:
    """Too many digits."""
    clean = s.replace(" ", "").replace("\n", "")
    if not clean:
        return False
    digit_count = sum(1 for c in clean if c.isdigit())
    return digit_count / len(clean) > 0.12


def _too_short(s: str, min_words: int = 8) -> bool:
    """Too short unless definition cue."""
    words = s.split()
    if len(words) >= min_words:
        return False
    def_cues = ("is defined as", "refers to", "means", "is called", "consists of")
    return not any(cue in s.lower() for cue in def_cues)


def passes_quality_filters(s: str) -> bool:
    """
    Combined quality check for exam candidates.
    Returns False if sentence should be rejected.
    """
    s = normalize_ws(s)
    if not s or len(s) < 20:
        return False
    if is_structural_noise(s):
        return False
    if is_exercise_prompt(s):
        return False
    if is_reference_line(s):
        return False
    if _numeric_overload(s):
        return False
    if content_ratio(s) <= 0.6:
        return False
    if _too_short(s):
        return False
    return True
