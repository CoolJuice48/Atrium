"""Concept extraction from answer dicts and chunk metadata."""

import re
from typing import Dict, List, Set

from graph.models import ConceptNode, make_concept_id


# Stopwords to skip (common English words that aren't concepts)
_STOPWORDS: Set[str] = {
    'about', 'above', 'after', 'again', 'almost', 'along', 'already',
    'also', 'always', 'among', 'another', 'anything', 'around',
    'been', 'before', 'being', 'below', 'between', 'beyond', 'both',
    'certain', 'could', 'does', 'doing', 'down', 'during',
    'each', 'either', 'enough', 'even', 'every', 'everything',
    'first', 'from', 'further', 'given', 'going', 'great',
    'have', 'having', 'hence', 'here', 'however', 'indeed',
    'into', 'itself', 'just', 'large', 'later', 'least', 'less',
    'like', 'little', 'longer', 'looking', 'mainly', 'major',
    'make', 'makes', 'making', 'many', 'might', 'minor',
    'more', 'most', 'much', 'must', 'nearly', 'need', 'needs',
    'never', 'none', 'nothing', 'often', 'only', 'order', 'other',
    'others', 'otherwise', 'over', 'overall', 'particular',
    'place', 'point', 'possible', 'present', 'provides', 'quite',
    'rather', 'really', 'result', 'right', 'same', 'second',
    'shall', 'short', 'should', 'shown', 'simply', 'since',
    'small', 'some', 'something', 'still', 'such', 'taken',
    'take', 'takes', 'than', 'that', 'their', 'them', 'then',
    'there', 'therefore', 'these', 'they', 'thing', 'things',
    'third', 'this', 'those', 'though', 'three', 'through',
    'together', 'total', 'under', 'unless', 'until', 'upon',
    'various', 'very', 'want', 'well', 'were', 'what', 'whatever',
    'when', 'where', 'whether', 'which', 'while', 'whose',
    'will', 'with', 'within', 'without', 'would', 'write',
    'your', 'answer', 'question', 'following', 'example',
    'called', 'using', 'used', 'known', 'allows', 'based',
}

# Regex for C++-style tokens (std::vector, template<T>, etc.)
_CODE_TOKEN_RE = re.compile(
    r'\b(std::\w+)'                      # std::vector, std::map
    r'|'
    r'\b(\w+<\w+>)'                      # vector<int>, map<string>
    r'|'
    r'\b(\w+::\w+)'                      # namespace::func
)

# Regex for capitalized terms (multi-word or single)
_CAP_TERM_RE = re.compile(
    r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b'   # Multi-word: Binary Search Tree
    r'|'
    r'\b([A-Z][a-z]{3,})\b'                     # Single capitalized >=4 chars
)

# Regex for hyphenated/underscored compound terms
_COMPOUND_RE = re.compile(r'\b([a-zA-Z]+(?:[-_][a-zA-Z]+)+)\b')


def extract_concepts(
    question: str,
    answer_dict: Dict,
    retrieved_chunks: List[Dict],
) -> List[str]:
    """
    Extract candidate concept terms from a question-answer pair.

    Sources:
        - answer_dict['key_points']
        - chunk metadata (section titles)
        - question text itself

    Returns:
        Deduplicated list of normalized concept terms.
    """
    raw_terms: List[str] = []

    # Collect text sources
    texts = [question]
    for kp in answer_dict.get('key_points', []):
        texts.append(kp)
    for chunk in retrieved_chunks:
        meta = chunk.get('metadata', {})
        section_title = meta.get('section_title', '')
        if section_title:
            texts.append(section_title)

    for text in texts:
        raw_terms.extend(_extract_from_text(text))

    # Deduplicate (preserve order, case-insensitive dedup)
    seen: Set[str] = set()
    unique: List[str] = []
    for term in raw_terms:
        normalized = _normalize_term(term)
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique.append(normalized)

    return unique


def _extract_from_text(text: str) -> List[str]:
    """Extract concept candidates from a single text string."""
    terms: List[str] = []

    # 1. Code tokens (preserve case)
    for m in _CODE_TOKEN_RE.finditer(text):
        token = m.group(0)
        terms.append(token)

    # 2. Capitalized terms (filter stopwords)
    for m in _CAP_TERM_RE.finditer(text):
        token = m.group(1) or m.group(2)
        if token and token.lower() not in _STOPWORDS:
            terms.append(token)

    # 3. Compound terms (hyphenated/underscored)
    for m in _COMPOUND_RE.finditer(text):
        token = m.group(1)
        if len(token) >= 5:
            terms.append(token)

    # 4. Noun-like tokens: not a stopword, length > 4
    words = re.findall(r'\b[a-zA-Z]{5,}\b', text)
    for w in words:
        if w.lower() not in _STOPWORDS:
            terms.append(w)

    return terms


def _normalize_term(term: str) -> str:
    """
    Normalize a concept term.

    Code tokens (containing :: or <>) are preserved as-is.
    Everything else is lowercased.
    """
    if '::' in term or '<' in term:
        return term.strip()
    return term.strip().lower()


def make_concept_nodes(
    terms: List[str],
    books: List[str],
    sections: List[str],
    question_id: str,
) -> List[ConceptNode]:
    """
    Build ConceptNode objects from extracted terms.

    Args:
        terms:       Normalized concept terms
        books:       Book names from the answer context
        sections:    Section identifiers
        question_id: QNode ID to link

    Returns:
        List of ConceptNode objects.
    """
    nodes: List[ConceptNode] = []
    for term in terms:
        cid = make_concept_id(term)
        nodes.append(ConceptNode(
            concept_id=cid,
            name=term,
            occurrences=1,
            books=list(books),
            sections=list(sections),
            linked_qnodes=[question_id],
        ))
    return nodes
