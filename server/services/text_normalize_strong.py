"""
Strong text normalization for PDF extraction artifacts.

Applied before candidate pooling, term extraction, and summary selection.
Removes hyphenated line breaks, ligatures, weird glyphs, and math-heavy content.
"""

import os
import re
import unicodedata
from typing import Set

# Ligatures: Unicode -> ASCII
_LIGATURES = {
    "\ufb00": "ff",
    "\ufb01": "fi",
    "\ufb02": "fl",
    "\ufb03": "ffi",
    "\ufb04": "ffl",
}

# PDF weird "f" artifact (Sutton/Barto di↵erent) - U+21B5
_PDF_WEIRD_F = "\u21b5"

# Arrows and directionals to remove
_ARROWS = frozenset("\u2190\u2192\u21d4\u21d0\u21d2\u21b5\u21b1\u21b2\u21b3\u21b4")

# Replacement character
_REPLACEMENT_CHAR = "\ufffd"

# Greek letters for math detection
_GREEK = frozenset("αβγδλμσπθωΔΣΠΛΓ")

# Math operators
_MATH_OPS = frozenset("=<>±×÷∑∫√^_{}[]()")


def normalize_unicode_basics(s: str) -> str:
    """
    Apply Unicode normalization, replace ligatures, fix PDF artifacts, remove arrows.
    """
    if not s or not isinstance(s, str):
        return ""
    s = unicodedata.normalize("NFKC", s)
    for lig, repl in _LIGATURES.items():
        s = s.replace(lig, repl)
    s = s.replace(_REPLACEMENT_CHAR, "")
    s = re.sub(r"([A-Za-z])" + re.escape(_PDF_WEIRD_F) + r"([A-Za-z])", r"\1f\2", s)
    for a in _ARROWS:
        s = s.replace(a, "")
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def repair_hyphenated_linebreaks(s: str, max_passes: int = 2) -> str:
    """
    Merge hyphenated line-break artifacts like "af- terposition" -> "afterposition".
    Skips TitleCase pairs, digits, and very long merges.
    """
    if not s or not isinstance(s, str):
        return ""
    for _ in range(max_passes):
        def _repl(m):
            left, right = m.group(1), m.group(2)
            if any(c.isdigit() for c in left + right):
                return m.group(0)
            if left[0].isupper() and right[0].isupper():
                return m.group(0)
            merged = left + right
            if len(merged) > 25:
                return m.group(0)
            return merged
        prev = s
        s = re.sub(r"([A-Za-z]{2,})-\s+([A-Za-z]{2,})", _repl, s)
        if s == prev:
            break
    return s


def strip_inline_garbage(s: str) -> str:
    """
    Remove repeated punctuation, stray commas, double spaces, isolated OCR noise.
    """
    if not s or not isinstance(s, str):
        return ""
    s = re.sub(r"\.{3,}", " ", s)
    s = re.sub(r"[,;]\s*[,;]+", ",", s)
    s = re.sub(r"\s{2,}", " ", s)
    s = re.sub(r"^\s*[•]\s*$", "", s, flags=re.M)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def math_density(s: str) -> float:
    """
    Return ratio of mathy tokens. mathy = contains digits, operators, greek, or LaTeX.
    """
    if not s or not isinstance(s, str):
        return 0.0
    tokens = s.split()
    if not tokens:
        return 0.0
    mathy = 0
    for t in tokens:
        if any(c.isdigit() for c in t):
            mathy += 1
            continue
        if any(c in _MATH_OPS for c in t):
            mathy += 1
            continue
        if any(c in _GREEK for c in t):
            mathy += 1
            continue
        if "\\" in t and re.search(r"\\[a-zA-Z]", t):
            mathy += 1
    return mathy / max(len(tokens), 1)


def is_math_heavy(s: str, threshold: float = 0.30) -> bool:
    """
    True if math_density >= threshold, or > 2 equation operators, or equation label.
    """
    if not s or not isinstance(s, str):
        return False
    if math_density(s) >= threshold:
        return True
    op_count = sum(1 for c in s if c in _MATH_OPS)
    if op_count > 2:
        return True
    if re.search(r"\(\d+\.\d+\)", s) and op_count >= 1:
        return True
    return False


def normalize_text_strong(s: str) -> str:
    """
    Full pipeline: unicode -> hyphen repair -> strip garbage.
    """
    if not s or not isinstance(s, str):
        return ""
    s = normalize_unicode_basics(s)
    s = repair_hyphenated_linebreaks(s)
    s = strip_inline_garbage(s)
    return s


def _strong_normalize_enabled() -> bool:
    """Read config from env. Default True."""
    v = os.environ.get("STRONG_NORMALIZE_ENABLED", "1")
    return v.lower() not in ("0", "false", "no")


def _math_heavy_threshold() -> float:
    """Read config from env. Default 0.30."""
    try:
        return float(os.environ.get("MATH_HEAVY_THRESHOLD", "0.30"))
    except ValueError:
        return 0.30


def _dedupe_jaccard() -> float:
    """Read config from env. Default 0.92."""
    try:
        return float(os.environ.get("DEDUPE_NEAR_JACCARD", "0.92"))
    except ValueError:
        return 0.92


def normalize_for_study_artifacts(s: str) -> str:
    """Apply strong normalization when enabled. Idempotent passthrough when disabled."""
    if not _strong_normalize_enabled():
        return s
    return normalize_text_strong(s)
