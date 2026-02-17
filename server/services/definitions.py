"""
DefinitionRegistry: per-scope registry of (term -> best definition) for exams and cards.

Extracts explicit definitions, picks best by centrality, RHS length, and noise.
Prevents redundant definition questions.
"""

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from server.services.text_quality import normalize_ws

if TYPE_CHECKING:
    from server.services.concepts import TermStat
    from server.services.exam_candidates import Candidate, CandidatePool

# Reuse exam_generation patterns for extraction
_DEF_PATTERNS_EXPLICIT = [
    (r"^(.+?)\s+(?:is|are)\s+defined\s+as\s+(.+)$", "is_defined_as"),
    (r"^(.+?)\s+refers\s+to\s+(.+)$", "refers_to"),
    (r"^(.+?)\s+means\s+(.+)$", "means"),
    (r"^(.+?)\s+(?:is|are)\s+called\s+(.+)$", "is_called"),
    (r"^(.+?)\s+consists\s+of\s+(.+)$", "consists_of"),
]
_DEF_PATTERN_WEAK = (r"^(.+?)\s+(?:is|are)\s+(.+)$", "is")


def _strip_trailing_citations(defn: str) -> str:
    """Remove trailing parentheticals that look like references."""
    defn = defn.strip()
    while defn and defn.endswith(")"):
        idx = defn.rfind("(")
        if idx < 0:
            break
        inner = defn[idx + 1 : -1]
        if re.search(r"\d{4}|\bchapter\b|\bfig\.?\s*\d", inner, re.I):
            defn = defn[:idx].rstrip(",; ")
        else:
            break
    return defn


def _definition_has_verb(text: str) -> bool:
    """Check if definition contains a verb (heuristic)."""
    lower = text.lower()
    for w in ("is", "are", "was", "were", "has", "have", "can", "will", "may", "does", "do", "refers", "means", "consists"):
        if re.search(rf"\b{w}\b", lower):
            return True
    if re.search(r"\b\w+ed\b|\b\w+ing\b", lower):
        return True
    return False


def _citation_noise_score(text: str) -> float:
    """Higher = more citation/numeric noise. Prefer lower."""
    score = 0.0
    score += len(re.findall(r"\[\d+\]|\(\d{4}\)", text)) * 2.0
    score += sum(1 for c in text if c.isdigit()) / max(1, len(text)) * 5.0
    return score


def _extract_pair(sentence: str) -> Optional[Tuple[str, str]]:
    """Extract (term, definition) from sentence. Returns None if invalid."""
    sentence = normalize_ws(sentence)
    if not sentence or len(sentence) < 20:
        return None
    for pattern, _ in _DEF_PATTERNS_EXPLICIT:
        m = re.match(pattern, sentence, re.IGNORECASE | re.DOTALL)
        if m:
            x_raw, y_raw = m.group(1).strip(), m.group(2).strip()
            term = normalize_ws(x_raw).rstrip(".,;:")
            defn = normalize_ws(y_raw).split("\n")[0]
            defn = _strip_trailing_citations(defn)
            defn_words = len(defn.split())
            if defn_words < 6 or defn_words > 35:
                continue
            if not _definition_has_verb(defn):
                continue
            if len(term) >= 4 and len(defn) >= 15:
                return (term, defn)
            return None
    m = re.match(_DEF_PATTERN_WEAK[0], sentence, re.IGNORECASE | re.DOTALL)
    if m:
        x_raw, y_raw = m.group(1).strip(), m.group(2).strip()
        term = normalize_ws(x_raw).rstrip(".,;:")
        defn = normalize_ws(y_raw).split("\n")[0]
        defn = _strip_trailing_citations(defn)
        defn_words = len(defn.split())
        if 6 <= defn_words <= 35 and _definition_has_verb(defn):
            if len(term) >= 4 and len(defn) >= 15:
                return (term, defn)
    return None


@dataclass
class Definition:
    """Single best definition for a term."""
    term: str
    definition: str
    centrality_score: float
    candidate: "Candidate"


def pick_best_definition(
    defs: List[Tuple[str, str, float, "Candidate"]],
) -> Optional[Tuple[str, str, float, "Candidate"]]:
    """
    Choose best definition from candidates.
    Prefer: highest centrality, shortest valid RHS (6-28 words), lowest numeric/citation noise.
    """
    if not defs:
        return None
    valid = []
    for term, defn, cent, cand in defs:
        words = len(defn.split())
        if words < 6 or words > 28:
            continue
        valid.append((term, defn, cent, cand))
    if not valid:
        valid = defs
    best = None
    best_score = (-1e9, 1e9, -1e9)
    for term, defn, cent, cand in valid:
        words = len(defn.split())
        noise = _citation_noise_score(defn)
        score = (cent, -words, -noise)
        if score > best_score:
            best_score = score
            best = (term, defn, cent, cand)
    return best


def extract_definitions(
    candidate_pool: "CandidatePool",
    term_stats: Optional[Dict[str, "TermStat"]] = None,
    stats: Optional[Any] = None,
) -> Dict[str, Definition]:
    """
    Extract explicit definitions from candidate pool.
    Returns dict[term_normalized] = Definition (best per term).
    Builds term_stats from pool if not provided.
    When stats provided, increments rejected_bad_first_token for invalid terms.
    """
    from server.services.concepts import build_term_stats
    from server.services.exam_stems import validate_definition_term
    from server.services.text_quality import is_exercise_prompt, is_reference_line, is_structural_noise

    if term_stats is None:
        all_sentences = [c.text for c in candidate_pool.candidates]
        term_stats = build_term_stats(all_sentences)
    by_term: Dict[str, List[Tuple[str, str, float, "Candidate"]]] = {}
    def_candidates = [c for c in candidate_pool.candidates if c.score_hint >= 2]
    for c in def_candidates:
        pair = _extract_pair(c.text)
        if not pair:
            continue
        term, defn = pair
        if stats:
            stats.seen_sentences = getattr(stats, "seen_sentences", 0) + 1
        if is_structural_noise(defn) or is_exercise_prompt(defn) or is_reference_line(defn):
            continue
        if not validate_definition_term(term):
            if stats and hasattr(stats, "rejected_bad_first_token"):
                stats.rejected_bad_first_token += 1
            continue
        key = term.lower().strip()
        if key not in by_term:
            by_term[key] = []
        by_term[key].append((term, defn, c.centrality_score, c))

    registry: Dict[str, Definition] = {}
    for key, defs in by_term.items():
        best = pick_best_definition(defs)
        if best:
            term, defn, cent, cand = best
            registry[key] = Definition(
                term=term,
                definition=defn,
                centrality_score=cent,
                candidate=cand,
            )
    return registry


def registry_to_card_format(
    registry: Dict[str, Definition],
    term_stats: Optional[Dict[str, "TermStat"]] = None,
) -> List[dict]:
    """Convert registry to simple dict list for card generation. Ordered by centrality."""
    ordered = registry_terms_ordered_by_centrality(registry, term_stats)
    result = []
    for key in ordered:
        d = registry[key]
        pages = ""
        if d.candidate.page_start is not None and d.candidate.page_end is not None:
            if d.candidate.page_start != d.candidate.page_end:
                pages = f"{d.candidate.page_start}-{d.candidate.page_end}"
            else:
                pages = str(d.candidate.page_start)
        result.append({
            "term": d.term,
            "definition": d.definition,
            "chunk_id": d.candidate.chunk_id,
            "pages": pages,
        })
    return result


def registry_terms_ordered_by_centrality(
    registry: Dict[str, Definition],
    term_stats: Optional[Dict[str, "TermStat"]] = None,
) -> List[str]:
    """
    Return registry terms ordered by centrality (highest first).
    Uses term_stats for term score when available, else definition centrality.
    """
    def key(t: str):
        d = registry[t]
        ts = term_stats.get(t, term_stats.get(d.term.lower())) if term_stats else None
        term_score = ts.score if ts else 0.0
        return (term_score, d.centrality_score, t)
    return sorted(registry.keys(), key=key, reverse=True)
