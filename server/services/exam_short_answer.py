"""
Grammar-aware short-answer question generation.

Only produces "Why ...?" questions when the source sentence has explicit
causal/explanatory structure. Rejects pronoun-led fragments and structural bleed.
"""

import re
from dataclasses import dataclass
from typing import Optional, Tuple

from server.services.exam_stems import validate_short_answer_stem
from server.services.text_quality import content_ratio

# Prepositions for strip_leading_prep_phrase (comma-boundary salvage)
_PREPOSITIONS = frozenset(
    "in on at for with within under over during after before from to by as".split()
)

# Strong causal cues: split anywhere (except first 2 tokens)
_STRONG_CAUSAL_CUES = ("because", "due to", "since", "so that")
# Discourse-result cues: only split with boundary or RHS verb
_DISCOURSE_CUES = ("as a result", "therefore", "thus")
# All cues for detection (strong first, then discourse)
_CAUSAL_CUES = _STRONG_CAUSAL_CUES + _DISCOURSE_CUES

# Verb-like tokens for RHS check and has_verb detection
_RHS_VERB_LIKE = frozenset(
    "is are was were has have had can could will would may might must "
    "do does did shall should use uses used improve improves store stores "
    "offer offers address addresses provide enables allow allows".split()
)

# Reject clause if starts with these
_CLAUSE_FIRST_REJECT = frozenset(
    "this that these those it they we he she i any then thus however "
    "therefore because if but so also".split()
)

# Structural tokens
_STRUCTURAL_TOKENS = frozenset(
    "chapter section figure table appendix references bibliography".split()
)

# Auxiliary verbs for detect_auxiliary
_AUX_VERBS = frozenset(
    "is are was were has have can could will would should may might must do does did".split()
)


def _normalize_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip()) if s else ""


def strip_leading_prep_phrase(clause: str, max_chars: int = 40) -> str:
    """
    If clause starts with preposition AND contains comma within first max_chars,
    strip prefix up to and including the comma. Else return clause unchanged.
    """
    if not clause:
        return clause
    clause = _normalize_ws(clause)
    lower = clause.lower()
    first_word = lower.split()[0] if lower.split() else ""
    if first_word not in _PREPOSITIONS:
        return clause
    comma_idx = clause.find(",")
    if comma_idx < 0 or comma_idx > max_chars:
        return clause
    return _normalize_ws(clause[comma_idx + 1 :])


# Meta-text patterns: reject LHS if any match (document-agnostic)
_META_TEXT_PATTERNS = [
    re.compile(r"\bin this (paper|section|chapter|work|study|article|report)\b", re.I),
    re.compile(r"\bthis (paper|section|chapter|work|study|article)\b", re.I),
    re.compile(
        r"\bwe (show|propose|present|introduce|describe|demonstrate|evaluate|argue|discuss)\b",
        re.I,
    ),
    re.compile(r"\bthe remainder of this (paper|section|chapter)\b", re.I),
    re.compile(
        r"\b(as shown|as discussed) in (figure|table|section|chapter)\b", re.I
    ),
    re.compile(r"\bsee (figure|table|section|chapter)\b", re.I),
    re.compile(r"\brelated work\b", re.I),
    re.compile(r"\b(conclusion|abstract|introduction)\b", re.I),
]


def clean_leading_structure(s: str) -> str:
    """
    Strip leading section/chapter numbering and headings.
    """
    if not s:
        return ""
    s = _normalize_ws(s)
    # Remove leading numbering: "4 ", "4.1 ", "4.1.2 "
    s = re.sub(r"^\s*(\d+(\.\d+)*)\s+", "", s)
    # Remove "Chapter N" or "Section N" or "Section N:"
    s = re.sub(r"^\s*(chapter|section)\s+\d+(\.\d+)*\s*[:\-]?\s*", "", s, flags=re.I)
    s = _normalize_ws(s)
    if not s:
        return s
    tokens = s.split()
    if len(tokens) < 3:
        return s
    # Heuristic: heading = high TitleCase ratio, no verbs in first 12 tokens
    first_tokens = tokens[:min(12, len(tokens))]
    title_case_count = sum(1 for t in first_tokens if t and t[0].isupper())
    has_verb = any(t.lower() in ("is", "are", "was", "were", "has", "have", "can", "uses", "use") for t in first_tokens)
    if title_case_count >= 0.7 * len(first_tokens) and not has_verb:
        # Drop prefix until first lowercase-starting token or verb
        drop = 0
        for i, t in enumerate(first_tokens):
            if t and t[0].islower():
                drop = i
                break
            if t.lower() in ("is", "are", "was", "were", "has", "have", "can", "uses", "use"):
                drop = i
                break
        if drop > 0:
            s = " ".join(tokens[drop:])
    return _normalize_ws(s)


def _lhs_has_verb(lhs: str) -> bool:
    """True if LHS contains a verb-like token."""
    tokens = lhs.lower().split()
    return bool(set(t.lower() for t in tokens) & _RHS_VERB_LIKE)


def _rhs_has_verb_in_first_n(rhs: str, n: int = 8) -> bool:
    """True if RHS has verb-like token in first n tokens."""
    tokens = rhs.lower().split()[:n]
    return bool(set(tokens) & _RHS_VERB_LIKE)


def _discourse_cue_acceptable_split(s: str, idx: int, cue: str) -> bool:
    """
    For "therefore/thus/as a result": only accept if boundary or RHS verb.
    """
    before = s[:idx].rstrip()
    after = s[idx + len(cue):].lstrip()
    after = re.sub(r"^[\s,;\-–—]+", "", after)
    # Check for hard boundary within 3 chars before cue
    tail = before[-3:] if len(before) >= 3 else before
    if ";" in tail or "." in tail:
        return True
    # Comma before cue AND LHS has verb
    if before.endswith(",") and _lhs_has_verb(before[:-1]):
        return True
    # RHS has verb in first 8 tokens
    if _rhs_has_verb_in_first_n(after, 8):
        return True
    return False


def split_on_causal_cue(s: str) -> Optional[Tuple[str, str, str]]:
    """
    Detect explicit causal cues and return (lhs, cue, rhs).
    Reject if cue occurs in first 2 tokens.
    Discourse cues (therefore/thus/as a result) require boundary or RHS verb.
    """
    s = _normalize_ws(s)
    if not s or len(s) < 15:
        return None
    lower = s.lower()
    best_idx = -1
    best_cue = ""
    for cue in _CAUSAL_CUES:
        idx = lower.find(cue)
        if idx < 0 or (best_idx >= 0 and idx >= best_idx):
            continue
        before = s[:idx].strip()
        before_tokens = before.split()
        if len(before_tokens) < 2:
            continue
        if cue in _DISCOURSE_CUES:
            if not _discourse_cue_acceptable_split(s, idx, cue):
                continue
        best_idx = idx
        best_cue = cue
    if best_idx < 0:
        return None
    lhs = s[:best_idx].strip()
    rhs = s[best_idx + len(best_cue):].strip()
    lhs = lhs.rstrip(".,;: \t-–—")
    rhs = re.sub(r"^[\s,;\-–—]+", "", rhs)
    lhs = _normalize_ws(lhs)
    rhs = _normalize_ws(rhs)
    if not lhs or not rhs:
        return None
    return (lhs, best_cue, rhs)


def _has_meta_text(clause: str) -> bool:
    """True if clause contains document meta-text patterns (section/paper/chapter refs)."""
    if not clause:
        return False
    for pat in _META_TEXT_PATTERNS:
        if pat.search(clause):
            return True
    return False


def clause_is_questionable(
    clause: str,
    *,
    reject_pronoun_led: bool = True,
    min_words: int = 4,
    max_words: int = 22,
    reject_meta_text: bool = False,
) -> bool:
    """
    Reject clause if pronoun-led, structural, wrong length, meta-text, or OCR junk.
    reject_pronoun_led=False for answer (rhs) which may start with "it/they".
    reject_meta_text=True for LHS only (question clause).
    """
    clause = _normalize_ws(clause)
    if not clause:
        return True
    tokens = clause.split()
    if len(tokens) < min_words or len(tokens) > max_words:
        return True
    if reject_pronoun_led:
        first = tokens[0].lower() if tokens else ""
        if first in _CLAUSE_FIRST_REJECT:
            return True
    if reject_meta_text and _has_meta_text(clause):
        return True
    lower = clause.lower()
    token_set = set(t.lower() for t in tokens)
    if token_set & _STRUCTURAL_TOKENS:
        return True
    if "\n" in clause or "↵" in clause or "…" in clause or "�" in clause:
        return True
    digit_count = sum(1 for c in clause if c.isdigit())
    if digit_count > 2:
        return True
    return False


# Prepositions: clause starting with these is not a clear leading pattern
_LEADING_PREPOSITIONS = frozenset("in on at to for with by from as".split())


@dataclass
class ShortAnswerStats:
    """Privacy-safe counters for short-answer pipeline. No text logged."""

    seen: int = 0
    cleaned: int = 0
    no_causal_cue: int = 0
    split_rejected: int = 0
    lhs_rejected: int = 0
    rhs_rejected: int = 0
    prep_salvaged: int = 0
    prep_rejected: int = 0
    mid_aux_rejected: int = 0
    build_question_failed: int = 0
    validation_failed: int = 0
    meta_text_rejected: int = 0


def detect_auxiliary(clause: str) -> Optional[Tuple[str, str]]:
    """
    Return (aux, rest) for "Why <aux> <rest>?".
    Returns None if aux is mid-sentence or clause doesn't match leading pattern.
    """
    clause = _normalize_ws(clause)
    if not clause:
        return None
    tokens = clause.split()
    if len(tokens) < 3:
        return None
    first_lower = tokens[0].lower() if tokens else ""
    if first_lower in _LEADING_PREPOSITIONS:
        return None
    aux_idx = -1
    for i, t in enumerate(tokens):
        if t.lower() in _AUX_VERBS:
            aux_idx = i
            break
    if aux_idx >= 0:
        if aux_idx < 1 or aux_idx >= len(tokens) - 1:
            return None
        subject_first = tokens[0].lower()
        if subject_first in _CLAUSE_FIRST_REJECT:
            return None
        aux = tokens[aux_idx].lower()
        rest_tokens = tokens[:aux_idx] + tokens[aux_idx + 1:]
        rest = " ".join(rest_tokens)
        rest = _normalize_ws(rest)
        return (aux, rest)
    if first_lower in _CLAUSE_FIRST_REJECT:
        return None
    has_verb = bool(set(t.lower() for t in tokens[1:]) & _RHS_VERB_LIKE)
    if not has_verb:
        return None
    if first_lower.endswith("s") and not first_lower.endswith("ss"):
        aux = "do"
    else:
        aux = "does"
    return (aux, clause)


def build_why_question(
    clause: str, stats: Optional["ShortAnswerStats"] = None
) -> Optional[str]:
    """
    Build "Why <aux> <rest>?" question. Max 18 words.
    Validates with validate_short_answer_stem; returns None if invalid.
    """
    clause = _normalize_ws(clause).rstrip(".")
    if not clause or len(clause) < 10:
        return None
    result = detect_auxiliary(clause)
    if not result:
        if stats:
            first = clause.split()[0].lower() if clause.split() else ""
            if first in _LEADING_PREPOSITIONS:
                stats.prep_rejected += 1
            else:
                stats.mid_aux_rejected += 1
        return None
    aux, rest = result
    if not rest:
        return None
    question = f"Why {aux} {rest}?"
    question = _normalize_ws(question)
    words = question.split()
    if len(words) > 18:
        return None
    if "  " in question:
        return None
    if not validate_short_answer_stem(question):
        if stats:
            stats.validation_failed += 1
        return None
    return question


def build_because_answer(rhs: str) -> Optional[str]:
    """
    Normalize answer, trim to <= 30 words, ensure single line.
    """
    rhs = _normalize_ws(rhs)
    rhs = re.sub(r"^[\s,;\-–—]+", "", rhs)
    if not rhs or len(rhs) < 3:
        return None
    if "\n" in rhs:
        return None
    words = rhs.split()
    if len(words) > 30:
        rhs = " ".join(words[:30])
    causal_start = ("because", "due to", "since", "as a result", "therefore", "thus")
    if not any(rhs.lower().startswith(w) for w in causal_start):
        rhs = "Because " + (rhs[0].lower() + rhs[1:] if len(rhs) > 1 else rhs)
    return _normalize_ws(rhs)


def generate_short_answer_from_sentence(
    sentence: str, stats: Optional[ShortAnswerStats] = None
) -> Optional[dict]:
    """
    Pipeline: clean -> split on causal cue -> salvage prep-led -> validate -> build.
    Returns { "question": str, "answer": str } or None.
    Optional stats for privacy-safe counters (no text logged).
    """
    if stats:
        stats.seen += 1
    s = clean_leading_structure(sentence)
    if not s or len(s) < 20:
        return None
    if stats:
        stats.cleaned += 1
    split = split_on_causal_cue(s)
    if not split:
        if stats:
            stats.no_causal_cue += 1
        return None
    lhs, cue, rhs = split
    lhs = _normalize_ws(lhs)
    rhs = _normalize_ws(rhs)
    lhs_before = lhs
    lhs = strip_leading_prep_phrase(lhs)
    if stats and lhs != lhs_before:
        stats.prep_salvaged += 1
    if clause_is_questionable(
        lhs, min_words=6, max_words=22, reject_meta_text=True
    ):
        if stats:
            stats.lhs_rejected += 1
            if _has_meta_text(lhs):
                stats.meta_text_rejected += 1
        return None
    if content_ratio(lhs) < 0.55:
        if stats:
            stats.lhs_rejected += 1
        return None
    if clause_is_questionable(rhs, reject_pronoun_led=False, min_words=4, max_words=30):
        if stats:
            stats.rhs_rejected += 1
        return None
    q = build_why_question(lhs, stats)
    if not q:
        if stats:
            stats.build_question_failed += 1
        return None
    a = build_because_answer(rhs)
    if not a:
        return None
    return {"question": q, "answer": a}
