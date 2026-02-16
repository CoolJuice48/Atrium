"""
Deterministic bullet-structured summary generator for summary-type questions.

No LLM, no heavyweight deps. Produces study-guide style output from retrieved chunks.
"""

import re
from typing import List, Tuple

# Simple stopwords for keyword extraction and clustering
_STOPWORDS = frozenset(
    "a an the and or but in on at to for of with by from as is was are were been be have has had do does did will would could should may might must can shall".split()
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


def split_sentences(text: str) -> List[str]:
    """Simple sentence splitter. Returns sentences 30-240 chars, min 6 words."""
    if not text or not text.strip():
        return []
    text = clean_text(text)
    # Split on sentence boundaries and line breaks
    raw = re.split(r"[.!?]+\s*|\n+", text)
    out = []
    for s in raw:
        s = s.strip()
        if not s:
            continue
        if 30 <= len(s) <= 240 and len(s.split()) >= 6:
            out.append(s)
    return out


def is_noisy_sentence(s: str) -> bool:
    """Return True if sentence is LaTeX/math noise, figure ref, or digit-heavy."""
    if not s or len(s) < 10:
        return True
    s_clean = s.strip()

    # Too many digits
    chars = len(s_clean.replace(" ", "")) or 1
    digit_count = sum(1 for c in s_clean if c.isdigit())
    if digit_count / chars > 0.18:
        return True

    # LaTeX / math noise
    for pat in _LATEX_PATTERNS:
        if re.search(pat, s_clean):
            return True
    if "\\" in s_clean and re.search(r"\\[a-zA-Z]+", s_clean):
        return True

    # Figure/table reference
    lower = s_clean.lower()
    if lower.startswith(("figure ", "table ", "eq.", "equation ")):
        return True
    if "fig." in lower and len(s_clean.split()) < 15:
        return True

    # Too many non-letters
    alpha_count = sum(1 for c in s_clean if c.isalpha())
    if alpha_count / max(len(s_clean), 1) < 0.65:
        return True

    # Long token sequences like "1 2 3 4 5" or many commas with short tokens
    tokens = s_clean.split()
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
    """Extract frequent non-stopword terms from sentences."""
    from collections import Counter

    counts: Counter = Counter()
    for sent in sentences:
        for t in _tokenize(sent):
            if t not in _STOPWORDS and len(t) > 2:
                counts[t] += 1
    return [t for t, _ in counts.most_common(max_terms)]


def compose_bulleted_summary(
    sentences: List[str],
    query: str,
    *,
    max_bullets: int = 10,
    max_candidates: int = 30,
) -> str:
    """
    Produce a study-guide style bullet summary from candidate sentences.

    Returns markdown-style string with ### Summary and optional ### Key terms.
    """
    # Filter noise
    clean = [s for s in sentences if not is_noisy_sentence(s)]
    if not clean:
        return "### Summary\n\nNo clear summary could be extracted from the retrieved content."

    # Score and rank (use chunk_idx=0 for all when no position info)
    scored = [(score_sentence(s, query, chunk_idx=0), s) for s in clean]
    scored.sort(key=lambda x: x[0], reverse=True)
    candidates = [s for _, s in scored[:max_candidates]]

    # Cluster
    clusters = cluster_sentences(candidates, max_clusters=6)

    # Select 1-2 best per cluster, trim
    bullets = []
    for cluster in clusters:
        # Re-score within cluster
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

    out = ["### Summary", ""]
    for b in bullets:
        out.append(f"- {b}")
    out.append("")

    # Optional key terms
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
