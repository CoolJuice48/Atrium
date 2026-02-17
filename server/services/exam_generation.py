"""
Deterministic practice exam question generators.

Uses only the candidate pool. No LLM. Reallocates distribution when insufficient candidates.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from server.services.exam_candidates import Candidate, CandidatePool
from server.services.exam_stems import validate_definition_term, validate_question_stem


# Definition extraction patterns: (term_group_idx, defn_group_idx)
_DEF_PATTERNS = [
    (r"\b([a-zA-Z][a-zA-Z0-9\s\-_]{2,50})\s+is\s+defined\s+as\s+(.+?)(?:\.|$)", 1, 2),
    (r"\b([a-zA-Z][a-zA-Z0-9\s\-_]{2,50})\s+refers\s+to\s+(.+?)(?:\.|$)", 1, 2),
    (r"\b([a-zA-Z][a-zA-Z0-9\s\-_]{2,50})\s+means\s+(.+?)(?:\.|$)", 1, 2),
    (r"\b([a-zA-Z][a-zA-Z0-9\s\-_]{2,50})\s+is\s+called\s+(.+?)(?:\.|$)", 1, 2),
]

# Enumeration cues for list questions
_LIST_CUES = ("types of", "components include", "three main", "steps are", "factors are", "elements include")

# Generic words to never blank in FIB
_FIB_BLACKLIST = frozenset(
    "this that the a an it is are was were have has had do does the method way".split()
)


@dataclass
class ExamQuestion:
    """Single exam question with typed structure."""
    q_type: str  # definition, fib, tf, short, list
    prompt: str
    answer: str
    citations: List[Dict[str, str]] = field(default_factory=list)


def _truncate_defn(defn: str, max_words: int = 28) -> str:
    """Truncate definition to max_words."""
    words = defn.split()
    if len(words) <= max_words:
        return defn
    return " ".join(words[:max_words])


def _make_citation(c: Candidate) -> Dict[str, str]:
    """Build citation dict from candidate."""
    pages = ""
    if c.page_start is not None and c.page_end is not None:
        pages = f"{c.page_start}-{c.page_end}" if c.page_start != c.page_end else str(c.page_start)
    return {"chunk_id": c.chunk_id, "pages": pages}


def _extract_definition_pair(text: str) -> Optional[Tuple[str, str]]:
    """Extract (term, definition) from sentence. Returns None if not a definition."""
    for pattern, ti, di in _DEF_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if m:
            term = m.group(ti).strip()
            defn = m.group(di).strip().split("\n")[0]
            if len(term) >= 4 and len(defn) >= 10:
                return (term, defn)
    return None


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


def _generate_definitions(pool: CandidatePool, count: int) -> List[ExamQuestion]:
    """Generate definition questions from definition-cue candidates."""
    def_candidates = [c for c in pool.candidates if c.score_hint >= 2]
    questions: List[ExamQuestion] = []
    seen_terms: set = set()
    for c in def_candidates:
        if len(questions) >= count:
            break
        pair = _extract_definition_pair(c.text)
        if not pair:
            continue
        term, defn = pair
        term_lower = term.lower()
        if term_lower in seen_terms:
            continue
        if not validate_definition_term(term):
            continue
        stem = f"What is {term}?"
        if not validate_question_stem(stem):
            continue
        seen_terms.add(term_lower)
        answer = _truncate_defn(defn)
        questions.append(ExamQuestion(
            q_type="definition",
            prompt=stem,
            answer=answer,
            citations=[_make_citation(c)],
        ))
    return questions


def _phrase_frequency(pool: CandidatePool, min_len: int = 2, max_len: int = 3) -> Dict[str, int]:
    """Count multiword phrase frequency for FIB blank selection."""
    freq: Dict[str, int] = {}
    for c in pool.candidates:
        if c.score_hint < 1:
            continue
        words = re.findall(r"[a-zA-Z]+", c.text)
        for n in range(min_len, max_len + 1):
            for i in range(len(words) - n + 1):
                phrase = " ".join(words[i : i + n]).lower()
                if any(w in _FIB_BLACKLIST for w in phrase.split()):
                    continue
                if len(phrase) < 3 or len(phrase) > 25:
                    continue
                freq[phrase] = freq.get(phrase, 0) + 1
    return freq


def _generate_fib(pool: CandidatePool, count: int) -> List[ExamQuestion]:
    """Generate fill-in-the-blank from high-quality candidates."""
    high = [c for c in pool.candidates if c.score_hint >= 1]
    freq = _phrase_frequency(pool)
    sorted_phrases = sorted(freq.items(), key=lambda x: -x[1])
    questions: List[ExamQuestion] = []
    used_prompts: set = set()
    for phrase, _ in sorted_phrases:
        if len(questions) >= count:
            break
        if len(phrase) < 3 or len(phrase) > 25:
            continue
        if any(w in _FIB_BLACKLIST for w in phrase.split()):
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
            if not validate_question_stem(f"Fill in the blank: {prompt}"):
                continue
            used_prompts.add(prompt)
            questions.append(ExamQuestion(
                q_type="fib",
                prompt=f"Fill in the blank: {prompt}",
                answer=phrase,
                citations=[_make_citation(c)],
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
                    seen_prompts.add(q.prompt)
                    results.append(q)
                    remaining -= 1

    return results[:total]
