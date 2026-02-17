"""
Strict stem validation for practice exam questions.

Hard rejects malformed prompts like "What is This?" or "What is because it?".
Deterministic, LLM-free.
"""

import re
from typing import List

# Determiners: reject terms starting with these
_DETERMINERS = frozenset("a an the any this that these those some each".split())

# Discourse markers: reject terms starting with these
_DISCOURSE_MARKERS = frozenset(
    "then thus however therefore because if but so also".split()
)

# Pronouns: reject terms starting with these
_PRONOUNS = frozenset(
    "it they we you he she i them us his her their its".split()
)

# Combined: first token must not be in any of these
_TERM_FIRST_TOKEN_REJECT = _DETERMINERS | _DISCOURSE_MARKERS | _PRONOUNS

# Stopwords that must not begin/end stems or terms (legacy + extended)
_STEM_STOPWORDS = frozenset(
    "a an the this that it because if but of to for with by from as is was are were "
    "been be have has had do does did will would could should may might must can "
    "shall its any then thus however therefore some each they we you he she i".split()
)

# Structural tokens: reject if term contains any
_STRUCTURAL_TOKENS = frozenset(
    "chapter section figure table appendix references bibliography".split()
)

# Verbs in term: reject if term contains these
_VERB_TOKENS = frozenset("is are was were be been being".split())

# Weird OCR / structural patterns
_BAD_PATTERNS = (
    r"\.\.+",
    r"[;:]",
    r"  +",
    r"chapter\s+\d+",
    r"figure\s+\d+",
    r"table\s+\d+",
    r"page\s+\d+",
    r"\d+\s*$",
    r"pp\.\s*\d+",
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
    Rejects determiners, discourse markers, pronouns, mid-clause fragments.
    """
    if not term or not isinstance(term, str):
        return False
    term = term.strip()
    if len(term) < 4:
        return False
    tokens = _alphabetic_tokens(term)
    # token_count must be 2..6
    if len(tokens) < 2 or len(tokens) > 6:
        return False
    # must contain at least one alphabetic token length >= 3
    if not any(len(t) >= 3 for t in tokens):
        return False
    first = tokens[0].lower() if tokens else ""
    last = tokens[-1].lower() if tokens else ""
    # reject if first token is determiner, discourse marker, or pronoun
    if first in _TERM_FIRST_TOKEN_REJECT:
        return False
    if first in _STEM_STOPWORDS or last in _STEM_STOPWORDS:
        return False
    if len(tokens[0]) == 1 or (len(tokens[0]) == 2 and tokens[0].lower() in ("s", "a", "i")):
        return False
    # reject bad chars/patterns
    if _BAD_RE.search(term):
        return False
    if ".." in term or "  " in term or ";" in term or ":" in term:
        return False
    lower = term.lower()
    token_set = set(t.lower() for t in tokens)
    # reject structural tokens
    if token_set & _STRUCTURAL_TOKENS:
        return False
    if any(w in lower for w in ("chapter", "figure", "table", "page")):
        return False
    # reject if term contains verbs
    if token_set & _VERB_TOKENS:
        return False
    if term.endswith(("ed", "ing")) and len(term) < 12:
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
