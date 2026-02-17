"""
Deterministic practice exam question generators.

Uses only the candidate pool. No LLM. Reallocates distribution when insufficient candidates.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from server.services.exam_candidates import Candidate, CandidatePool
from server.services.exam_stems import validate_definition_term, validate_question_stem
from server.services.text_quality import (
    is_exercise_prompt,
    is_reference_line,
    is_structural_noise,
    normalize_ws,
)

# Explicit definition patterns: ^X <cue> Y.  All match sentence-initial X only.
_DEF_PATTERNS_EXPLICIT = [
    (r"^(.+?)\s+(?:is|are)\s+defined\s+as\s+(.+)$", "is_defined_as"),
    (r"^(.+?)\s+refers\s+to\s+(.+)$", "refers_to"),
    (r"^(.+?)\s+means\s+(.+)$", "means"),
    (r"^(.+?)\s+(?:is|are)\s+called\s+(.+)$", "is_called"),
    (r"^(.+?)\s+consists\s+of\s+(.+)$", "consists_of"),
]
# Weaker: X is/are Y - only if sentence-initial and Y passes quality
_DEF_PATTERN_WEAK = (r"^(.+?)\s+(?:is|are)\s+(.+)$", "is")

# Enumeration cues for list questions
_LIST_CUES = ("types of", "components include", "three main", "steps are", "factors are", "elements include")

# FIB: determiners, discourse, pronouns, verbs - never blank
_FIB_BLACKLIST = frozenset(
    "this that the a an it is are was were have has had do does the method way "
    "any some each then thus however therefore because if but so also "
    "they we you he she i them us his her their its function value method".split()
)

# FIB: too generic even if not in blacklist
_FIB_GENERIC = frozenset("thing stuff part element type form way".split())


@dataclass
class ExamQuestion:
    """Single exam question with typed structure."""
    q_type: str  # definition, fib, tf, short, list
    prompt: str
    answer: str
    citations: List[Dict[str, str]] = field(default_factory=list)
    source_text: Optional[str] = None  # for optional local LLM polish


def _truncate_defn(defn: str, max_words: int = 28) -> str:
    """Truncate definition to max_words."""
    words = defn.split()
    if len(words) <= max_words:
        return defn
    return " ".join(words[:max_words])


def _strip_trailing_citations(defn: str) -> str:
    """Remove trailing parentheticals that look like references."""
    defn = defn.strip()
    # Remove trailing (Author, 2020) or (see Chapter X)
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


def extract_definition_pairs(sentence: str) -> List[Tuple[str, str, str]]:
    """
    Extract (term, definition, pattern_name) from sentence.
    Only accepts sentence-initial patterns. Returns [] if no valid pair.
    """
    sentence = normalize_ws(sentence)
    if not sentence or len(sentence) < 20:
        return []
    # Must match from start - no mid-clause extraction
    results = []
    for pattern, name in _DEF_PATTERNS_EXPLICIT:
        m = re.match(pattern, sentence, re.IGNORECASE | re.DOTALL)
        if m:
            x_raw, y_raw = m.group(1).strip(), m.group(2).strip()
            term = normalize_ws(x_raw).rstrip(".,;:")
            defn = normalize_ws(y_raw).split("\n")[0]
            defn = _strip_trailing_citations(defn)
            defn = _truncate_defn(defn, 28)
            defn_words = len(defn.split())
            if defn_words < 6 or defn_words > 35:
                continue
            if not _definition_has_verb(defn):
                continue
            if is_structural_noise(defn) or is_exercise_prompt(defn) or is_reference_line(defn):
                continue
            if len(term) >= 4 and len(defn) >= 15:
                results.append((term, defn, name))
                return results  # first match wins
    # Weaker: X is Y - only if explicit patterns failed and Y passes quality
    m = re.match(_DEF_PATTERN_WEAK[0], sentence, re.IGNORECASE | re.DOTALL)
    if m and not results:
        x_raw, y_raw = m.group(1).strip(), m.group(2).strip()
        term = normalize_ws(x_raw).rstrip(".,;:")
        defn = normalize_ws(y_raw).split("\n")[0]
        defn = _strip_trailing_citations(defn)
        defn = _truncate_defn(defn, 28)
        defn_words = len(defn.split())
        if 6 <= defn_words <= 35 and _definition_has_verb(defn):
            if not (is_structural_noise(defn) or is_exercise_prompt(defn) or is_reference_line(defn)):
                if len(term) >= 4 and len(defn) >= 15:
                    results.append((term, defn, "is"))
    return results


def _make_citation(c: Candidate) -> Dict[str, str]:
    """Build citation dict from candidate."""
    pages = ""
    if c.page_start is not None and c.page_end is not None:
        pages = f"{c.page_start}-{c.page_end}" if c.page_start != c.page_end else str(c.page_start)
    return {"chunk_id": c.chunk_id, "pages": pages}


def _has_verb(text: str) -> bool:
    """Simple heuristic: common verb patterns."""
    lower = text.lower()
    for w in ("is", "are", "was", "were", "has", "have", "can", "will", "may", "does", "do"):
        if re.search(rf"\b{w}\b", lower):
            return True
    if re.search(r"\b\w+ed\b|\b\w+ing\b|\b\w+s\b", lower):
        return True
    return False


def _citation_density(text: str) -> float:
    """Rough citation density (brackets, years)."""
    brackets = len(re.findall(r"\[\d+\]|\(\d{4}\)", text))
    return brackets / max(1, len(text.split()))


def _validate_answer(answer: str, min_words: int = 5, max_words: int = 30) -> bool:
    """Sanity check: answer length and single line."""
    if not answer or "\n" in answer:
        return False
    words = answer.split()
    return min_words <= len(words) <= max_words


def _final_sanity_check(q: ExamQuestion) -> bool:
    """Before returning: validate stem, answer length, single line (except list)."""
    if not validate_question_stem(q.prompt):
        return False
    if q.q_type == "list":
        return bool(q.answer)
    if q.q_type == "tf":
        return q.answer in ("True", "False") and "\n" not in q.answer
    if q.q_type == "fib":
        return _validate_answer(q.answer, min_words=1, max_words=5)
    return _validate_answer(q.answer, min_words=5, max_words=30)


def _generate_definitions(pool: CandidatePool, count: int) -> List[ExamQuestion]:
    """Generate definition questions from definition-cue candidates. Sentence-initial only."""
    def_candidates = [c for c in pool.candidates if c.score_hint >= 2]
    questions: List[ExamQuestion] = []
    seen_terms: set = set()
    for c in def_candidates:
        if len(questions) >= count:
            break
        pairs = extract_definition_pairs(c.text)
        if not pairs:
            continue
        term, defn, _ = pairs[0]
        term_lower = term.lower()
        if term_lower in seen_terms:
            continue
        if not validate_definition_term(term):
            continue
        stem = f"What is {term}?"
        if not validate_question_stem(stem):
            continue
        answer = _truncate_defn(defn)
        if not _validate_answer(answer):
            continue
        seen_terms.add(term_lower)
        questions.append(ExamQuestion(
            q_type="definition",
            prompt=stem,
            answer=answer,
            citations=[_make_citation(c)],
            source_text=c.text,
        ))
    return questions


_FIB_VERB_ADJACENT = frozenset("is are was were be been being".split())


def _fib_phrase_ok(phrase: str, words: List[str], start_idx: int) -> bool:
    """
    Check phrase is noun-ish and not adjacent to passive voice.
    start_idx = index of first word of phrase in words.
    """
    phrase_words = phrase.lower().split()
    if not phrase_words:
        return False
    last = phrase_words[-1]
    if last in _FIB_VERB_ADJACENT:
        return False
    if any(w in _FIB_BLACKLIST or w in _FIB_GENERIC for w in phrase_words):
        return False
    # avoid blank adjacent to verb on either side
    if start_idx > 0:
        prev = words[start_idx - 1].lower()
        if prev in _FIB_VERB_ADJACENT:
            return False
    end_idx = start_idx + len(phrase_words)
    if end_idx < len(words):
        nxt = words[end_idx].lower()
        if nxt in _FIB_VERB_ADJACENT:
            return False
    return True


def _fib_blank_creates_bad_grammar(prompt: str) -> bool:
    """Reject if ______ is adjacent to verb on both sides."""
    parts = re.split(r"______", prompt, maxsplit=1)
    if len(parts) != 2:
        return True
    left, right = parts[0], parts[1]
    left_words = re.findall(r"[a-zA-Z]+", left)
    right_words = re.findall(r"[a-zA-Z]+", right)
    left_last = left_words[-1].lower() if left_words else ""
    right_first = right_words[0].lower() if right_words else ""
    if left_last in _FIB_VERB_ADJACENT and right_first in _FIB_VERB_ADJACENT:
        return True
    return False


def _phrase_frequency(pool: CandidatePool, min_len: int = 1, max_len: int = 3) -> Dict[str, int]:
    """Count phrase frequency. Only from sentences 12-28 words, score_hint>=1."""
    freq: Dict[str, int] = {}
    for c in pool.candidates:
        if c.score_hint < 1:
            continue
        words = re.findall(r"[a-zA-Z]+", c.text)
        if len(words) < 12 or len(words) > 28:
            continue
        for n in range(min_len, max_len + 1):
            for i in range(len(words) - n + 1):
                phrase = " ".join(words[i : i + n]).lower()
                if any(w in _FIB_BLACKLIST or w in _FIB_GENERIC for w in phrase.split()):
                    continue
                if len(phrase) < 3 or len(phrase) > 25:
                    continue
                if not phrase.replace(" ", "").isalpha():
                    continue
                if not _fib_phrase_ok(phrase, words, i):
                    continue
                freq[phrase] = freq.get(phrase, 0) + 1
    return freq


def _generate_fib(pool: CandidatePool, count: int) -> List[ExamQuestion]:
    """Generate fill-in-the-blank. Grammar-safe: no passive voice breaks."""
    high = [
        c for c in pool.candidates
        if c.score_hint >= 1
        and 12 <= len(c.text.split()) <= 28
    ]
    freq = _phrase_frequency(pool)
    # Prefer freq>=2, then TitleCase/domain-like (length>=5)
    def _score(phrase: str, f: int) -> int:
        s = f * 10
        if f >= 2:
            s += 50
        if any(len(w) >= 5 for w in phrase.split()):
            s += 20
        if phrase != phrase.lower() and phrase[0].isupper():
            s += 10
        return s

    sorted_phrases = sorted(freq.items(), key=lambda x: -_score(x[0], x[1]))
    questions: List[ExamQuestion] = []
    used_prompts: set = set()
    for phrase, _ in sorted_phrases:
        if len(questions) >= count:
            break
        if len(phrase) < 3 or len(phrase) > 25:
            continue
        if any(w in _FIB_BLACKLIST or w in _FIB_GENERIC for w in phrase.split()):
            continue
        if phrase.isdigit():
            continue
        blank = "______"
        for c in high:
            if len(questions) >= count:
                break
            if phrase not in c.text.lower():
                continue
            prompt = re.sub(re.escape(phrase), blank, c.text, count=1, flags=re.I)
            if prompt in used_prompts:
                continue
            if _fib_blank_creates_bad_grammar(prompt):
                continue
            words_in_prompt = prompt.split()
            if words_in_prompt[0] == "______" or words_in_prompt[-1] == "______":
                continue
            if not validate_question_stem(f"Fill in the blank: {prompt}"):
                continue
            answer = phrase
            if not _validate_answer(answer, min_words=1, max_words=5):
                continue
            used_prompts.add(prompt)
            questions.append(ExamQuestion(
                q_type="fib",
                prompt=f"Fill in the blank: {prompt}",
                answer=answer,
                citations=[_make_citation(c)],
                source_text=c.text,
            ))
    return questions


def _generate_tf(pool: CandidatePool, count: int) -> List[ExamQuestion]:
    """Generate true/false from declarative candidates with verbs."""
    candidates = [
        c for c in pool.candidates
        if c.score_hint >= -1
        and _has_verb(c.text)
        and _citation_density(c.text) < 0.05
        and 40 <= len(c.text) <= 200
    ]
    questions: List[ExamQuestion] = []
    seen: set = set()
    for c in candidates:
        if len(questions) >= count:
            break
        stmt = c.text.strip()
        if not stmt.endswith((".", "!")):
            continue
        norm = re.sub(r"\s+", " ", stmt).lower()
        if norm in seen:
            continue
        stem = f"True or False: {stmt}"
        if not validate_question_stem(stem):
            continue
        seen.add(norm)
        questions.append(ExamQuestion(
            q_type="tf",
            prompt=stem,
            answer="True",
            citations=[_make_citation(c)],
        ))
    return questions


def _generate_short_answer(pool: CandidatePool, count: int) -> List[ExamQuestion]:
    """Generate short answer from causal/explanatory candidates."""
    causal = [
        c for c in pool.candidates
        if any(cue in c.text.lower() for cue in ("because", "due to", "therefore", "thus", "hence"))
        and c.score_hint >= 0
    ]
    questions: List[ExamQuestion] = []
    seen: set = set()
    for c in causal:
        if len(questions) >= count:
            break
        lower = c.text.lower()
        if "because" in lower:
            idx = lower.index("because")
            before = c.text[:idx].strip()
            after = c.text[idx:].strip()
            stem = f"Why does {before}?"
            answer = _truncate_defn(after, 30)
        elif "due to" in lower:
            idx = lower.index("due to")
            before = c.text[:idx].strip()
            after = c.text[idx:].strip()
            stem = f"Why does {before}?"
            answer = _truncate_defn(after, 30)
        else:
            stem = f"Explain: {c.text[:80]}..."
            answer = _truncate_defn(c.text, 30)
        if stem.lower() in seen:
            continue
        if not validate_question_stem(stem):
            continue
        seen.add(stem.lower())
        questions.append(ExamQuestion(
            q_type="short",
            prompt=stem,
            answer=answer,
            citations=[_make_citation(c)],
        ))
    return questions


def _extract_list_items(text: str) -> Optional[List[str]]:
    """Extract list items from enumeration. Returns None if invalid."""
    for cue in _LIST_CUES:
        if cue not in text.lower():
            continue
        parts = re.split(r"[,;]\s*|\s+and\s+", text)
        items = [p.strip() for p in parts if len(p.strip()) >= 2 and len(p.strip().split()) <= 6]
        if 3 <= len(items) <= 7:
            return items
    return None


def _generate_list(pool: CandidatePool, count: int) -> List[ExamQuestion]:
    """Generate list questions from enumeration candidates."""
    candidates = [
        c for c in pool.candidates
        if any(cue in c.text.lower() for cue in _LIST_CUES)
    ]
    questions: List[ExamQuestion] = []
    seen: set = set()
    for c in candidates:
        if len(questions) >= count:
            break
        items = _extract_list_items(c.text)
        if not items:
            continue
        stem = "List the following:"
        answer = "\n".join(f"- {i}" for i in items[:7])
        key = answer.lower()
        if key in seen:
            continue
        if not validate_question_stem(stem):
            continue
        seen.add(key)
        questions.append(ExamQuestion(
            q_type="list",
            prompt=stem,
            answer=answer,
            citations=[_make_citation(c)],
        ))
    return questions


def generate_exam_questions(
    pool: CandidatePool,
    distribution: Optional[Dict[str, int]] = None,
    total: int = 20,
) -> List[ExamQuestion]:
    """
    Generate questions to match distribution. Reallocates when insufficient candidates.
    """
    if distribution is None:
        distribution = {
            "definition": 5,
            "fib": 4,
            "tf": 4,
            "short": 4,
            "list": 3,
        }
    target = {k: min(v, total) for k, v in distribution.items()}
    total_target = sum(target.values())
    if total_target > total:
        scale = total / total_target
        target = {k: max(1, int(v * scale)) for k, v in target.items()}
        target["definition"] += total - sum(target.values())

    generators = {
        "definition": _generate_definitions,
        "fib": _generate_fib,
        "tf": _generate_tf,
        "short": _generate_short_answer,
        "list": _generate_list,
    }

    results: List[ExamQuestion] = []
    for qtype, gen in generators.items():
        n = target.get(qtype, 0)
        if n <= 0:
            continue
        qs = gen(pool, n)
        results.extend(qs)

    remaining = total - len(results)
    if remaining > 0:
        seen_prompts = {q.prompt for q in results}
        for qtype in ("definition", "tf", "short", "fib", "list"):
            if remaining <= 0:
                break
            gen = generators[qtype]
            extra = gen(pool, target.get(qtype, 0) + remaining)
            for q in extra:
                if remaining <= 0:
                    break
                if q.prompt not in seen_prompts:
                    if not _final_sanity_check(q):
                        continue
                    seen_prompts.add(q.prompt)
                    results.append(q)
                    remaining -= 1

    return [_q for _q in results[:total] if _final_sanity_check(_q)]
