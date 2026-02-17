"""
Sentence-level deduplication for study artifacts.

Removes exact and near-duplicate sentences (paragraph + bullet repeats).
Meaning-preserving guardrails: do not near-dedupe when flip tokens conflict
(negation, increase/decrease, max/min, etc.).
Deterministic, no embeddings.
"""

import re
from typing import Dict, List, Optional, Set

from server.services.text_normalize_strong import (
    math_density,
    normalize_for_study_artifacts,
    normalize_text_strong,
)

# Light stopwords for dedupe normalization (optional)
_DEDUPE_STOPWORDS = frozenset(
    "a an the and or but in on at to for of with by".split()
)

# Flip-token vocabularies for meaning-preserving guardrails
_NEG = frozenset(
    "not no never none neither without cannot can't won't isn't aren't "
    "doesn't don't didn't".split()
)
_INC = frozenset(
    "increase increases increased increasing rise rises rising grow grows growing "
    "higher more greater larger maximize maximizes maximum max".split()
)
_DEC = frozenset(
    "decrease decreases decreased decreasing drop drops dropping lower less "
    "smaller minimize minimizes minimum min fewer".split()
)
_ABS_ALWAYS = frozenset("always all every must".split())
_ABS_NEVER = frozenset("never none cannot can't won't".split())


def tokenize_for_flip_check(s: str) -> List[str]:
    """
    Tokenize for flip-signature check. Lowercases, strips edge punctuation,
    keeps internal apostrophes. Runs normalize_text_strong first. No stopword removal.
    """
    if not s or not isinstance(s, str):
        return []
    s = normalize_text_strong(s)
    s = s.lower()
    tokens = []
    for t in s.split():
        t = re.sub(r"^[^\w']+|[^\w']+$", "", t)
        if t:
            tokens.append(t)
    return tokens


def contains_any(tokens: Set[str], vocab: Set[str]) -> bool:
    """True if any token is in vocab."""
    return bool(tokens & vocab)


def flip_signature(s: str) -> Dict[str, bool]:
    """
    Return a small signature dict indicating presence of flip tokens.
    Used to avoid near-deduping semantically opposite sentences.
    """
    tokens = set(tokenize_for_flip_check(s))
    return {
        "negation": contains_any(tokens, _NEG),
        "increase": contains_any(tokens, _INC),
        "decrease": contains_any(tokens, _DEC),
        "greater": contains_any(tokens, {"greater", "larger"}),
        "less": contains_any(tokens, {"less", "smaller"}),
        "max": contains_any(tokens, {"max", "maximum", "maximize", "maximizes"}),
        "min": contains_any(tokens, {"min", "minimum", "minimize", "minimizes"}),
        "higher": contains_any(tokens, {"higher"}),
        "lower": contains_any(tokens, {"lower"}),
        "more": contains_any(tokens, {"more"}),
        "fewer": contains_any(tokens, {"fewer"}),
        "always": contains_any(tokens, _ABS_ALWAYS),
        "never": contains_any(tokens, _ABS_NEVER),
    }


def flip_conflict(sig_a: Dict[str, bool], sig_b: Dict[str, bool]) -> bool:
    """
    True if the two signatures indicate semantic opposition.
    Only triggers when one side has a token and the other has an opposing token.
    """
    if sig_a["negation"] != sig_b["negation"]:
        return True
    if (sig_a["increase"] and sig_b["decrease"]) or (sig_a["decrease"] and sig_b["increase"]):
        return True
    if (sig_a["max"] and sig_b["min"]) or (sig_a["min"] and sig_b["max"]):
        return True
    if (sig_a["higher"] and sig_b["lower"]) or (sig_a["lower"] and sig_b["higher"]):
        return True
    if (sig_a["more"] and sig_b["less"]) or (sig_a["less"] and sig_b["more"]):
        return True
    if (sig_a["more"] and sig_b["fewer"]) or (sig_a["fewer"] and sig_b["more"]):
        return True
    if (sig_a["greater"] and sig_b["less"]) or (sig_a["less"] and sig_b["greater"]):
        return True
    if (sig_a["always"] and sig_b["never"]) or (sig_a["never"] and sig_b["always"]):
        return True
    return False


def should_near_dedupe(a: str, b: str, jaccard: float, threshold: float) -> bool:
    """
    True if we may near-dedupe (collapse) a and b.
    False if jaccard < threshold or if flip_conflict indicates semantic opposition.
    """
    if jaccard < threshold:
        return False
    if flip_conflict(flip_signature(a), flip_signature(b)):
        return False
    return True


def normalize_for_dedupe(s: str, remove_stopwords: bool = False) -> str:
    """
    Normalize for dedupe: lowercase, strip punctuation, collapse spaces.
    Applies strong normalization first when enabled.
    """
    if not s or not isinstance(s, str):
        return ""
    s = normalize_for_study_artifacts(s)
    s = s.lower()
    s = re.sub(r"[^\w\s']", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if remove_stopwords:
        tokens = [t for t in s.split() if t not in _DEDUPE_STOPWORDS]
        s = " ".join(tokens)
    return s


def _token_set(s: str) -> set:
    """Token set for Jaccard."""
    norm = normalize_for_dedupe(s)
    return set(norm.split()) if norm else set()


def _jaccard(a: set, b: set) -> float:
    """Jaccard similarity of two sets."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _cleaner_score(s: str) -> tuple:
    """
    Heuristic: prefer cleaner sentence. Lower is better.
    (fewer non-ascii, lower math_density, reasonable length)
    """
    non_ascii = sum(1 for c in s if ord(c) > 127)
    m = math_density(s)
    ln = len(s)
    return (non_ascii, m, -min(ln, 200))


def _dedupe_jaccard_default() -> float:
    import os
    try:
        return float(os.environ.get("DEDUPE_NEAR_JACCARD", "0.92"))
    except ValueError:
        return 0.92


def dedupe_sentences(
    sentences: List[str],
    *,
    near_dupe_jaccard: Optional[float] = None,
) -> List[str]:
    """
    Exact + near dedupe. Preserves order. Keeps earlier/cleaner of duplicates.
    """
    if near_dupe_jaccard is None:
        near_dupe_jaccard = _dedupe_jaccard_default()
    if not sentences:
        return []
    seen_hashes: set = set()
    result: List[str] = []
    for s in sentences:
        s = s.strip()
        if not s:
            continue
        norm = normalize_for_dedupe(s)
        if not norm:
            continue
        h = hash(norm)
        if h in seen_hashes:
            continue
        duped = False
        for i, kept in enumerate(result):
            kept_norm = normalize_for_dedupe(kept)
            if not kept_norm:
                continue
            j = _jaccard(_token_set(s), _token_set(kept))
            if j >= near_dupe_jaccard and should_near_dedupe(s, kept, j, near_dupe_jaccard):
                if _cleaner_score(s) < _cleaner_score(kept):
                    result[i] = s
                    seen_hashes.discard(hash(kept_norm))
                    seen_hashes.add(h)
                duped = True
                break
        if not duped:
            seen_hashes.add(h)
            result.append(s)
    return result
