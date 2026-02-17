"""
Strict stem validation for practice exam questions.

Hard rejects malformed prompts like "What is This?" or "What is because it?".
Deterministic, LLM-free.
"""

import re
from typing import List

# Stopwords that must not begin/end stems or terms
_STEM_STOPWORDS = frozenset(
    "a an the this that it because if but of to for with by from as is was are were "
    "been be have has had do does did will would could should may might must can "
    "shall its".split()
)

# Common verb suffixes (simple heuristic)
_VERB_SUFFIXES = ("ed", "ing", "es", "s")

# Weird OCR / structural patterns
_BAD_PATTERNS = (
    r"\.\.+",           # ellipsis / OCR junk
    r"chapter\s+\d+",
    r"figure\s+\d+",
    r"table\s+\d+",
    r"page\s+\d+",
    r"\d+\s*$",         # trailing page number
)
_BAD_RE = re.compile("|".join(f"({p})" for p in _BAD_PATTERNS), re.I)


def _alphabetic_tokens(s: str) -> List[str]:
    """Return list of alphabetic tokens (letters only)."""
    return re.findall(r"[a-zA-Z]+", s)


def _token_count(s: str) -> int:
    """Count of alphabetic tokens."""
    return len(_alphabetic_tokens(s))


def validate_definition_term(term: str) -> bool:
    """
    Validate a definition term (e.g. "X" in "What is X?").
    Returns False if term should be rejected.
    """
    if not term or not isinstance(term, str):
        return False
    term = term.strip()
    if len(term) < 4:
        return False
    tokens = _alphabetic_tokens(term)
    if len(tokens) < 2:
        return False
    if len(tokens) < 3 and len(term) < 10:
        return False
    first = tokens[0].lower() if tokens else ""
    last = tokens[-1].lower() if tokens else ""
    if first in _STEM_STOPWORDS or last in _STEM_STOPWORDS:
        return False
    if len(tokens[0]) == 1 or (len(tokens[0]) == 2 and tokens[0].lower() in ("s", "a", "i")):
        return False
    if _BAD_RE.search(term):
        return False
    if ".." in term or "  " in term:
        return False
    lower = term.lower()
    if any(w in lower for w in ("chapter", "figure", "table", "page")):
        return False
    if term.endswith(("ed", "ing")) and len(term) < 12:
        return False
    if any(w in ("is", "are", "was", "were") for w in tokens):
        return False
    return True


def validate_question_stem(stem: str) -> bool:
    """
    Validate a question stem (e.g. "What is X?" or "Why does Y occur?").
    Returns False if stem should be rejected.
    """
    if not stem or not isinstance(stem, str):
        return False
    stem = stem.strip()
    tokens = _alphabetic_tokens(stem)
    if len(tokens) < 4:
        return False
    first = tokens[0].lower() if tokens else ""
    last = tokens[-1].lower() if tokens else ""
    if first in _STEM_STOPWORDS or last in _STEM_STOPWORDS:
        return False
    if _BAD_RE.search(stem):
        return False
    if ".." in stem or "  " in stem:
        return False
    lower = stem.lower()
    if any(w in lower for w in ("chapter", "figure", "table", "page")):
        return False
    return True
