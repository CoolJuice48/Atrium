"""
Heading mining from chunks for fallback when outline has no TOC (page ranges only).

Detects heading-like lines: TitleCase ratio, short length, no verbs.
Returns list of heading strings for use as pseudo-title_terms in centrality.
"""

import re
from typing import Any, Dict, List

# Common verbs that suggest a line is body text, not a heading
_VERB_PATTERNS = re.compile(
    r"\b(is|are|was|were|have|has|had|do|does|did|will|would|can|could|"
    r"may|might|must|shall|should|be|been|being)\b",
    re.I,
)


def _is_heading_like(line: str) -> bool:
    """
    Heuristic: heading-like lines have high TitleCase ratio, short length, no verbs.
    """
    line = line.strip()
    if not line or len(line) < 4:
        return False
    words = line.split()
    if len(words) > 10:
        return False
    if len(words) < 2:
        return False
    # Reject if contains verb
    if _VERB_PATTERNS.search(line):
        return False
    # TitleCase ratio: words starting with uppercase / total alphabetic words
    upper_start = sum(1 for w in words if w and w[0].isupper())
    total = len(words)
    ratio = upper_start / total if total else 0
    return ratio >= 0.5


def extract_headings_from_chunks(chunks: List[Dict[str, Any]]) -> List[str]:
    """
    Extract heading-like lines from chunk text within scope.
    Returns list of heading strings (not terms). Caller should derive terms via extract_title_terms.
    """
    headings: List[str] = []
    seen = set()
    for ch in chunks:
        text = ch.get("text", "")
        if not text or not isinstance(text, str):
            continue
        for raw_line in text.split("\n"):
            line = raw_line.strip()
            if not line:
                continue
            # Normalize for dedup
            norm = re.sub(r"\s+", " ", line.lower())
            if norm in seen:
                continue
            if _is_heading_like(line):
                seen.add(norm)
                headings.append(line)
    return headings
