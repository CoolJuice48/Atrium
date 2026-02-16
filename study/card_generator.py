"""Generate study cards from compose_answer() output or directly from chunks."""

import random
import re
from typing import Dict, List, Optional, Tuple

from study.models import Card, Citation, make_card_id, make_structure_card_id
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

# Structure-first: extract definitions from chunk text (lowercase + uppercase)
_DEF_CHUNK_IS_DEFINED_AS = re.compile(
    r'\b([a-zA-Z][a-zA-Z0-9\s\-_]{2,40})\s+is\s+defined\s+as\s+(.+?)(?:\.|$)',
    re.DOTALL | re.IGNORECASE
)
_DEF_CHUNK_REFERS_TO = re.compile(
    r'\b([a-zA-Z][a-zA-Z0-9\s\-_]{2,40})\s+refers\s+to\s+(.+?)(?:\.|$)',
    re.DOTALL | re.IGNORECASE
)
_DEF_CHUNK_MEANS = re.compile(
    r'\b([a-zA-Z][a-zA-Z0-9\s\-_]{2,40})\s+means\s+(.+?)(?:\.|$)',
    re.DOTALL | re.IGNORECASE
)
_DEF_CHUNK_IS_A = re.compile(
    r'\b([a-zA-Z][a-zA-Z0-9\s\-_]{2,40})\s+is\s+(?:a|an)\s+(.+?)(?:\.|$)',
    re.DOTALL | re.IGNORECASE
)

# List detection: bullets and numbered
_LIST_BULLET_RE = re.compile(r'^[\s]*[-•*]\s+(.+)$', re.MULTILINE)
_LIST_NUMBERED_RE = re.compile(r'^[\s]*(?:\d+[.)]\s+|[a-z][.)]\s+)(.+)$', re.MULTILINE)

# Heading detection (for topic inference)
_HEADING_RE = re.compile(r'^#+\s+(.+)$|^([A-Z][^.!?]*)$', re.MULTILINE)

# Min sentence length for true/false (chars)
_TF_MIN_SENTENCE_LEN = 40


def _extract_tags(section_title: str, book_name: str) -> List[str]:
    """Build tags from section title tokens + book name."""
    tags = []
    if book_name:
        tags.append(book_name)
    if section_title:
        tokens = re.findall(r'[a-zA-Z]{3,}', section_title)
        tags.extend(t.lower() for t in tokens)
    return list(dict.fromkeys(tags))  # dedupe preserving order


def _normalize_chunk_id(chunk: Dict) -> str:
    """
    Return a stable chunk identifier. Accepts the same structure from both
    global packs and user uploads; no branching on origin.
    Uses chunk_id when present; otherwise synthesizes from metadata.
    """
    meta = chunk.get('metadata', chunk)
    cid = meta.get('chunk_id', chunk.get('chunk_id', ''))
    if cid:
        return cid
    book = meta.get('book_id', meta.get('book', meta.get('book_name', '')))
    ch = str(meta.get('chapter', meta.get('chapter_number', '')))
    sec = str(meta.get('section', meta.get('section_number', '')))
    idx = meta.get('chunk_index', 0)
    return f"{book}|ch{ch}|sec{sec}|i{idx}"


def _make_citations_from_chunks(retrieved_chunks: List[Dict]) -> List[Citation]:
    """Extract Citation objects from retrieved chunk dicts."""
    citations = []
    seen = set()
    for chunk in retrieved_chunks:
        meta = chunk.get('metadata', chunk)
        chunk_id = _normalize_chunk_id(chunk)
        if chunk_id in seen:
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


# ---- Structure-first extraction (no question/answer_dict) ----

def _infer_chunk_topic(text: str, metadata: Dict) -> str:
    """Infer a topic label for a chunk. Prefer heading, else best keyword."""
    lines = text.strip().split('\n')
    for line in lines[:5]:
        line = line.strip()
        if not line:
            continue
        m = _HEADING_RE.match(line)
        if m:
            h = (m.group(1) or m.group(2) or '').strip()
            if len(h) >= 3 and len(h) <= 80:
                return h
    section = metadata.get('section_title', metadata.get('section', ''))
    if section:
        return str(section)
    tokens = re.findall(r'[a-zA-Z]{4,}', text)
    if tokens:
        return tokens[0].lower()
    return "content"


def _extract_definitions_from_chunk(text: str) -> List[Tuple[str, str]]:
    """Extract (term, definition) pairs from chunk text using heuristics."""
    results = []
    for pattern in (_DEF_CHUNK_IS_DEFINED_AS, _DEF_CHUNK_REFERS_TO, _DEF_CHUNK_MEANS, _DEF_CHUNK_IS_A):
        for m in pattern.finditer(text):
            term = m.group(1).strip()
            defn = m.group(2).strip()
            if len(term) >= 2 and len(defn) >= 5 and len(term) <= 50:
                defn = defn.split('\n')[0][:300]
                results.append((term, defn))
    return results


def _extract_list_items(text: str) -> List[str]:
    """Extract bullet or numbered list items. Returns items if >= 3."""
    bullets = _LIST_BULLET_RE.findall(text)
    numbered = _LIST_NUMBERED_RE.findall(text)
    items = bullets if len(bullets) >= len(numbered) else numbered
    items = [s.strip() for s in items if len(s.strip()) >= 2]
    return items if len(items) >= 3 else []


def _extract_declarative_sentence(text: str) -> Optional[str]:
    """Pick a strong declarative sentence for true/false. Only returns True-candidates."""
    sentences = re.split(r'[.!?]\s+', text)
    for s in sentences:
        s = s.strip()
        if _TF_MIN_SENTENCE_LEN <= len(s) <= 200 and s.endswith(('.', '!', '?')):
            if not s.startswith(('What', 'How', 'Why', 'When', 'Where', 'Which')):
                return s
    return None


def _extract_cloze_from_definition(term: str, definition: str) -> Optional[Tuple[str, str]]:
    """Create cloze from definition: blank out the term. Term must be 3+ chars."""
    term = term.strip()
    if len(term) < 3 or len(term) > 50:
        return None
    if term not in definition:
        return None
    cloze_prompt = definition.replace(term, '______', 1)
    if cloze_prompt == definition:
        return None
    return (cloze_prompt, term)


def _cards_from_chunk(
    chunk: Dict,
    blueprint: Dict[str, int],
    rng: random.Random,
    book_name: str,
    tags: List[str],
) -> List[Card]:
    """Generate cards from a single chunk. Respects blueprint counts."""
    text = chunk.get('text', '')
    meta = chunk.get('metadata', chunk)
    chunk_id = _normalize_chunk_id(chunk)
    citation = _make_citations_from_chunks([chunk])
    topic = _infer_chunk_topic(text, meta)

    cards: List[Card] = []
    seen_ids: set = set()

    def _add(c: Optional[Card]) -> None:
        if c and c.card_id not in seen_ids:
            cards.append(c)
            seen_ids.add(c.card_id)

    # 1. Definitions (including lowercase)
    for term, defn in _extract_definitions_from_chunk(text):
        if blueprint.get(CardType.DEFINITION.value, 0) <= sum(1 for x in cards if x.card_type == CardType.DEFINITION.value):
            break
        prompt = f"What is {term}?"
        card_id = make_structure_card_id(CardType.DEFINITION.value, prompt, chunk_id, term)
        _add(Card(
            card_id=card_id,
            book_name=book_name,
            tags=tags,
            prompt=prompt,
            answer=defn,
            card_type=CardType.DEFINITION.value,
            citations=citation[:3],
        ))

    # 2. List cards
    items = _extract_list_items(text)
    if items and blueprint.get(CardType.LIST.value, 0) > sum(1 for x in cards if x.card_type == CardType.LIST.value):
        prompt = f"List the main points/components/steps of {topic}."
        answer = '\n'.join(f"• {x}" for x in items[:15])
        card_id = make_structure_card_id(CardType.LIST.value, prompt, chunk_id)
        _add(Card(
            card_id=card_id,
            book_name=book_name,
            tags=tags + ['list'],
            prompt=prompt,
            answer=answer,
            card_type=CardType.LIST.value,
            citations=citation[:3],
        ))

    # 3. True/False
    sent = _extract_declarative_sentence(text)
    if sent and blueprint.get(CardType.TRUE_FALSE.value, 0) > sum(1 for x in cards if x.card_type == CardType.TRUE_FALSE.value):
        prompt = f"True or False: {sent}"
        justification = text[:200].replace(sent, '').strip()[:150]
        answer = f"True. {justification}" if justification else "True."
        card_id = make_structure_card_id(CardType.TRUE_FALSE.value, prompt, chunk_id)
        _add(Card(
            card_id=card_id,
            book_name=book_name,
            tags=tags + ['true_false'],
            prompt=prompt,
            answer=answer,
            card_type=CardType.TRUE_FALSE.value,
            citations=citation[:3],
        ))

    # 4. Cloze (prefer definition-based)
    defs = _extract_definitions_from_chunk(text)
    for term, defn in defs:
        if blueprint.get(CardType.CLOZE.value, 0) <= sum(1 for x in cards if x.card_type == CardType.CLOZE.value):
            break
        pair = _extract_cloze_from_definition(term, defn)
        if pair:
            cloze_prompt, ans = pair
            if len(ans) >= 3 and len(ans) <= 40:
                full_prompt = f"Fill in the blank: {cloze_prompt}"
                card_id = make_structure_card_id(CardType.CLOZE.value, full_prompt, chunk_id, term)
                _add(Card(
                    card_id=card_id,
                    book_name=book_name,
                    tags=tags,
                    prompt=full_prompt,
                    answer=ans,
                    card_type=CardType.CLOZE.value,
                    citations=citation[:2],
                ))
    # Fallback: key terms
    for kp in re.split(r'[.\n]', text)[:5]:
        kp = kp.strip()
        if len(kp) < 20:
            continue
        match = _KEY_TERM_RE.search(kp)
        if match:
            term = match.group(0)
        else:
            words = [w for w in kp.split() if len(w) >= 5 and w.isalpha()]
            if not words:
                continue
            term = max(words, key=len)
        if blueprint.get(CardType.CLOZE.value, 0) <= sum(1 for x in cards if x.card_type == CardType.CLOZE.value):
            break
        cloze_prompt = kp.replace(term, '______', 1)
        if cloze_prompt == kp or len(term) < 3 or len(term) > 40:
            continue
        full_prompt = f"Fill in the blank: {cloze_prompt}"
        card_id = make_structure_card_id(CardType.CLOZE.value, full_prompt, chunk_id, term)
        _add(Card(
            card_id=card_id,
            book_name=book_name,
            tags=tags,
            prompt=full_prompt,
            answer=term,
            card_type=CardType.CLOZE.value,
            citations=citation[:2],
        ))

    # 5. Short-answer fallback
    if text.strip() and blueprint.get(CardType.SHORT_ANSWER.value, 0) > sum(1 for x in cards if x.card_type == CardType.SHORT_ANSWER.value):
        prompt = f"Summarize the key points about {topic}."
        answer = text[:400].strip()
        card_id = make_structure_card_id(CardType.SHORT_ANSWER.value, prompt, chunk_id)
        _add(Card(
            card_id=card_id,
            book_name=book_name,
            tags=tags,
            prompt=prompt,
            answer=answer,
            card_type=CardType.SHORT_ANSWER.value,
            citations=citation[:3],
        ))

    return cards


def generate_cards_from_chunks(
    retrieved_chunks: List[Dict],
    *,
    max_cards: int = 20,
    blueprint: Optional[Dict] = None,
    seed: Optional[int] = None,
) -> List[Card]:
    """
    Generate cards from chunks alone (no question/answer_dict).
    Deterministic given same inputs and seed.

    Accepts the exact same retrieved_chunks structure from both global packs
    and user uploads; no branching based on origin.
    """
    if not retrieved_chunks:
        return []

    default_blueprint = {
        CardType.DEFINITION.value: 4,
        CardType.CLOZE.value: 4,
        CardType.LIST.value: 3,
        CardType.TRUE_FALSE.value: 3,
        CardType.SHORT_ANSWER.value: 6,
    }
    bp = {k if isinstance(k, str) else (k.value if hasattr(k, 'value') else str(k)): v
          for k, v in (blueprint or default_blueprint).items()}

    rng = random.Random(seed)
    book_name = ''
    if retrieved_chunks:
        meta = retrieved_chunks[0].get('metadata', retrieved_chunks[0])
        book_name = meta.get('book', meta.get('book_name', meta.get('title', '')))
    section_title = ''
    if retrieved_chunks:
        meta = retrieved_chunks[0].get('metadata', retrieved_chunks[0])
        section_title = meta.get('section_title', '')
    tags = _extract_tags(section_title, book_name)

    all_cards: List[Card] = []
    seen_ids: set = set()
    consumed: Dict[str, int] = {k: 0 for k in bp}
    chunks_shuffled = retrieved_chunks.copy()
    rng.shuffle(chunks_shuffled)

    for chunk in chunks_shuffled:
        if len(all_cards) >= max_cards:
            break
        remaining_slots = max_cards - len(all_cards)
        chunk_bp = {k: max(0, v - consumed.get(k, 0)) for k, v in bp.items()}
        chunk_bp = {k: min(v, remaining_slots) for k, v in chunk_bp.items()}
        new_cards = _cards_from_chunk(chunk, chunk_bp, rng, book_name, tags)
        for c in new_cards:
            if c.card_id not in seen_ids:
                all_cards.append(c)
                seen_ids.add(c.card_id)
                consumed[c.card_type] = consumed.get(c.card_type, 0) + 1
        if len(all_cards) >= max_cards:
            break

    all_cards = postprocess_cards(all_cards, mode="none")
    return all_cards[:max_cards]


def generate_practice_exam(
    retrieved_chunks: List[Dict],
    *,
    exam_size: int = 20,
    blueprint: Optional[Dict] = None,
    seed: Optional[int] = None,
) -> Dict:
    """
    Generate a practice exam from chunks. Uses generate_cards_from_chunks.
    Returns {title, questions, meta}.
    """
    exam_blueprint = blueprint or {
        CardType.DEFINITION.value: 5,
        CardType.CLOZE.value: 4,
        CardType.LIST.value: 3,
        CardType.TRUE_FALSE.value: 4,
        CardType.SHORT_ANSWER.value: 4,
    }
    questions = generate_cards_from_chunks(
        retrieved_chunks,
        max_cards=exam_size,
        blueprint=exam_blueprint,
        seed=seed,
    )
    type_counts = {}
    for c in questions:
        type_counts[c.card_type] = type_counts.get(c.card_type, 0) + 1
    meta = {
        "counts_by_type": type_counts,
        "total": len(questions),
        "sampling_occurred": len(retrieved_chunks) > 1,
    }
    topic = "Study Material"
    if retrieved_chunks:
        meta0 = retrieved_chunks[0].get('metadata', retrieved_chunks[0])
        topic = meta0.get('section_title', meta0.get('book', 'Study Material'))
    title = f"Practice Exam: {topic}"
    return {"title": title, "questions": questions, "meta": meta}


def postprocess_cards(cards: List[Card], mode: str = "none") -> List[Card]:
    """
    Extension point for optional card polish (e.g. local LLM).
    mode="none" does nothing. Future: mode="local_llm" for polish.
    No runtime dependencies added.
    """
    if mode == "none":
        return cards
    return cards


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
        book_name = meta.get('book', meta.get('book_name', meta.get('title', '')))

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
