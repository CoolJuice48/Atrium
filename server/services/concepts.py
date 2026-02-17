"""
Deterministic concept centrality scoring for summaries and exams.

Assigns scores based on: key term density, cross-sentence recurrence,
section-title alignment, definition anchoring. No LLM.
"""

import re
from collections import Counter
from dataclasses import dataclass
from typing import Dict, List, Optional, Set

from server.services.text_quality import is_structural_noise, normalize_ws


def _numeric_overload(s: str) -> bool:
    """Too many digits (reuse text_quality logic)."""
    clean = s.replace(" ", "").replace("\n", "")
    if not clean:
        return False
    digit_count = sum(1 for c in clean if c.isdigit())
    return digit_count / len(clean) > 0.12

# Stopwords for n-gram extraction (reuse + extend for generic/low-info)
_NGRAM_STOPWORDS = frozenset(
    "a an the and or but in on at to for of with by from as is was are were been be "
    "have has had do does did will would could should may might must can shall "
    "this that these those it its using consider given thus hence therefore however "
    "thing stuff part element type form way method process result".split()
)

# Definition cues for anchoring boost
_DEF_CUES = ("is defined as", "refers to", "means", "is called", "consists of")


@dataclass
class TermStat:
    """Per-term statistics: document frequency, total frequency, centrality score."""
    df: int
    tf: int
    score: float


def _tokenize_alphabetic(text: str) -> List[str]:
    """Return list of lowercase alphabetic tokens."""
    return re.findall(r"[a-z]+", text.lower())


def extract_title_terms(title: str) -> List[str]:
    """
    Extract 1-3 gram terms from a title for centrality alignment.
    Tokenize, normalize, remove stopwords. Used by outline and heading mining.
    """
    if not title or not isinstance(title, str):
        return []
    return _extract_ngrams(title, min_n=1, max_n=3)


def extract_ngrams_from_sentence(sentence: str) -> List[str]:
    """Extract 1-3 gram terms from a sentence. Used by bundles for co-occurrence."""
    if not sentence or not isinstance(sentence, str):
        return []
    return _extract_ngrams(normalize_ws(sentence), min_n=1, max_n=3)


def _extract_ngrams(sentence: str, min_n: int = 1, max_n: int = 3) -> List[str]:
    """Extract 1-3 gram candidates, stopword filtered."""
    tokens = _tokenize_alphabetic(sentence)
    if not tokens:
        return []
    ngrams = []
    for n in range(min_n, max_n + 1):
        for i in range(len(tokens) - n + 1):
            ngram = " ".join(tokens[i : i + n])
            if any(t in _NGRAM_STOPWORDS for t in tokens[i : i + n]):
                continue
            if len(ngram) < 3:
                continue
            ngrams.append(ngram)
    return ngrams


def build_term_stats(sentences: List[str]) -> Dict[str, TermStat]:
    """
    Build term statistics from sentences.
    df = sentences containing term, tf = total occurrences.
    score = df * (1 + multiword_boost) - generic_penalty, normalized.
    """
    if not sentences:
        return {}
    doc_freq: Counter = Counter()
    tot_freq: Counter = Counter()
    for sent in sentences:
        sent = normalize_ws(sent)
        if not sent:
            continue
        ngrams = _extract_ngrams(sent)
        seen = set()
        for ng in ngrams:
            tot_freq[ng] += 1
            if ng not in seen:
                doc_freq[ng] += 1
                seen.add(ng)

    n_sentences = max(1, len([s for s in sentences if normalize_ws(s)]))
    stats: Dict[str, TermStat] = {}
    for term, df in doc_freq.items():
        tf = tot_freq[term]
        n_words = len(term.split())
        multiword_boost = 0.3 * (n_words - 1) if n_words >= 2 else 0.0
        raw = df * (1.0 + multiword_boost)
        if df < 2 and n_words == 1:
            raw *= 0.5
        score = max(0.0, raw)
        stats[term] = TermStat(df=df, tf=tf, score=score)

    if stats:
        max_score = max(s.score for s in stats.values())
        if max_score > 0:
            for term in stats:
                stats[term].score = stats[term].score / max_score
    return stats


def sentence_centrality(
    sentence: str,
    term_stats: Dict[str, TermStat],
    section_title_terms: Optional[Set[str]] = None,
) -> float:
    """
    Compute centrality score for a sentence.
    score = sum(term_stats[t].score for t in sentence) / length
    + title_alignment_boost if sentence shares terms with section title
    + definition_boost if sentence defines a high-score term
    - penalties for numeric overload / structural (reuse text_quality)
    """
    sentence = normalize_ws(sentence)
    if not sentence or not term_stats:
        return 0.0
    if _numeric_overload(sentence):
        return 0.0
    if is_structural_noise(sentence):
        return 0.0

    ngrams = _extract_ngrams(sentence)
    if not ngrams:
        return 0.0

    total = 0.0
    matched = 0
    for ng in ngrams:
        if ng in term_stats:
            total += term_stats[ng].score
            matched += 1

    length_factor = max(1, len(sentence.split()))
    base_score = total / length_factor

    title_boost = 0.0
    if section_title_terms:
        sent_terms = set(ngrams)
        overlap = len(sent_terms & section_title_terms)
        if overlap > 0:
            title_boost = 0.15 * min(overlap, 3)

    def_boost = 0.0
    lower = sentence.lower()
    if any(cue in lower for cue in _DEF_CUES):
        for ng in ngrams:
            if ng in term_stats and term_stats[ng].score >= 0.3:
                def_boost = 0.1
                break

    return base_score + title_boost + def_boost


def count_matched_terms(sentence: str, term_stats: Dict[str, TermStat]) -> int:
    """Return count of n-grams in sentence that appear in term_stats."""
    sentence = normalize_ws(sentence)
    if not sentence or not term_stats:
        return 0
    ngrams = _extract_ngrams(sentence)
    return sum(1 for ng in ngrams if ng in term_stats)


def get_top_term(sentence: str, term_stats: Dict[str, TermStat]) -> Optional[str]:
    """Return the highest-scoring term in the sentence, or None."""
    sentence = normalize_ws(sentence)
    if not sentence or not term_stats:
        return None
    ngrams = _extract_ngrams(sentence)
    best = None
    best_score = -1.0
    for ng in ngrams:
        if ng in term_stats and term_stats[ng].score > best_score:
            best_score = term_stats[ng].score
            best = ng
    return best


def extract_section_title_terms(chunks: List[dict]) -> Set[str]:
    """Extract alphabetic terms from section_title and chapter titles in chunks."""
    terms: Set[str] = set()
    for ch in chunks:
        meta = ch.get("metadata", ch)
        for key in ("section_title", "chapter_title", "section_title_clean"):
            val = meta.get(key, ch.get(key, ""))
            if val and isinstance(val, str):
                for t in extract_title_terms(val):
                    if t:
                        terms.add(t)
    return terms


def get_section_title_terms_for_scope(
    items: List[dict],
    item_ids: List[str],
    chunks: List[dict],
) -> Set[str]:
    """
    Derive section_title_terms from selected outline items for centrality alignment.
    If outline is fallback (page ranges), mine headings from chunks as pseudo-title_terms.
    """
    terms: Set[str] = set()
    id_to_item = {it["id"]: it for it in items}
    for iid in item_ids:
        if iid not in id_to_item:
            continue
        it = id_to_item[iid]
        title_terms = it.get("title_terms")
        if isinstance(title_terms, list):
            for t in title_terms:
                if t and isinstance(t, str) and len(t) >= 2:
                    terms.add(t)
        else:
            terms.update(extract_title_terms(it.get("title", "")))

    # Filter generic fallback terms (e.g. "pages" from "Pages 1–20")
    generic = {"pages", "page"}
    terms = {t for t in terms if t not in generic}

    if not terms:
        from server.services.heading_mine import extract_headings_from_chunks

        headings = extract_headings_from_chunks(chunks)
        for h in headings[:15]:
            terms.update(extract_title_terms(h))

    if not terms:
        terms = extract_section_title_terms(chunks)

    return terms
