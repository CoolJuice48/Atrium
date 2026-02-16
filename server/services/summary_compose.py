"""
Deterministic bullet-structured summary generator for summary-type questions.

No LLM, no heavyweight deps. Produces study-guide style output from retrieved chunks.
"""

import re
from typing import List, Tuple

# Simple stopwords for keyword extraction and clustering
_STOPWORDS = frozenset(
    "a an the and or but in on at to for of with by from as is was are were been be have has had do does did will would could should may might must can shall this that these those it its using consider given".split()
)

# Extended stopwords for key terms (exclude garbage)
_KEYTERM_STOPWORDS = _STOPWORDS | frozenset(
    "reward states erential reward using consider given thus hence therefore however".split()
)

# LaTeX/math noise patterns (escape [ in char classes)
_LATEX_PATTERNS = [
    r"\\alpha", r"\\beta", r"\\lambda", r"\\theta", r"\\sum", r"\\frac",
    r"\$[^$]+\$",  # inline math
    r"_[\[\{]", r"\^[\[\{]",  # sub/superscript
]


def clean_text(text: str) -> str:
    """Normalize whitespace, remove repeated dot leaders, strip control chars, collapse newlines."""
    if not text:
        return ""
    # Strip weird control chars (keep printable)
    text = "".join(c for c in text if c.isprintable() or c in "\n\t")
    # Remove hyphenation artifacts: word-\nword -> word word
    text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)
    # Collapse multiple newlines
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Remove repeated dot leaders (...., . . . ., etc.)
    text = re.sub(r"\.{4,}", " ", text)
    text = re.sub(r"\.\s+\.\s+\.(\s+\.)*", " ", text)
    # Normalize whitespace
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n ", "\n", text)
    return text.strip()


def _pre_normalize_for_split(text: str) -> str:
    """Pre-normalize separators before sentence splitting."""
    # Em/en dashes -> newline
    text = re.sub(r"[—–]", "\n", text)
    # Bullet " • " -> newline
    text = re.sub(r"\s+•\s+", "\n", text)
    # "Example 10: " or "Chapter 5: " style heading labels -> newline (split point)
    text = re.sub(
        r"(?:example|chapter|section|figure|table)\s+\d+(?:\.\d+)*[.:]\s*",
        "\n",
        text,
        flags=re.I,
    )
    # ": " before capital (heading-like) -> .\n
    text = re.sub(r":\s+(?=[A-Z])", ".\n", text)
    # Multiple dot-leaders -> newline
    text = re.sub(r"\.{3,}\s*", "\n", text)
    return text


def _hard_split_long(seg: str, max_len: int = 240, min_len: int = 30) -> List[str]:
    """Split segment > max_len on ; , : into clauses in valid range."""
    if len(seg) <= max_len:
        return [seg] if min_len <= len(seg) else []
    out = []
    for part in re.split(r"[;,:]\s+", seg):
        part = part.strip()
        if not part:
            continue
        if len(part) > max_len:
            # Recursively split on spaces (greedy)
            words = part.split()
            current = []
            cur_len = 0
            for w in words:
                if cur_len + len(w) + 1 > max_len and current:
                    clause = " ".join(current)
                    if min_len <= len(clause) <= max_len:
                        out.append(clause)
                    current = []
                    cur_len = 0
                current.append(w)
                cur_len += len(w) + (1 if current else 0)
            if current:
                clause = " ".join(current)
                if min_len <= len(clause) <= max_len:
                    out.append(clause)
        elif min_len <= len(part) <= max_len:
            out.append(part)
    return out


def split_sentences(text: str) -> List[str]:
    """
    Sentence splitter. Returns sentences 30-240 chars, min 6 words.
    Pre-normalizes dashes, bullets, dot-leaders. Hard-splits mega-sentences.
    """
    if not text or not text.strip():
        return []
    text = clean_text(text)
    text = _pre_normalize_for_split(text)

    # Primary split: . ! ? newlines
    raw = re.split(r"[.!?]+\s*|\n+", text)
    candidates = []
    for s in raw:
        s = s.strip()
        if not s:
            continue
        # Secondary split: ; and : when segment > 220 chars
        if len(s) > 220:
            for sub in re.split(r"[;:]\s+", s):
                sub = sub.strip()
                if sub:
                    candidates.append(sub)
        else:
            candidates.append(s)

    out = []
    for s in candidates:
        s = s.strip()
        if not s:
            continue
        if len(s) > 240:
            clauses = _hard_split_long(s, max_len=240, min_len=30)
            for c in clauses:
                if 30 <= len(c) <= 240 and len(c.split()) >= 6:
                    out.append(c)
        elif 30 <= len(s) <= 240 and len(s.split()) >= 6:
            out.append(s)
    return out


def is_noisy_sentence(s: str, *, for_summary: bool = False) -> bool:
    """
    Return True if sentence is LaTeX/math noise, figure ref, heading, exercise, or digit-heavy.
    When for_summary=True, applies stricter rules for summary bullets.
    """
    if not s or len(s) < 10:
        return True
    s_clean = s.strip()
    lower = s_clean.lower()
    tokens = s_clean.split()

    # Digit ratio (stricter for summary: 0.12 vs 0.18)
    chars = len(s_clean.replace(" ", "")) or 1
    digit_count = sum(1 for c in s_clean if c.isdigit())
    digit_ratio = digit_count / chars
    if digit_ratio > (0.12 if for_summary else 0.18):
        return True

    # Numeric token count (for summary: >= 3 numeric tokens -> noisy)
    numeric_tokens = sum(1 for t in tokens if t.isdigit())
    if for_summary and numeric_tokens >= 3:
        return True

    # LaTeX / math noise
    for pat in _LATEX_PATTERNS:
        if re.search(pat, s_clean):
            return True
    if "\\" in s_clean and re.search(r"\\[a-zA-Z]+", s_clean):
        return True

    # Figure/table reference
    if lower.startswith(("figure ", "table ", "eq.", "equation ")):
        return True
    if "fig." in lower and len(tokens) < 15:
        return True

    # Exercise/question prompt detection (for_summary)
    if for_summary:
        if s_clean.rstrip().endswith("?"):
            return True
        start_words = (
            "what", "why", "how", "prove", "derive", "compute",
            "calculate", "exercise", "problem", "question",
        )
        first_word = tokens[0].lower() if tokens else ""
        if first_word in start_words:
            return True
        if lower.startswith("show that"):
            return True
        if re.search(r"exercise\s+\d+|problem\s+\d+|q\d+", lower):
            return True

    # Heading/reference detection
    if re.search(r"\bchapter\s+\d+", lower):
        return True
    if re.search(r"\bsection\s+\d+(?:\.\d+)*", lower):
        return True
    if re.search(r"\bexample\s+\d+", lower):
        return True
    if re.search(r"\bfigure\s+\d+", lower):
        return True
    if re.search(r"\btable\s+\d+", lower):
        return True
    if re.search(r"\bp\.\s*\d+|\bpp\.\s*\d+", lower):
        return True
    if re.search(r"\bcontents\b", lower):
        return True
    if re.search(r"§\s*\d+(?:\.\d+)*", s_clean):
        return True
    # "Kernel-based ... 232" type: ends with number, many dots or spaced numbers
    if re.search(r"\d+\s*$", s_clean) and (s_clean.count(".") >= 3 or numeric_tokens >= 2):
        return True

    # Too many non-letters
    alpha_count = sum(1 for c in s_clean if c.isalpha())
    if alpha_count / max(len(s_clean), 1) < 0.65:
        return True

    # Long token sequences like "1 2 3 4 5" or many commas with short tokens
    if len(tokens) >= 5:
        numeric_run = 0
        for t in tokens:
            if t.isdigit() or (len(t) == 1 and t in ".,;:"):
                numeric_run += 1
            else:
                numeric_run = 0
            if numeric_run >= 4:
                return True
    comma_count = s_clean.count(",")
    if comma_count >= 4 and len(tokens) < 12:
        return True

    return False


def _tokenize(text: str) -> set:
    """Lowercase word tokens (letters+digits)."""
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def score_sentence(
    s: str,
    query: str,
    *,
    position_bias: float = 0.15,
    chunk_idx: int = 0,
    is_definition: bool = False,
) -> float:
    """Compute relevance score: overlap + position boost + definition boost."""
    q_tokens = _tokenize(query)
    s_tokens = _tokenize(s)
    if not s_tokens:
        return 0.0
    overlap = len(q_tokens & s_tokens) / len(s_tokens)
    pos_boost = position_bias * (1.0 / (1.0 + chunk_idx))
    score = overlap + pos_boost
    if is_definition:
        def_phrases = ["is defined as", "refers to", "means", "denotes"]
        if any(p in s.lower() for p in def_phrases):
            score += 0.1
    return score


def cluster_sentences(sentences: List[str], max_clusters: int = 6) -> List[List[str]]:
    """Greedy theme grouping via keyword overlap (Jaccard > 0.2)."""
    if not sentences:
        return []
    # Top N tokens per sentence (exclude stopwords)
    def keywords(s: str, n: int = 5) -> set:
        toks = [t for t in _tokenize(s) if t not in _STOPWORDS and len(t) > 1]
        return set(toks[:n]) if toks else set()

    clusters: List[Tuple[set, List[str]]] = []  # (cluster_keywords, sentences)

    for sent in sentences:
        kw = keywords(sent)
        if not kw:
            continue
        placed = False
        for i, (ckw, sents) in enumerate(clusters):
            inter = len(kw & ckw)
            union = len(kw | ckw)
            if union > 0 and inter / union > 0.2:
                clusters[i] = (ckw | kw, sents + [sent])
                placed = True
                break
        if not placed:
            clusters.append((kw, [sent]))

    # Cap by merging smallest clusters
    while len(clusters) > max_clusters:
        clusters.sort(key=lambda x: len(x[1]))
        # Merge smallest two
        (k1, s1), (k2, s2) = clusters[0], clusters[1]
        clusters = [(k1 | k2, s1 + s2)] + clusters[2:]

    return [sents for _, sents in clusters]


def _trim_bullet(s: str, max_len: int = 180) -> str:
    """Remove leading conjunctions, trim to max_len at comma/semicolon."""
    lower = s.strip().lower()
    for conj in ["and ", "but ", "however ", "also ", "furthermore "]:
        if lower.startswith(conj):
            s = s[len(conj) :].strip()
            lower = s.lower()
    if len(s) <= max_len:
        return s.rstrip(".,;")
    # Cut at last comma/semicolon before max_len
    cut = s[: max_len + 1]
    last_comma = max(cut.rfind(","), cut.rfind(";"), cut.rfind(" "))
    if last_comma > max_len // 2:
        s = s[:last_comma].strip()
    else:
        s = s[:max_len].rstrip()
        if not s.endswith((".", "!", "?")):
            s += "."
    return s.rstrip(".,;")


def _extract_key_terms(sentences: List[str], max_terms: int = 8) -> List[str]:
    """
    Extract frequent terms for key terms section.
    Excludes stopwords, tokens < 4 chars, hyphenation remnants.
    """
    from collections import Counter

    counts: Counter = Counter()
    for sent in sentences:
        for t in _tokenize(sent):
            if t in _KEYTERM_STOPWORDS:
                continue
            if len(t) < 4:
                continue
            if "-" in t or t.endswith("'s") or re.search(r"\d", t):
                continue
            counts[t] += 1
    return [t for t, _ in counts.most_common(max_terms)]


def _is_bullet_eligible(
    s: str,
    *,
    min_words: int = 10,
    max_words: int = 28,
    max_words_relaxed: int = 34,
    max_numeric_tokens: int = 2,
) -> bool:
    """
    Hard eligibility for summary bullets.
    Returns True only if sentence passes word count, numeric limit, and heading/exercise filters.
    """
    s = s.strip()
    if s.endswith("?"):
        return False
    tokens = s.split()
    word_count = len(tokens)
    numeric_count = sum(1 for t in tokens if t.isdigit())

    if numeric_count > max_numeric_tokens:
        return False

    heading_keywords = (
        "chapter", "section", "example", "exercise", "problem",
        "figure", "table", "contents",
    )
    lower = s.lower()
    for kw in heading_keywords:
        if kw in lower:
            return False
    if re.search(r"\bp\.\s*\d|\bpp\.\s*\d", lower):
        return False

    if min_words <= word_count <= max_words:
        return True
    if word_count <= max_words_relaxed and word_count >= min_words:
        return True
    return False


def compose_bulleted_summary(
    sentences: List[str],
    query: str,
    *,
    max_bullets: int = 10,
    max_candidates: int = 30,
) -> str:
    """
    Produce a study-guide style bullet summary from candidate sentences.

    Returns markdown-style string with ### Summary (header only, no sentence appended)
    and optional ### Key terms.
    """
    # Filter noise (for_summary=True for stricter heading/exercise filters)
    clean = [s for s in sentences if not is_noisy_sentence(s, for_summary=True)]
    if not clean:
        return "### Summary\n\nNo clear summary could be extracted from the retrieved content."

    # Hard bullet eligibility: word count 10-28, numeric <= 2, no heading/exercise
    eligible = [s for s in clean if _is_bullet_eligible(s, max_words=28)]
    if len(eligible) < 3:
        eligible = [s for s in clean if _is_bullet_eligible(s, max_words=34)]
    candidates = eligible if eligible else clean

    # Score and rank
    scored = [(score_sentence(s, query, chunk_idx=0), s) for s in candidates]
    scored.sort(key=lambda x: x[0], reverse=True)
    candidates = [s for _, s in scored[:max_candidates]]

    # Cluster
    clusters = cluster_sentences(candidates, max_clusters=6)

    # Select 1-2 best per cluster, trim
    bullets = []
    for cluster in clusters:
        cluster_scored = [(score_sentence(s, query, chunk_idx=0), s) for s in cluster]
        cluster_scored.sort(key=lambda x: x[0], reverse=True)
        for _, s in cluster_scored[:2]:
            bullet = _trim_bullet(s, max_len=180)
            if bullet and bullet not in bullets:
                bullets.append(bullet)
            if len(bullets) >= max_bullets:
                break
        if len(bullets) >= max_bullets:
            break

    bullets = bullets[:max_bullets]

    # Header exactly "### Summary" with no sentence appended
    out = ["### Summary", ""]
    for b in bullets:
        out.append(f"- {b}")
    out.append("")

    # Key terms (improved quality)
    terms = _extract_key_terms(candidates, max_terms=8)
    if terms:
        out.append("### Key terms (from text)")
        out.append("")
        out.append(", ".join(terms))
        out.append("")

    return "\n".join(out)


def compose_summary_from_chunks(
    chunks: List[dict],
    query: str,
    *,
    max_chunks: int = 12,
    max_bullets: int = 10,
) -> dict:
    """
    Build bulleted summary from chunk list.

    Returns answer_dict with keys: answer, key_points, citations, confidence.
    """
    from legacy.textbook_search_offline import _format_citation

    # Pool text from top chunks
    all_sentences = []
    metas_by_order = []
    for i, ch in enumerate(chunks[:max_chunks]):
        text = ch.get("text", "")
        meta = ch.get("metadata", ch)
        if isinstance(meta, dict):
            pass
        else:
            meta = {}
        if not text:
            text = meta.get("text", "")
        cleaned = clean_text(text)
        sents = split_sentences(cleaned)
        for s in sents:
            all_sentences.append((s, i, meta))
        metas_by_order.append(meta)

    flat_sentences = [s for s, _, _ in all_sentences]
    answer = compose_bulleted_summary(flat_sentences, query, max_bullets=max_bullets)

    # Extract key_points from bullet lines (strip "- ")
    key_points = []
    for line in answer.split("\n"):
        line = line.strip()
        if line.startswith("- "):
            key_points.append(line[2:].strip())

    # Build citations from chunk metadata (top 5-10, unique by cite string)
    citations = []
    seen_cites = set()
    for m in metas_by_order[:10]:
        cite = _format_citation(m)
        if cite and cite not in seen_cites:
            seen_cites.add(cite)
            citations.append(cite)

    return {
        "answer": answer,
        "key_points": key_points,
        "citations": citations,
        "confidence": {
            "level": "medium" if key_points else "low",
            "evidence_coverage_score": 0.5 if key_points else 0.0,
            "source_diversity_score": len(citations),
            "redundancy_score": 0.0,
            "contradiction_flag": False,
        },
    }
