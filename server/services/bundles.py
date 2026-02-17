"""
Concept bundles: group related terms and sentences for study-guide-style outputs.

Bundle = {label_term, supporting_terms, supporting_sentences}
Uses co-occurrence graph from term_stats to cluster concepts.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from server.services.concepts import (
    TermStat,
    extract_ngrams_from_sentence,
    sentence_centrality,
)
from server.services.text_quality import normalize_ws


@dataclass
class ConceptBundle:
    """Single concept bundle: label term, co-occurring terms, and supporting sentences."""
    label_term: str
    supporting_terms: List[str] = field(default_factory=list)
    supporting_sentences: List[str] = field(default_factory=list)


def build_cooccurrence_graph(
    sentences: List[str],
    terms: Set[str],
) -> Dict[Tuple[str, str], int]:
    """
    Build co-occurrence graph for given terms.
    Edge weight (A, B) = number of sentences where both A and B appear.
    Returns dict keyed by (min_term, max_term) for deterministic ordering.
    """
    if not sentences or not terms:
        return {}
    graph: Dict[Tuple[str, str], int] = defaultdict(int)
    for sent in sentences:
        sent = normalize_ws(sent)
        if not sent:
            continue
        ngrams = set(extract_ngrams_from_sentence(sent)) & terms
        ngrams = sorted(ngrams)
        for i, a in enumerate(ngrams):
            for b in ngrams[i + 1 :]:
                key = (a, b)
                graph[key] += 1
    return dict(graph)


def build_bundles(
    term_stats: Dict[str, TermStat],
    sentences: List[str],
    *,
    top_k_terms: int = 15,
    max_supporting_terms: int = 5,
    max_sentences_per_bundle: int = 8,
    section_title_terms: Optional[Set[str]] = None,
) -> List[ConceptBundle]:
    """
    Build concept bundles from term_stats and sentences.
    For each top term: choose top co-occurring terms, assign sentences containing
    label_term AND >=1 supporting_term.
    """
    if not term_stats or not sentences:
        return []

    top_terms = sorted(
        term_stats.keys(),
        key=lambda t: term_stats[t].score,
        reverse=True,
    )[:top_k_terms]
    terms_set = set(top_terms)

    graph = build_cooccurrence_graph(sentences, terms_set)

    bundles: List[ConceptBundle] = []
    for label in top_terms:
        cooccur: List[Tuple[str, int]] = []
        for (a, b), w in graph.items():
            if a == label:
                cooccur.append((b, w))
            elif b == label:
                cooccur.append((a, w))
        cooccur.sort(key=lambda x: -x[1])
        supporting = [t for t, _ in cooccur[:max_supporting_terms]]

        sent_candidates: List[Tuple[float, str]] = []
        for s in sentences:
            s = normalize_ws(s)
            if not s:
                continue
            ngrams = set(extract_ngrams_from_sentence(s)) & terms_set
            if label not in ngrams:
                continue
            if supporting and not (ngrams & set(supporting)):
                continue
            cent = sentence_centrality(
                s, term_stats, section_title_terms=section_title_terms
            )
            sent_candidates.append((cent, s))

        sent_candidates.sort(key=lambda x: (-x[0], x[1]))
        supporting_sents = [s for _, s in sent_candidates[:max_sentences_per_bundle]]

        bundles.append(ConceptBundle(
            label_term=label,
            supporting_terms=supporting,
            supporting_sentences=supporting_sents,
        ))

    return bundles


def select_sentences_across_bundles(
    bundles: List[ConceptBundle],
    max_total: int,
    max_per_bundle: int = 2,
) -> List[str]:
    """
    Select sentences across bundles to avoid overfitting to one bundle.
    Round-robin: 1 per bundle, then 1 per bundle again, until max_total.
    """
    result: List[str] = []
    seen: Set[str] = set()
    for round_num in range(max_per_bundle):
        if len(result) >= max_total:
            break
        for b in bundles:
            if len(result) >= max_total:
                break
            for s in b.supporting_sentences:
                if s not in seen:
                    seen.add(s)
                    result.append(s)
                    break
    return result
