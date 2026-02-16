"""Generate study cards from compose_answer() output."""

import re
from typing import Dict, List, Optional

from study.models import Card, Citation, make_card_id
from study.card_types import CardType


# Capitalized phrases or hyphenated/underscored terms
_KEY_TERM_RE = re.compile(
    r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b'   # Multi-word capitalized (e.g. "Binary Search")
    r'|'
    r'\b([A-Z][a-z]{3,})\b'                     # Single capitalized word (>= 4 chars)
    r'|'
    r'\b([a-z]+(?:[-_][a-z]+)+)\b'              # Hyphenated/underscored terms
)

_DEFINITION_RE = re.compile(
    r'^(?:what\s+is|what\s+are|define|explain|describe)\b', re.IGNORECASE
)


def _extract_tags(section_title: str, book_name: str) -> List[str]:
    """Build tags from section title tokens + book name."""
    tags = []
    if book_name:
        tags.append(book_name)
    if section_title:
        tokens = re.findall(r'[a-zA-Z]{3,}', section_title)
        tags.extend(t.lower() for t in tokens)
    return list(dict.fromkeys(tags))  # dedupe preserving order


def _make_citations_from_chunks(retrieved_chunks: List[Dict]) -> List[Citation]:
    """Extract Citation objects from retrieved chunk dicts."""
    citations = []
    seen = set()
    for chunk in retrieved_chunks:
        meta = chunk.get('metadata', chunk)
        chunk_id = meta.get('chunk_id', chunk.get('chunk_id', ''))
        if not chunk_id or chunk_id in seen:
            continue
        seen.add(chunk_id)

        # Handle page formatting from either legacy or RAG metadata
        pages = meta.get('pages', '')
        if not pages:
            ps = meta.get('page_start', '')
            pe = meta.get('page_end', '')
            if ps:
                pages = f'{ps}-{pe}' if pe and pe != ps else str(ps)

        citations.append(Citation(
            chunk_id=chunk_id,
            chapter=str(meta.get('chapter', meta.get('chapter_number', ''))),
            section=str(meta.get('section', meta.get('section_number', ''))),
            pages=str(pages),
        ))
    return citations


def _make_definition_card(
    question: str,
    answer_dict: Dict,
    citations: List[Citation],
    tags: List[str],
    book_name: str,
) -> Optional[Card]:
    """Generate a definition card for 'What is/Define/Explain' questions."""
    if not _DEFINITION_RE.match(question.strip()):
        return None

    answer_text = answer_dict.get('answer', '')
    if not answer_text:
        return None

    cids = [c.chunk_id for c in citations] if citations else ['']
    card_id = make_card_id(question, cids)

    return Card(
        card_id=card_id,
        book_name=book_name,
        tags=tags,
        prompt=question,
        answer=answer_text,
        card_type=CardType.DEFINITION.value,
        citations=citations[:3],
    )


def _make_cloze_cards(
    answer_dict: Dict,
    citations: List[Citation],
    tags: List[str],
    book_name: str,
    max_cloze: int = 2,
) -> List[Card]:
    """
    Generate cloze cards by blanking out key terms in key_points.

    Heuristic: find the first capitalized term or hyphenated term
    in each key point and replace it with '______'.
    """
    cards = []
    for kp in answer_dict.get('key_points', [])[:max_cloze]:
        match = _KEY_TERM_RE.search(kp)
        if match:
            term = match.group(0)
        else:
            # Fallback: blank the longest word (>= 5 chars)
            words = kp.split()
            long_words = [w for w in words if len(w) >= 5 and w.isalpha()]
            if not long_words:
                continue
            term = max(long_words, key=len)

        cloze_prompt = kp.replace(term, '______', 1)
        if cloze_prompt == kp:
            continue

        cids = [c.chunk_id for c in citations] if citations else ['']
        card_id = make_card_id(cloze_prompt, cids)

        cards.append(Card(
            card_id=card_id,
            book_name=book_name,
            tags=tags,
            prompt=f"Fill in the blank: {cloze_prompt}",
            answer=term,
            card_type=CardType.CLOZE.value,
            citations=citations[:2],
        ))

    return cards


def _make_compare_card(
    question: str,
    answer_dict: Dict,
    citations: List[Citation],
    tags: List[str],
    book_name: str,
) -> Optional[Card]:
    """Generate a comparison card when answer_dict has a 'comparison' key."""
    comp = answer_dict.get('comparison')
    if not comp:
        return None

    concept_a = comp.get('concept_a', {}).get('name', 'A')
    concept_b = comp.get('concept_b', {}).get('name', 'B')
    differences = comp.get('differences', [])

    prompt = f"Compare {concept_a} and {concept_b}. What are the key differences?"
    answer_text = '\n'.join(differences) if differences else answer_dict.get('answer', '')

    if not answer_text:
        return None

    cids = [c.chunk_id for c in citations] if citations else ['']
    card_id = make_card_id(prompt, cids)

    return Card(
        card_id=card_id,
        book_name=book_name,
        tags=tags + ['compare'],
        prompt=prompt,
        answer=answer_text,
        card_type=CardType.COMPARE.value,
        citations=citations[:3],
    )


def _make_short_answer_card(
    question: str,
    answer_dict: Dict,
    citations: List[Citation],
    tags: List[str],
    book_name: str,
) -> Optional[Card]:
    """Fallback short-answer card from the question itself."""
    answer_text = answer_dict.get('answer', '')
    if not answer_text:
        return None

    cids = [c.chunk_id for c in citations] if citations else ['']
    card_id = make_card_id(question, cids)

    return Card(
        card_id=card_id,
        book_name=book_name,
        tags=tags,
        prompt=question,
        answer=answer_text,
        card_type=CardType.SHORT_ANSWER.value,
        citations=citations[:3],
    )


def generate_cards(
    question: str,
    answer_dict: Dict,
    retrieved_chunks: List[Dict],
    *,
    max_cards: int = 6,
) -> List[Card]:
    """
    Generate study cards from a question + compose_answer() result + retrieved chunks.

    Strategy:
        1. Definition card if question is definition-style
        2. Cloze cards from key_points (up to 2)
        3. Compare card if answer_dict has 'comparison'
        4. Short-answer card as fallback
        5. Cap at max_cards

    Every card gets >= 1 citation with chunk_id.
    """
    citations = _make_citations_from_chunks(retrieved_chunks)

    # Determine book_name from first chunk
    book_name = ''
    if retrieved_chunks:
        meta = retrieved_chunks[0].get('metadata', retrieved_chunks[0])
        book_name = meta.get('book', meta.get('book_name', ''))

    # Build tags
    section_title = ''
    if retrieved_chunks:
        meta = retrieved_chunks[0].get('metadata', retrieved_chunks[0])
        section_title = meta.get('section_title', '')
    tags = _extract_tags(section_title, book_name)

    cards: List[Card] = []
    seen_ids = set()

    def _add(card):
        if card and card.card_id not in seen_ids:
            cards.append(card)
            seen_ids.add(card.card_id)

    # 1. Definition card
    _add(_make_definition_card(question, answer_dict, citations, tags, book_name))

    # 2. Cloze cards
    for c in _make_cloze_cards(answer_dict, citations, tags, book_name):
        _add(c)

    # 3. Compare card
    _add(_make_compare_card(question, answer_dict, citations, tags, book_name))

    # 4. Short-answer fallback
    _add(_make_short_answer_card(question, answer_dict, citations, tags, book_name))

    return cards[:max_cards]
